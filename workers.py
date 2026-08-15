"""
Prism GUI — background workers
───────────────────────────────
Routing, browser automation and Groq calls all block for real seconds/minutes
— every one of them runs on a QThread so the UI never freezes. Each worker's
job is ONLY to call into core_bridge and turn the result into a Qt signal;
no decision-making lives here.
"""
from __future__ import annotations
import threading
from PySide6.QtCore import QThread, Signal

import core_bridge as CB


class AuthorizeWorker(QThread):
    """Ask the licence server whether this run may go ahead.

    On its own thread because the answer takes a network round trip and the
    customer has just pressed a button — freezing the window while we wait
    reads as a crash, which is exactly the moment they decide the software is
    broken.
    """

    done = Signal(object)      # licensing.Authorization

    def __init__(self, feature: str = "core", action: str = "run", parent=None):
        super().__init__(parent)
        self._feature = feature
        self._action = action

    def run(self):
        import licensing
        try:
            self.done.emit(licensing.authorize(self._feature, self._action))
        except Exception as e:                      # noqa: BLE001
            # Never strand the caller: a bug in here must not mean the button
            # silently does nothing forever.
            self.done.emit(licensing.Authorization(
                False, message=f"Couldn't check your licence: {e}"))


class RouteWorker(QThread):
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, query: str, cfg: dict, attachments: list):
        super().__init__()
        self.query, self.cfg, self.attachments = query, cfg, attachments

    def run(self):
        try:
            routing = CB.router.route(self.query, self.cfg, self.attachments)
            self.done.emit(routing)
        except Exception as e:
            self.failed.emit(str(e))


class AutomationWorker(QThread):
    stage_event = Signal(str, dict)
    done = Signal(dict, dict)
    failed = Signal(str)

    def __init__(self, routing: dict, cfg: dict, attachments: list, query: str,
                 custom_stages=None, chatgpt_analysis: bool = True):
        super().__init__()
        self.routing, self.cfg = routing, cfg
        self.attachments, self.query = attachments, query
        # custom_stages lets an add-on (e.g. BOQ) name its own ordered stages
        # instead of going through the router's fixed categories; the engine
        # accepts them directly. None = ordinary routed run, unchanged.
        self.custom_stages = custom_stages
        self.chatgpt_analysis = chatgpt_analysis
        self._stop = threading.Event()

    def stop(self):
        """Ask the run to wind up at the next safe point.

        The engine polls this between stages and inside its waits, so a stop
        lands within a second or two rather than at the end of the current
        step — and it keeps everything already finished, emitting a
        "cancelled" event with the count. Nothing is killed mid-write.
        """
        self._stop.set()

    def stopping(self) -> bool:
        return self._stop.is_set()

    def run(self):
        ok, err = CB.automation_available()
        if not ok:
            self.failed.emit(f"Automation deps not available ({err}).")
            return
        automation = CB.get_automation()
        try:
            kwargs = {}
            if self.custom_stages is not None:
                kwargs["custom_stages"] = self.custom_stages
                kwargs["chatgpt_analysis"] = self.chatgpt_analysis
            responses, links = automation.run(
                self.routing, self.cfg, attachments=self.attachments,
                on_event=lambda kind, payload: self.stage_event.emit(kind, payload),
                query=self.query, should_stop=self._stop.is_set, **kwargs,
            )
            self.done.emit(responses, links)
        except Exception as e:
            self.failed.emit(str(e))


class RecordWorker(QThread):
    """Push-to-talk: recording starts as soon as this thread runs, and stops
    the instant .stop() is called from the GUI thread (e.g. a toggle
    button's second click) — no terminal/keypress dependency."""
    done = Signal(str, str)   # text, language
    failed = Signal(str)

    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        try:
            wav = CB.voice.record_until(self._stop.is_set)
            text, lang = CB.voice.transcribe(wav, self.cfg)
            self.done.emit(text, lang)
        except Exception as e:
            self.failed.emit(str(e))


