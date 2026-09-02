"""Gerber add-on — measure a PCB job, no AI sees the design.

Same shape as BOQ: one prompt, one drop target, the measuring happens the
instant a file lands and before anything is typed. Where this has to be
STRICTER than BOQ is the one place BOQ attaches the customer's drawing to
the writing stage (`files.insert(0, CB.files.attach(self.cad_path))` in
boq_dialog.py) — that is fine for a building drawing, and it is never fine
for a Gerber set, because the Gerber files ARE the customer's product. This
dialog never attaches them to anything; the write-up stage receives
`core.gerber.agent_brief()` — five numbers and nothing else — and passes
`attachments=[]` explicitly, the same guarantee the terminal's /gerber makes
and the same function that builds its text, so the two cannot say the
confidentiality sentence two different ways.
"""
from __future__ import annotations
import os
import time

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QFrame, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QPushButton,
    QPlainTextEdit, QMessageBox, QProgressBar,
)

import core_bridge as CB
import i18n
import theme
from dialogs.base import PrismDialog
from workers import AutomationWorker, GerberCleanWorker, GerberWorker
from widgets import icons
from widgets.ask_panel import AskPanel

# Every other add-on's numbers land in the hidden ~/.prism/runs folder, which
# is exactly where a factory owner never thinks to look for the CSV they
# need to email a customer in the next five minutes. The measured Gerber
# figures go somewhere they will actually be found again: a named folder
# right on the Desktop.
REPORTS_DIR = os.path.join(os.path.expanduser("~/Desktop"), "Prism Gerber")


