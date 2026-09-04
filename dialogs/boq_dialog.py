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
    QComboBox, QWidget,
)

import core_bridge as CB
import i18n
import theme
import wakeword
from dialogs.base import PrismDialog
from workers import AutomationWorker, MeasureWorker, RecordWorker
from widgets import controls as C
from widgets.ask_panel import AskPanel, MoreOptions
from widgets.output_panel import short_duration


def _preselect(combo: QComboBox, value: str):
    """Select `value` in the combo if it is one of the options; otherwise
    leave the registry's own first-listed (recommended) default in place."""
    if not value:
        return
    i = combo.findText(value)
    if i >= 0:
        combo.setCurrentIndex(i)


class BoqDialog(PrismDialog):
    def __init__(self, cfg: dict, attachments: list, parent=None,
                 mode: str = "boq"):
        # One dialog, two documents. BOQ = quantities of construction WORK for a
        # QS to price; BOM = the PARTS list to fabricate a manufactured assembly.
        # The measurement backbone is identical (core.boq measures either way) —
        # only the write-up/research prompts and the on-screen copy differ, so
        # this is one class parameterised by mode rather than two that drift
        # apart (and BOM inherits every fix BOQ has: dedup, agent picker,
        # follow-up, timing, the scroll). Set before super() — the header copy
        # below reads self._doc.
        self.mode = "bom" if mode == "bom" else "boq"
        self._doc = "Bill of Materials" if self.mode == "bom" else "Bill of Quantities"
        self._noun = "BOM" if self.mode == "bom" else "BOQ"
        super().__init__(
            i18n.t(self._doc),
            i18n.t("Attach a drawing and it is measured here, on this "
                   "machine. Nothing is measured by an AI."),
            icon="file", parent=parent, closable=False, scrollable=True)
        self.setWindowTitle(self._doc)
        self.resize(780, 700)
        self.setMinimumSize(620, 600)
        self.cfg = cfg
        self.boq = CB.get_boq()
        # The research + write-up prompts come from core.bom in BOM mode and
        # core.boq in BOQ mode; measurement, interpretation and roles_text
        # always come from self.boq (they are mode-independent).
        self._pm = CB.bom if self.mode == "bom" else self.boq

        self.cad_path = ""
        self.templates: list[dict] = []
        self.images: list[dict] = []
        self.notes: list[dict] = []
        self.q = None
        self.summary = ""
        self.csv_path = ""
        self._worker = None
        self._rec = None
        self._run_pending = False   # "Make my BOQ" pressed while still measuring
        # Task timing: t0 is when the run began, and _stage_log accumulates
        # (stage, seconds) as each stage finishes, so completion can report how
        # long the whole BOQ took and where the time went.
        self._t0 = 0.0
        self._last_t = 0.0
        self._stage_log: list[tuple[str, float]] = []
        self._standards = ""
        self._brief = ""        # the interpreter's legend & scope brief
        self._links: dict = {}
        # Accumulated across the stage chain so the main window can offer its
        # post-completion follow-up once this dialog closes: every stage's
        # output, and which agent produced it. The dialog runs its own worker
        # chain (never the main window's _on_run_done), so without carrying
        # these out the "anything to change?" refinement was unreachable here.
        self._all_responses: dict = {}
        self._stage_agents_map: dict = {}

        # The base class owns the header and the footer; `root` is its body
        # column, which already carries the page padding and the card gutter.
        root = self.body
        # A stacked form, not a grid of cards: the 16px card gutter
        # between every row of a single column is what turns a short
        # form into a tall one with bands of canvas through it.
        root.setSpacing(theme.ROW_GAP)

        title = QLabel(f"What do you need a {self._noun} for?")
        title.setObjectName("h4")
        root.addWidget(title)

        if self.mode == "bom":
            placeholder = (
                "Just say it — for example:\n"
                "\"Parts list to fabricate this over-band magnetic separator\"  (attach the GA drawing)\n"
                "\"BOM for one 36x24 jaw crusher, 100 TPH\"  (no drawing needed)")
        else:
            placeholder = (
                "Just say it — for example:\n"
                "\"BOQ for CCTV, cabling and fibre for this site\"  (attach the drawing)\n"
                "\"materials to build one 36x24 jaw crusher, 100 TPH\"  (no drawing needed)")
        self.ask = AskPanel(placeholder)
        self.ask.speak_clicked.connect(self._toggle_record)
        self.ask.files_added.connect(self._on_files_added)
        root.addWidget(self.ask)

        # Say which format works BEFORE a drawing is attached, not in an error
        # afterwards.
        #
        # .dwg is Autodesk's closed format, and reading it needs a separate
        # converter Prism is not allowed to ship: ODA File Converter is only
        # distributed through a registration form with an EULA, and its licence
        # forbids redistribution. So on a machine without one, a customer who
        # attached the obvious file got told to go and install a program —
        # after picking the file, naming the job and pressing the button.
        #
        # .dxf needs none of that. Every CAD program exports it in one step,
        # ezdxf reads it directly, and it is the same geometry. Making that the
        # expected input is the difference between a five-minute detour and a
        # dead end — and it costs the customer one menu item they already know.
        #
        # Shown only when this machine genuinely has no converter: a client who
        # has installed one can attach .dwg all day and must not be nagged
        # about a problem they do not have.
        if not self.boq.find_dwg_converter():
            dxf_note = QLabel(
                "Attaching a drawing? Save it as <b>DXF</b> first — in AutoCAD "
                "that is File → Save As → <i>AutoCAD DXF</i>, and most other "
                "CAD programs have the same option. Prism measures DXF "
                "directly. A .dwg needs an extra converter this computer "
                "does not have.")
            dxf_note.setObjectName("note")
            dxf_note.setWordWrap(True)
            root.addWidget(dxf_note)

        # Only appears once a drawing has actually been measured.
        self.meas_box = QGroupBox("Measured from your drawing")
        meas_l = QVBoxLayout(self.meas_box)
        self.meas_view = QPlainTextEdit()
        self.meas_view.setReadOnly(True)
        self.meas_view.setFixedHeight(120)
        meas_l.addWidget(self.meas_view)
        # Not the dashed #emptyState box it used to be: this line says "your
        # numbers are saved, here is where", which is a result and not the
        # absence of one. A dashed placeholder box around a success message
        # reads as a slot still waiting to be filled.
        self.csv_label = QLabel("")
        self.csv_label.setWordWrap(True)
        self.csv_label.setStyleSheet(
            f"color: {theme.OK_INK}; background: {theme.OK_BG};"
            f" border-radius: {theme.R_CONTROL}px;"
            f" padding: {theme.SPACE_2}px {theme.SPACE_3}px;"
            f" font-size: 13px;")
        meas_l.addWidget(self.csv_label)
        self.meas_box.setVisible(False)
        root.addWidget(self.meas_box)

        # Which AIs run the BOQ. Defaults to the agents configured in Settings,
        # but re-pickable per BOQ: the write-up tool (Claude vs ChatGPT vs …)
        # and the standards-research tool (Perplexity vs Consensus vs …) each
        # change the result, and the user should be able to choose them for one
        # document without editing the global Agents setup. The interpreter
        # (screenshot reader) stays automatic — it only runs when an image is
        # attached, and ChatGPT is the right tool for it.
        cfg_agents = CB.config.active_agents(self.cfg)
        try:
            cats = CB.agents.CATEGORIES
        except Exception:                               # noqa: BLE001
            cats = {}
        writer_opts = list(dict.fromkeys(
            list(cats.get("brains", {}).get("agents", []))
            + list(cats.get("content", {}).get("agents", [])))) or ["Claude", "ChatGPT"]
        research_opts = list(cats.get("research", {}).get("agents", [])) or ["Perplexity"]
        self.writer_combo = QComboBox()
        self.writer_combo.addItems(writer_opts)
        self.research_combo = QComboBox()
        self.research_combo.addItems(research_opts)
        _preselect(self.writer_combo,
                   cfg_agents.get("content") or cfg_agents.get("brains"))
        _preselect(self.research_combo,
                   cfg_agents.get("research") or cfg_agents.get("brains"))
        picker = QWidget()
        prow = QHBoxLayout(picker)
        prow.setContentsMargins(0, 0, 0, 0)
        prow.setSpacing(theme.SPACE_2)
        wlab = QLabel(i18n.t("Write with")); wlab.setObjectName("meta")
        rlab = QLabel(i18n.t("· Research with")); rlab.setObjectName("meta")
        prow.addWidget(wlab)
        prow.addWidget(self.writer_combo)
        prow.addWidget(rlab)
        prow.addWidget(self.research_combo)
        prow.addStretch(1)
        root.addWidget(picker)

        # Everything technical lives here, shut by default.
        self.more = MoreOptions("More options")
        self.unit_edit = QLineEdit()
        self.unit_edit.setPlaceholderText("Drawing unit, if you know it — e.g. meters")
        self.more.add(self.unit_edit)
        self.scope_edit = QLineEdit()
        self.scope_edit.setPlaceholderText("Only include layers containing… (comma separated)")
        self.more.add(self.scope_edit)
        # The CLI takes this as a `legend:` directive on /boq. Same thing, so
        # the interpreter stage gets the same hint in both apps.
        self.legend_edit = QLineEdit()
        self.legend_edit.setPlaceholderText(
            "What the drawing's symbols mean, if the sheet doesn't say — e.g. "
            "circles = light points")
        self.more.add(self.legend_edit)
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
        self.result.setPlaceholderText(f"Your {self._noun} will appear here.")
        self.result.setMinimumHeight(120)
        root.addWidget(self.result, stretch=1)

        self.open_btn = self.button(i18n.t("Open in browser"), "secondary",
                                    icon_name="external", small=True,
                                    on_click=self._open_link)
        self.open_btn.setEnabled(False)
        self.footer.add_utility(self.open_btn)
        self.footer.add_secondary(self.button(i18n.t("Close"), on_click=self.reject))
        self.run_btn = self.button(f"Make my {self._noun}", "primary", icon_name="check",
                                   on_click=self._run)
        self.footer.set_primary(self.run_btn)

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
        # emit=False: we are already inside the files_added handler, and
        # add_paths dedupes on its own now — re-emitting would re-enter here
        # and classify every file (and re-count templates/images) twice.
        self.ask.add_paths([a["path"] for a in atts], emit=False)
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
        # A real, usable file — the numbers a customer or estimator would
        # want to keep even if they never open the formatted deck. RUNS_DIR
        # is a hidden working folder; Artifacts is where a copy survives.
        # `task` matches the query _write() below gives the "format" stage,
        # so the quantities CSV and the written-up deck land in the same
        # Artifacts subfolder rather than two differently-named ones.
        try:
            CB.config.save_artifact(
                self.csv_path, os.path.basename(self.cad_path), kind="boq",
                task=f"{self._doc} — {self.request}")
        except Exception:                               # noqa: BLE001
            pass
        note = "  ".join(notes)
        self.csv_label.setText(
            f"Saved so you can check every number → {self.csv_path}"
            + (f"\n⚠ {note}" if note else ""))
        self._set_busy(False, "Measured from the drawing itself — not by an AI.")
        # If the user already pressed "Make my BOQ" while this was measuring,
        # start it now — with the measured quantities it was waiting for.
        if self._run_pending:
            self._run_pending = False
            self._run()

    def _on_measure_failed(self, error: str):
        self._set_busy(False, "")
        # Don't auto-start a deferred run on a failed measure — the user should
        # see the error and decide (they can still run a derived/spec BOQ).
        self._run_pending = False
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
                f"    {wakeword.install_hint()}\n\n"
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
                f"Tell me what the {self._noun} is for — or attach a drawing.")
            return

        # A drawing is attached but still being measured: wait for it. The
        # measured quantities now feed EVERY stage's prompt (research, interpret
        # and format), so starting before they land would quietly produce a BOQ
        # blind to the drawing. Re-enters _run automatically from _on_measured.
        worker = getattr(self, "_measure_worker", None)
        if self.cad_path and self.q is None and worker is not None and worker.isRunning():
            self._run_pending = True
            self._set_busy(True, "Finishing measuring the drawing — your BOQ "
                                 "starts the moment it's done…")
            return

        # The agent pickers are the source of truth now (defaulted from the
        # configured agents). This also removes the old "no writing agent set
        # up yet" dead end — the picker always offers the registry's tools.
        self.writer_agent = self.writer_combo.currentText().strip()
        if not self.writer_agent:
            QMessageBox.warning(self, "BOQ",
                                "Pick an AI to write the BOQ (the 'Write with' box).")
            return
        self.researcher = self.research_combo.currentText().strip()
        # ChatGPT specifically, and only when there is something it can read.
        # It is the stage that turns a screenshot of the sheet plus a sample
        # BOQ into the legend, scope and house style the writer then follows.
        # Matches cmd_boq in prism_terminal/prism.py — the pipelines have to
        # agree, or the same drawing produces two different documents.
        self.interpreter = "ChatGPT" if self.images else None
        self.request = request or f"Produce a {self._doc} from the attached drawing."

        # Start the clock for this run's timing report.
        self._t0 = time.time()
        self._last_t = self._t0
        self._stage_log = []

        if self.derive_cb.isChecked() and self.researcher:
            self._set_busy(True, f"{self.researcher} is checking the standard "
                                 "sizes and norms…")
            self._worker = AutomationWorker(
                {}, self.cfg, [], f"design/material standards for a {self._noun}",
                custom_stages=[("standards", self.researcher,
                                [self._pm.standards_prompt(
                                    self.request, project_context=self.request,
                                    measured_text=self.summary)])],
                chatgpt_analysis=False)
            self._worker.done.connect(self._on_standards)
            self._worker.failed.connect(self._on_failed)
            self._worker.start()
        else:
            self._interpret()

    def _lap(self, stage: str):
        """Record how long the stage that just finished took, and restart the
        clock for the next one."""
        now = time.time()
        self._stage_log.append((stage, now - (self._last_t or now)))
        self._last_t = now

    # Human labels for the stage keys, in the order a person reads the run.
    _STAGE_LABELS = {"standards": "research", "interpret": "read drawing",
                     "format": "write"}

    def _timing_text(self) -> str:
        """"2m 34s  ·  research 1m 02s · read drawing 45s · write 47s" — the
        total this run took and where it went. Empty if the run wasn't timed."""
        if not self._t0:
            return ""
        total = short_duration(time.time() - self._t0)
        parts = [f"{self._STAGE_LABELS.get(s, s)} {short_duration(d)}"
                 for s, d in self._stage_log]
        return total + (f"  ·  {' · '.join(parts)}" if parts else "")

    def _on_standards(self, responses: dict, links: dict):
        got = [t for t in (responses.get("standards") or []) if t.strip()]
        self._standards = got[0] if got else ""
        self._links.update(links)
        self._all_responses.update(responses)
        self._stage_agents_map["standards"] = self.researcher
        self._lap("standards")
        self._interpret()

    def _interpret(self):
        """Read the screenshot and the sample BOQ for legend, scope and style.

        A separate automation.run from the others because each stage needs a
        DIFFERENT file set — and this one must never receive the .dwg.
        ChatGPT cannot parse a binary CAD file; handing it one is what made
        this stage return nothing in the CLI, leaving the writer following a
        brief that did not exist.
        """
        if not self.interpreter:
            self._write()
            return
        self._set_busy(True, f"{self.interpreter} is reading the drawing "
                             "screenshot and your sample…")
        prompt = self.boq.interpretation_prompt(
            self.request, self.summary,
            self.boq.roles_text([], self.templates, self.images, self.notes),
            legend_hint=self.legend_edit.text().strip())
        self._worker = AutomationWorker(
            {}, self.cfg,
            # Images, sample and notes only — deliberately not the drawing.
            list(self.images) + list(self.templates) + list(self.notes),
            "read a drawing screenshot for BOQ legend and scope",
            custom_stages=[("interpret", self.interpreter, [prompt])],
            chatgpt_analysis=False)
        self._worker.done.connect(self._on_interpreted)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_interpreted(self, responses: dict, links: dict):
        got = [t for t in (responses.get("interpret") or []) if t.strip()]
        self._brief = got[0] if got else ""
        self._links.update(links)
        self._all_responses.update(responses)
        self._stage_agents_map["interpret"] = self.interpreter
        self._lap("interpret")
        self._write()

    def _write(self):
        self._set_busy(True, f"{self.writer_agent} is writing your BOQ…")
        prompt = self._pm.formatting_prompt(
            self.summary, project_context=self.request,
            has_template=bool(self.templates),
            legend=self.legend_edit.text().strip(),
            scoped=bool(self.scope_edit.text().strip()),
            # Threaded through explicitly rather than relying on the browser
            # relay to carry it between stages — the CLI learned that the hard
            # way, with an empty handoff and then a garbled one.
            brief_text=self._brief,
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
            {}, self.cfg, files, f"{self._doc} — {self.request}",
            custom_stages=[("format", self.writer_agent, [prompt])],
            chatgpt_analysis=False)
        self._worker.done.connect(self._on_written)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_written(self, responses: dict, links: dict):
        self._set_busy(False, "")
        self._links.update(links)
        self._all_responses.update(responses)
        self._stage_agents_map["format"] = self.writer_agent
        self._lap("format")
        # How long the whole BOQ took, and where the time went — the stages are
        # web round-trips of tens of seconds each, so "why did that take three
        # minutes" is answered here rather than left a mystery.
        timing = self._timing_text()
        texts = [t for t in (responses.get("format") or []) if t.strip()]
        if not texts:
            self.status.setText("Nothing came back. The measured numbers above "
                                "are still saved." + (f"  ({timing})" if timing else ""))
        else:
            self.result.setPlainText(texts[0])
            self.status.setText(
                (f"Done in {timing}. " if timing else "Done. ")
                + "Check the numbers against the saved file above.")
        self.open_btn.setEnabled(bool(self._links.get("format")))
        CB.config.save_run({
            "query": f"{self._noun} — {self.request}", "responses": responses,
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

    def closeEvent(self, event):
        """Wind up any worker before this dialog is destroyed.

        A QThread destroyed while still running aborts the whole process —
        "QThread: Destroyed while thread is still running", then a core dump —
        so closing the BOQ window mid-run took Prism down with it. The
        automation worker polls a stop flag between stages and inside its
        waits, so asking first lets it close its browser tab cleanly instead
        of being killed.
        """
        for worker in (getattr(self, "_worker", None),
                       getattr(self, "_measure_worker", None),
                       getattr(self, "_rec", None)):
            if worker is None or not worker.isRunning():
                continue
            if hasattr(worker, "stop"):
                worker.stop()
            # Bounded: a stage mid-scrape can take a moment to notice, but a
            # dialog that refuses to close is its own bug.
            if not worker.wait(8000):
                worker.terminate()
                worker.wait(1000)
        super().closeEvent(event)

    def _open_link(self):
        import webbrowser
        url = self._links.get("format")
        if url:
            webbrowser.open(url)
