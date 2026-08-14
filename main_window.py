"""The main window: wires the sidebar + workbench columns together and owns
every background worker's lifecycle. This is the only file that makes
decisions — every widget below it is dumb display + signals.

Layout is direction 1b of the Prism Directions canvas: "everything in view,
nothing to drag". Three fixed columns — rail, work, context — replacing the
old floating QDockWidgets. Nothing here can be closed or lost behind a tab, so
there's no View menu and no way to end up staring at an empty window.

The work column is a two-page stack: composing (task + plan) and running
(live output). Those are the only two things you can be doing, they never
want to be on screen at once, and the plan is one click back."""
from __future__ import annotations
import os
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QFont, QCursor
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QMessageBox, QFrame,
    QFileDialog, QDialog, QLabel, QScrollArea, QStackedWidget, QPushButton,
    QMenu,
)

import awake
import core_bridge as CB
import diagnostics
import i18n
import identity
import licensing
import theme
import workspace
from widgets import icons
from widgets.sidebar import Sidebar
from widgets.input_panel import InputPanel
from widgets.files_panel import FilesPanel
from widgets.prompt_panel import PromptPanel
from widgets.agents_panel import AgentsPanel
from widgets.output_panel import OutputPanel
from workers import (RouteWorker, AutomationWorker, RecordWorker,
                     InterpretWorker, FindWorker, AuthorizeWorker,
                     FFmpegWorker)
import wakeword
from wakeword import WakeWordListener
from dialogs.setup_dialog import SetupDialog
from dialogs.ai_directory_dialog import AIDirectoryDialog
from dialogs.email_dialog import EmailComposeDialog, EmailSetupDialog
from dialogs.boq_dialog import BoqDialog
from dialogs.reel_dialog import ReelDialog
from dialogs.completion_dialog import CompletionDialog
from dialogs.history_dialog import HistoryDialog

COMPOSE, RUNNING = 0, 1

# Wake-word threads that were asked to stop but had not finished in time.
# Module level, not an attribute: on window close there is nothing else left
# holding the reference, and a QThread collected while its OS thread is still
# running aborts the process. Entries remove themselves once finished fires.
_retired_listeners: list = []


def _is_running(worker) -> bool:
    """True if this QThread is still alive.

    A worker whose C++ side has already been deleted raises RuntimeError from
    isRunning() rather than returning False, and that exception thrown during
    closeEvent would skip retiring every worker after it in the list — turning
    a tidy shutdown back into the abort this is here to prevent.
    """
    try:
        return bool(worker.isRunning())
    except RuntimeError:
        return False


def _retire_listener(listener, wait_ms: int = 3000) -> None:
    """Stop a wake-word listener, and make sure nothing drops it while its
    thread is still alive.

    stop() waits, but only briefly — an in-flight Whisper request holds the
    loop until its own 60s timeout, and blocking the GUI thread for that long
    is worse than the bug. When the wait runs out the listener is parked here,
    referenced and alive, until finished says the thread has really gone.
    Releasing it any earlier is precisely the "Destroyed while thread is still
    running" abort this exists to prevent.
    """
    if listener.stop(wait_ms):
        return
    _retired_listeners.append(listener)

    def _drop():
        try:
            _retired_listeners.remove(listener)
        except ValueError:
            pass

    listener.finished.connect(_drop)

