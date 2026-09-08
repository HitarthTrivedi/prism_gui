"""
Prism Sales Automation — the Leads & Outreach workbench
────────────────────────────────────────────────────────
The screen behind the rail's "Leads & Outreach". Bring a sheet of leads,
qualify each against what you sell, and get one ready-to-send email per hot/warm
lead — each grounded in that company's own why-now. It PREPARES; a person
presses Send, and only the value claims from the seller's own file are ever
made (prospector/reach.py). Sending goes out one-per-person from the owner's own
account, through the same engine mailer the Email add-on uses.

The heavy work runs off the UI thread: `ProspectorWorker` qualifies and drafts,
`LeadsSendWorker` sends. The window never blocks — see workers.py for why that
is not optional.
"""
from __future__ import annotations

import html as _html
import os
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFileDialog, QHBoxLayout, QHeaderView,
    QLineEdit, QMessageBox, QPlainTextEdit, QSpinBox, QSplitter, QTableWidget,
    QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget,
)

import core_bridge as CB
import i18n
import theme
from dialogs.base import PrismDialog
from dialogs.email_dialog import EmailSetupDialog
from widgets import controls as C
from workers import (LeadsExportWorker, LeadsSendWorker, ProspectorWorker,
                     SourceWorker)

try:
    from prospector.run_poc import DEFAULT_OFFER
except Exception:                                       # noqa: BLE001
    DEFAULT_OFFER = "what your company sells"

_COLS = ("Verdict", "Company", "Name", "Fit", "Outcome", "Signal")

# Pre-filled ICP so a first "Build from my ICP" run is one click. Editable.
_DEFAULT_INDUSTRIES = (
    "Automobile\nAuto Components\nTyre\nSteel Manufacturing\nDie Casting\n"
    "Aerospace & MRO\nDefense\nElectrical & Electronics\n"
    "Warehousing & Logistics\nMining")
_DEFAULT_ROLES = (
    "Head of Digital Transformation / Industry 4.0 / IIoT\n"
    "Automation Head / Smart Manufacturing\n"
    "Manufacturing Excellence / Operations / Production Head\n"
    "Business Excellence & Continuous Improvement\n"
    "Plant Head / Head of Manufacturing\n"
    "Supply Chain / Warehouse / Materials Head")


