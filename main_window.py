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
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QFont
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QMessageBox, QFrame,
    QFileDialog, QDialog, QLabel, QScrollArea, QStackedWidget, QPushButton,
)

import core_bridge as CB
import licensing
import theme
from widgets import icons
from widgets.sidebar import Sidebar
from widgets.input_panel import InputPanel
from widgets.files_panel import FilesPanel
from widgets.prompt_panel import PromptPanel
from widgets.agents_panel import AgentsPanel
from widgets.output_panel import OutputPanel
from workers import (RouteWorker, AutomationWorker, RecordWorker,
                     InterpretWorker, FindWorker, AuthorizeWorker)
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

        self._build_ui()
        self._wire()
        self.refresh_licence_ui()

        # Only nag about setup once the licence is sorted — a customer who
        # cannot use Prism yet does not need a Groq key dialog on top.
        if licensing.state().usable and not CB.config.is_configured(self.cfg):
            self._open_setup()

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

        self.statusBar().showMessage("Ready.")

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
        """Repaint everything that depends on the licence: the banner, and the
        locks in the rail. Called at startup and after any licence change."""
        state = licensing.state()
        self.sidebar.set_entitlements(state.features, state.usable)

        if state.status == licensing.VALID:
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

        self.files_panel.mention_accepted.connect(self._accept_mention)
        self.files_panel.mention_change_requested.connect(self._change_mention)
        self.files_panel.detach_requested.connect(self._detach)

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
        self.input_panel.reset()
        self.agents_panel.clear()
        self.prompt_panel.clear()
        self.files_panel.clear_mentions()
        self.output_panel.set_finished(False)
        self.statusBar().showMessage("Ready for the next one.", 4000)

    # ── sidebar commands ─────────────────────────────────────────────────────
    def _handle_command(self, key: str):
        if key == "catalog":
            AIDirectoryDialog(self).exec()
        elif key in ("agents", "profile", "key", "chrome", "licence", "config"):
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
            QMessageBox.information(self, "Reel", err)
            return
        ReelDialog(self.cfg, self.attachments, self).exec()

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
        self.statusBar().showMessage(f"Opened {len(urls)} login tab(s) in Chrome.", 4000)

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
    def _attach_path(self, path: str):
        try:
            if os.path.isdir(path):
                added = CB.files.attach_dir(path)
                self.attachments.extend(added)
            else:
                self.attachments.append(CB.files.attach(path))
        except Exception as e:
            QMessageBox.warning(self, "Attach", f"Couldn't attach {path}: {e}")
            return
        self.files_panel.set_attached(self.attachments)

    def _attach_file_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Attach a file")
        if path:
            self._attach_path(path)

    def _attach_folder_dialog(self):
        path = QFileDialog.getExistingDirectory(self, "Attach a folder")
        if path:
            self._attach_path(path)

    def _detach(self, path: str):
        self.attachments = [a for a in self.attachments if a["path"] != path]
        self.files_panel.set_attached(self.attachments)

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
        path = QFileDialog.getExistingDirectory(self, "Pick the right folder…")
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "…or pick the right file")
        if path:
            self._attach_path(path)

    # ── routing ───────────────────────────────────────────────────────────────
    def _route(self, query: str):
        if not query.strip():
            self.statusBar().showMessage("Type or speak a task first.", 4000)
            return
        if not licensing.require("core", self):
            return
        if not CB.config.is_configured(self.cfg):
            QMessageBox.warning(self, "Setup needed", "Finish Setup (API key + agents) first.")
            return
        self._last_query = query
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
            self.input_panel.set_busy(False)
            self.input_panel.set_state("ready")
            QMessageBox.warning(self, "Licence", auth.message)
            return
        self._run_id = getattr(auth, "run_id", "")
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
        self.statusBar().showMessage(
            "Plan ready — drop any step you don't want, then Start the work.", 6000)

    def _on_route_failed(self, error: str):
        self.input_panel.set_busy(False)
        self.input_panel.set_state("ready")
        QMessageBox.warning(self, "Planning failed", error)

    # ── running the pipeline ────────────────────────────────────────────────
    def _run_pipeline(self):
        if not self.routing:
            return
        if not licensing.require("core", self):
            return
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
                f"{names} isn't part of your licence, so "
                f"{'those steps' if len(locked) > 1 else 'that step'} can't run."
                f"\n\nRun the rest of the plan without "
                f"{'them' if len(locked) > 1 else 'it'}?",
                QMessageBox.Yes | QMessageBox.Cancel)
            if answer != QMessageBox.Yes:
                # Straight to the pitch — they have just told us they want it.
                licensing.require(AGENT_FEATURES[next(iter(locked.values()))], self)
                return
            run_agents = {stage: name for stage, name in run_agents.items()
                          if stage not in locked}
            if not run_agents:
                QMessageBox.information(
                    self, "Run", "Every step in this plan needs an add-on that "
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
                    f"{why}\n\nRun with the fixed house style (Prism Reel) "
                    "instead?",
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
            self.agents_panel.set_run_enabled(True)
            QMessageBox.warning(self, "Licence", auth.message)
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
                self, "Discard this plan",
                "Throw this plan away and clear the task?\n\n"
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
        try:
            CB.config.save_run(record)
        except Exception as e:
            self.statusBar().showMessage(f"Couldn't save this run to history: {e}", 8000)

    def _on_run_done(self, responses: dict, links: dict):
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

        if stopped:
            # A stopped run still produced whatever finished before it, and
            # that is worth keeping and showing — the customer stopped it
            # because of what came next, not to throw away what came before.
            self.statusBar().showMessage(
                "Stopped — everything finished so far is saved to History.",
                8000)
            if self._stage_results:
                CompletionDialog(self._stage_results, self).exec()
            return

        self.statusBar().showMessage("All done — saved to History.", 6000)
        if self._stage_results:
            CompletionDialog(self._stage_results, self).exec()
        else:
            QMessageBox.information(self, "Finished",
                                    "No step produced output — check the results above.")

    def _on_run_failed(self, error: str):
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
        QMessageBox.warning(self, "Run failed", error)
        if self._stage_results:   # some stages still completed before the failure
            CompletionDialog(self._stage_results, self).exec()

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
            self._wake_listener.stop()
            self._wake_listener = None
            self.statusBar().showMessage("Wake word off.", 3000)

    def _on_wake_heard(self):
        self.statusBar().showMessage('Heard "Prism" — starting a take…', 3000)
        if self._record_worker is None:
            self._toggle_mic()

    def closeEvent(self, event):
        if self._wake_listener:
            self._wake_listener.stop()
        # Anything metered but not yet sent — a run that ended just before the
        # window closed, or events buffered while the server was unreachable.
        licensing.report_usage(getattr(self, "_run_id", ""))
        event.accept()