class InterpretWorker(QThread):
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, text: str, cfg: dict):
        super().__init__()
        self.text, self.cfg = text, cfg

    def run(self):
        try:
            self.done.emit(CB.voice.interpret(self.text, self.cfg))
        except Exception as e:
            self.failed.emit(str(e))


class SendWorker(QThread):
    """The email blast. SMTP login, then one message per recipient with a
    provider-friendly pause between them — minutes of blocking for a real
    list, which is exactly as long as the window would be frozen if this ran
    where it used to (straight off the Send button)."""
    progress = Signal(int, int, str, bool, str)   # i, total, email, ok, error
    done = Signal(list, list)                     # sent, failed
    failed = Signal(str)                          # couldn't even connect

    def __init__(self, cfg: dict, recipients: list, subject: str, body: str,
                 files: list):
        super().__init__()
        self.cfg, self.recipients = cfg, recipients
        self.subject, self.body, self.files = subject, body, files
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def run(self):
        try:
            sent, failed = CB.mailer.send_bulk(
                self.cfg, self.recipients, self.subject, self.body, self.files,
                on_progress=lambda i, n, email, ok, err:
                    self.progress.emit(i, n, email, ok, err),
                should_stop=self._stop.is_set,
            )
            self.done.emit(sent, failed)
        except Exception as e:
            # Raised out of the login/connect, before any message went out —
            # nothing was sent, so this is a failure of the account, not of a
            # recipient.
            self.failed.emit(str(e))


class VerifyWorker(QThread):
    """Log in and hang up, to check the account before a real blast."""
    done = Signal(str)   # "" == fine, else the reason

    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg

    def run(self):
        try:
            self.done.emit(CB.mailer.verify(self.cfg))
        except Exception as e:
            self.done.emit(str(e))


class FindWorker(QThread):
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, desc: str, cfg: dict):
        super().__init__()
        self.desc, self.cfg = desc, cfg

    def run(self):
        try:
            self.done.emit(CB.pathfinder.find(self.desc, self.cfg))
        except Exception as e:
            self.failed.emit(str(e))


class MeasureWorker(QThread):
    """Parse a CAD drawing off the UI thread.

    A 13 MB DWG takes ~40 s to convert and measure. Doing that inline froze
    the whole dialog with no feedback — the app looked hung, which on a
    client's laptop reads as broken software.
    """
    done = Signal(object, list)      # quantities dict, converter notes
    failed = Signal(str)

    def __init__(self, path: str, unit: str = "", scope: list | None = None):
        super().__init__()
        self.path, self.unit, self.scope = path, unit, scope or []

    def run(self):
        try:
            boq = CB.get_boq()
            dxf_path, notes = boq.ensure_dxf(self.path)
            q = boq.measure(dxf_path)
            if self.unit:
                boq.apply_known_unit(q, self.unit)
            if self.scope:
                q = boq.filter_by_keywords(q, self.scope)
            self.done.emit(q, notes)
        except Exception as e:
            self.failed.emit(str(e))


class ReelWorker(QThread):
    """Render the reel off the UI thread.

    A 30-second reel is 900 frames of drawing plus encoding — around 16
    seconds. Inline that would freeze the window with no feedback, which on a
    client's laptop reads as a crash.
    """
    progress = Signal(int, int)      # frames done, total
    done = Signal(str)               # output path
    failed = Signal(str)

    def __init__(self, spec: dict, out_path: str):
        super().__init__()
        self.spec, self.out_path = spec, out_path

    def run(self):
        try:
            reel = CB.get_reel()
            reel.render(self.spec, self.out_path,
                        on_progress=lambda d, t: self.progress.emit(d, t))
            self.done.emit(self.out_path)
        except Exception as e:
            self.failed.emit(str(e))


# ── Inquiry automation ────────────────────────────────────────────────────────