class LeadsDialog(PrismDialog):
    def __init__(self, cfg: dict, parent=None):
        super().__init__(
            i18n.t("Leads & Outreach"),
            i18n.t("Bring a sheet of leads. Prism qualifies each one and writes "
                   "an email grounded in that company's own why-now — you read "
                   "every word before it goes."),
            icon="user", parent=parent)
        self.cfg = cfg or {}
        self._mode = "sheet"
        self._path = ""
        self._claims_path = ""
        self._drafts = []
        self._draft_by = {}
        self._res = None
        self._worker = None
        self._send_worker = None
        self._export_worker = None
        self._announce_export = False
        self._opened_autosave = False

        self._build_inputs()
        self._build_results()
        self._build_footer()
        self.resize(1000, 700)

    # ── inputs ───────────────────────────────────────────────────────────────
    def _build_inputs(self):
        card = C.Card()
        col = card.body()
        col.setSpacing(theme.ROW_GAP)
        col.addWidget(C.label(i18n.t("Your leads"), level="CARD_TITLE"))

        # Two ways in: a sheet you already have, or a fresh list built from the
        # ICP (Exa people-search → real-domain e-mails → qualify → draft).
        mode_row = QHBoxLayout()
        mode_row.setSpacing(theme.SPACE_2)
        self._mode_sheet = C.button(i18n.t("Bring a sheet"), "secondary",
                                    on_click=lambda: self._set_mode("sheet"))
        self._mode_icp = C.button(i18n.t("Build from my ICP"), "secondary",
                                  on_click=lambda: self._set_mode("icp"))
        mode_row.addWidget(self._mode_sheet)
        mode_row.addWidget(self._mode_icp)
        mode_row.addStretch(1)
        col.addLayout(mode_row)

        # -- sheet mode --------------------------------------------------------
        self._sheet_box = QWidget()
        sb = QVBoxLayout(self._sheet_box)
        sb.setContentsMargins(0, 0, 0, 0)
        sb.setSpacing(theme.SPACE_2)
        file_row = QHBoxLayout()
        file_row.setSpacing(theme.SPACE_3)
        self._pick = C.button(i18n.t("Choose a sheet…"), "secondary",
                              icon_name="paperclip", on_click=self._choose_file)
        file_row.addWidget(self._pick)
        self._file_lbl = C.label(
            i18n.t("No file chosen — an Excel or CSV export of your leads"),
            level="SUPPORT")
        file_row.addWidget(self._file_lbl, stretch=1)
        sb.addLayout(file_row)
        col.addWidget(self._sheet_box)

        # -- ICP mode ----------------------------------------------------------
        self._icp_box = QWidget()
        ib = QVBoxLayout(self._icp_box)
        ib.setContentsMargins(0, 0, 0, 0)
        ib.setSpacing(theme.SPACE_2)
        ib.addWidget(C.label(i18n.t("Industries you sell to (one per line)"),
                             level="SUPPORT"))
        self._industries = QPlainTextEdit()
        self._industries.setPlainText(_DEFAULT_INDUSTRIES)
        self._industries.setFixedHeight(66)
        self._industries.textChanged.connect(self._refresh_prepare)
        ib.addWidget(self._industries)
        ib.addWidget(C.label(i18n.t("Decision-maker roles (one per line)"),
                             level="SUPPORT"))
        self._roles = QPlainTextEdit()
        self._roles.setPlainText(_DEFAULT_ROLES)
        self._roles.setFixedHeight(66)
        self._roles.textChanged.connect(self._refresh_prepare)
        ib.addWidget(self._roles)
        icp_row = QHBoxLayout()
        icp_row.setSpacing(theme.SPACE_3)
        icp_row.addWidget(C.label(i18n.t("Location"), level="SUPPORT"))
        self._location = QLineEdit("India")
        self._location.setMaximumWidth(160)
        icp_row.addWidget(self._location)
        icp_row.addStretch(1)
        icp_row.addWidget(C.label(i18n.t("Source up to"), level="SUPPORT"))
        self._target = QSpinBox()
        self._target.setRange(20, 2000)
        self._target.setValue(300)
        icp_row.addWidget(self._target)
        ib.addLayout(icp_row)
        col.addWidget(self._icp_box)

        # -- shared ------------------------------------------------------------
        col.addWidget(C.label(i18n.t("What you sell — every lead is qualified "
                                     "against this"), level="SUPPORT"))
        self._offer = QLineEdit()
        self._offer.setText(DEFAULT_OFFER)
        col.addWidget(self._offer)

        col.addWidget(C.label(i18n.t("Why-now signals — Exa API key "
                                     "(required to build a list; saved once)"),
                             level="SUPPORT"))
        self._exa = QLineEdit()
        self._exa.setText(self.cfg.get("exa_api_key") or "")
        self._exa.setPlaceholderText(i18n.t(
            "With a key, each email cites the company's real recent news."))
        col.addWidget(self._exa)

        col.addWidget(C.label(i18n.t(
            "Verify & find emails — set your keys once in Settings → Agents "
            "(Reoon, Verifalia, ZeroBounce, AbstractAPI, Kickbox, Tomba, "
            "Hunter). Prism uses them here automatically, free tiers first, so "
            "most checks cost nothing."), level="SUPPORT"))

        opt_row = QHBoxLayout()
        opt_row.setSpacing(theme.SPACE_3)
        self._claims = C.button(i18n.t("Approved claims file…"), "tertiary",
                                icon_name="file", on_click=self._choose_claims)
        opt_row.addWidget(self._claims)
        self._claims_lbl = C.label(
            i18n.t("Optional — with none, the emails make no numeric claim"),
            level="SUPPORT")
        opt_row.addWidget(self._claims_lbl, stretch=1)
        opt_row.addWidget(C.label(i18n.t("Qualify how many"), level="SUPPORT"))
        self._limit = QSpinBox()
        self._limit.setRange(1, 500)
        self._limit.setValue(25)
        opt_row.addWidget(self._limit)
        opt_row.addWidget(C.label(i18n.t("Verify (Hunter)"), level="SUPPORT"))
        self._verify_limit = QSpinBox()
        self._verify_limit.setRange(0, 200)
        self._verify_limit.setValue(25)
        self._verify_limit.setToolTip(i18n.t(
            "How many hot/warm addresses to check with Hunter. Its free tier is "
            "~50 credits a month, so keep this modest — 0 skips verification."))
        opt_row.addWidget(self._verify_limit)
        col.addLayout(opt_row)

        act_row = QHBoxLayout()
        act_row.setSpacing(theme.SPACE_3)
        self._prepare = C.button(i18n.t("Prepare outreach"), "primary",
                                 icon_name="play", on_click=self._on_prepare)
        act_row.addWidget(self._prepare)
        self._leads_only = C.button(
            i18n.t("Leads sheet only (no Groq)"), "secondary", icon_name="file",
            on_click=lambda: self._on_prepare(leads_only=True))
        self._leads_only.setToolTip(i18n.t(
            "Source and enrich a leads sheet only — no qualification, no emails, "
            "no Groq. Uses Exa alone, so a rate-limited Groq key can't block it."))
        act_row.addWidget(self._leads_only)
        self._status = C.label("", level="SUPPORT")
        act_row.addWidget(self._status, stretch=1)
        col.addLayout(act_row)
        self.body.addWidget(card)
        self._set_mode("sheet")

    def _set_mode(self, mode: str):
        self._mode = mode
        self._sheet_box.setVisible(mode == "sheet")
        self._icp_box.setVisible(mode == "icp")
        self._leads_only.setVisible(mode == "icp")   # ICP-only cheap deliverable
        self._refresh_prepare()

    def _refresh_prepare(self):
        if self._mode == "icp":
            ok = bool(self._split(self._industries.toPlainText())
                      and self._split(self._roles.toPlainText()))
        else:
            ok = bool(self._path)
        self._prepare.setEnabled(ok)
        self._leads_only.setEnabled(ok and self._mode == "icp")

    @staticmethod
    def _split(text: str) -> list:
        return [p.strip() for p in re.split(r"[\n,]", text or "") if p.strip()]

    # ── results: table on the left, the full email on the right ──────────────
    def _build_results(self):
        # The run summary: what happened to the whole batch, so nothing is a
        # silent black box (hot/warm/cold, dropped, rate-limited, signal coverage).
        self._summary = C.label("", level="SUPPORT")
        self.body.addWidget(self._summary)
        split = QSplitter(Qt.Horizontal)
        self._table = QTableWidget(0, len(_COLS))
        self._table.setHorizontalHeaderLabels([i18n.t(h) for h in _COLS])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setAlternatingRowColors(True)
        head = self._table.horizontalHeader()
        head.setSectionResizeMode(1, QHeaderView.Stretch)
        for c in (0, 2, 3, 4, 5):
            head.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self._table.currentCellChanged.connect(lambda *_: self._show_selected())
        split.addWidget(self._table)

        self._preview = QTextBrowser()
        self._preview.setOpenExternalLinks(True)
        split.addWidget(self._preview)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        split.setSizes([480, 500])
        self.body.addWidget(split, stretch=1)
        self._show_placeholder()

    def _build_footer(self):
        self.footer.add_utility(self.button(
            i18n.t("Export sheets"), "tertiary", icon_name="file",
            on_click=self._export))
        self.footer.add_secondary(self.button(i18n.t("Close"),
                                              on_click=self.reject))
        self._send_btn = self.button(i18n.t("Send all"), "primary",
                                     icon_name="mail", on_click=self._on_send)
        self._send_btn.setEnabled(False)
        self.footer.set_primary(self._send_btn)

    # ── file pickers ─────────────────────────────────────────────────────────
    def _choose_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.t("Choose a leads sheet"), "",
            "Leads (*.xlsx *.xlsm *.csv)")
        if not path:
            return
        self._path = path
        self._file_lbl.setText(os.path.basename(path))
        self._refresh_prepare()

    def _choose_claims(self):
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.t("Approved value claims — one per line"), "",
            "Text (*.txt *.md);;All files (*.*)")
        if not path:
            return
        self._claims_path = path
        self._claims_lbl.setText(os.path.basename(path))

    # ── prepare ──────────────────────────────────────────────────────────────
    def _on_prepare(self, leads_only: bool = False):
        from prospector import reach
        # Persist the Exa key the way the email account and Groq key are — once,
        # to config — so the pipeline picks it up here and on every run after.
        exa = self._exa.text().strip()
        changed = exa != (self.cfg.get("exa_api_key") or "")
        self.cfg["exa_api_key"] = exa
        if changed:
            try:
                CB.config.save(self.cfg)
            except Exception:                               # noqa: BLE001
                pass
        claims = reach.load_claims(self._claims_path)
        offer = self._offer.text().strip() or DEFAULT_OFFER
        if self._mode == "icp":
            industries = self._split(self._industries.toPlainText())
            roles = self._split(self._roles.toPlainText())
            if not (industries and roles):
                return
            self._set_running(True)
            self._status.setText(i18n.t("Sourcing your list (no Groq)…")
                                 if leads_only else i18n.t("Sourcing your list…"))
            self._worker = SourceWorker(
                industries, roles, offer, self.cfg,
                location=self._location.text().strip() or "India",
                target=self._target.value(), limit=self._limit.value(),
                verify_limit=self._verify_limit.value(),
                sender=self._sender(), claims=claims,
                exclude_domains=self._seller_domains(), leads_only=leads_only)
        else:
            if not self._path:
                return
            self._set_running(True)
            self._status.setText(i18n.t("Reading the sheet…"))
            self._worker = ProspectorWorker(
                self._path, offer, self.cfg, limit=self._limit.value(),
                verify_limit=self._verify_limit.value(),
                sender=self._sender(), claims=claims,
                exclude_domains=self._seller_domains())
        self._worker.progress.connect(self._status.setText)
        self._worker.done.connect(self._on_prepared)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _seller_domains(self) -> list:
        """The seller's own site(s), pulled from the offer text and the claims
        file, so the why-now search never cites the seller's own pages."""
        text = self._offer.text()
        if self._claims_path:
            try:
                with open(self._claims_path, encoding="utf-8") as f:
                    text += " " + f.read()
            except Exception:                               # noqa: BLE001
                pass
        return sorted(set(re.findall(
            r"\b([a-z0-9][a-z0-9-]*\.(?:com|in|io|ai|co|net|org))\b",
            text.lower())))

    def _on_prepared(self, res, drafts):
        self._res = res
        self._drafts = drafts
        self._draft_by = {id(d.dossier): d for d in drafts}
        self._set_running(False)
        self._fill_table()
        leads_only = not res.dossiers and bool(getattr(res, "all_leads", None))
        if leads_only:
            self._summary.setText(i18n.t(
                "Sourced {n} leads · enriched · saving the sheet "
                "(no qualification, no Groq used).").format(n=res.total_in_sheet))
        else:
            self._summary.setText(self._run_summary(res, drafts))
            self._status.setText(i18n.t(
                "{n} ready to send — every lead below shows its outcome."
            ).format(n=len(drafts)))
        self._send_btn.setEnabled(bool(drafts))
        # The sheets ARE the deliverable — write them automatically to a known
        # folder the moment a run finishes (leads-only included, which needed no
        # Groq at all), so a run always produces a file instead of hiding it
        # behind a button the user must find.
        if res.dossiers:
            self._table.selectRow(0)
            self._start_export(self._autosave_dir(), announce=False)
        elif leads_only:
            self._start_export(self._autosave_dir(), announce=False)
            self._show_placeholder()
        else:
            self._show_placeholder()

    def _on_failed(self, msg):
        self._set_running(False)
        self._status.setText("")
        QMessageBox.warning(self, i18n.t("Leads & Outreach"),
                            i18n.t("Something went wrong:\n\n{msg}").format(msg=msg))

    # ── the table + preview ──────────────────────────────────────────────────
    def _fill_table(self):
        self._table.setRowCount(0)
        for dos in (self._res.dossiers if self._res else []):
            lead = dos.lead
            row = self._table.rowCount()
            self._table.insertRow(row)
            outcome, ohue = self._outcome(dos, self._draft_by.get(id(dos)))
            cells = (dos.verdict.upper(), lead.company, lead.name,
                     f"{lead.fit_score:g}", outcome, i18n.t(dos.signal_status))
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c == 0:
                    item.setToolTip(i18n.t("score {n} · {r}").format(
                        n=dos.score, r=lead.fit_reason))
                    hue = {"hot": theme.WARN, "warm": theme.NEUTRAL[600],
                           "cold": theme.NEUTRAL[500]}.get(dos.verdict)
                    if hue:
                        item.setForeground(QColor(hue))
                if c == 4 and ohue:
                    item.setForeground(QColor(ohue))
                self._table.setItem(row, c, item)

    def _outcome(self, dos, draft):
        """One line saying what actually happened to this lead — so no lead ever
        silently vanishes. Returns (text, colour)."""
        lead = dos.lead
        if draft is not None:
            return {"sent": (i18n.t("sent"), theme.OK),
                    "failed": (i18n.t("send failed"), theme.WARN)}.get(
                        draft.status, (i18n.t("drafted"), theme.OK))
        if dos.status != "ok":
            return {
                "qualify_error": i18n.t("rate-limited"),
                "non_json": i18n.t("bad output"),
                "no_model": i18n.t("no Groq key"),
            }.get(dos.status, dos.status), theme.WARN
        if dos.verdict == "cold":
            return i18n.t("cold"), theme.NEUTRAL[500]
        if not (lead.email or "").strip():
            return i18n.t("no email"), theme.WARN
        ec = (lead.extra or {}).get("email_check")
        if ec == "invalid":
            return i18n.t("invalid"), theme.WARN
        if ec in ("catch-all", "unknown"):
            return i18n.t(ec), theme.WARN
        drops = lead.drops or []
        if "role_account" in drops:
            return i18n.t("role account"), theme.WARN
        if "email_unsendable" in drops:
            return i18n.t("held (unverified)"), theme.WARN
        return i18n.t("not reached"), theme.NEUTRAL[500]

    def _run_summary(self, res, drafts) -> str:
        dos = res.dossiers
        c = lambda p: sum(1 for d in dos if p(d))
        bits = [i18n.t("Sourced {n}").format(n=res.total_in_sheet),
                i18n.t("qualified {n}").format(n=len(dos)),
                i18n.t("{h} hot / {w} warm / {c} cold").format(
                    h=c(lambda d: d.verdict == "hot"),
                    w=c(lambda d: d.verdict == "warm"),
                    c=c(lambda d: d.verdict == "cold")),
                i18n.t("{n} drafted").format(n=len(drafts))]
        no_email = c(lambda d: d.status == "ok" and not (d.lead.email or "").strip())
        if no_email:
            bits.append(i18n.t("{n} no-email").format(n=no_email))
        errs = c(lambda d: d.status != "ok")
        if errs:
            bits.append(i18n.t("{n} qualify-errors").format(n=errs))
        cov = i18n.t("why-now {a}/{b}").format(
            a=c(lambda d: d.signal_status == "found"), b=len(dos))
        sig_err = c(lambda d: d.signal_status == "source_error")
        if sig_err:
            cov += i18n.t(" ({n} source-errors)").format(n=sig_err)
        bits.append(cov)
        return "   ·   ".join(bits)

    def _show_placeholder(self):
        self._preview.setHtml(
            f"<div style='color:{theme.NEUTRAL[500]}; padding:24px'>"
            + _html.escape(i18n.t(
                "Choose a sheet and press Prepare outreach. Then pick a lead "
                "here to read the email Prism wrote for them."))
            + "</div>")

    def _show_selected(self):
        row = self._table.currentRow()
        dossiers = self._res.dossiers if self._res else []
        if row < 0 or row >= len(dossiers):
            return
        dos = dossiers[row]
        draft = self._draft_by.get(id(dos))
        self._render_draft(draft) if draft else self._render_dossier(dos)

    def _render_draft(self, d):
        dos = d.dossier
        parts = [f"<h3 style='margin:0 0 2px'>{_html.escape(d.subject)}</h3>",
                 f"<div style='color:{theme.NEUTRAL[500]};font-size:12px'>"
                 f"{_html.escape(dos.lead.display())} &nbsp;·&nbsp; "
                 f"{_html.escape(dos.verdict.upper())} {dos.score}</div>"]
        if dos.signals:
            s = dos.signals[0]
            parts.append(
                f"<div style='color:{theme.NEUTRAL[500]};font-size:12px;margin-top:6px'>"
                f"{_html.escape(i18n.t('why-now'))}: "
                f"{_html.escape(s.title)} {_html.escape(s.cite())}</div>")
        if d.note:
            parts.append(
                f"<div style='color:{theme.WARN};font-size:12px;margin-top:6px'>"
                f"{_html.escape(d.note)}</div>")
        parts.append("<hr>")
        parts.append("<div style='white-space:pre-wrap'>"
                     + _html.escape(d.body) + "</div>")
        self._preview.setHtml("".join(parts))

    def _render_dossier(self, dos):
        """A lead we did NOT draft — show WHY (the reason + the case file), so the
        drop is legible instead of a silent disappearance."""
        lead = dos.lead
        outcome, _ = self._outcome(dos, None)
        parts = [
            f"<h3 style='margin:0 0 2px'>{_html.escape(lead.display())}</h3>",
            f"<div style='color:{theme.NEUTRAL[500]};font-size:12px'>"
            f"{_html.escape(dos.verdict.upper())} {dos.score} &nbsp;·&nbsp; "
            f"fit {lead.fit_score:g} ({_html.escape(lead.fit_reason)}) &nbsp;·&nbsp; "
            f"{_html.escape(lead.email or i18n.t('no email'))}</div>",
            f"<div style='color:{theme.WARN};font-size:12px;margin-top:6px'>"
            f"{_html.escape(i18n.t('Not reached'))}: {_html.escape(outcome)}"
            + (f" — {_html.escape(dos.note)}" if dos.note else "") + "</div>",
            "<hr>"]
        for dim in dos.dimensions:
            src = (f" <span style='color:{theme.NEUTRAL[500]}'>[{_html.escape(dim.source)}]</span>"
                   if dim.source else "")
            parts.append(
                f"<div style='margin:2px 0'><b>{_html.escape(dim.name)}</b> "
                f"{_html.escape(dim.mark())} {_html.escape(dim.evidence)}{src}</div>")
        self._preview.setHtml("".join(parts))

    # ── send ─────────────────────────────────────────────────────────────────
    def _on_send(self):
        if not self._drafts:
            return
        if not CB.mailer.is_configured(self.cfg):
            dlg = EmailSetupDialog(self.cfg, self)
            if dlg.exec() != QDialog.Accepted:
                return
            self.cfg = dlg.cfg
        addr = (self.cfg.get("email") or {}).get("address", "")
        confirm = QMessageBox.question(
            self, i18n.t("Send outreach"),
            i18n.t("Send {n} personalised email(s) — one to each lead — from "
                   "{addr}?\n\nEach person gets their own message, from your "
                   "own account.").format(n=len(self._drafts), addr=addr))
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._set_running(True, sending=True)
        self._status.setText(i18n.t("Sending…"))
        self._send_worker = LeadsSendWorker(self._drafts, self.cfg)
        self._send_worker.progress.connect(self._on_send_progress)
        self._send_worker.done.connect(self._on_sent)
        self._send_worker.failed.connect(self._on_failed)
        self._send_worker.start()

    def _on_send_progress(self, i, total, _draft):
        self._status.setText(i18n.t("Sent {i} of {total}…").format(
            i=i, total=total))
        self._fill_table()

    def _on_sent(self, sent, failed):
        self._set_running(False)
        self._fill_table()
        self._status.setText(i18n.t("Sent {s}, failed {f}.").format(
            s=len(sent), f=len(failed)))
        QMessageBox.information(
            self, i18n.t("Leads & Outreach"),
            i18n.t("Sent {s} email(s). {f} failed.").format(
                s=len(sent), f=len(failed)))

    # ── shared ───────────────────────────────────────────────────────────────
    def _autosave_dir(self) -> str:
        """Where a run's sheets land without asking — a predictable folder the
        user can always find, created on first use."""
        d = os.path.join(os.path.expanduser("~"), "Documents", "Prism Leads")
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:                                   # noqa: BLE001
            d = os.path.expanduser("~")
        return d

    def _export(self):
        """The manual 'Export sheets' button — choose where, and confirm loudly."""
        if not self._res or not self._res.dossiers:
            QMessageBox.information(self, i18n.t("Leads & Outreach"),
                                    i18n.t("Prepare a list first."))
            return
        folder = QFileDialog.getExistingDirectory(
            self, i18n.t("Choose a folder for the sheets"))
        if not folder:
            return
        self._start_export(folder, announce=True)

    def _start_export(self, folder: str, announce: bool):
        """Write the two xlsx (live MX check per row → worker thread) plus the
        drafts CSV. `announce=False` is the automatic save after a run — quiet,
        opens the folder once; `announce=True` is the button — confirms loudly."""
        if not self._res or not (self._res.dossiers
                                 or getattr(self._res, "all_leads", None)):
            return
        self._announce_export = announce
        # The drafts CSV is quick — write it inline; the xlsx go to the worker.
        from prospector import reach
        try:
            reach.write_outreach(self._drafts, os.path.join(folder, "outreach.csv"))
        except Exception:                                   # noqa: BLE001
            pass
        self._set_running(True)
        self._status.setText(i18n.t("Verifying e-mails and writing the sheets…"))
        self._export_worker = LeadsExportWorker(
            self._res.all_leads, self._res.dossiers, folder)
        self._export_worker.progress.connect(self._status.setText)
        self._export_worker.done.connect(self._on_exported)
        self._export_worker.failed.connect(self._on_failed)
        self._export_worker.start()

    def _on_exported(self, paths):
        self._set_running(False)
        folder = os.path.dirname(paths[0]) if paths else ""
        self._status.setText(
            i18n.t("Leads sheet + hot list saved to {f}").format(f=folder)
            if folder else i18n.t("Sheets written."))
        if folder and (self._announce_export or not self._opened_autosave):
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
            self._opened_autosave = True
        if self._announce_export:
            QMessageBox.information(
                self, i18n.t("Leads & Outreach"),
                i18n.t("Wrote the leads sheet and the hot list (xlsx), plus "
                       "outreach.csv, to that folder."))

    def _sender(self) -> str:
        try:
            import identity
            return identity.describe() or ""
        except Exception:                                   # noqa: BLE001
            return ""

    def _set_running(self, running: bool, sending: bool = False):
        for w in (self._pick, self._offer, self._claims, self._limit,
                  self._verify_limit, self._prepare, self._leads_only,
                  self._send_btn, self._mode_sheet, self._mode_icp,
                  self._industries, self._roles, self._location, self._target,
                  self._exa):
            w.setEnabled(not running)
        if not running:
            self._refresh_prepare()
            self._send_btn.setEnabled(bool(self._drafts))
