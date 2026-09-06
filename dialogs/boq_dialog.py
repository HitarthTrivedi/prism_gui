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

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QBrush, QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QPushButton,
    QPlainTextEdit, QLineEdit, QMessageBox, QCheckBox, QProgressBar,
    QComboBox, QWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QDoubleSpinBox, QFileDialog, QAbstractItemView, QSizePolicy,
)

import core_bridge as CB
import i18n
import theme
import wakeword
from dialogs.base import PrismDialog
from workers import AutomationWorker, BoqPdfWorker, MeasureWorker, RecordWorker
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
        self.resize(700, 720)
        self.setMinimumSize(560, 540)
        self.cfg = cfg
        self.boq = CB.get_boq()
        self.boqp = CB.get_boq_price()
        # Start priced against the bundled indicative rates so the grid is
        # useful the moment a drawing is measured; "Load rate list…" swaps in
        # the user's own price list or a DSR/SOR export.
        try:
            self._rate_items = self.boqp.starter_rate_items()
        except Exception:                               # noqa: BLE001
            self._rate_items = []
        # The research + write-up prompts come from core.bom in BOM mode and
        # core.boq in BOQ mode; measurement, interpretation and roles_text
        # always come from self.boq (they are mode-independent).
        self._pm = CB.bom if self.mode == "bom" else self.boq

        self.cad_path = ""
        self.dxf_path = ""      # readable DXF from measuring (a .dwg is converted)
        # Real files this session produced (CSV, priced Excel, tender PDF) — handed
        # to the post-completion follow-up so it carries the actual deliverables,
        # which live under their own Artifacts task folders the run's own key misses.
        self._produced_files: list[str] = []
        self.templates: list[dict] = []
        self.images: list[dict] = []
        self.notes: list[dict] = []
        self.q = None
        self.summary = ""
        self.csv_path = ""
        self._worker = None
        self._rec = None
        self._pdf_worker = None
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

        # ── Price it → a tender-ready Excel BOQ (deterministic) ─────────────
        # The measured quantities, priced. No AI touches a number here:
        # quantities are the measured ones (locked), rates come from a library
        # or are typed, and every amount/tax/total is a LIVE formula in the
        # exported .xlsx — the estimator opens it and keeps working. Hidden
        # until a drawing has been measured, because pricing needs quantities.
        self.price_box = QGroupBox(
            f"Price it — export a tender-ready Excel {self._noun}")
        pv = QVBoxLayout(self.price_box)
        phint = QLabel(i18n.t(
            "Quantities are measured and locked. Set a rate per line, or load "
            "your price list / SOR to auto-fill rates where the unit matches. "
            "Unpriced lines are shaded; totals update live."))
        phint.setObjectName("note")
        phint.setWordWrap(True)
        pv.addWidget(phint)

        self.rate_table = QTableWidget(0, 6)
        self.rate_table.setHorizontalHeaderLabels(
            ["Section", "Description", "Unit", "Qty", "Rate ₹", "Amount ₹"])
        self.rate_table.verticalHeader().setVisible(False)
        self.rate_table.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.SelectedClicked
            | QAbstractItemView.EditKeyPressed | QAbstractItemView.AnyKeyPressed)
        # Fixed, compact widths for everything except Description (which soaks up
        # the slack). ResizeToContents was letting the table demand ~1600px of
        # width and drag the whole dialog wide; explicit widths + an internal
        # horizontal scrollbar keep the table inside the window instead.
        self.rate_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.rate_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        header = self.rate_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        for c in (0, 2, 3, 4, 5):
            header.setSectionResizeMode(c, QHeaderView.Interactive)
        for col, w in ((0, 132), (2, 58), (3, 58), (4, 80), (5, 96)):
            self.rate_table.setColumnWidth(col, w)
        self.rate_table.setMinimumHeight(200)
        self.rate_table.setMinimumWidth(320)
        self.rate_table.itemChanged.connect(self._on_rate_cell_changed)
        pv.addWidget(self.rate_table)

        controls = QWidget()
        crow = QHBoxLayout(controls)
        crow.setContentsMargins(0, 0, 0, 0)
        crow.setSpacing(theme.SPACE_2)
        crow.setSpacing(theme.SPACE_1)
        self.load_rates_btn = self.button(
            i18n.t("Load rates…"), "secondary", small=True,
            on_click=self._load_rate_list)
        self.add_row_btn = self.button(
            i18n.t("Add"), "secondary", small=True,
            on_click=lambda: (self._add_price_row(), self._recompute_totals()))
        crow.addWidget(self.load_rates_btn)
        crow.addWidget(self.add_row_btn)
        crow.addStretch(1)          # actions on the left, tax params on the right
        # Compact: the "%" lives in the spinner suffix, so the labels stay short
        # and the whole row fits without widening the dialog.
        clab = QLabel(i18n.t("Cont.")); clab.setObjectName("meta")
        crow.addWidget(clab)
        self.contingency_spin = QDoubleSpinBox()
        self.contingency_spin.setRange(0, 100)
        self.contingency_spin.setDecimals(1)
        self.contingency_spin.setValue(3.0)
        self.contingency_spin.setSuffix(" %")
        self.contingency_spin.setMaximumWidth(78)
        self.contingency_spin.valueChanged.connect(self._recompute_totals)
        crow.addWidget(self.contingency_spin)
        glab = QLabel(i18n.t("GST")); glab.setObjectName("meta")
        crow.addWidget(glab)
        # A preset picker, not a free number: works-contract GST is a fixed set
        # (18% standard, 12% some works, 5% specified) — typing an arbitrary
        # rate like 15% is simply wrong, so it isn't offered.
        self.gst_combo = QComboBox()
        for pct in ("18", "12", "5"):
            self.gst_combo.addItem(f"{pct} %", pct)
        self.gst_combo.setMaximumWidth(78)
        self.gst_combo.currentIndexChanged.connect(self._recompute_totals)
        crow.addWidget(self.gst_combo)
        self.interstate_cb = QCheckBox(i18n.t("IGST"))
        self.interstate_cb.setToolTip(i18n.t(
            "Inter-state supply — one IGST line instead of CGST + SGST"))
        self.interstate_cb.toggled.connect(self._recompute_totals)
        crow.addWidget(self.interstate_cb)
        pv.addWidget(controls)

        # A clean total bar: a caption over the big figure, with a small unpriced
        # note beneath, on the left; the deliverable buttons on the right. The
        # figure is short so nothing wraps — the single wrapping label this
        # replaced was the ungainly part.
        totals = QWidget()
        trow = QHBoxLayout(totals)
        trow.setContentsMargins(0, theme.SPACE_2, 0, 0)
        tcol = QVBoxLayout()
        tcol.setContentsMargins(0, 0, 0, 0)
        tcol.setSpacing(0)
        cap = QLabel(i18n.t("Grand total (incl. GST)"))
        cap.setObjectName("meta")
        cap.setWordWrap(True)
        self.total_label = QLabel("—")
        self.total_label.setObjectName("h4")
        self.unpriced_label = QLabel("")
        self.unpriced_label.setObjectName("meta")
        self.unpriced_label.setStyleSheet(f"color:{theme.ERR_INK};")
        self.unpriced_label.setWordWrap(True)
        self.unpriced_label.setVisible(False)
        tcol.addWidget(cap)
        tcol.addWidget(self.total_label)
        tcol.addWidget(self.unpriced_label)
        trow.addLayout(tcol)
        trow.addStretch(1)
        # The tender PDF (Schedule A+B) is a works-BOQ deliverable; BOM mode,
        # which bills a parts list, gets the Excel export only.
        if self.mode == "boq":
            self.pdf_btn = self.button(
                i18n.t("Tender PDF"), "secondary", small=True,
                on_click=self._export_tender_pdf)
            trow.addWidget(self.pdf_btn, 0, Qt.AlignVCenter)
        self.export_btn = self.button(
            i18n.t("Export Excel"), "primary", small=True,
            on_click=self._export_priced_xlsx)
        trow.addWidget(self.export_btn, 0, Qt.AlignVCenter)
        pv.addWidget(totals)

        self.price_box.setVisible(False)
        root.addWidget(self.price_box)

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
        self.writer_combo.setMaximumWidth(150)
        self.research_combo = QComboBox()
        self.research_combo.addItems(research_opts)
        self.research_combo.setMaximumWidth(150)
        _preselect(self.writer_combo,
                   cfg_agents.get("content") or cfg_agents.get("brains"))
        _preselect(self.research_combo,
                   cfg_agents.get("research") or cfg_agents.get("brains"))
        # ── Write it up with AI — the alternative to the priced export ──────
        # A second card, matching "Price it" above: the AIs research the
        # standards and format the document. Works with or without a drawing.
        self.ai_box = QGroupBox(i18n.t("Write it up with AI"))
        ai_l = QVBoxLayout(self.ai_box)
        ai_l.setSpacing(theme.ROW_GAP)
        ai_hint = QLabel(i18n.t(
            "The AIs look up the standard sizes and norms and write the "
            f"{self._noun} up as a formatted document — with or without a drawing."))
        ai_hint.setObjectName("note")
        ai_hint.setWordWrap(True)
        ai_l.addWidget(ai_hint)

        picker = QWidget()
        prow = QHBoxLayout(picker)
        prow.setContentsMargins(0, 0, 0, 0)
        prow.setSpacing(theme.SPACE_2)
        wlab = QLabel(i18n.t("Write with")); wlab.setObjectName("meta")
        rlab = QLabel(i18n.t("· Research")); rlab.setObjectName("meta")
        prow.addWidget(wlab)
        prow.addWidget(self.writer_combo)
        prow.addWidget(rlab)
        prow.addWidget(self.research_combo)
        prow.addStretch(1)
        ai_l.addWidget(picker)

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
        ai_l.addWidget(self.more)

        self.result = QPlainTextEdit()
        self.result.setReadOnly(True)
        self.result.setPlaceholderText(f"Your {self._noun} will appear here.")
        self.result.setMinimumHeight(120)
        ai_l.addWidget(self.result, stretch=1)
        root.addWidget(self.ai_box, stretch=1)

        # Shared status line for both cards — measuring, exporting, or writing up.
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        root.addWidget(self.progress)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.open_btn = self.button(i18n.t("Open in browser"), "secondary",
                                    icon_name="external", small=True,
                                    on_click=self._open_link)
        self.open_btn.setEnabled(False)
        self.footer.add_utility(self.open_btn)
        self.footer.add_secondary(self.button(i18n.t("Close"), on_click=self.reject))
        # Secondary, not the footer's primary: the priced export in the "Price
        # it" card is now the main deliverable, so the AI write-up is the
        # alternative rather than a second competing blue button.
        self.run_btn = self.button(f"Make my {self._noun}", "secondary",
                                   icon_name="check", on_click=self._run)
        self.footer.add_secondary(self.run_btn)

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
        # The DXF the engine actually read (converted from a .dwg if needed) —
        # attached to the AI write-up so it reads geometry with ezdxf in seconds
        # instead of trying to build a converter itself.
        self.dxf_path = getattr(self._measure_worker, "dxf_path", "")
        self.summary = self.boq.summary_text(q)
        self.meas_view.setPlainText(self.summary)
        self.meas_box.setVisible(True)

        os.makedirs(CB.config.RUNS_DIR, exist_ok=True)
        self.csv_path = os.path.join(
            CB.config.RUNS_DIR, f"boq_quantities_{int(time.time())}.csv")
        self.boq.write_quantities_csv(q, self.csv_path)
        self._produced_files.append(self.csv_path)
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
        # Build the priced grid from the measured quantities — the deterministic
        # path to a tender-ready Excel, alongside the AI write-up below.
        self._populate_pricing()
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

    # ── pricing → tender-ready Excel (deterministic; no AI touches a number) ──

    def _populate_pricing(self):
        """Build the pricing grid from the measured quantities and reveal it.
        Rates pre-fill from the loaded library only where the unit matches — a
        length is never priced at a per-cum rate; every other line waits for a
        rate the user enters."""
        if not self.q:
            return
        try:
            boq = self.boqp.boq_from_measured(
                self.q, rate_items=self._rate_items, title=self._doc)
        except Exception:                               # noqa: BLE001
            return
        self._fill_table(boq.items)
        self.price_box.setVisible(True)

    def _fill_table(self, items):
        self.rate_table.blockSignals(True)
        self.rate_table.setRowCount(0)
        for it in items:
            self._add_price_row(it)
        self.rate_table.blockSignals(False)
        self._recompute_all()

    def _add_price_row(self, item=None):
        r = self.rate_table.rowCount()
        prev = self.rate_table.blockSignals(True)
        self.rate_table.insertRow(r)
        measured = bool(item and item.source.startswith("measured"))
        values = [
            item.section if item else "Additional items",
            item.description if item else "",
            item.unit if item else "nos",
            f"{float(item.quantity):g}" if item else "1",
            (f"{float(item.rate):g}" if (item and item.priced) else ""),
            "",
        ]
        for c, val in enumerate(values):
            cell = QTableWidgetItem(val)
            if c in (3, 4, 5):
                cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if c == 5 or (c == 3 and measured):   # amount & measured qty: locked
                cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
            self.rate_table.setItem(r, c, cell)
        if item and item.remark:
            self.rate_table.item(r, 1).setToolTip(item.remark)
        self._recompute_row(r)
        self.rate_table.blockSignals(prev)

    def _cell_text(self, r, c):
        it = self.rate_table.item(r, c)
        return it.text().strip() if it else ""

    def _cell_decimal(self, r, c):
        from decimal import Decimal, InvalidOperation
        try:
            return Decimal(self._cell_text(r, c).replace(",", "") or "0")
        except (InvalidOperation, ValueError):
            return Decimal(0)

    def _recompute_row(self, r):
        prev = self.rate_table.blockSignals(True)
        qty = self._cell_decimal(r, 3)
        rate = self._cell_decimal(r, 4)
        amount = self.boqp.quoting.rupees(qty * rate)
        acell = self.rate_table.item(r, 5)
        if acell is None:
            acell = QTableWidgetItem()
            acell.setFlags(acell.flags() & ~Qt.ItemIsEditable)
            acell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.rate_table.setItem(r, 5, acell)
        acell.setText(f"{amount:,.2f}")
        # Flag an unpriced row with the app's own error tone — background AND
        # ink together (theme.ERR_BG/ERR_INK), the same pairing every Prism
        # status pill uses. Setting only the background (as this first did) left
        # the theme's default light text on a light tint — unreadable, and out
        # of step with the palette. Priced rows clear BOTH back to the default.
        if rate <= 0:
            bg, fg = QColor(theme.ERR_BG), QColor(theme.ERR_INK)
        else:
            bg, fg = QBrush(), QBrush()
        for c in range(6):
            cell = self.rate_table.item(r, c)
            if cell is not None:
                cell.setBackground(bg)
                cell.setForeground(fg)
        self.rate_table.blockSignals(prev)

    def _recompute_all(self):
        for r in range(self.rate_table.rowCount()):
            self._recompute_row(r)
        self._recompute_totals()

    def _on_rate_cell_changed(self, item):
        if item.column() in (2, 3, 4):      # unit / qty / rate change the amount
            self._recompute_row(item.row())
        self._recompute_totals()

    def _recompute_totals(self, *_):
        boq = self._collect_boq()
        total = boq.grand_total()
        try:
            shown = self.boqp.quoting.indian_currency(total)
        except Exception:                               # noqa: BLE001
            shown = f"₹ {total:,.2f}"
        self.total_label.setText(shown)
        n = len(boq.unpriced())
        self.unpriced_label.setText(f"{n} item(s) unpriced" if n else "")
        self.unpriced_label.setVisible(bool(n))

    def _collect_boq(self):
        from datetime import date
        from decimal import Decimal
        items = []
        for r in range(self.rate_table.rowCount()):
            desc = self._cell_text(r, 1)
            if not desc:
                continue
            items.append(self.boqp.BoqItem(
                description=desc,
                unit=self._cell_text(r, 2) or "nos",
                quantity=self._cell_decimal(r, 3),
                rate=self._cell_decimal(r, 4),
                section=self._cell_text(r, 0) or "Measured Works"))
        return self.boqp.Boq(
            title=self._doc, items=items,
            project=(self.ask.text().strip()[:120] if hasattr(self, "ask") else ""),
            date=date.today().strftime("%d-%m-%Y"),
            contingency_pct=Decimal(str(self.contingency_spin.value())),
            gst_pct=Decimal(self.gst_combo.currentData()),
            interstate=self.interstate_cb.isChecked())

    def _load_rate_list(self):
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.t("Load rate list"), "",
            "Rate lists (*.xlsx *.xlsm *.csv);;All files (*)")
        if not path:
            return
        try:
            items = self.boqp.quoting.load_rates(path)
        except Exception as e:                          # noqa: BLE001
            QMessageBox.warning(self, self._noun,
                                f"Couldn't read that rate list:\n\n{e}")
            return
        self._rate_items = items
        self._reprice_blanks()
        self.status.setText(
            f"Loaded {len(items)} rates from {os.path.basename(path)} — filled "
            "matching blank rates; your typed rates were kept.")

    def _reprice_blanks(self):
        """Fill only the still-blank rate cells from the current library, and
        only where the unit matches — never overwrite a rate the user typed."""
        prev = self.rate_table.blockSignals(True)
        for r in range(self.rate_table.rowCount()):
            if self._cell_text(r, 4):
                continue
            desc = self._cell_text(r, 1)
            unit = self._cell_text(r, 2)
            if not desc:
                continue
            matches = self.boqp.quoting.match_item(desc, self._rate_items)
            if matches and self.boqp.quoting.is_confident(matches):
                best = matches[0].item
                if self.boqp._units_match(unit, best.unit):
                    self.rate_table.item(r, 4).setText(f"{float(best.rate):g}")
        self.rate_table.blockSignals(prev)
        self._recompute_all()

    def _export_priced_xlsx(self):
        import time
        boq = self._collect_boq()
        if not boq.items:
            QMessageBox.information(
                self, self._noun,
                "Nothing to price yet — measure a drawing or add an item first.")
            return
        unpriced = boq.unpriced()
        if unpriced:
            ans = QMessageBox.question(
                self, self._noun,
                f"{len(unpriced)} item(s) have no rate yet — they'll export as "
                "₹0 and be shaded red in the sheet.\n\nExport anyway?",
                QMessageBox.Yes | QMessageBox.No)
            if ans != QMessageBox.Yes:
                return
        try:
            os.makedirs(CB.config.RUNS_DIR, exist_ok=True)
            out = os.path.join(CB.config.RUNS_DIR,
                               f"boq_priced_{int(time.time())}.xlsx")
            self.boqp.write_boq_xlsx(boq, out)
        except Exception as e:                          # noqa: BLE001
            QMessageBox.warning(self, self._noun,
                                f"Couldn't write the Excel BOQ:\n\n{e}")
            return
        try:
            CB.config.save_artifact(
                out, os.path.basename(self.cad_path or out),
                kind="boq", task=f"{self._doc} — priced")
        except Exception:                               # noqa: BLE001
            pass
        self._produced_files.append(out)
        self.status.setText(f"Priced {self._noun} saved → {out}")
        QDesktopServices.openUrl(QUrl.fromLocalFile(out))

    def _export_tender_pdf(self):
        """Render the Schedule A+B tender PDF — off the UI thread, because
        launching the browser to print takes a second or two."""
        import time
        boq = self._collect_boq()
        if not boq.items:
            QMessageBox.information(
                self, self._noun,
                "Nothing to export yet — measure a drawing or add an item first.")
            return
        unpriced = boq.unpriced()
        if unpriced:
            ans = QMessageBox.question(
                self, self._noun,
                f"{len(unpriced)} item(s) have no rate yet — they'll show as "
                "'—' and be excluded from the totals.\n\nExport the PDF anyway?",
                QMessageBox.Yes | QMessageBox.No)
            if ans != QMessageBox.Yes:
                return
        os.makedirs(CB.config.RUNS_DIR, exist_ok=True)
        out = os.path.join(CB.config.RUNS_DIR, f"boq_tender_{int(time.time())}.pdf")
        self._set_busy(True, "Rendering the tender PDF…")
        self.pdf_btn.setEnabled(False)
        self._pdf_worker = BoqPdfWorker(boq, out)
        self._pdf_worker.done.connect(self._on_pdf_done)
        self._pdf_worker.failed.connect(self._on_pdf_failed)
        self._pdf_worker.start()

    def _on_pdf_done(self, path: str):
        self._set_busy(False, "")
        self.pdf_btn.setEnabled(True)
        try:
            CB.config.save_artifact(
                path, os.path.basename(self.cad_path or path),
                kind="boq", task=f"{self._doc} — tender PDF")
        except Exception:                               # noqa: BLE001
            pass
        self._produced_files.append(path)
        self.status.setText(f"Tender PDF saved → {path}")
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _on_pdf_failed(self, error: str):
        self._set_busy(False, "")
        self.pdf_btn.setEnabled(True)
        QMessageBox.warning(self, self._noun,
                            f"Couldn't render the tender PDF:\n\n{error}")

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
        # Attach the DXF the writer can actually read, for spatial context. For a
        # .dwg source this is the DXF Prism ALREADY converted while measuring, so
        # the writer reads the geometry with ezdxf in seconds instead of trying
        # to build a converter itself. Prism has already measured it; the summary
        # carries the numbers — this is only so the write-up can reason about
        # WHERE things sit (zones, routes, counts) for any derived items.
        dxf = self.dxf_path if self.dxf_path.lower().endswith(".dxf") else (
            self.cad_path if self.cad_path.lower().endswith(".dxf") else "")
        if self.q and dxf and os.path.exists(dxf):
            try:
                files.insert(0, CB.files.attach(dxf))
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
                       getattr(self, "_pdf_worker", None),
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