# Routed agents that belong to a paid add-on. The rail gate alone would miss
# these: the router can put Prism Reel into a plan without the customer ever
# touching the Reel item in the sidebar.
AGENT_FEATURES = {"Prism Reel": "reel", "Prism Studio": "reel"}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Prism")
        self._fit_to_screen()

        self.cfg = CB.config.load()
        self.attachments: list[dict] = []
        self.pending_mentions: list[dict] = []   # [{"description","path","kind"}]
        self.routing: dict | None = None

        self._record_worker = None
        self._wake_listener = None
        self._workers = []    # keep references so QThreads aren't GC'd mid-run
        self._stage_agents: dict[str, str] = {}   # stage -> agent, from stage_start
        self._stage_results: list[dict] = []      # built up during a run, for the completion popup
        self._run_finished = False                # a finished plan is spent — see _back_to_plan
        self._run_id = ""                         # licence server's id for the current run
        self._active_run = None                   # the AutomationWorker, so Stop can reach it

        # ── the task queue ───────────────────────────────────────────────────
        # Tasks the user lined up before pressing Make a plan. Each one is a
        # full journey of its own — plan, authorise, run — because the router
        # can only plan one task at a time and each is separately billable.
        # _task_runs accumulates {"task", "stages"} so the completion window
        # can say which AIs ran for task 1 as distinct from task 2.
        self._task_queue: list[str] = []
        self._task_pos = 0                        # 1-based index of the running task
        self._task_runs: list[dict] = []
        self._queue_stopped = False               # a licence refusal kills the rest
        self._auto_run = False                    # set once Start the work is pressed

        self._build_ui()
        self._wire()
        self.refresh_licence_ui()
        self._start_licence_timer()

        # The explainer needs nothing but eyes on the window, so it no longer
        # waits on the licence — a first launch with a stuck licence sync is
        # exactly when a brand-new user most needs to be told what Prism is,
        # not left alone with a locked sidebar and no context. _first_run
        # keeps the Groq key dialog behind the licence check: a customer who
        # cannot use Prism yet does not need a key dialog on top of that.
        if not CB.config.is_configured(self.cfg):
            # Deferred to the event loop rather than run here. A modal opened
            # from inside __init__ blocks before the window is on screen, so
            # it can appear behind it or with nowhere to centre itself — and
            # the constructor never returns until it is dismissed.
            QTimer.singleShot(0, self._first_run)

    # ── keeping the licence and lease current ───────────────────────────────
    # The authorisation lease is short by design (about half an hour), so a
    # window left open all afternoon would let it lapse and turn the next
    # click into a blocking round trip — the exact latency the lease exists to
    # remove. This tops it up quietly instead.
    #
    # The timer lives here rather than in the licensing package for the same
    # reason set_paywall_handler does: that package deliberately never imports
    # Qt, so the CLI and the tests can use it without a display.
    LICENCE_REFRESH_MS = 10 * 60 * 1000

    def _start_licence_timer(self):
        """Renew token and lease in the background, forever, off the UI thread.

        licensing.refresh() returns immediately and does its work on a daemon
        thread, so this costs the event loop nothing. Ten minutes against a
        thirty-minute lease means two chances to recover from a blip before
        anyone notices one — and /v1/lease records no usage, so a customer is
        never billed for Prism keeping itself current.
        """
        self._licence_timer = QTimer(self)
        self._licence_timer.setInterval(self.LICENCE_REFRESH_MS)
        self._licence_timer.timeout.connect(self._tick_licence)
        self._licence_timer.start()

    def _tick_licence(self):
        try:
            licensing.refresh()
            # Repaint from the CACHED state, which the previous tick's refresh
            # has by now written. Reading it here rather than waiting on this
            # tick's network call is what keeps the timer non-blocking.
            licensing.reload()
            self.refresh_licence_ui()
        except Exception:                          # noqa: BLE001
            pass    # a licence refresh must never be able to crash the window

    # ── layout ──────────────────────────────────────────────────────────────
    def _fit_to_screen(self):
        """Size (and center) the window to whatever screen it's actually on,
        instead of a fixed 1400x900 that can overflow a smaller display."""
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        if avail:
            w = min(1360, int(avail.width() * 0.92))
            h = min(880, int(avail.height() * 0.88))
            self.resize(w, h)
            self.move(avail.center().x() - w // 2, avail.center().y() - h // 2)
        else:
            self.resize(1180, 760)
        # Three columns with fixed rails need more floor than the old dock
        # layout did — below this the work column starts eating its own text.
        self.setMinimumSize(1060, 640)

    def _build_ui(self):
        central = QWidget()
        # A vertical shell so the licence banner can span the full width above
        # all three columns. It has to be impossible to miss and impossible to
        # confuse with a run message, which rules out the status bar.
        shell = QVBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        shell.addWidget(self._licence_banner())

        columns = QWidget()
        outer = QHBoxLayout(columns)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.sidebar = Sidebar()
        outer.addWidget(self.sidebar)
        outer.addWidget(self._work_column(), stretch=1)
        outer.addWidget(self._context_column())
        shell.addWidget(columns, stretch=1)
        self.setCentralWidget(central)

    # ── licence ─────────────────────────────────────────────────────────────
    def _licence_banner(self) -> QWidget:
        self.banner = QFrame()
        self.banner.setObjectName("licenceBanner")
        row = QHBoxLayout(self.banner)
        row.setContentsMargins(20, 9, 14, 9)
        row.setSpacing(10)
        self._banner_icon = QLabel()
        row.addWidget(self._banner_icon)
        self._banner_text = QLabel()
        self._banner_text.setWordWrap(True)
        row.addWidget(self._banner_text, stretch=1)
        self._banner_btn = QPushButton("Enter a licence key")
        self._banner_btn.setObjectName("smallBtn")
        self._banner_btn.setCursor(Qt.PointingHandCursor)
        self._banner_btn.clicked.connect(self._open_license_dialog)
        row.addWidget(self._banner_btn)
        self.banner.setVisible(False)
        return self.banner

    def refresh_licence_ui(self):
        """Repaint everything that depends on the licence: the banner, the
        locks in the rail, and the idle status message. That last one used to
        be a hardcoded "Ready." set once in _build_ui — which stayed on
        screen, unchanged, underneath a banner saying new work was paused.
        `usable` is the same flag the rest of the licence gate goes by, so the
        status bar never again claims something the banner just denied.
        Called at startup and after any licence change."""
        state = licensing.state()
        self.sidebar.set_entitlements(state.features, state.usable)
        if state.usable:
            self.statusBar().showMessage("Ready.")
        else:
            self.statusBar().clearMessage()

        if state.status == licensing.VALID:
            # A healthy licence frees the banner for the other thing worth
            # interrupting someone about: their work is no longer reaching the
            # shared folder, so their manager cannot see it.
            offline = workspace.unreachable(self.cfg)
            if offline:
                self._show_banner(offline, "#8a5a2f", "alert")
            else:
                self.banner.setVisible(False)
            return

        if state.status == licensing.STALE:
            tone, icon_name = theme.NEUTRAL[600], "clock"
            text = ("Prism hasn't been able to reach the licence server. "
                    "New work is paused until it can — History and everything "
                    "you've already made are still here.")
        elif state.status == licensing.GRACE:
            tone, icon_name = theme.NEUTRAL[600], "clock"
            days = max(state.days_left + state.grace_days, 0)
            text = (f"Prism couldn't confirm your licence. It keeps working for "
                    f"about {days} more day{'s' if days != 1 else ''} — check "
                    f"this computer's internet connection.")
        elif state.status == licensing.TAMPERED:
            tone, icon_name = "#8a2f2f", "lock"
            text = (state.message
                    or "Prism can't verify this computer's licence.")
        else:                                   # EXPIRED or NONE
            tone, icon_name = "#8a2f2f", "lock"
            text = ("Your licence has ended. History and everything you've "
                    "already made are still here — new runs are paused until "
                    "it's renewed.")
        self._show_banner(text, tone, icon_name)

    def _show_banner(self, text: str, tone: str, icon_name: str):
        self._banner_icon.setPixmap(icons.pixmap(icon_name, 16, tone))
        self._banner_text.setText(text)
        self._banner_text.setStyleSheet(f"color: {tone}; font-size: 13px;")
        self.banner.setStyleSheet(
            f"QFrame#licenceBanner {{ background: {theme.NEUTRAL[100]};"
            f"border-bottom: 1px solid {theme.DIVIDER}; }}")
        self.banner.setVisible(True)

    def _open_license_dialog(self, mode: str = "change"):
        from dialogs.license_dialog import LicenseDialog
        LicenseDialog(self, mode=mode).exec()
        licensing.reload()
        self.refresh_licence_ui()

    def _work_column(self) -> QWidget:
        self.input_panel = InputPanel()
        self.agents_panel = AgentsPanel()
        self.output_panel = OutputPanel()

        # -- page 0: compose ------------------------------------------------
        compose_inner = QWidget()
        compose = QVBoxLayout(compose_inner)
        compose.setContentsMargins(0, 0, 0, 0)
        compose.setSpacing(18)
        compose.addWidget(self.input_panel)
        compose.addWidget(self.agents_panel)
        compose.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(compose_inner)

        # -- the stack ------------------------------------------------------
        self.work_stack = QStackedWidget()
        self.work_stack.addWidget(scroll)             # COMPOSE
        self.work_stack.addWidget(self.output_panel)  # RUNNING

        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.addWidget(self.work_stack)
        return wrap

    def _context_column(self) -> QWidget:
        self.files_panel = FilesPanel()
        self.prompt_panel = PromptPanel()

        rail = QFrame()
        rail.setObjectName("contextRail")
        rail.setFixedWidth(272)
        # Scoped by object name on purpose: an unscoped rule set on a parent
        # cascades into every descendant, which would draw this border down
        # the left edge of each child in the rail too.
        rail.setStyleSheet("QFrame#contextRail { border-left: 1px solid #d0d0d1; }")
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(18, 22, 18, 18)
        layout.setSpacing(20)
        layout.addWidget(self.files_panel)
        layout.addWidget(self.prompt_panel)
        layout.addStretch(1)

        tip = QLabel("Tip.  Click any step to leave it out, or click its tool "
                     "chip to run that step somewhere else.")
        tip.setObjectName("note")
        tip.setWordWrap(True)
        layout.addWidget(tip)
        return rail

    def _wire(self):
        self.sidebar.command_triggered.connect(self._handle_command)
        self.sidebar.favorite_chosen.connect(self._attach_path)
        self.sidebar.wakeword_toggled.connect(self.toggle_wakeword)

        self.input_panel.route_clicked.connect(self._route)
        self.input_panel.mic_toggle_clicked.connect(self._toggle_mic)
        self.input_panel.attach_file_clicked.connect(self._attach_file_dialog)
        self.input_panel.attach_folder_clicked.connect(self._attach_folder_dialog)
        self.input_panel.queue_changed.connect(self._on_queue_changed)

        self.files_panel.mention_accepted.connect(self._accept_mention)
        self.files_panel.mention_change_requested.connect(self._change_mention)
        self.files_panel.detach_requested.connect(self._detach)
        self.files_panel.detach_folder_requested.connect(self._detach_folder)
        self.files_panel.detach_all_requested.connect(self._detach_all)

        self.agents_panel.run_requested.connect(self._run_pipeline)
        self.output_panel.back_requested.connect(self._back_to_plan)
        self.output_panel.stop_requested.connect(self._stop_run)
        self.agents_panel.discard_requested.connect(self._discard_plan)

    # ── moving between the two pages ────────────────────────────────────────
    def _back_to_plan(self):
        """Leaving the results page. A run that finished has consumed its
        plan — every step in it has already been done, so handing it back
        with Start the work still armed invites re-running the whole thing by
        accident. Wipe it and start clean. A run that FAILED keeps its plan:
        there, retrying is the point."""
        if self._run_finished:
            self._reset_for_new_task()
        self.work_stack.setCurrentIndex(COMPOSE)

    def _reset_for_new_task(self):
        """Back to a blank workbench. Attachments survive on purpose — they're
        explicit choices sitting visibly in the rail with their own Detach
        button, and the next task usually concerns the same files."""
        self._run_finished = False
        self.routing = None
        self._last_query = ""
        self._stage_agents = {}
        self._stage_results = []
        self.pending_mentions = []
        # The queue belongs to the journey that just ended, not the next one.
        self._task_queue = []
        self._task_pos = 0
        self._task_runs = []
        self._queue_stopped = False
        self._auto_run = False
        self.input_panel.reset()
        self.agents_panel.clear()
        self.prompt_panel.clear()
        self.files_panel.clear_mentions()
        self.output_panel.set_finished(False)
        self.statusBar().showMessage("Ready for the next one.", 4000)

    def _on_queue_changed(self, count: int):
        if count:
            self.statusBar().showMessage(
                f"{count} task{'s' if count != 1 else ''} queued. Add more, or "
                "Show steps to start the first one.", 5000)

    # ── sidebar commands ─────────────────────────────────────────────────────
    def _handle_command(self, key: str):
        if key == "catalog":
            AIDirectoryDialog(self).exec()
        elif key == "guide":
            self._open_guide()
        elif key in ("agents", "profile", "key", "chrome", "licence",
                     "language", "team", "config"):
            self._open_setup(focus=key)
        elif key == "login":
            self._open_login_tabs()
        elif key == "status":
            self._show_status()
        elif key == "runs":
            self._show_runs()
        elif key == "email":
            self._open_email()
        elif key == "boq":
            self._open_boq()
        elif key == "inquiry":
            self._open_inquiry()

    def _authorized_then(self, feature: str, action: str, then):
        """Ask the licence server, then run `then()` if it said yes.

        Off the UI thread: it is a network round trip behind a click, and a
        frozen window reads as a crash. The cached `require()` check runs
        first as a fast path so an add-on the customer plainly does not own
        opens the pitch instantly instead of after a round trip.
        """
        if not licensing.require(feature, self):
            return
        self.statusBar().showMessage("Checking your licence…")

        def proceed(auth):
            self.statusBar().clearMessage()
            if not auth.allowed:
                if auth.code == "FEATURE_NOT_LICENSED":
                    licensing.require(feature, self)     # show the pitch
                else:
                    QMessageBox.warning(self, "Licence", auth.message)
                return
            then()

        worker = AuthorizeWorker(feature, action)
        worker.done.connect(proceed)
        self._workers.append(worker)
        worker.start()

    def _open_reel(self):
        self._authorized_then("reel", "addon", self._open_reel_dialog)

    def _open_reel_dialog(self):
        ok, err = CB.reel_available()
        if not ok:
            # FFmpeg specifically is something Prism can fix by itself, so it
            # gets an offer rather than an apology. Everything else missing
            # here (Pillow) is a broken install and needs a person.
            if "ffmpeg" in err.lower():
                self._offer_ffmpeg(then=self._open_reel_dialog)
                return
            QMessageBox.information(self, i18n.t("Reel"), err)
            return
        ReelDialog(self.cfg, self.attachments, self).exec()

    def _offer_ffmpeg(self, then=None):
        """Offer to fetch FFmpeg, then carry on with what they were doing.

        Windows does not ship FFmpeg and nobody installs it by accident, so
        before this the first Windows customer to press Reel was handed a
        codec install guide. A build now bundles it; this is the path for a
        build that somehow did not, and for anyone running from source.
        """
        answer = QMessageBox.question(
            self, i18n.t("Reel"),
            i18n.t("Making a video needs FFmpeg, a free standard program "
                   "that isn't part of Prism.\n\nPrism can download and set "
                   "it up for you — about 30 MB, roughly a minute, and it "
                   "only happens once.\n\nDownload it now?"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer != QMessageBox.Yes:
            return

        from PySide6.QtWidgets import QProgressDialog
        box = QProgressDialog(i18n.t("Downloading FFmpeg…"), "", 0, 100, self)
        box.setWindowTitle(i18n.t("Reel"))
        box.setCancelButton(None)      # a half-written binary helps nobody
        box.setAutoClose(False)
        box.setMinimumDuration(0)
        box.setValue(0)

        def moved(done: int, total: int):
            if total:
                box.setMaximum(100)
                box.setValue(int(100 * done / total))
            else:
                # No content-length. Show motion rather than a bar stuck at 0.
                box.setMaximum(0)
            box.setLabelText(i18n.t("Downloading FFmpeg… {mb} MB").replace(
                "{mb}", f"{done / 1e6:.0f}"))

        def finished(_path: str):
            box.close()
            self.statusBar().showMessage(
                i18n.t("FFmpeg is ready. Video will work from now on."), 6000)
            if then:
                then()

        def broke(message: str):
            box.close()
            self._explain(message, "run")

        worker = FFmpegWorker()
        worker.progress.connect(moved)
        worker.done.connect(finished)
        worker.failed.connect(broke)
        self._workers.append(worker)
        worker.start()

    def _open_inquiry(self):
        self._authorized_then("inbox", "addon", self._open_inquiry_dialog)

    def _open_inquiry_dialog(self):
        from dialogs.inquiry_dialog import InquiryDialog
        dialog = InquiryDialog(self.cfg, self)
        dialog.exec()
        # The dialog saves its own settings and its reading bookmark, so pick
        # up whatever it wrote rather than overwriting it from a stale copy on
        # the next Settings save.
        self.cfg = CB.config.load()

    def _open_boq(self):
        self._authorized_then("boq", "addon", self._open_boq_dialog)

    def _open_boq_dialog(self):
        # Dependency probe comes AFTER the licence check: a customer who
        # hasn't bought BOQ should be told that, not sent off to install ezdxf
        # for a feature they still won't be able to open.
        ok, err = CB.boq_available()
        if not ok:
            QMessageBox.information(
                self, "BOQ",
                "The BOQ add-on needs the ezdxf library to measure drawings:\n\n"
                "    pip install ezdxf\n\n"
                "A .dwg also needs a converter — `brew install libredwg` on "
                f"macOS.\n\nDetail: {err}")
            return
        BoqDialog(self.cfg, self.attachments, self).exec()

    def _open_email(self):
        self._authorized_then("email", "addon", self._open_email_dialog)

    def _open_email_dialog(self):
        if not CB.mailer.is_configured(self.cfg):
            dlg = EmailSetupDialog(self.cfg, self)
            if dlg.exec() != QDialog.Accepted:
                return
            self.cfg = dlg.cfg
        EmailComposeDialog(self.cfg, self.attachments, self).exec()

    def _open_setup(self, focus: str | None = None):
        """The rail links straight at individual settings, so pass along which
        one was asked for — Setup scrolls there rather than making the user
        find it."""
        dlg = SetupDialog(self.cfg, self, focus=focus)
        if dlg.exec() == QDialog.Accepted:
            self.cfg = dlg.cfg
            self.statusBar().showMessage("Setup saved.", 4000)

    def _first_run(self):
        self._welcome()
        if licensing.state().usable:
            self._open_setup()

    def _welcome(self):
        """Shown once, before Setup, on a machine that has never been set up.

        Setup asks for an API key from a service they have not heard of. Doing
        that cold is the moment a first-time user decides the software is for
        somebody else — so it is worth thirty seconds explaining what Prism is
        and offering the guide first.
        """
        from PySide6.QtWidgets import QMessageBox
        box = QMessageBox(self)
        box.setWindowTitle(i18n.t("Welcome to Prism"))
        box.setText(i18n.t("Prism does jobs for you using AI."))
        box.setInformativeText(i18n.t(
            "You describe a job in your own words — \u201cwrite a proposal "
            "for a 40-camera CCTV project\u201d — and Prism works out which "
            "AI tools are needed, uses them in order, and hands you the "
            "finished result.\n\n"
            "Setting up takes about five minutes and only happens once. "
            "Would you like a quick tour first?"))
        tour = box.addButton(i18n.t("Show me around"), QMessageBox.AcceptRole)
        box.addButton(i18n.t("Set up now"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is tour:
            self._open_guide()

    def _open_guide(self):
        """The guide, with its buttons wired back into the rail so reading
        about a thing and reaching it are the same gesture."""
        from dialogs.guide_dialog import GuideDialog
        dialog = GuideDialog(self)
        dialog.command_requested.connect(self._handle_command)
        dialog.exec()

    def _open_login_tabs(self):
        agents = CB.config.active_agents(self.cfg)
        if not agents:
            QMessageBox.information(self, "Login", "No agents configured yet — open Setup first.")
            return
        ok, err = CB.automation_available()
        if not ok:
            QMessageBox.warning(self, "Login", f"Automation deps not available: {err}")
            return
        automation = CB.get_automation()
        urls, seen = [], set()
        for name in agents.values():
            if name not in seen:
                urls.append(CB.agents.AGENT_REGISTRY[name]["url"])
                seen.add(name)
        automation.open_login_tabs(urls)
        self.statusBar().showMessage(
            i18n.t("Opened {n} login tab(s) in Chrome.").format(n=len(urls)),
            4000)

    def _show_status(self):
        agents = CB.config.active_agents(self.cfg)
        lines = [
            f"Profile: {self.cfg.get('profile') or '—'}",
            f"Groq key: {'set' if self.cfg.get('api_key') else 'NOT set'}",
            f"Chrome: {self.cfg.get('chrome_version') or 'auto-detect'}",
            "Agents:",
        ] + [f"  {cat}: {name}" for cat, name in agents.items()]
        QMessageBox.information(self, "Status", "\n".join(lines))

    def _show_runs(self):
        HistoryDialog(self).exec()

    # ── attachments ───────────────────────────────────────────────────────────
    def _explain(self, error: object, context: str = "") -> None:
        """Show a problem the way a first-time user needs to see it.

        Every failure the customer can meet goes through here rather than
        through a raw QMessageBox, so each one arrives as "here is what
        happened and here is what to do" — and so the technical text is
        logged even though it is not what fills the screen.

        The dialog can hand back an action, which is the difference between
        telling somebody to open Settings and taking them there.
        """
        from dialogs.problem_dialog import show_problem
        action = show_problem(self, error, context)
        if not action:
            return
        if action.startswith("settings:"):
            self._open_setup(focus=action.split(":", 1)[1])
        elif action == "login":
            self._open_login_tabs()
        elif action == "guide":
            self._open_guide()

    def _attach_path(self, path: str):
        """Take one file or folder into the run.

        The whole body is guarded, redrawing the panel included. It used to
        guard only the read: anything that went wrong while RENDERING the new
        row escaped the slot, Qt swallowed it, and the file appeared not to
        attach at all — no error, no row, nothing to go on. A failure here has
        to be visible, because an attachment silently not arriving is
        indistinguishable from a dead button.
        """
        if not path:
            return
        already = {a["path"] for a in self.attachments}
        try:
            if os.path.isdir(path):
                # Stamped with where they came from so the tray can show one
                # row for the folder and take the whole group back out again.
                # The engine still gets the flat list — it uploads files, not
                # folders — so this is presentation only.
                added = [{**a, "from_dir": path} for a in CB.files.attach_dir(path)]
            else:
                added = [CB.files.attach(path)]
        except Exception as e:                          # noqa: BLE001
            self._explain(e, "attach")
            return

        # Attaching a folder and then a file inside it used to queue the same
        # file twice, and every stage then uploaded it twice.
        fresh = [a for a in added if a["path"] not in already]
        if not fresh:
            self.statusBar().showMessage(
                i18n.t("Already attached."), 4000)
            return
        self.attachments.extend(fresh)
        try:
            self.files_panel.set_attached(self.attachments)
        except Exception as e:                          # noqa: BLE001
            # The read succeeded; only the drawing failed. Say so rather than
            # letting the exception escape the slot, where Qt swallows it and
            # the attachment appears simply not to have happened.
            QMessageBox.warning(self, "Attach", i18n.t(
                "Attached, but the list couldn't be drawn: {error}"
            ).format(error=e))
            return
        if len(fresh) == 1:
            self.statusBar().showMessage(i18n.t("Attached {name}.").format(
                name=fresh[0]["name"]), 4000)
        else:
            self.statusBar().showMessage(i18n.t(
                "Attached {n} files from {name}.").format(
                    n=len(fresh),
                    name=os.path.basename(path.rstrip(os.sep))), 4000)
        # A folder whose files were all already attached falls out above, at
        # the "Already attached" guard.

    def _attach_file_dialog(self):
        """Ask where the file is before asking which file.

        A plain file dialog can only offer the disk, and half of what a
        company wants to feed Prism lives in its Drive. The choice comes
        first, and is skipped entirely when Drive isn't set up in this build —
        an option that always fails is worse than no option.
        """
        # Every source is a folder on this machine — Drive for Desktop,
        # OneDrive and Dropbox all mount as one — so "pick a source" is really
        # "which folder should the chooser open in". That keeps the whole
        # feature to one extra menu and no credentials at all.
        try:
            import cloud
            places = cloud.sources()
        except Exception:                               # noqa: BLE001
            places = []

        start_in = ""
        if places:
            menu = QMenu(self)
            here = menu.addAction(i18n.t("This computer"))
            menu.addSeparator()
            for place in places:
                act = menu.addAction(place["label"])
                act.setData(place["path"])
            chosen = menu.exec(QCursor.pos())
            if chosen is None:
                return                                  # dismissed the menu
            if chosen is not here:
                start_in = chosen.data() or ""

        # One chooser either way. Opening it INSIDE the cloud folder is the
        # whole trick: from there it behaves exactly like picking any other
        # file, and nothing downstream needs to know where it came from.
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.t("Attach a file"), start_in)
        if path:
            self._attach_path(path)
        else:
            # Distinguishes "you closed the chooser" from "the chooser never
            # opened" and from "attaching failed" — three very different bugs
            # that otherwise all look like a button that does nothing.
            self.statusBar().showMessage(i18n.t("No file chosen."), 3000)

    def _attach_from_drive(self):
        """Pick from Drive, download, then hand the local path to the same
        attach path a local file takes — nothing downstream knows the
        difference."""
        from dialogs.drive_dialog import DriveDialog
        picker = DriveDialog(self)
        if picker.exec() == QDialog.Accepted and picker.path:
            self._attach_path(picker.path)
            self.statusBar().showMessage(
                i18n.t("Brought {name} down from Google Drive.").format(
                    name=os.path.basename(picker.path)), 5000)

    def _attach_folder_dialog(self):
        path = QFileDialog.getExistingDirectory(self, i18n.t("Attach a folder"))
        if path:
            self._attach_path(path)

    def _detach(self, path: str):
        self.attachments = [a for a in self.attachments if a["path"] != path]
        self.files_panel.set_attached(self.attachments)

    def _detach_folder(self, folder: str):
        """Take a whole "Add folder" back out in one go.

        A folder is attached as its individual files, so before this the only
        way to undo one was to select and detach fifteen rows by hand — and
        Prism would have uploaded all fifteen to every tool in the meantime.
        """
        keep = [a for a in self.attachments if a.get("from_dir") != folder]
        removed = len(self.attachments) - len(keep)
        self.attachments = keep
        self.files_panel.set_attached(self.attachments)
        if removed:
            where = os.path.basename(folder.rstrip(os.sep))
            self.statusBar().showMessage(
                (i18n.t("Detached 1 file from {name}.").format(name=where)
                 if removed == 1 else
                 i18n.t("Detached {n} files from {name}.").format(
                     n=removed, name=where)), 4000)

    def _detach_all(self):
        if not self.attachments:
            return
        count = len(self.attachments)
        self.attachments = []
        self.files_panel.set_attached(self.attachments)
        self.statusBar().showMessage(
            (i18n.t("Detached the one attached file.") if count == 1
             else i18n.t("Detached all {n} files.").format(n=count)), 4000)

    # ── voice: record → interpret → resolve mentions ─────────────────────────
    def _toggle_mic(self):
        if self._record_worker is None:
            if not self.cfg.get("api_key"):
                QMessageBox.warning(self, "Voice", "Set your Groq API key in Setup first.")
                self.input_panel.set_recording(False)
                return
            ok, why = wakeword.available()
            if not ok:
                QMessageBox.warning(self, "Voice", why)
                self.input_panel.set_recording(False)
                return
            self._record_worker = RecordWorker(self.cfg)
            self._record_worker.done.connect(self._on_transcribed)
            self._record_worker.failed.connect(self._on_voice_failed)
            self._record_worker.start()
            self.input_panel.set_recording(True)
            self.input_panel.append_status("Recording — press Stop when you're done…")
        else:
            self._record_worker.stop()
            self.input_panel.set_recording(False)
            self.input_panel.append_status("Transcribing…")

    def _on_transcribed(self, text: str, lang: str):
        self._record_worker = None
        if not text:
            self.input_panel.append_status("Didn't catch anything — try again, or type.")
            return
        note = f"  ({lang})" if lang and lang != "english" else ""
        self.input_panel.append_status(f'Heard: "{text}"{note}')
        worker = InterpretWorker(text, self.cfg)
        worker.done.connect(self._on_interpreted)
        worker.failed.connect(lambda e: self._on_interpreted(
            {"cleaned": text, "files": [], "task": text, "ok": False}))
        self._workers.append(worker)
        worker.start()

    def _on_voice_failed(self, error: str):
        self._record_worker = None
        self.input_panel.set_recording(False)
        QMessageBox.warning(self, "Voice", f"Recording/transcription failed: {error}")

    def _on_interpreted(self, intent: dict):
        if not intent.get("ok", True):
            self.input_panel.append_status(
                "Interpreter unavailable — using your words as-is; "
                "mention any file manually with Add file.")
        self.input_panel.set_query_text(intent.get("task") or intent.get("cleaned") or "")
        self.pending_mentions = []
        self.files_panel.clear_mentions()
        for desc in intent.get("files") or []:
            self._resolve_mention(desc)

    def _resolve_mention(self, description: str):
        worker = FindWorker(description, self.cfg)
        index = len(self.pending_mentions)
        self.pending_mentions.append({"description": description, "path": None, "kind": None})

        def on_done(res: dict):
            path = res.get("dir") if not res.get("files") else (res["files"][0] if res["files"] else None)
            kind = "folder" if (path and not res.get("files")) else ("file" if path else None)
            self.pending_mentions[index]["path"] = path
            self.pending_mentions[index]["kind"] = kind
            self.files_panel.add_mention(index, description, path or "", kind or "?")

        worker.done.connect(on_done)
        worker.failed.connect(lambda e: self.files_panel.add_mention(index, description, "", "?"))
        self._workers.append(worker)
        worker.start()

    def _accept_mention(self, index: int):
        m = self.pending_mentions[index]
        if m["path"]:
            self._attach_path(m["path"])

    def _change_mention(self, index: int):
        path = QFileDialog.getExistingDirectory(self, i18n.t("Pick the right folder…"))
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, i18n.t("…or pick the right file"))
        if path:
            self._attach_path(path)

    # ── routing ───────────────────────────────────────────────────────────────
    def _route(self, query: str):
        """Start the journey. The button hands over whatever is in the box,
        but the queue is the real source of truth — the box is only its last
        entry (see InputPanel.tasks).

        `query` still wins when the panel has nothing, so callers that drive
        the window directly — the wake word, a remote prompt, the tests —
        keep working without going through the text box.
        """
        tasks = self.input_panel.tasks() or (
            [query] if query and query.strip() else [])
        if not tasks:
            self.statusBar().showMessage("Type or speak a task first.", 4000)
            return
        self._task_queue = tasks
        self._task_pos = 0
        self._task_runs = []
        self._queue_stopped = False
        self._plan_task(0)

    def _plan_task(self, index: int):
        """Plan task `index` of the queue. Every task goes through this, so a
        single task is just a queue of one and there is no second code path to
        keep in step."""
        self._task_pos = index + 1
        self._route_one(self._task_queue[index])

    def _route_one(self, query: str):
        if not query.strip():
            self.statusBar().showMessage("Type or speak a task first.", 4000)
            return
        if not licensing.require("core", self):
            return
        if not CB.config.is_configured(self.cfg):
            QMessageBox.warning(self, "Setup needed", "Finish Setup (API key + agents) first.")
            return
        self._last_query = query
        if len(self._task_queue) > 1:
            self.statusBar().showMessage(
                f"Planning task {self._task_pos} of {len(self._task_queue)}…", 0)
        self.input_panel.set_busy(True)
        # Planning is itself a Groq call — it costs tokens and is the step
        # every run begins with — so it is authorised and metered like one.
        # Gating only "Start the work" left the whole planning path reachable
        # with the licence server unreachable, which is not what live
        # authorisation is supposed to mean.
        # action="plan", not "run": planning is the billable step (three Groq
        # calls) and the one the daily allowance counts. The pipeline that
        # follows is browser automation against the customer's own logins and
        # costs us nothing, so counting both would burn two units per journey.
        auth_worker = AuthorizeWorker("core", "plan")
        auth_worker.done.connect(lambda result: self._start_route(result, query))
        self._workers.append(auth_worker)
        auth_worker.start()

    def _start_route(self, auth, query: str):
        """Second half of _route, once the server has said yes."""
        if not auth.allowed:
            # A refusal will refuse identically for every task behind this
            # one, so stop the queue rather than firing N hopeless requests
            # at the licence server.
            self._queue_stopped = True
            self.input_panel.set_busy(False)
            self.input_panel.set_state("ready")
            QMessageBox.warning(self, "Licence", auth.message)
            self._finish_queue()
            return
        self._run_id = getattr(auth, "run_id", "")
        if getattr(auth, "offline", False):
            # Authorised from the cached lease because the server could not be
            # reached. Say so, and do not stop: an arbitrary network failure is
            # not a licence failure, and the whole point of the offline window
            # is that the customer keeps working through it. A status message
            # rather than a dialog — nothing here needs a decision from them.
            self.statusBar().showMessage(
                i18n.t("Working offline — Prism couldn't reach the licence "
                       "server, so it's using this computer's saved "
                       "authorisation."), 8000)
        worker = RouteWorker(query, self.cfg, self.attachments)
        worker.done.connect(self._on_routed)
        worker.failed.connect(self._on_route_failed)
        self._workers.append(worker)
        worker.start()

    def _on_routed(self, routing: dict):
        self.input_panel.set_busy(False)
        # The router's Groq calls are already counted by licensing/meter.py;
        # send them now rather than waiting for a run that may never happen.
        licensing.report_usage(getattr(self, "_run_id", ""))
        self.input_panel.set_state("planned")
        self.routing = routing
        agents_cfg = CB.config.active_agents(self.cfg)
        self.prompt_panel.set_content(self._last_query, routing, agents_cfg)
        self.agents_panel.set_content(routing, agents_cfg)
        self.work_stack.setCurrentIndex(COMPOSE)
        # Tasks 2..n were authorised by the same "Start the work" press as
        # task 1 — stopping to ask again for each would defeat the point of
        # queueing them. Only the first plan is offered for review.
        if self._auto_run:
            self.statusBar().showMessage(
                f"Task {self._task_pos} of {len(self._task_queue)} — starting…",
                4000)
            self._run_pipeline()
            return
        total = len(self._task_queue)
        self.statusBar().showMessage(
            "Steps ready — drop any you don't want, then Start the work."
            if total <= 1 else
            f"Steps ready for task 1 of {total}. Start the work and Prism will "
            f"run all {total} in order.", 8000)

    def _on_route_failed(self, error: str):
        self.input_panel.set_busy(False)
        self.input_panel.set_state("ready")
        # Mid-queue a planning failure is one bad task, not a dead run — record
        # it and carry on, the same way a failed stage doesn't end a pipeline.
        if self._auto_run and self._task_pos < len(self._task_queue):
            self._record_task_run(failed=f"Planning failed: {error}")
            self.statusBar().showMessage(
                f"Task {self._task_pos} couldn't be planned — moving on.", 6000)
            self._advance_queue()
            return
        self._explain(error, "plan")

    # ── running the pipeline ────────────────────────────────────────────────
    def _run_pipeline(self):
        if not self.routing:
            return
        if not licensing.require("core", self):
            return
        # Pressing Start the work commits the whole queue, not just the plan on
        # screen. From here every later task plans and runs without stopping.
        self._auto_run = True
        run_agents = self.agents_panel.selected_agents()
        if not run_agents:
            QMessageBox.information(self, "Run", "Every step is switched off — "
                                                 "turn at least one back on.")
            return

        # The router can put a paid add-on into a plan without the customer
        # ever opening it from the rail, so the entitlement has to be checked
        # here too. Offer to run everything else rather than refusing outright:
        # losing one step is a far better outcome than losing the whole run.
        locked = {stage: name for stage, name in run_agents.items()
                  if AGENT_FEATURES.get(name)
                  and not licensing.has(AGENT_FEATURES[name])}
        if locked:
            names = ", ".join(sorted(set(locked.values())))
            answer = QMessageBox.question(
                self, "Not in your licence",
                (i18n.t("{tools} isn't part of your licence, so those steps "
                        "can't run.\n\nRun the rest of the steps without them?")
                 if len(locked) > 1 else
                 i18n.t("{tools} isn't part of your licence, so that step "
                        "can't run.\n\nRun the rest of the steps without it?")
                 ).format(tools=names),
                QMessageBox.Yes | QMessageBox.Cancel)
            if answer != QMessageBox.Yes:
                # Straight to the pitch — they have just told us they want it.
                licensing.require(AGENT_FEATURES[next(iter(locked.values()))], self)
                return
            run_agents = {stage: name for stage, name in run_agents.items()
                          if stage not in locked}
            if not run_agents:
                QMessageBox.information(
                    self, "Run", "Every step here needs an add-on that "
                                 "isn't in your licence.")
                return
        # Prism Studio needs a browser engine the rest of Prism does not. Say
        # so before the run rather than at the last stage, an hour of tool
        # calls later — and offer the renderer that does work.
        if "Prism Studio" in run_agents.values():
            ok, why = CB.studio_available()
            if not ok:
                answer = QMessageBox.question(
                    self, "Prism Studio",
                    i18n.t("{why}\n\nRun with the fixed house style "
                           "(Prism Reel) instead?").format(why=why),
                    QMessageBox.Yes | QMessageBox.Cancel)
                if answer != QMessageBox.Yes:
                    return
                run_agents = {k: ("Prism Reel" if v == "Prism Studio" else v)
                              for k, v in run_agents.items()}

        # Ask the licence server, live, before committing to the run. This is
        # the ONLY place a run is authorised — never again once it is moving,
        # because a pipeline is tens of minutes of browser automation and
        # killing it half way for a transient reason throws away real work.
        self.agents_panel.set_run_enabled(False)
        self.statusBar().showMessage("Checking your licence…")
        auth_worker = AuthorizeWorker("core", "run")
        auth_worker.done.connect(
            lambda result: self._start_run(result, run_agents))
        self._workers.append(auth_worker)
        auth_worker.start()

    def _start_run(self, auth, run_agents: dict):
        """Second half of _run_pipeline, once the server has said yes."""
        self.statusBar().clearMessage()
        if not auth.allowed:
            # Same reasoning as the planning refusal: it will say no to every
            # remaining task too, so end the queue instead of grinding through.
            self._queue_stopped = True
            self.agents_panel.set_run_enabled(True)
            QMessageBox.warning(self, "Licence", auth.message)
            self._finish_queue()
            return

        self._run_id = getattr(auth, "run_id", "")
        cfg_for_run = dict(self.cfg)
        cfg_for_run["agents"] = run_agents
        self.output_panel.clear()
        self._stage_agents = {}
        self._stage_results = []
        self.input_panel.set_state("running")
        self._run_finished = False
        self.output_panel.set_finished(False)
        self.output_panel.set_running(True)
        self.work_stack.setCurrentIndex(RUNNING)
        worker = AutomationWorker(self.routing, cfg_for_run, self.attachments, self._last_query)
        # Hold the machine awake for the duration. A run is tens of minutes
        # and the whole promise is that you walk away — a laptop that sleeps
        # halfway through takes the browser session with it.
        awake.acquire()
        self._active_run = worker
        worker.stage_event.connect(self._on_stage_event)
        worker.done.connect(self._on_run_done)
        worker.failed.connect(self._on_run_failed)
        self._workers.append(worker)
        worker.start()

    def _discard_plan(self):
        """Throw away a plan the customer doesn't want.

        Attachments survive on purpose — they are explicit choices sitting
        visibly in the rail with their own Detach button, and the next task is
        usually about the same files.
        """
        if QMessageBox.question(
                self, "Discard these steps",
                "Throw these steps away and clear the task?\n\n"
                "Files you've attached stay attached.",
                QMessageBox.Yes | QMessageBox.Cancel) != QMessageBox.Yes:
            return
        self._reset_for_new_task()

    def _stop_run(self):
        """Ask the running pipeline to wind up.

        Deliberately not a thread kill: the engine polls a flag between stages
        and inside its waits, so it stops at a safe point and keeps every step
        that already finished. Terminating the QThread instead would abandon a
        live Chrome session and lose completed output — the exact work the
        customer is trying to protect by stopping.
        """
        worker = getattr(self, "_active_run", None)
        if worker is None or not worker.isRunning():
            return
        worker.stop()
        self.statusBar().showMessage(
            "Stopping — finishing the current step, keeping what's done…", 0)

    def _on_stage_event(self, kind: str, payload: dict):
        stage = payload.get("stage", "")
        if kind == "cancelled":
            done = payload.get("done", 0)
            self.statusBar().showMessage(
                f"Stopped. {done} step{'s' if done != 1 else ''} finished and "
                f"kept." if done else "Stopped before anything ran.", 8000)
            return
        if kind == "stage_start":
            agent = payload.get("agent", "")
            self._stage_agents[stage] = agent
            self.output_panel.stage_started(stage, agent)
        elif kind == "waiting":
            self.output_panel.stage_waiting(stage, payload.get("seconds", 0))
        elif kind == "stage_done":
            texts = payload.get("texts") or []
            url = payload.get("url", "")
            timed_out = bool(payload.get("timed_out"))
            self.output_panel.stage_done(stage, texts, url, timed_out)
            if texts:
                snippet = (texts[0][:150] + "…") if len(texts[0]) > 150 else texts[0]
            elif timed_out:
                snippet = "still generating in the tool — open the link"
            else:
                snippet = "no response captured"
            self._stage_results.append({
                "stage": stage, "agent": self._stage_agents.get(stage, "?"),
                "text": "\n\n---\n\n".join(texts), "url": url,
                "snippet": snippet, "ok": bool(texts), "timed_out": timed_out,
            })
            # Metering: which tool ran which stage. No prompt text, no output —
            # see licensing/meter.py for why that line is drawn hard.
            licensing.meter.record(
                "stage", tool=self._stage_agents.get(stage, ""), stage=stage,
                ok=bool(texts))
        elif kind == "stage_failover":
            # A tool could not finish and Prism is handing the step to another
            # one. Said out loud rather than done quietly: the customer is
            # about to wait several more minutes, and a screen that sits still
            # for that long without explaining itself reads as a hang.
            failed = payload.get("failed", "the tool")
            agent = payload.get("agent", "")
            why = ("has hit its usage limit" if payload.get("exhausted")
                   else "couldn't finish")
            self._stage_agents[stage] = agent
            self.statusBar().showMessage(
                i18n.t("{failed} {why} — trying {agent} instead…")
                .replace("{failed}", failed).replace("{why}", why)
                .replace("{agent}", agent), 15000)
            self.output_panel.stage_started(stage, agent)
        elif kind == "stage_recovered":
            texts = payload.get("texts") or []
            url = payload.get("url", "")
            agent = payload.get("agent", "")
            self.output_panel.stage_done(stage, texts, url, False)
            # Replace the failed record rather than appending a second one, or
            # the completion popup lists the step twice — once failed, once
            # done — and the customer cannot tell which one they got.
            record = {
                "stage": stage, "agent": agent,
                "text": "\n\n---\n\n".join(texts), "url": url,
                "snippet": (texts[0][:150] + "…") if texts and len(texts[0]) > 150
                           else (texts[0] if texts else ""),
                "ok": True, "timed_out": False,
                # Kept for History: which tool was asked first, and why the
                # answer came from somewhere other than the plan said.
                "failover_from": payload.get("failed", ""),
            }
            for i, existing in enumerate(self._stage_results):
                if existing.get("stage") == stage and not existing.get("ok"):
                    self._stage_results[i] = record
                    break
            else:
                self._stage_results.append(record)
            licensing.meter.record("stage", tool=agent, stage=stage, ok=True)
            self.statusBar().showMessage(
                i18n.t("{agent} finished the {stage} step.")
                .replace("{agent}", agent).replace("{stage}", stage), 8000)
        elif kind == "stage_unrecovered":
            self.statusBar().showMessage(
                i18n.t("No other tool could finish the {stage} step either.")
                .replace("{stage}", stage), 10000)
        elif kind == "stage_error":
            error = payload.get("error", "")
            licensing.meter.record(
                "stage", tool=self._stage_agents.get(stage, ""), stage=stage,
                ok=False)
            # The engine hands back the tab it died on whenever there is one —
            # a slow tool often finishes server-side after we stopped waiting,
            # so the link is kept and offered even on a failed step.
            url = payload.get("url", "")
            self.output_panel.stage_error(stage, error, url)
            self._stage_results.append({
                "stage": stage, "agent": self._stage_agents.get(stage, "?"),
                "text": error, "url": url,
                "snippet": f"failed: {error[:120]}", "ok": False,
            })

    def _save_run(self, responses: dict | None = None, links: dict | None = None,
                  error: str = ""):
        """Persist the run to ~/.prism/runs, the same place and shape the CLI
        writes — it's what the History dialog reads, and until now only the
        CLI ever wrote there, so nothing done in the GUI was ever kept.

        Failures are swallowed to the status bar on purpose: the run itself
        succeeded, and a full disk shouldn't turn that into an error dialog."""
        if responses is None or links is None:
            # A failed run has no engine return value — rebuild what did land
            # from the per-stage events we collected on the way.
            responses = {r["stage"]: [r["text"]] for r in self._stage_results if r["ok"]}
            links = {r["stage"]: r["url"] for r in self._stage_results if r.get("url")}
        record = {
            "query": getattr(self, "_last_query", ""),
            "routing": self.routing or {},
            "responses": responses or {},
            "links": links or {},
            # names, not dicts — matches what prism.py writes
            "attachments": [a["name"] for a in self.attachments],
            # not in the CLI's record: which tool actually ran each step, so
            # History can name them instead of showing bare stage keys
            "agents": dict(self._stage_agents),
        }
        if error:
            record["error"] = error
        # Stamped with who ran it, so a run file is self-describing even if it
        # is later copied out of its folder — the manager's History shows a
        # name against the work rather than inferring one from the path.
        me = identity.current()
        record["member"] = {"mid": me["mid"], "name": me["name"],
                            "role": me["role"]}
        try:
            # Always the REAL member, never identity.viewing(): an admin
            # reading someone else's profile and then starting a run must file
            # that run under themselves, not under the person they were
            # looking at.
            CB.config.save_run(record, workspace.runs_dir(me["mid"], self.cfg))
        except Exception as e:
            self.statusBar().showMessage(f"Couldn't save this run to history: {e}", 8000)

    # ── the task queue ───────────────────────────────────────────────────────
    def _record_task_run(self, failed: str = ""):
        """Bank the task that just ended, so its stages survive the reset at
        the top of the next run. This is the whole reason the queue works:
        _stage_results is emptied for every run, and without copying it out
        first, task 1's results would be gone before task 2 finished."""
        self._task_runs.append({
            "task": getattr(self, "_last_query", ""),
            "index": self._task_pos,
            "stages": list(self._stage_results),
            "error": failed,
        })

    def _more_tasks(self) -> bool:
        return (not self._queue_stopped
                and self._task_pos < len(self._task_queue))

    def _advance_queue(self):
        """Plan and run the next queued task."""
        if not self._more_tasks():
            self._finish_queue()
            return
        nxt = self._task_pos          # _task_pos is 1-based, so this is the next index
        self.statusBar().showMessage(
            f"Task {nxt} done — planning task {nxt + 1} of "
            f"{len(self._task_queue)}…", 5000)
        self._plan_task(nxt)

    def _finish_queue(self):
        """Every task is done (or the queue was cut short). Show one window
        covering all of them."""
        self._auto_run = False
        self.input_panel.clear_queue()
        groups = [g for g in self._task_runs if g["stages"] or g["error"]]
        if not groups:
            if not self._queue_stopped:
                QMessageBox.information(
                    self, "Finished",
                    "No step produced output — check the results above.")
            return
        # One task behaves exactly as before: a flat list, no task headings.
        if len(groups) == 1:
            CompletionDialog(groups[0]["stages"], self).exec()
        else:
            CompletionDialog(groups[0]["stages"], self, task_groups=groups).exec()

    def _on_run_done(self, responses: dict, links: dict):
        awake.release()
        stopped = bool(getattr(self, "_active_run", None)
                       and self._active_run.stopping())
        self._active_run = None
        self.agents_panel.set_run_enabled(True)
        self.input_panel.set_state("done")
        self._run_finished = True
        self.output_panel.set_finished(True)
        self.output_panel.set_running(False)
        licensing.report_usage(getattr(self, "_run_id", ""))
        self._save_run(responses, links)
        self._record_task_run()

        if stopped:
            # Stop means stop the lot. Pressing it to escape one bad task and
            # then watching four more start would be the opposite of what the
            # button says — but everything already finished is still shown.
            self._queue_stopped = True
            self.statusBar().showMessage(
                "Stopped — everything finished so far is saved to History.",
                8000)
            self._finish_queue()
            return

        if self._more_tasks():
            self._advance_queue()
            return

        self.statusBar().showMessage("All done — saved to History.", 6000)
        self._finish_queue()

    def _on_run_failed(self, error: str):
        awake.release()
        self._active_run = None
        self.agents_panel.set_run_enabled(True)
        self.output_panel.set_running(False)
        self.input_panel.set_state("planned")
        # A failed run is still consumption — it drove browsers and spent Groq
        # tokens — and it is the more interesting half of the usage data.
        licensing.report_usage(getattr(self, "_run_id", ""))
        # Kept too — a run that broke halfway is exactly the one you want to
        # go back and read later.
        self._save_run(error=error)
        self._record_task_run(failed=error)

        # Tasks are independent, so one broken pipeline is not a reason to
        # abandon the four the customer queued behind it. Report it in the
        # status bar rather than a modal — a dialog per failure in a ten-task
        # queue would need ten dismissals before anything else could run.
        if self._more_tasks():
            self.statusBar().showMessage(
                f"Task {self._task_pos} failed ({error}) — carrying on.", 8000)
            self._advance_queue()
            return

        self._explain(error, "run")
        self._finish_queue()

    # ── wake word ─────────────────────────────────────────────────────────────
    def toggle_wakeword(self, on: bool):
        if on:
            if not self.cfg.get("api_key"):
                QMessageBox.warning(self, "Wake word", "Set your Groq API key in Setup first.")
                self.sidebar.set_listening(False)
                return
            # Packaged builds ship without PortAudio (it's a system library, not
            # a wheel), so say what's missing instead of failing silently.
            ok, why = wakeword.available()
            if not ok:
                QMessageBox.warning(self, "Wake word", why)
                self.sidebar.set_listening(False)
                return
            self._wake_listener = WakeWordListener(self.cfg)
            self._wake_listener.heard.connect(self._on_wake_heard)
            self._wake_listener.error.connect(
                lambda e: QMessageBox.warning(self, "Wake word", e))
            self._wake_listener.start()
            self.statusBar().showMessage('Listening for "Prism"…')
        elif self._wake_listener:
            _retire_listener(self._wake_listener)
            self._wake_listener = None
            self.statusBar().showMessage("Wake word off.", 3000)

    def _on_wake_heard(self):
        self.statusBar().showMessage('Heard "Prism" — starting a take…', 3000)
        if self._record_worker is None:
            self._toggle_mic()

    def closeEvent(self, event):
        if self._wake_listener:
            # Longer than the toggle case: the app is going away, so a brief
            # stall costs nothing, while a listener still running when the
            # process tears down is the abort itself.
            _retire_listener(self._wake_listener, wait_ms=8000)
            self._wake_listener = None
        # Anything metered but not yet sent — a run that ended just before the
        # window closed, or events buffered while the server was unreachable.
        licensing.report_usage(getattr(self, "_run_id", ""))
        # An unbalanced acquire (window closed mid-run) would otherwise leave
        # `caffeinate` alive after Prism has gone, and the machine would never
        # sleep again until reboot.
        awake.release_all()
        # Every worker still running has to be stopped and JOINED before the
        # process is allowed to tear down.
        #
        # Skipping this does not leak quietly — it aborts. Qt's ~QThread calls
        # qFatal() on a thread that is still running, and PySide destroys every
        # QThread during interpreter shutdown, so closing Prism mid-run ends in
        # "Python quit unexpectedly" with a macOS crash report. The user sees a
        # crash; the log's last line is a perfectly ordinary "Prism closed".
        #
        # Reported as exactly that: a Studio run was four seconds into a
        # ChatGPT stage when the window closed, and Prism aborted.
        self._retire_workers()
        diagnostics.write("INFO", "--- Prism closed ---")
        event.accept()

    # How long to wait for a worker to notice it should stop. A routed run is
    # inside a Selenium poll that can be several seconds wide, so a short wait
    # would time out and abort anyway; ten seconds covers the widest of them.
    _WORKER_WAIT_MS = 10_000

    def _retire_workers(self):
        """Ask every live worker to stop, then wait for it.

        Ordered stop-all-then-wait-all rather than stop-and-wait each: the
        waits then overlap, so three stuck workers cost ten seconds between
        them instead of thirty.
        """
        live = [w for w in self._workers if w is not None and _is_running(w)]
        if not live:
            return
        diagnostics.write("INFO", f"stopping {len(live)} worker(s) before exit")

        for worker in live:
            stop = getattr(worker, "stop", None)
            if callable(stop):
                try:
                    stop()
                except Exception:               # noqa: BLE001
                    pass    # a worker that cannot be asked still gets waited on

        for worker in live:
            try:
                if not worker.wait(self._WORKER_WAIT_MS):
                    # Out of options. terminate() is unsafe in general, but the
                    # alternative here is a guaranteed abort a moment later, and
                    # a killed thread in a process that is exiting anyway can
                    # corrupt nothing that outlives it.
                    diagnostics.write(
                        "WARN", f"{type(worker).__name__} did not stop in "
                                f"{self._WORKER_WAIT_MS}ms — terminating it")
                    worker.terminate()
                    worker.wait(2000)
            except RuntimeError:
                pass        # already gone; nothing to wait for
        self._workers.clear()