class InboxVerifyWorker(QThread):
    """Find the mail server and check the password, off the UI thread.

    A wrong host means a DNS timeout, and three of those in a row is most of a
    minute with the window frozen — at the exact moment somebody is deciding
    whether this software works.
    """
    done = Signal(dict, str)      # settings (empty on failure), error ("" on success)

    def __init__(self, address: str, password: str, host: str = ""):
        super().__init__()
        self.address, self.password = address, password
        # Whatever the user typed into the Mail server box, tried before any
        # guess. Empty means "work it out".
        self.host = host

    def run(self):
        try:
            inbox = CB.get_inbox()
            settings, error = inbox.discover(self.address, self.password,
                                             host=self.host)
            self.done.emit(settings, error)
        except Exception as e:
            self.done.emit({}, str(e))


class InboxCheckWorker(QThread):
    """One run of the daily loop: fetch, sort, register, work out what is due.

    Everything it does is a read, so it is safe to run on a timer and safe to
    cancel by simply ignoring the result. mailflow.check() never raises and
    never sends, so there is no partial state to unwind.
    """
    done = Signal(object)         # mailflow.Result
    failed = Signal(str)

    def __init__(self, cfg: dict, root: str, *, state=None, knowledge=None,
                 local_only: bool = False, followup_days: int = 2,
                 max_reminders: int = 3):
        super().__init__()
        self.cfg, self.root, self.state = cfg, root, state
        self.knowledge = knowledge
        self.local_only, self.followup_days = local_only, followup_days
        self.max_reminders = max_reminders

    def run(self):
        try:
            mailflow = CB.get_mailflow()
            result = mailflow.check(
                self.cfg, mailflow.Paths(self.root), state=self.state,
                knowledge=self.knowledge, local_only=self.local_only,
                followup_days=self.followup_days,
                max_reminders=self.max_reminders)
            self.done.emit(result)
        except Exception as e:
            self.failed.emit(str(e))


class DraftWorker(QThread):
    """Write one email using the AI tools in the customer's own browser.

    Minutes, not seconds: it opens Chrome, types the prompt into whichever
    tool they picked, and waits for the answer to finish streaming. That is
    the price of using their subscription instead of an API key, and it is
    why this is only ever used for the handful of emails a week that are
    worth writing well — never for sorting the inbox.
    """
    progress = Signal(str)           # a line for the status label
    done = Signal(object)            # drafting.Draft
    failed = Signal(str)

    def __init__(self, cfg: dict, prompt: str, *, purpose: str = "draft",
                 attachments: list | None = None):
        super().__init__()
        self.cfg, self.prompt, self.purpose = cfg, prompt, purpose
        self.attachments = list(attachments or [])
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        try:
            drafting = CB.get_drafting()
            result = drafting.draft(
                self.cfg, self.prompt, purpose=self.purpose,
                attachments=self.attachments,
                on_event=self._event,
                should_stop=self._stop.is_set)
            self.done.emit(result)
        except Exception as e:
            self.failed.emit(str(e))

    def _event(self, kind: str, payload):
        """Turn the pipeline's own progress events into one readable line.

        The tool names are worth showing: a customer watching Chrome open by
        itself wants to know Prism meant to do that.
        """
        if kind == "stage_start":
            self.progress.emit(
                f"Asking {payload.get('agent', 'the AI tool')}…")
        elif kind == "stage_done":
            self.progress.emit("Reading the answer…")


class FFmpegWorker(QThread):
    """Download and install FFmpeg, off the UI thread.

    30 MB over an office connection is a minute of nothing, and a frozen
    window for a minute is indistinguishable from a crash — which is the
    impression this feature exists to avoid making.
    """
    progress = Signal(int, int)      # bytes done, bytes total (0 = unknown)
    done = Signal(str)               # path to the executable
    failed = Signal(str)

    def run(self):
        try:
            ffmpeg = CB.get_ffmpeg()
            self.done.emit(ffmpeg.download(
                lambda done, total: self.progress.emit(done, total)))
        except Exception as e:
            self.failed.emit(str(e))
