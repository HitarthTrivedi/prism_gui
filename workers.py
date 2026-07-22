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

    def __init__(self, routing: dict, cfg: dict, attachments: list, query: str):
        super().__init__()
        self.routing, self.cfg = routing, cfg
        self.attachments, self.query = attachments, query

    def run(self):
        ok, err = CB.automation_available()
        if not ok:
            self.failed.emit(f"Automation deps not available ({err}).")
            return
        automation = CB.get_automation()
        try:
            responses, links = automation.run(
                self.routing, self.cfg, attachments=self.attachments,
                on_event=lambda kind, payload: self.stage_event.emit(kind, payload),
                query=self.query,
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
