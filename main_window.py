"""The main window: wires the sidebar + five panels together and owns every
background worker's lifecycle. This is the only file that makes decisions —
every widget below it is dumb display + signals."""
from __future__ import annotations
import os
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QDockWidget, QMessageBox,
    QFileDialog, QDialog, QListWidget, QListWidgetItem, QTextEdit,
)

import core_bridge as CB
from widgets.sidebar import Sidebar
from widgets.input_panel import InputPanel
from widgets.files_panel import FilesPanel
from widgets.prompt_panel import PromptPanel
from widgets.agents_panel import AgentsPanel
from widgets.output_panel import OutputPanel
from workers import RouteWorker, AutomationWorker, RecordWorker, InterpretWorker, FindWorker
from wakeword import WakeWordListener
from dialogs.setup_dialog import SetupDialog
from dialogs.ai_directory_dialog import AIDirectoryDialog
from dialogs.email_dialog import EmailComposeDialog, EmailSetupDialog
from dialogs.completion_dialog import CompletionDialog


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

        self._build_ui()
        self._wire()

        if not CB.config.is_configured(self.cfg):
            self._open_setup()

    # ── layout ──────────────────────────────────────────────────────────────
    def _fit_to_screen(self):
        """Size (and center) the window to whatever screen it's actually on,
        instead of a fixed 1400x900 that can overflow a smaller display."""
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        if avail:
            w = min(1400, int(avail.width() * 0.92))
            h = min(900, int(avail.height() * 0.88))
            self.resize(w, h)
            self.move(avail.center().x() - w // 2, avail.center().y() - h // 2)
        else:
            self.resize(1100, 720)
        self.setMinimumSize(760, 480)

    def _build_ui(self):
        # Central area = sidebar + the always-visible task input. The four
        # working segments (files/prompt/agents/output) are QDockWidgets, so
        # each one can be dragged out into its own window, resized on its
        # own, or closed and reopened from the View menu — exactly the
        # "open this segment separately" behaviour a fixed split-pane layout
        # can't give you.
        self.setDockOptions(QMainWindow.AnimatedDocks | QMainWindow.AllowNestedDocks
                            | QMainWindow.AllowTabbedDocks)

        central = QWidget()
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.sidebar = Sidebar()
        outer.addWidget(self.sidebar)

        right = QVBoxLayout()
        right.setContentsMargins(16, 16, 16, 16)
        self.input_panel = InputPanel()
        right.addWidget(self.input_panel)
        right.addStretch(1)
        right_wrap = QWidget()
        right_wrap.setLayout(right)
        outer.addWidget(right_wrap, stretch=1)
        self.setCentralWidget(central)

        self.files_panel = FilesPanel()
        self.prompt_panel = PromptPanel()
        self.agents_panel = AgentsPanel()
        self.output_panel = OutputPanel()

        self.files_dock = self._make_dock("Files & Folders", self.files_panel)
        self.prompt_dock = self._make_dock("Prompt Engineering", self.prompt_panel)
        self.agents_dock = self._make_dock("Agents", self.agents_panel)
        self.output_dock = self._make_dock("Pipeline Output", self.output_panel)

        self.addDockWidget(Qt.LeftDockWidgetArea, self.files_dock)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.agents_dock)
        self.splitDockWidget(self.files_dock, self.agents_dock, Qt.Vertical)

        self.addDockWidget(Qt.RightDockWidgetArea, self.prompt_dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self.output_dock)
        self.splitDockWidget(self.prompt_dock, self.output_dock, Qt.Vertical)

        view_menu = self.menuBar().addMenu("View")
        for dock in (self.files_dock, self.prompt_dock, self.agents_dock, self.output_dock):
            view_menu.addAction(dock.toggleViewAction())

        self.statusBar().showMessage("Ready.")

    def _make_dock(self, title: str, widget: QWidget) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(title.replace(" ", "_"))
        dock.setWidget(widget)
        dock.setFeatures(QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetMovable
                         | QDockWidget.DockWidgetFloatable)
        return dock

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

    # ── sidebar commands ─────────────────────────────────────────────────────
    def _handle_command(self, key: str):
        if key == "catalog":
            AIDirectoryDialog(self).exec()
        elif key in ("agents", "profile", "key", "chrome", "config"):
            self._open_setup()
        elif key == "login":
            self._open_login_tabs()
        elif key == "status":
            self._show_status()
        elif key == "runs":
            self._show_runs()
        elif key == "email":
            self._open_email()

    def _open_email(self):
        if not CB.mailer.is_configured(self.cfg):
            dlg = EmailSetupDialog(self.cfg, self)
            if dlg.exec() != QDialog.Accepted:
                return
            self.cfg = dlg.cfg
        EmailComposeDialog(self.cfg, self.attachments, self).exec()

    def _open_setup(self):
        dlg = SetupDialog(self.cfg, self)
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
        runs_dir = CB.config.RUNS_DIR
        if not os.path.isdir(runs_dir):
            QMessageBox.information(self, "Run history", "No saved runs yet.")
            return
        files = sorted(os.listdir(runs_dir), reverse=True)
        if not files:
            QMessageBox.information(self, "Run history", "No saved runs yet.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Run history")
        dlg.resize(700, 500)
        layout = QHBoxLayout(dlg)
        lst = QListWidget()
        lst.addItems(files)
        layout.addWidget(lst, stretch=1)
        viewer = QTextEdit()
        viewer.setReadOnly(True)
        layout.addWidget(viewer, stretch=2)

        def show_run(item: QListWidgetItem):
            path = os.path.join(runs_dir, item.text())
            try:
                with open(path, "r", encoding="utf-8") as f:
                    viewer.setPlainText(f.read())
            except Exception as e:
                viewer.setPlainText(f"Couldn't read {path}: {e}")

        lst.itemClicked.connect(show_run)
        dlg.exec()

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
            self._record_worker = RecordWorker(self.cfg)
            self._record_worker.done.connect(self._on_transcribed)
            self._record_worker.failed.connect(self._on_voice_failed)
            self._record_worker.start()
            self.input_panel.set_recording(True)
            self.input_panel.append_status("🎤 recording — click Stop when you're done…")
        else:
            self._record_worker.stop()
            self.input_panel.set_recording(False)
            self.input_panel.append_status("⏳ transcribing…")

    def _on_transcribed(self, text: str, lang: str):
        self._record_worker = None
        if not text:
            self.input_panel.append_status("didn't catch anything — try again, or type.")
            return
        note = f"  ({lang})" if lang and lang != "english" else ""
        self.input_panel.append_status(f'heard: "{text}"{note}')
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
                "interpreter unavailable — using your words as-is; "
                "mention any file manually with Attach.")
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
        if not CB.config.is_configured(self.cfg):
            QMessageBox.warning(self, "Setup needed", "Finish Setup (API key + agents) first.")
            return
        self._last_query = query
        self.input_panel.set_busy(True)
        worker = RouteWorker(query, self.cfg, self.attachments)
        worker.done.connect(self._on_routed)
        worker.failed.connect(self._on_route_failed)
        self._workers.append(worker)
        worker.start()

    def _on_routed(self, routing: dict):
        self.input_panel.set_busy(False)
        self.routing = routing
        agents_cfg = CB.config.active_agents(self.cfg)
        self.prompt_panel.set_content(self._last_query, routing, agents_cfg)
        self.agents_panel.set_content(routing, agents_cfg)
        self.statusBar().showMessage("Routed — review agents, then Run Pipeline.", 6000)

    def _on_route_failed(self, error: str):
        self.input_panel.set_busy(False)
        QMessageBox.warning(self, "Routing failed", error)

    # ── running the pipeline ────────────────────────────────────────────────
    def _run_pipeline(self):
        if not self.routing:
            return
        run_agents = self.agents_panel.selected_agents()
        if not run_agents:
            QMessageBox.information(self, "Run", "No stages are checked to run.")
            return
        cfg_for_run = dict(self.cfg)
        cfg_for_run["agents"] = run_agents
        self.output_panel.clear()
        self._stage_agents = {}
        self._stage_results = []
        self.agents_panel.set_run_enabled(False)
        worker = AutomationWorker(self.routing, cfg_for_run, self.attachments, self._last_query)
        worker.stage_event.connect(self._on_stage_event)
        worker.done.connect(self._on_run_done)
        worker.failed.connect(self._on_run_failed)
        self._workers.append(worker)
        worker.start()

    def _on_stage_event(self, kind: str, payload: dict):
        stage = payload.get("stage", "")
        if kind == "stage_start":
            agent = payload.get("agent", "")
            self._stage_agents[stage] = agent
            self.output_panel.stage_started(stage, agent)
        elif kind == "waiting":
            self.output_panel.stage_waiting(stage, payload.get("seconds", 0))
        elif kind == "stage_done":
            texts = payload.get("texts") or []
            url = payload.get("url", "")
            self.output_panel.stage_done(stage, texts, url)
            snippet = (texts[0][:150] + "…") if texts and len(texts[0]) > 150 else (texts[0] if texts else "no response captured")
            self._stage_results.append({
                "stage": stage, "agent": self._stage_agents.get(stage, "?"),
                "text": "\n\n---\n\n".join(texts), "url": url,
                "snippet": snippet, "ok": bool(texts),
            })
        elif kind == "stage_error":
            error = payload.get("error", "")
            self.output_panel.stage_error(stage, error)
            self._stage_results.append({
                "stage": stage, "agent": self._stage_agents.get(stage, "?"),
                "text": error, "url": "", "snippet": f"failed: {error[:120]}", "ok": False,
            })

    def _on_run_done(self, responses: dict, links: dict):
        self.agents_panel.set_run_enabled(True)
        self.statusBar().showMessage("Pipeline finished.", 6000)
        if self._stage_results:
            CompletionDialog(self._stage_results, self).exec()
        else:
            QMessageBox.information(self, "Pipeline finished",
                                    "No stage produced output — check the Output dock.")

    def _on_run_failed(self, error: str):
        self.agents_panel.set_run_enabled(True)
        QMessageBox.warning(self, "Run failed", error)
        if self._stage_results:   # some stages still completed before the failure
            CompletionDialog(self._stage_results, self).exec()

    # ── wake word ─────────────────────────────────────────────────────────────
    def toggle_wakeword(self, on: bool):
        if on:
            if not self.cfg.get("api_key"):
                QMessageBox.warning(self, "Wake word", "Set your Groq API key in Setup first.")
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
        event.accept()
