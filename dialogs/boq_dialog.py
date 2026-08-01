"""Bill of Quantities — say what you need, get the document.

The screen is deliberately one prompt and one button. The user does not
choose a mode, does not fill a form, and is never asked what a "scope
filter" is. Attach a drawing and it gets measured; attach nothing and the
quantities are derived from the words. Both are the same button.

The measuring itself is done locally by the engine (core.boq, ezdxf) and
never by an AI — real geometry in, an auditable CSV out — and only then do
the agents write it up. The measured figures are shown before anything is
generated, because that is what makes the number checkable.
"""
from __future__ import annotations
import os
import time

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QPushButton,
    QPlainTextEdit, QLineEdit, QMessageBox, QCheckBox, QProgressBar,
)

import core_bridge as CB
from workers import AutomationWorker, MeasureWorker, RecordWorker
from widgets.ask_panel import AskPanel, MoreOptions


class BoqDialog(QDialog):
    def __init__(self, cfg: dict, attachments: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bill of Quantities")
        self.resize(720, 660)
        self.cfg = cfg
        self.boq = CB.get_boq()

        self.cad_path = ""
        self.templates: list[dict] = []
        self.images: list[dict] = []
        self.notes: list[dict] = []
        self.q = None
        self.summary = ""
        self.csv_path = ""
        self._worker = None
        self._rec = None
        self._standards = ""
        self._links: dict = {}

        root = QVBoxLayout(self)

        title = QLabel("What do you need a BOQ for?")
        title.setObjectName("h2")
        root.addWidget(title)

        self.ask = AskPanel(
            "Just say it — for example:\n"
            "\"BOQ for CCTV, cabling and fibre for this site\"  (attach the drawing)\n"
            "\"materials to build one 36x24 jaw crusher, 100 TPH\"  (no drawing needed)")
        self.ask.speak_clicked.connect(self._toggle_record)
        self.ask.files_added.connect(self._on_files_added)
        root.addWidget(self.ask)

        # Only appears once a drawing has actually been measured.
        self.meas_box = QGroupBox("Measured from your drawing")
        meas_l = QVBoxLayout(self.meas_box)
        self.meas_view = QPlainTextEdit()
        self.meas_view.setReadOnly(True)
        self.meas_view.setFixedHeight(120)
        meas_l.addWidget(self.meas_view)
        self.csv_label = QLabel("")
        self.csv_label.setObjectName("emptyState")
        self.csv_label.setWordWrap(True)
        meas_l.addWidget(self.csv_label)
        self.meas_box.setVisible(False)
        root.addWidget(self.meas_box)

        # Everything technical lives here, shut by default.
        self.more = MoreOptions("More options")
        self.unit_edit = QLineEdit()
        self.unit_edit.setPlaceholderText("Drawing unit, if you know it — e.g. meters")
        self.more.add(self.unit_edit)
        self.scope_edit = QLineEdit()
        self.scope_edit.setPlaceholderText("Only include layers containing… (comma separated)")
        self.more.add(self.scope_edit)
        self.derive_cb = QCheckBox(
            "Estimate items the drawing doesn't contain (marked as an estimate)")
        self.derive_cb.setChecked(True)
        self.more.add(self.derive_cb)
        root.addWidget(self.more)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        root.addWidget(self.progress)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.result = QPlainTextEdit()
        self.result.setReadOnly(True)
        self.result.setPlaceholderText("Your BOQ will appear here.")
        self.result.setMinimumHeight(120)
        root.addWidget(self.result, stretch=1)

        btns = QHBoxLayout()
        self.open_btn = QPushButton("Open in browser")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open_link)
        btns.addWidget(self.open_btn)
        btns.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        btns.addWidget(close)
        self.run_btn = QPushButton("Make my BOQ")
        self.run_btn.setObjectName("primary")
        self.run_btn.setDefault(True)
        self.run_btn.clicked.connect(self._run)
        btns.addWidget(self.run_btn)
        root.addLayout(btns)

        # Files already attached on the home screen come along automatically.
        if attachments:
            self._absorb([a["path"] for a in attachments])

    # ── files ───────────────────────────────────────────────────────────

    def _on_files_added(self, paths: list):
        self._absorb(paths)

    def _absorb(self, paths: list):
        """Work out what each file IS. The user should never be asked which
        box a file belongs in — a .dwg is the drawing, a .docx is the sample,
        an image is a screenshot of the sheet."""
        atts = []
        for p in paths:
            try:
                atts.append(CB.files.attach(p))
            except Exception:
                pass
        if not atts:
            return
        cad, templates, images, notes = self.boq.classify_inputs(atts)
        self.templates += templates
        self.images += images
        self.notes += notes
        known = self.ask.paths()
        self.ask.add_paths([a["path"] for a in atts if a["path"] not in known])
        if cad:
            self.cad_path = cad[0]["path"]
            self._measure()

    # ── measuring ───────────────────────────────────────────────────────

    def _measure(self):
        if not self.cad_path or not os.path.exists(self.cad_path):
            return
        self._set_busy(True, f"Reading {os.path.basename(self.cad_path)} — "
                             "a large drawing can take a minute…")
        self._measure_worker = MeasureWorker(
            self.cad_path, self.unit_edit.text().strip(),
            [s.strip() for s in self.scope_edit.text().split(",") if s.strip()])
        self._measure_worker.done.connect(self._on_measured)
        self._measure_worker.failed.connect(self._on_measure_failed)
        self._measure_worker.start()

    def _on_measured(self, q, notes: list):
        self.q = q
        self.summary = self.boq.summary_text(q)
        self.meas_view.setPlainText(self.summary)
        self.meas_box.setVisible(True)

        os.makedirs(CB.config.RUNS_DIR, exist_ok=True)
        self.csv_path = os.path.join(
            CB.config.RUNS_DIR, f"boq_quantities_{int(time.time())}.csv")
        self.boq.write_quantities_csv(q, self.csv_path)
        note = "  ".join(notes)
        self.csv_label.setText(
            f"Saved so you can check every number → {self.csv_path}"
            + (f"\n⚠ {note}" if note else ""))
        self._set_busy(False, "Measured from the drawing itself — not by an AI.")

    def _on_measure_failed(self, error: str):
        self._set_busy(False, "")
        QMessageBox.warning(self, "BOQ", error)

    # ── voice ───────────────────────────────────────────────────────────

    def _toggle_record(self):
        if self._rec:
            self._rec.stop()
            self.ask.set_recording(False)
            return
        if not CB.voice.available():
            QMessageBox.information(
                self, "Speak",
                "Voice needs PyAudio on this machine:\n\n"
                "    brew install portaudio && pip install pyaudio\n\n"
                "Everything else works — just type instead.")
            return
        self.ask.set_recording(True)
        self.status.setText("Listening — press Stop when you're done.")
        self._rec = RecordWorker(self.cfg)
        self._rec.done.connect(self._on_spoken)
        self._rec.failed.connect(self._on_spoken_failed)
        self._rec.start()

    def _on_spoken(self, text: str, lang: str):
        self._rec = None
        self.ask.set_recording(False)
        self.status.setText("")
        if text:
            self.ask.append_text(text)

    def _on_spoken_failed(self, error: str):
        self._rec = None
        self.ask.set_recording(False)
        self.status.setText("")
        QMessageBox.information(self, "Speak", error)

    # ── the run ─────────────────────────────────────────────────────────

    def _run(self):
        request = self.ask.text()
        if not request and not self.q:
            QMessageBox.information(
                self, "BOQ",
                "Tell me what the BOQ is for — or attach a drawing.")
            return

        agents = CB.config.active_agents(self.cfg)
        writer = next((s for s in ("content", "brains") if agents.get(s)), None)
        if not writer:
            QMessageBox.warning(self, "BOQ",
                                "No writing agent set up yet — open Agents first.")
            return
        self.writer_agent = agents[writer]
        self.researcher = agents.get("research") or agents.get("brains")
        self.request = request or "Produce a Bill of Quantities from the attached drawing."

        if self.derive_cb.isChecked() and self.researcher:
            self._set_busy(True, f"{self.researcher} is checking the standard "
                                 "sizes and norms…")
            self._worker = AutomationWorker(
                {}, self.cfg, [], "design standards for a BOQ trade",
                custom_stages=[("standards", self.researcher,
                                [self.boq.standards_prompt(self.request,
                                                           project_context=self.request)])],
                chatgpt_analysis=False)
            self._worker.done.connect(self._on_standards)
            self._worker.failed.connect(self._on_failed)
            self._worker.start()
        else:
            self._write()

    def _on_standards(self, responses: dict, links: dict):
        got = [t for t in (responses.get("standards") or []) if t.strip()]
        self._standards = got[0] if got else ""
        self._links.update(links)
        self._write()

    def _write(self):
        self._set_busy(True, f"{self.writer_agent} is writing your BOQ…")
        prompt = self.boq.formatting_prompt(
            self.summary, project_context=self.request,
            has_template=bool(self.templates),
            scoped=bool(self.scope_edit.text().strip()),
            standards_text=self._standards,
            allow_derived=self.derive_cb.isChecked() or not self.q,
            has_cad=bool(self.q))

        files = list(self.templates) + list(self.notes)
        if self.q and self.cad_path:
            try:
                files.insert(0, CB.files.attach(self.cad_path))
            except Exception:
                pass

        self._worker = AutomationWorker(
            {}, self.cfg, files, f"Bill of Quantities — {self.request}",
            custom_stages=[("format", self.writer_agent, [prompt])],
            chatgpt_analysis=False)
        self._worker.done.connect(self._on_written)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_written(self, responses: dict, links: dict):
        self._set_busy(False, "")
        self._links.update(links)
        texts = [t for t in (responses.get("format") or []) if t.strip()]
        if not texts:
            self.status.setText("Nothing came back. The measured numbers above "
                                "are still saved.")
        else:
            self.result.setPlainText(texts[0])
            self.status.setText("Done. Check the numbers against the saved file above.")
        self.open_btn.setEnabled(bool(self._links.get("format")))
        CB.config.save_run({
            "query": f"BOQ — {self.request}", "responses": responses,
            "links": self._links,
            "boq": {"quantities_csv": self.csv_path, "source": self.cad_path},
        })

    def _on_failed(self, error: str):
        self._set_busy(False, "")
        QMessageBox.warning(self, "BOQ", error)

    def _set_busy(self, busy: bool, message: str):
        self.progress.setVisible(busy)
        self.run_btn.setEnabled(not busy)
        self.status.setText(message)

    def _open_link(self):
        import webbrowser
        url = self._links.get("format")
        if url:
            webbrowser.open(url)
