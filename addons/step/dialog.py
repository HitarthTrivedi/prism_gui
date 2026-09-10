"""STEP add-on — measure a 3D model, then draft, ask or edit. No AI sees it.

The GUI face of the terminal's /step, /step-auto and /step-ask, on the same
rule as Gerber: the customer's STEP file is their product, and it never
leaves this machine. core.stepfile measures it here; the only things that
ever reach an AI are the measured NUMBERS and Prism's own plain render of
the parts (a PNG Prism drew, not the model). The three actions:

    Draft  — measure, then the image tool draws a dimensioned drawing sheet
             FROM THE NUMBERS (auto_brief) — the model stays here.
    Ask    — measure, then Groq suggests improvements from the numbers and
             the question, and a reviewing agent turns them into an exact
             change plan shown on a review page. Nothing is built.
    Edit   — Ask, then — after the person confirms against the review page
             — the plan is applied to a COPY of the model, locally, and the
             copy is re-measured so the After column is real, not predicted.

Several models can be attached at once; each is measured into its own
folder, named after it, under the folder the person chose (asked once, the
first time, and kept in cfg["step_out_dir"]). Every file inside carries the
model's own name — see core.stepfile.names().
"""
from __future__ import annotations

import os
import shutil

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QFileDialog, QFrame, QGroupBox, QHBoxLayout,
    QLabel, QMessageBox, QPlainTextEdit, QProgressBar, QRadioButton,
    QVBoxLayout, QWidget,
)

import core_bridge as CB
import i18n
import theme
from dialogs.base import PrismDialog
from workers import AutomationWorker
from addons.step.workers import (StepApplyWorker, StepAskWorker,
                                 StepMeasureWorker)
from widgets import icons
from widgets.ask_panel import AskPanel

MODEL_EXTS = (".step", ".stp")

# (key, label, what it does) — the order they are offered in.
ACTIONS = (
    ("draft", "Draft",
     "Measure and draw the dimensioned sheet here (front, top and side "
     "views, sizes in mm, hole table — no AI), then ChatGPT also draws a "
     "styled version from the numbers, never from the model."),
    ("ask", "Ask",
     "Measure, then get suggestions for the part from the numbers and your "
     "question, reviewed into an exact change plan you can read. Nothing "
     "is changed."),
    ("edit", "Edit",
     "Ask, then — once you confirm against the review page — apply the "
     "plan to a COPY of the model, here, and re-measure it. The original "
     "is never touched."),
)