class GerberDialog(PrismDialog):
    def __init__(self, cfg: dict, attachments: list, parent=None):
        super().__init__(
            i18n.t("Gerber"),
            i18n.t("PCB size, track width, spacing, drill size and count — "
                   "measured off the files themselves."),
            icon="grid", parent=parent, closable=False, scrollable=True)
        self.setWindowTitle("Gerber — PCB fabrication data")
        self.resize(820, 780)
        # Lower than before now that the body scrolls (scrollable=True) — a
        # fixed, non-scrolling height is what let the measured-results box
        # (260px) plus the write-up box (100px) plus everything above them
        # outgrow the window and get compressed into illegibility instead of
        # just scrolling, once a job was actually measured.
        self.setMinimumSize(620, 480)
        self.cfg = cfg
        self.gerber = CB.get_gerber()

        self.paths: list[str] = []
        self.jobs: list = []          # [(name, job_dict), ...] once measured
        self._worker = None
        self._agent_worker = None
        self._clean_worker = None
        self._links: dict = {}

        # The base class owns the header and footer; `root` is its body column.
        root = self.body
        # A stacked form, not a grid of cards: the 16px card gutter
        # between every row of a single column is what turns a short
        # form into a tall one with bands of canvas through it.
        root.setSpacing(theme.ROW_GAP)

        title = QLabel("What is this job, and what do you want done with it?")
        title.setObjectName("h4")
        root.addWidget(title)

        self.ask = AskPanel(
            "Drop the customer's zip or rar exactly as it arrived — a "
            "folder works too. Set the client's format below if you want "
            "it, then press Generate.\n\n"
            "Optionally say what to do with the numbers, e.g. \"reply with "
            "our price for 500 pieces\" — leave it blank to just get the "
            "five figures.")
        self.ask.files_added.connect(self._on_files_added)
        root.addWidget(self.ask)

        # The confidentiality promise is the reason this add-on is sellable, so
        # it is stated as a real notice rather than as an emoji in front of a
        # dashed placeholder box. The padlock is the system's own line icon: an
        # emoji arrives pre-coloured and pre-weighted from whatever font the
        # platform picked, which is the one thing every other glyph in Prism
        # avoids.
        lock = QFrame()
        lock.setObjectName("gerberLock")
        lock.setAttribute(Qt.WA_StyledBackground, True)
        lock.setStyleSheet(
            f"#gerberLock {{ background: {theme.OK_BG};"
            f" border: 1px solid {theme.OK};"
            f" border-radius: {theme.R_CONTROL}px; }}")
        lock_row = QHBoxLayout(lock)
        lock_row.setContentsMargins(theme.SPACE_3, theme.SPACE_3,
                                    theme.SPACE_3, theme.SPACE_3)
        lock_row.setSpacing(theme.SPACE_3)
        lock_glyph = QLabel()
        lock_glyph.setPixmap(icons.pixmap("lock", 17, theme.OK_INK))
        lock_glyph.setAlignment(Qt.AlignTop)
        lock_row.addWidget(lock_glyph)
        lock_text = QLabel(
            "The Gerber files never leave this machine. If you ask for a "
            "write-up below, only the measured NUMBERS are shown to an "
            "agent — never a file, never a path.")
        lock_text.setWordWrap(True)
        lock_text.setStyleSheet(f"color: {theme.OK_INK}; font-size: 13px;")
        lock_row.addWidget(lock_text, stretch=1)
        root.addWidget(lock)

        # The client's own format. FCC's F-SAL-01 quotation form was the
        # request that built this: "put the parameters inside OUR template".
        # Choose it once — the path is remembered — and every measured job
        # also lands as a filled copy of that form: labels Prism recognises
        # get the measured value in the cell beside them, the form's own
        # formulas and everything else stay exactly as the client drew it.
        form_box = QGroupBox(i18n.t("Client's format (optional)"))
        form_l = QHBoxLayout(form_box)
        self.form_label = QLabel(self._form_caption())
        self.form_label.setWordWrap(True)
        form_l.addWidget(self.form_label, stretch=1)
        form_l.addWidget(self.button(i18n.t("Choose template…"), "secondary",
                                     small=True, on_click=self._pick_form))
        self.form_clear_btn = self.button(i18n.t("Forget it"), "secondary",
                                          small=True, on_click=self._clear_form)
        self.form_clear_btn.setVisible(
            bool(self.cfg.get("gerber_form_template")))
        form_l.addWidget(self.form_clear_btn)
        root.addWidget(form_box)

        # Only appears once a job has actually been measured.
        self.meas_box = QGroupBox("Measured — not by an AI")
        meas_l = QVBoxLayout(self.meas_box)
        self.meas_view = QPlainTextEdit()
        self.meas_view.setReadOnly(True)
        self.meas_view.setMinimumHeight(260)
        meas_l.addWidget(self.meas_view)
        # A result, not the absence of one — see the same change in BOQ.
        self.csv_label = QLabel("")
        self.csv_label.setWordWrap(True)
        self.csv_label.setStyleSheet(
            f"color: {theme.OK_INK}; background: {theme.OK_BG};"
            f" border-radius: {theme.R_CONTROL}px;"
            f" padding: {theme.SPACE_2}px {theme.SPACE_3}px;"
            f" font-size: 13px;")
        meas_l.addWidget(self.csv_label)
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
            "If you asked for a write-up, the agent's reply appears here.")
        self.result.setMinimumHeight(100)
        root.addWidget(self.result)

        self.clean_btn = self.button(i18n.t("Clean outside the border"),
                                     "secondary", icon_name="file", small=True)
        self.clean_btn.setToolTip(i18n.t(
            "Remove everything that lies outside the board outline and save "
            "the cleaned layers on the Desktop, with a report of what went"))
        self.clean_btn.setEnabled(False)
        self.clean_btn.clicked.connect(self._clean)
        self.footer.add_utility(self.clean_btn)

        self.open_btn = self.button(i18n.t("Open in browser"), "secondary",
                                    icon_name="external", small=True,
                                    on_click=self._open_link)
        self.open_btn.setEnabled(False)
        self.footer.add_utility(self.open_btn)
        # The AI write-up is the sideline, not the headline: a small utility
        # button beside Clean/Open, enabled only once figures exist. The
        # PRIMARY action is Generate — measuring waits for it, so the user
        # can set the client's format (or think) after dropping the job.
        self.run_btn = self.button(i18n.t("Answer with AI"), "secondary",
                                   icon_name="pencil", small=True,
                                   on_click=self._write_up)
        self.run_btn.setEnabled(False)
        self.run_btn.setToolTip(i18n.t(
            "After generating: an agent writes the reply or quotation from "
            "the measured numbers — the files still never leave"))
        self.footer.add_utility(self.run_btn)
        self.footer.add_secondary(
            self.button(i18n.t("Close"), on_click=self.reject))
        self.generate_btn = self.button(i18n.t("Generate"), "primary",
                                        icon_name="grid",
                                        on_click=self._measure)
        self.generate_btn.setEnabled(False)
        self.generate_btn.setToolTip(i18n.t("Attach a job first"))
        self.footer.set_primary(self.generate_btn)

        if attachments:
            self._on_files_added([a["path"] for a in attachments])

    # ── the client's own form ───────────────────────────────────────────

    def _form_caption(self) -> str:
        path = self.cfg.get("gerber_form_template") or ""
        if path and os.path.exists(path):
            return i18n.t("Filled copies of “{name}” are saved beside the "
                          "CSVs for every measured job.").replace(
                              "{name}", os.path.basename(path))
        return i18n.t("If the client wants the figures in their own Excel "
                      "form — a quotation format, a checklist — choose it "
                      "here. Prism fills the cells it recognises and leaves "
                      "everything else exactly as they drew it.")

    def _pick_form(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.t("Client's Excel format"), "",
            "Excel (*.xlsx *.xlsm)")
        if not path:
            return
        self.cfg["gerber_form_template"] = path
        CB.config.save(self.cfg)
        self.form_label.setText(self._form_caption())
        self.form_clear_btn.setVisible(True)
        if self.jobs:
            self._fill_forms()   # a job is already measured — fill it now

    def _clear_form(self):
        self.cfg.pop("gerber_form_template", None)
        CB.config.save(self.cfg)
        self.form_label.setText(self._form_caption())
        self.form_clear_btn.setVisible(False)

    def _fill_forms(self):
        """One filled copy of the client's form per measured job. A fill
        that fails says so and never blocks the measurement it decorates."""
        template = self.cfg.get("gerber_form_template") or ""
        if not template or not os.path.exists(template) or not self.jobs:
            return
        form = CB.get_gerber_form()
        os.makedirs(REPORTS_DIR, exist_ok=True)
        made = []
        for name, job in self.jobs:
            stem = "".join(c if c.isalnum() or c in "-_ " else "_"
                           for c in name).strip()[:40] or "job"
            out = os.path.join(
                REPORTS_DIR,
                f"{stem} — "
                f"{os.path.splitext(os.path.basename(template))[0]}"
                " (filled).xlsx")
            try:
                result = form.fill_form(job, template, out,
                                        meta={"part": name})
            except Exception as e:                      # noqa: BLE001
                self.status.setText(
                    i18n.t("Couldn't fill the client's form: ") + str(e))
                continue
            made.append((out, len(result["filled"])))
            try:
                CB.config.save_artifact(out, os.path.basename(out),
                                        kind="gerber", task=name)
            except Exception:                           # noqa: BLE001
                pass
        if made:
            self.meas_view.appendPlainText(
                "\n\nCLIENT'S FORMAT\n" + "\n".join(
                    f"  {n} cell(s) filled → {p}" for p, n in made))

    # ── files ───────────────────────────────────────────────────────────

    def _on_files_added(self, paths: list):
        new = [p for p in paths if p not in self.paths]
        if not new:
            return
        self.paths += new
        self.clean_btn.setEnabled(True)
        known = self.ask.paths()
        self.ask.add_paths([p for p in new if p not in known])
        # Deliberately NOT measuring yet. Measuring on drop left no moment
        # to choose the client's format first — the CSV was already made.
        # Generate is the go button.
        self.generate_btn.setEnabled(True)
        self.generate_btn.setToolTip("")
        self.status.setText(i18n.t(
            "Job attached. Choose the client's format above if you want "
            "the figures in their form, then press Generate."))

    # ── measuring ───────────────────────────────────────────────────────

    def _measure(self):
        if not self.paths:
            return
        self.meas_view.clear()
        self._set_busy(True, "Measuring — the design never leaves this "
                             "machine, and a dense multilayer board can "
                             "take a few minutes…")
        self._worker = GerberWorker(list(self.paths))
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_measured)
        self._worker.failed.connect(self._on_measure_failed)
        self._worker.start()

    def _on_progress(self, line: str):
        self.meas_view.appendPlainText(f"   {line}")

    def _on_measured(self, results: list):
        self.jobs = results
        G = self.gerber
        blocks = []
        csv_paths = []
        # (path, task) — each job's own CSV is grouped under that job's name;
        # the summary below covers every job at once, so it has none to
        # belong to and stays ungrouped rather than picking one arbitrarily.
        to_save = []
        os.makedirs(REPORTS_DIR, exist_ok=True)
        for name, job in results:
            label = name if len(results) > 1 else ""
            heading = f"═══ {name} ═══\n" if len(results) > 1 else ""
            blocks.append(
                heading
                + "FILES\n" + G.files_text(job) + "\n\n"
                + "THE FIVE NUMBERS\n" + G.answers_text(job) + "\n\n"
                + "WORKINGS\n" + G.summary_text(job) + "\n\n"
                + "CHECKED AGAINST\n" + G.crosscheck_text(G.crosscheck(job))
                + ("\n\nWARNINGS\n  ! " + "\n  ! ".join(job["warnings"])
                   if job["warnings"] else ""))
            stem = "".join(c if c.isalnum() or c in "-_" else "_"
                          for c in label)[:40]
            csv_name = f"gerber_{stem}_{int(time.time())}.csv" if stem \
                else f"gerber_{int(time.time())}.csv"
            csv_path = os.path.join(REPORTS_DIR, csv_name)
            G.write_report_csv(job, csv_path)
            csv_paths.append(csv_path)
            to_save.append((csv_path, name))
        self.meas_view.setPlainText("\n\n".join(blocks))

        note = ""
        if len(results) > 1:
            summary_path = os.path.join(
                REPORTS_DIR, f"gerber_summary_{int(time.time())}.csv")
            G.write_summary_csv(results, summary_path)
            csv_paths.append(summary_path)
            to_save.append((summary_path, ""))
            note = f"{len(results)} jobs measured separately. "
        # These CSVs are the real, checkable numbers this whole panel exists
        # to produce — worth a copy in Artifacts, not only in the Desktop
        # reports folder this dialog already writes them to.
        for p, task in to_save:
            try:
                CB.config.save_artifact(p, os.path.basename(p), kind="gerber",
                                        task=task)
            except Exception:                           # noqa: BLE001
                pass
        self.csv_label.setText(
            note + "Saved so every number can be checked → "
            + "; ".join(csv_paths))
        self.meas_box.setVisible(True)
        self.run_btn.setEnabled(True)
        self.run_btn.setToolTip("")
        self._fill_forms()
        self._set_busy(False, "Measured from the Gerber geometry itself — "
                              "not by an AI.")

    def _on_measure_failed(self, error: str):
        self._set_busy(False, "")
        QMessageBox.warning(self, "Gerber", error)

    # ── writing it up ─────────────────────────────────────────────────────

    def _write_up(self):
        if not self.jobs:
            return
        if len(self.jobs) > 1:
            QMessageBox.information(
                self, "Gerber",
                "Several jobs were measured in one go. Write-ups are one "
                "job at a time — attach just the one you want written up "
                "and measure it on its own.")
            return

        agents = CB.config.active_agents(self.cfg)
        writer = next((s for s in ("content", "brains") if agents.get(s)),
                     None)
        if not writer:
            QMessageBox.warning(
                self, "Gerber",
                "No writing agent set up yet — open Agents first.")
            return

        _, job = self.jobs[0]
        context = self.ask.text().strip()
        # agent_brief() is the ONE place this text is built — the terminal's
        # /gerber calls the same function, so the confidentiality sentence
        # cannot be worded two different ways in the two surfaces that hand
        # an agent a job's numbers.
        brief = self.gerber.agent_brief(job, context)

        self._set_busy(True, f"{agents[writer]} is writing this up — only "
                             "the numbers above were shown to it…")
        # attachments=[] is not a default being left alone — it is the
        # guarantee. Nothing that reached this call could ever be a path
        # into the customer's Gerber files, because nothing was ever handed
        # one: `brief` is text, built above from `job["answers"]` only.
        self._agent_worker = AutomationWorker(
            {}, self.cfg, [], f"Gerber job — {context or 'write-up'}",
            custom_stages=[("write", agents[writer], [brief])],
            chatgpt_analysis=False)
        self._agent_worker.done.connect(self._on_written)
        self._agent_worker.failed.connect(self._on_write_failed)
        self._agent_worker.start()

    def _on_written(self, responses: dict, links: dict):
        self._set_busy(False, "")
        self._links.update(links)
        texts = [t for t in (responses.get("write") or []) if t.strip()]
        if not texts:
            self.status.setText("Nothing came back. The measured numbers "
                                "above are still saved.")
        else:
            self.result.setPlainText(texts[0])
            self.status.setText("Done. The agent saw only the numbers above.")
        self.open_btn.setEnabled(bool(self._links.get("write")))
        name, job = self.jobs[0]
        CB.config.save_run({
            "query": f"Gerber — {self.ask.text().strip() or name}",
            "responses": responses, "links": self._links,
            "gerber": {"job": name, "answers": job["answers"]},
        })

    def _on_write_failed(self, error: str):
        self._set_busy(False, "")
        QMessageBox.warning(self, "Gerber", error)

    # ── cleaning outside the border ─────────────────────────────────────

    def _clean(self):
        """Write a copy of the job with everything outside the board
        outline removed, next to the reports on the Desktop, so the CAM
        operator can put it beside their own cleaned files and compare."""
        if not self.paths:
            return
        stem = os.path.splitext(os.path.basename(self.paths[0]))[0]
        stem = "".join(c if c.isalnum() or c in "-_ " else "_"
                       for c in stem).strip()[:40] or "job"
        self._clean_stem = stem
        out_dir = os.path.join(REPORTS_DIR,
                               f"{stem} cleaned {time.strftime('%Y-%m-%d %H%M')}")
        self._set_busy(True, "Cleaning outside the border — nothing leaves "
                             "this machine…")
        self.clean_btn.setEnabled(False)
        self._clean_worker = GerberCleanWorker(list(self.paths), out_dir)
        self._clean_worker.progress.connect(self._on_progress)
        self._clean_worker.done.connect(self._on_cleaned)
        self._clean_worker.failed.connect(self._on_clean_failed)
        self._clean_worker.start()

    def _on_cleaned(self, report: dict):
        text = CB.get_gerber_clean().report_text(report)
        self.meas_view.appendPlainText("\n\n" + text)
        self.meas_box.setVisible(True)
        removed = sum(l["removed"] for l in report["layers"])
        crossing = sum(l["crossing"] for l in report["layers"])
        self._set_busy(False,
                       f"Cleaned: {removed} object(s) removed outside the "
                       f"border, {crossing} crossing it kept for you to "
                       f"decide. Saved to {report['out_dir']}")
        self.clean_btn.setEnabled(True)
        # The cleaned layers, the report and its comparison page are the
        # actual deliverable this button exists to produce — a whole folder,
        # not one file, so it goes to Artifacts by copying the tree rather
        # than through save_artifact()'s single-file copy.
        try:
            import shutil
            task_dir = CB.config.artifact_task_dir(
                getattr(self, "_clean_stem", "") or "Gerber cleaned")
            shutil.copytree(report["out_dir"],
                            os.path.join(task_dir, os.path.basename(
                                report["out_dir"])),
                            dirs_exist_ok=True)
        except Exception:                               # noqa: BLE001
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(
            report.get("compare_html") or report["out_dir"]))

    def _on_clean_failed(self, error: str):
        self._set_busy(False, "")
        self.clean_btn.setEnabled(bool(self.paths))
        QMessageBox.warning(self, "Gerber", error)

    def _set_busy(self, busy: bool, message: str):
        self.progress.setVisible(busy)
        self.generate_btn.setEnabled(not busy and bool(self.paths))
        self.run_btn.setEnabled(not busy and bool(self.jobs))
        self.status.setText(message)

    def closeEvent(self, event):
        """Same reasoning as BoqDialog: a QThread destroyed mid-run aborts
        the whole process, so ask each worker to stop and wait for it rather
        than let Qt tear it down underneath."""
        for worker in (getattr(self, "_worker", None),
                       getattr(self, "_agent_worker", None),
                       getattr(self, "_clean_worker", None)):
            if worker is None or not worker.isRunning():
                continue
            if hasattr(worker, "stop"):
                worker.stop()
            if not worker.wait(8000):
                worker.terminate()
                worker.wait(1000)
        super().closeEvent(event)

    def _open_link(self):
        import webbrowser
        url = self._links.get("write")
        if url:
            webbrowser.open(url)