class StepDialog(PrismDialog):
    def __init__(self, cfg: dict, attachments: list, parent=None):
        super().__init__(
            i18n.t("STEP"),
            i18n.t("Attach a 3D model. It is measured here, on this machine "
                   "— no AI ever sees the STEP file."),
            icon="grid", parent=parent, closable=False, scrollable=True)
        self.setWindowTitle("STEP — 3D model measurement")
        self.resize(820, 820)
        self.setMinimumSize(620, 520)
        self.cfg = cfg
        self.sf = CB.get_stepfile()

        self.paths: list[str] = []
        # Once measured: [{"path", "report", "out_dir", "drawn", "xlsx"}]
        self.models: list[dict] = []
        self._queue: list[dict] = []      # models still waiting for the action
        self._current: dict | None = None
        self._worker = None
        self._agent_worker = None
        self._ask_worker = None
        self._apply_worker = None
        self._links: dict = {}
        self._responses: dict = {}
        self._made_files: list = []
        self._notes: list[str] = []

        root = self.body
        root.setSpacing(theme.ROW_GAP)

        # ── 1 · the model first ────────────────────────────────────────
        # The file comes before the question, in that order on screen: the
        # question and the choice of action only appear once a model is
        # attached, because nothing below makes sense without one.
        title = QLabel(i18n.t("1 · Attach the STEP model"))
        title.setObjectName("h4")
        root.addWidget(title)
        hint = QLabel(i18n.t("Add the .step / .stp file — several at once "
                             "is fine. What to do with it comes next."))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.NEUTRAL[700]}; font-size: 12.5px;")
        root.addWidget(hint)

        self.ask = AskPanel(
            "For Ask and Edit, say what you want — e.g. \"how do I make "
            "this lighter?\" or \"fit M8 bolts instead of M6\". Draft needs "
            "no text.")
        self.ask.files_added.connect(self._on_files_added)
        root.addWidget(self.ask)

        # The confidentiality promise, stated as a real notice — same as
        # Gerber, because it is the same promise and the reason this sells.
        lock = QFrame()
        lock.setObjectName("stepLock")
        lock.setAttribute(Qt.WA_StyledBackground, True)
        lock.setStyleSheet(
            f"#stepLock {{ background: {theme.OK_BG};"
            f" border: 1px solid {theme.OK};"
            f" border-radius: {theme.R_CONTROL}px; }}")
        lock_row = QHBoxLayout(lock)
        lock_row.setContentsMargins(theme.SPACE_3, theme.SPACE_3,
                                    theme.SPACE_3, theme.SPACE_3)
        lock_row.setSpacing(theme.SPACE_3)
        glyph = QLabel()
        glyph.setPixmap(icons.pixmap("lock", 17, theme.OK_INK))
        glyph.setAlignment(Qt.AlignTop)
        lock_row.addWidget(glyph)
        lock_text = QLabel(
            "The STEP file never leaves this machine. Draft, Ask and Edit "
            "show an AI only the measured NUMBERS and Prism's own plain "
            "render of the parts — never the model, never a path. Edits are "
            "made here, on a copy.")
        lock_text.setWordWrap(True)
        lock_text.setStyleSheet(f"color: {theme.OK_INK}; font-size: 13px;")
        lock_row.addWidget(lock_text, stretch=1)
        root.addWidget(lock)

        # ── options: material, and where the files go ──────────────────
        opt_box = QGroupBox(i18n.t("Options"))
        opt_v = QVBoxLayout(opt_box)
        opt_v.setSpacing(theme.SPACE_2)
        mat_row = QHBoxLayout()
        mat_row.addWidget(QLabel(i18n.t("Material")))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(list(self.sf.MODES))
        self.mode_combo.setCurrentText(self.cfg.get("step_mode") or "metal")
        mat_row.addWidget(self.mode_combo)
        mat_note = QLabel(i18n.t("— sheet metal reads thickness and weight "
                                 "in steel; plastic reads wall and ABS/PP/PC"))
        mat_note.setStyleSheet(
            f"color: {theme.NEUTRAL[700]}; font-size: 12.5px;")
        mat_row.addWidget(mat_note)
        mat_row.addStretch(1)
        opt_v.addLayout(mat_row)

        # Where everything for a model goes. Asked ONCE, the first time
        # Generate is pressed (see _ensure_root), and shown here so the
        # answer is never a mystery and can be changed at any time.
        dir_row = QHBoxLayout()
        self.root_label = QLabel(self._root_caption())
        self.root_label.setWordWrap(True)
        dir_row.addWidget(self.root_label, stretch=1)
        dir_row.addWidget(self.button(i18n.t("Change folder…"), "secondary",
                                      small=True, on_click=self._pick_root))
        self.root_default_btn = self.button(i18n.t("Use the Desktop"),
                                            "secondary", small=True,
                                            on_click=self._use_default_root)
        self.root_default_btn.setVisible(bool(self.cfg.get("step_out_dir")))
        dir_row.addWidget(self.root_default_btn)
        opt_v.addLayout(dir_row)
        root.addWidget(opt_box)

        # ── 2 · then what to do with it ────────────────────────────────
        # Hidden until a model is attached. The question box and the Speak
        # button are the AskPanel's own, reparented down here so the page
        # reads top to bottom: the file, then the ask, then the action.
        self.step2 = QWidget()
        step2_v = QVBoxLayout(self.step2)
        step2_v.setContentsMargins(0, 0, 0, 0)
        step2_v.setSpacing(theme.ROW_GAP)
        title2 = QLabel(i18n.t("2 · What do you want done with it?"))
        title2.setObjectName("h4")
        step2_v.addWidget(title2)
        step2_v.addWidget(self.ask.edit)
        mic_row = QHBoxLayout()
        mic_row.addWidget(self.ask.mic_btn)
        mic_row.addStretch(1)
        step2_v.addLayout(mic_row)
        act_box = QGroupBox(i18n.t("What to do"))
        act_v = QVBoxLayout(act_box)
        act_v.setSpacing(theme.SPACE_2)
        self._action_group = QButtonGroup(self)
        self._action_buttons: dict[str, QRadioButton] = {}
        for key, label, blurb in ACTIONS:
            row = QWidget()
            row_l = QHBoxLayout(row)
            row_l.setContentsMargins(0, 0, 0, 0)
            row_l.setSpacing(theme.SPACE_2)
            radio = QRadioButton(i18n.t(label))
            radio.setProperty("action", key)
            self._action_group.addButton(radio)
            self._action_buttons[key] = radio
            row_l.addWidget(radio)
            note = QLabel(i18n.t(blurb))
            note.setWordWrap(True)
            note.setStyleSheet(
                f"color: {theme.NEUTRAL[700]}; font-size: 12.5px;")
            row_l.addWidget(note, stretch=1)
            act_v.addWidget(row)
        self._action_buttons["draft"].setChecked(True)
        step2_v.addWidget(act_box)
        self.step2.setVisible(False)
        root.addWidget(self.step2)

        # Only appears once a model has actually been measured.
        self.meas_box = QGroupBox(i18n.t("Measured — not by an AI"))
        meas_l = QVBoxLayout(self.meas_box)
        self.meas_view = QPlainTextEdit()
        self.meas_view.setReadOnly(True)
        self.meas_view.setMinimumHeight(220)
        meas_l.addWidget(self.meas_view)
        self.files_label = QLabel("")
        self.files_label.setWordWrap(True)
        self.files_label.setStyleSheet(
            f"color: {theme.OK_INK}; background: {theme.OK_BG};"
            f" border-radius: {theme.R_CONTROL}px;"
            f" padding: {theme.SPACE_2}px {theme.SPACE_3}px;"
            f" font-size: 13px;")
        meas_l.addWidget(self.files_label)
        self.meas_box.setVisible(False)
        root.addWidget(self.meas_box, stretch=1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        root.addWidget(self.progress)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.result = QPlainTextEdit()
        self.result.setReadOnly(True)
        self.result.setPlaceholderText(
            i18n.t("What the AI drew, suggested or planned appears here."))
        self.result.setMinimumHeight(120)
        root.addWidget(self.result)

        self.folder_btn = self.button(i18n.t("Open folder"), "secondary",
                                      icon_name="folder", small=True,
                                      on_click=self._open_folder)
        self.folder_btn.setEnabled(False)
        self.footer.add_utility(self.folder_btn)
        self.open_btn = self.button(i18n.t("Open in browser"), "secondary",
                                    icon_name="external", small=True,
                                    on_click=self._open_link)
        self.open_btn.setEnabled(False)
        self.footer.add_utility(self.open_btn)
        self.footer.add_secondary(
            self.button(i18n.t("Close"), on_click=self.reject))
        self.generate_btn = self.button(i18n.t("Generate"), "primary",
                                        icon_name="grid",
                                        on_click=self._generate)
        self.generate_btn.setEnabled(False)
        self.generate_btn.setToolTip(i18n.t("Attach a model first"))
        self.footer.set_primary(self.generate_btn)

        if attachments:
            self._on_files_added([a["path"] for a in attachments])

    # ── where the files go ───────────────────────────────────────────────

    def _root(self) -> str:
        return self.cfg.get("step_out_dir") or self.sf.DEFAULT_OUT_ROOT

    def _root_caption(self) -> str:
        return (i18n.t("Files go to {folder} — a folder per model, every "
                       "file named after the model.")
                .replace("{folder}", self._root()))

    def _pick_root(self) -> bool:
        path = QFileDialog.getExistingDirectory(
            self, i18n.t("Where should Prism keep the files for your STEP "
                         "models?"), self._root())
        if not path:
            return False
        self.cfg["step_out_dir"] = path
        CB.config.save(self.cfg)
        self.root_label.setText(self._root_caption())
        self.root_default_btn.setVisible(True)
        return True

    def _use_default_root(self):
        self.cfg["step_out_dir"] = ""
        CB.config.save(self.cfg)
        self.root_label.setText(self._root_caption())
        self.root_default_btn.setVisible(False)

    def _ensure_root(self) -> bool:
        """The question the owner asked for: where do all the files for a
        model go? Asked once — the answer is kept in cfg — and only at the
        moment it matters, the first Generate. Choosing the Desktop stores
        the default explicitly, so the question is not asked again."""
        if self.cfg.get("step_out_dir"):
            return True
        box = QMessageBox(self)
        box.setWindowTitle(i18n.t("STEP"))
        box.setIcon(QMessageBox.Question)
        box.setText(i18n.t("Where should Prism keep the files for your STEP "
                           "models?"))
        box.setInformativeText(i18n.t(
            "Prism makes a folder named after each model inside it, and every "
            "file in that folder carries the model's name. You can change "
            "this any time from the Options box."))
        choose = box.addButton(i18n.t("Choose a folder…"),
                               QMessageBox.AcceptRole)
        desktop = box.addButton(i18n.t("Use the Desktop"),
                                QMessageBox.ActionRole)
        box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(choose)
        box.exec()
        clicked = box.clickedButton()
        if clicked is choose:
            return self._pick_root()
        if clicked is desktop:
            self.cfg["step_out_dir"] = self.sf.DEFAULT_OUT_ROOT
            CB.config.save(self.cfg)
            self.root_label.setText(self._root_caption())
            self.root_default_btn.setVisible(True)
            return True
        return False

    # ── files ───────────────────────────────────────────────────────────

    def _on_files_added(self, paths: list):
        models, other = [], []
        for p in paths:
            if p and p.lower().endswith(MODEL_EXTS):
                if p not in self.paths:
                    models.append(p)
            elif p:
                other.append(os.path.basename(p))
        skipped = (i18n.t("Only .step / .stp models are measured — skipped: ")
                   + ", ".join(other)) if other else ""
        if not models:
            if skipped:
                self.status.setText(skipped)
            return
        self.paths += models
        self.ask.add_paths(models, emit=False)
        self.step2.setVisible(True)      # the file is in; now the ask
        self.generate_btn.setEnabled(True)
        self.generate_btn.setToolTip("")
        n = len(self.paths)
        self.status.setText(
            (i18n.t("{n} models attached. ").format(n=n) if n > 1
             else i18n.t("Model attached. "))
            + i18n.t("Now say what you want done with it, then press "
                     "Generate.")
            + (f"  {skipped}" if skipped else ""))

    def _action(self) -> str:
        for key, radio in self._action_buttons.items():
            if radio.isChecked():
                return key
        return "draft"

    def _mode(self) -> str:
        return self.mode_combo.currentText().strip() or "metal"

    # ── generate: measure, then the chosen action per model ────────────

    def _agents(self) -> dict:
        return CB.config.active_agents(self.cfg) or {}

    # Draft is ChatGPT's job, full stop. Not "the configured visual tool",
    # not a fallback to whichever image model answers: its image model is
    # the one that draws a dimension sheet well from a numbers-only brief,
    # and a second, differently-wrong sheet from another tool is not a
    # rescue. The stage runs with failover off for the same reason.
    ARTIST = "ChatGPT"

    def _artist(self) -> str:
        return self.ARTIST

    def _planner(self) -> str:
        agents = self._agents()
        return next((agents[s] for s in ("brains", "content", "research")
                     if agents.get(s)), "")

    def _generate(self):
        if not self.paths:
            return
        action = self._action()
        question = self.ask.text().strip()
        if action in ("ask", "edit"):
            if not question:
                QMessageBox.warning(self, "STEP", i18n.t(
                    "Say what you want to know or change — type the "
                    "question in the box above."))
                return
            if not self.cfg.get("api_key"):
                QMessageBox.warning(self, "STEP", i18n.t(
                    "Ask and Edit start with Groq — add your Groq key in "
                    "Settings first."))
                return
        if action == "edit" and not self._planner():
            QMessageBox.warning(self, "STEP", i18n.t(
                "Edit needs a reasoning tool to review the plan — open "
                "Agents and pick one for Reasoning first."))
            return
        if not self._ensure_root():
            return

        self.cfg["step_mode"] = self._mode()
        try:
            CB.config.save(self.cfg)
        except Exception:                               # noqa: BLE001
            pass
        self.models = []
        self._responses, self._links, self._notes = {}, {}, []
        self.meas_view.clear()
        self.result.clear()
        self._set_busy(True, i18n.t(
            "Measuring — the model never leaves this machine…"))
        self._worker = StepMeasureWorker(list(self.paths), self._mode(),
                                         self._root())
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_measured)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_progress(self, line: str):
        self.meas_view.appendPlainText(f"   {line}")

    def _on_measured(self, results: list):
        self.models = results
        blocks, files = [], []
        for m in results:
            report = m["report"]
            heading = (f"═══ {report['file']} ═══\n" if len(results) > 1
                       else "")
            blocks.append(heading + self.sf.report_text(report))
            files.append(m["out_dir"])
            for path in (m.get("xlsx"), (m.get("drawn") or {}).get("png")):
                if path and os.path.exists(path):
                    try:
                        CB.config.save_artifact(path, os.path.basename(path),
                                                kind="step",
                                                task=report["file"])
                    except Exception:                   # noqa: BLE001
                        pass
        self.meas_view.setPlainText("\n\n".join(blocks))
        self.files_label.setText(
            i18n.t("Saved so every number can be checked → ")
            + "; ".join(files))
        self.meas_box.setVisible(True)
        self.folder_btn.setEnabled(True)
        self._queue = list(results)
        self._next()

    def _next(self):
        """The chosen action, one model at a time — an AI stage per model,
        in order, then the run is saved once."""
        if not self._queue:
            self._finish()
            return
        self._current = self._queue.pop(0)
        {"draft": self._draft, "ask": self._ask,
         "edit": self._ask}[self._action()](self._current)

    # ── draft ───────────────────────────────────────────────────────────

    def _draft(self, m: dict):
        report = m["report"]
        artist = self._artist()
        # Only Prism's OWN render travels — never the model. With no PNG
        # (no browser engine) the numbers in the brief carry it alone.
        files = []
        png = (m.get("drawn") or {}).get("png")
        if png and os.path.exists(png):
            try:
                files.append(CB.files.attach(png))
            except Exception:                           # noqa: BLE001
                pass
        self._made_files = []
        self._set_busy(True, i18n.t(
            "{agent} is drawing the dimensioned sheet for {file} — from "
            "the measured numbers only; the model stays here…")
            .replace("{agent}", artist).replace("{file}", report["file"]))
        self._agent_worker = AutomationWorker(
            {}, self.cfg, files, f"STEP — draft sheet for {report['file']}",
            custom_stages=[("visual", artist, [self.sf.auto_brief(report)])],
            chatgpt_analysis=False, files_out=self._made_files,
            # A picture is the point: the engine's full image budget — and
            # ChatGPT only, no hand-off to another tool if it stumbles.
            image_stages={"visual"}, failover=False)
        self._agent_worker.done.connect(self._on_drafted)
        self._agent_worker.failed.connect(self._on_failed)
        self._agent_worker.start()

    def _on_drafted(self, responses: dict, links: dict):
        m = self._current
        report, out_dir = m["report"], m["out_dir"]
        self._links.update({f"{k} · {report['stem']}": v
                            for k, v in links.items()})
        kept = []
        for rec in self._made_files:
            src = rec.get("path", "") if isinstance(rec, dict) else str(rec)
            if not src or not os.path.exists(src):
                continue
            dest = os.path.join(out_dir, self.sf.ai_sheet_name(
                report["stem"], len(kept) + 1, os.path.splitext(src)[1]))
            try:
                shutil.copyfile(src, dest)
                kept.append(dest)
                CB.config.save_artifact(dest, os.path.basename(dest),
                                        kind="step", task=report["file"])
            except Exception:                           # noqa: BLE001
                pass
        texts = [t for t in (responses.get("visual") or []) if t.strip()]
        self._responses[f"draft · {report['stem']}"] = texts
        if kept:
            self._notes.append(f"{report['file']}: AI drawing sheet → "
                               + "; ".join(kept))
            self.result.appendPlainText(
                f"{report['file']} — AI drawing sheet saved:\n  "
                + "\n  ".join(kept))
        elif texts:
            self._notes.append(f"{report['file']}: no image came back — "
                               "the agent's words are saved with the run")
            self.result.appendPlainText(f"{report['file']} — {texts[0]}")
        else:
            self._notes.append(f"{report['file']}: the agent returned "
                               "nothing; Prism's own measured sheet stands")
        self._next()

    # ── ask / edit ──────────────────────────────────────────────────────

    def _ask(self, m: dict):
        report = m["report"]
        self._set_busy(True, i18n.t(
            "Asking Groq about {file} — the measured numbers and your "
            "question only; the model stays here…")
            .replace("{file}", report["file"]))
        self._ask_worker = StepAskWorker(self.cfg, report,
                                         self.ask.text().strip())
        self._ask_worker.done.connect(self._on_suggested)
        self._ask_worker.failed.connect(self._on_failed)
        self._ask_worker.start()

    def _on_suggested(self, suggestions: str):
        m = self._current
        report = m["report"]
        self._responses[f"groq · {report['stem']}"] = [suggestions]
        self.result.appendPlainText(
            f"═══ {report['file']} — suggestions (from the measured "
            f"figures) ═══\n{suggestions}\n")
        planner = self._planner()
        if not planner:
            self._notes.append(f"{report['file']}: suggestions only — no "
                               "reasoning tool set up to plan changes")
            self._next()
            return
        files = []
        png = (m.get("drawn") or {}).get("png")
        if png and os.path.exists(png):
            try:
                files.append(CB.files.attach(png))
            except Exception:                           # noqa: BLE001
                pass
        self._set_busy(True, i18n.t(
            "{agent} is reviewing the suggestions into an exact change "
            "plan for {file}…")
            .replace("{agent}", planner).replace("{file}", report["file"]))
        self._agent_worker = AutomationWorker(
            {}, self.cfg, files,
            f"STEP — review and plan CAD changes for {report['file']}",
            custom_stages=[("plan", planner, [self.sf.plan_prompt(
                report, self.ask.text().strip(), suggestions)])],
            chatgpt_analysis=False)
        self._agent_worker.done.connect(self._on_planned)
        self._agent_worker.failed.connect(self._on_failed)
        self._agent_worker.start()

    def _on_planned(self, responses: dict, links: dict):
        m = self._current
        report, out_dir = m["report"], m["out_dir"]
        self._links.update({f"{k} · {report['stem']}": v
                            for k, v in links.items()})
        texts = [t for t in (responses.get("plan") or []) if t.strip()]
        self._responses[f"plan · {report['stem']}"] = texts
        plan, why = self.sf.parse_plan(texts)
        if plan is None:
            self._notes.append(f"{report['file']}: {why}")
            self.result.appendPlainText(f"{report['file']} — {why}")
            self._next()
            return
        m["plan"] = plan
        lines = []
        for ch in plan["changes"]:
            what = (f"Ø{ch['dia_mm']:g} → Ø{ch['new_dia_mm']:g} on {ch['part']}"
                    if ch["op"] == "enlarge_hole"
                    else f"scale {ch['part']} x {ch['factor']:g}")
            lines.append(f"  ▸ {what}" + (f" — {ch['why']}" if ch["why"] else ""))
        for a in plan["advice"]:
            lines.append(f"  • (for the designer) {a}")
        question = self.ask.text().strip()
        review = self.sf.review_html(report, plan, out_dir, question=question)
        QDesktopServices.openUrl(QUrl.fromLocalFile(review))
        self.result.appendPlainText(
            f"{report['file']} — the plan (review page → {review}):\n"
            + ("\n".join(lines) if lines else "  nothing Prism can apply by "
                                             "itself — the advice is the "
                                             "deliverable") + "\n")
        if self._action() != "edit" or not plan["changes"]:
            self._notes.append(f"{report['file']}: plan reviewed → {review}")
            self._next()
            return
        # Edit: the person confirms against the page they can SEE, and only
        # then is a copy built. The original file is never written.
        out = self.sf.names(report)
        answer = QMessageBox.question(
            self, "STEP",
            i18n.t("Reviewed the page for {file}? Build {name} now? The "
                   "original file is never touched.")
            .replace("{file}", report["file"]).replace("{name}", out["modified"]),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer != QMessageBox.Yes:
            self._notes.append(f"{report['file']}: not built — the review "
                               "page stays as the record of the plan")
            self._next()
            return
        self._set_busy(True, i18n.t(
            "Building {name} and re-measuring it — here, on a copy…")
            .replace("{name}", out["modified"]))
        self._apply_worker = StepApplyWorker(
            m["path"], plan, report, self._mode(), out_dir, question)
        self._apply_worker.done.connect(self._on_applied)
        self._apply_worker.failed.connect(self._on_failed)
        self._apply_worker.start()

    def _on_applied(self, result: dict):
        m = self._current
        report = m["report"]
        m["modified"] = result["out"]
        self.result.appendPlainText(
            f"{report['file']} — built {os.path.basename(result['out'])}:\n  "
            + "\n  ".join(result["log"]) + "\n\n"
            + self.sf.report_text(result["after"]) + "\n")
        self._notes.append(f"{report['file']}: modified model → "
                           f"{result['out']}")
        try:
            CB.config.save_artifact(result["out"],
                                    os.path.basename(result["out"]),
                                    kind="step", task=report["file"])
        except Exception:                               # noqa: BLE001
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(result["review"]))
        self._next()

    # ── finishing ───────────────────────────────────────────────────────

    def _finish(self):
        action = self._action()
        label = {"draft": "Draft", "ask": "Ask", "edit": "Edit"}[action]
        self._set_busy(False, i18n.t("Done. ") + (
            " ".join(self._notes) if self._notes
            else i18n.t("Measured from the geometry itself — not by an AI.")))
        self.open_btn.setEnabled(bool(self._links))
        names = ", ".join(m["report"]["file"] for m in self.models)
        question = self.ask.text().strip()
        try:
            CB.config.save_run({
                "query": f"STEP — {label}: {question or names}",
                "responses": self._responses, "links": self._links,
                "step": {
                    "action": action, "mode": self._mode(),
                    "question": question,
                    "models": [{"file": m["report"]["file"],
                                "out_dir": m["out_dir"],
                                "modified": m.get("modified", "")}
                               for m in self.models],
                },
            })
        except Exception:                               # noqa: BLE001
            pass

    def _on_failed(self, error: str):
        self._set_busy(False, "")
        QMessageBox.warning(self, "STEP", error)
        # A failure on one model must not strand the rest of the queue.
        if self._queue:
            self._next()

    def _set_busy(self, busy: bool, message: str):
        self.progress.setVisible(busy)
        self.generate_btn.setEnabled(not busy and bool(self.paths))
        self.status.setText(message)

    def _open_folder(self):
        for m in self.models[:1]:
            QDesktopServices.openUrl(QUrl.fromLocalFile(m["out_dir"]))

    def _open_link(self):
        import webbrowser
        for url in self._links.values():
            if url:
                webbrowser.open(url)
                break

    def closeEvent(self, event):
        """Same reasoning as Gerber: a QThread destroyed mid-run aborts the
        whole process, so ask each worker to stop and wait for it."""
        for worker in (self._worker, self._agent_worker, self._ask_worker,
                       self._apply_worker):
            if worker is None or not worker.isRunning():
                continue
            if hasattr(worker, "stop"):
                worker.stop()
            if not worker.wait(8000):
                worker.terminate()
                worker.wait(1000)
        super().closeEvent(event)
