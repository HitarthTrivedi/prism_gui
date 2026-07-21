"""Email — GUI equivalent of the CLI's /email setup and /email <goal>.
Recipients come from an attached CSV and/or addresses typed in the goal
text; if none are found, offers to search for the recipient's public
contact email via the research/brains agent (same regex-based extraction
the CLI uses). Drafting reuses automation.run() through a normal
AutomationWorker so it's a real pipeline stage, not a special code path."""
from __future__ import annotations
import re
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QLabel,
    QPushButton, QTextEdit, QListWidget, QListWidgetItem, QMessageBox,
    QDialogButtonBox, QGroupBox,
)

import core_bridge as CB
from workers import AutomationWorker

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


class EmailSetupDialog(QDialog):
    """One-time sending-account setup (mirrors CLI's /email setup)."""

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Email account setup")
        self.cfg = dict(cfg)
        root = QVBoxLayout(self)
        root.addWidget(QLabel(
            "Prism sends through YOUR account via SMTP — nothing is stored "
            "anywhere but ~/.prism/config.json.\n\nGmail: this needs an APP "
            "PASSWORD, not your real one — create one at "
            "myaccount.google.com/apppasswords"))
        form = QFormLayout()
        existing = cfg.get("email") or {}
        self.addr_edit = QLineEdit(existing.get("address", ""))
        form.addRow("Your email address:", self.addr_edit)
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.Password)
        self.pass_edit.setPlaceholderText("app password")
        form.addRow("Password:", self.pass_edit)
        self.host_edit = QLineEdit(existing.get("host", ""))
        self.host_edit.setPlaceholderText("auto-detected for Gmail/Outlook/Yahoo")
        form.addRow("SMTP host:", self.host_edit)
        self.port_edit = QLineEdit(str(existing.get("port", "") or ""))
        self.port_edit.setPlaceholderText("465 = SSL, 587 = STARTTLS")
        form.addRow("SMTP port:", self.port_edit)
        root.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _save(self):
        address = self.addr_edit.text().strip()
        if not address or "@" not in address:
            QMessageBox.warning(self, "Email setup", "That doesn't look like an email address.")
            return
        password = self.pass_edit.text()
        if not password:
            QMessageBox.warning(self, "Email setup", "Enter your app password.")
            return
        known = CB.mailer.smtp_for(address)
        host = self.host_edit.text().strip() or (known[0] if known else "")
        port_txt = self.port_edit.text().strip() or (str(known[1]) if known else "587")
        if not host:
            QMessageBox.warning(self, "Email setup", "Enter an SMTP host — couldn't auto-detect one.")
            return
        try:
            port = int(port_txt)
        except ValueError:
            QMessageBox.warning(self, "Email setup", "Port must be a number.")
            return
        self.cfg["email"] = {"address": address, "password": password, "host": host, "port": port}
        CB.config.save(self.cfg)
        self.accept()


class EmailComposeDialog(QDialog):
    def __init__(self, cfg: dict, attachments: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Compose Email")
        self.resize(640, 640)
        self.cfg = cfg
        self.attachments = attachments
        self.recipients: list[dict] = []
        self.source_files: list = []
        self._worker = None

        root = QVBoxLayout(self)

        goal_box = QGroupBox("✉️  What is this email about?")
        goal_layout = QVBoxLayout(goal_box)
        self.goal_edit = QTextEdit()
        self.goal_edit.setPlaceholderText(
            "e.g. \"pitch our new brochure to investors — jane@fund.com, "
            "mark@fund.com\" (mention addresses here, or attach a recipients CSV)")
        self.goal_edit.setFixedHeight(70)
        goal_layout.addWidget(self.goal_edit)
        root.addWidget(goal_box)

        rec_box = QGroupBox("📇  Recipients")
        rec_layout = QVBoxLayout(rec_box)
        self.rec_empty = QLabel("No recipients yet — Find recipients or search below.")
        self.rec_empty.setObjectName("emptyState")
        self.rec_empty.setWordWrap(True)
        rec_layout.addWidget(self.rec_empty)
        self.rec_list = QListWidget()
        self.rec_list.setMaximumHeight(90)
        self.rec_list.setVisible(False)
        rec_layout.addWidget(self.rec_list)
        rec_btns = QHBoxLayout()
        find_btn = QPushButton("Find recipients (from text + attached CSV)")
        find_btn.clicked.connect(self._find_recipients)
        rec_btns.addWidget(find_btn)
        discover_btn = QPushButton("No address? Search for their public email")
        discover_btn.clicked.connect(self._discover_recipient)
        rec_btns.addWidget(discover_btn)
        rec_layout.addLayout(rec_btns)
        root.addWidget(rec_box)

        draft_box = QGroupBox("📝  Draft")
        draft_layout = QVBoxLayout(draft_box)
        draft_btn = QPushButton("Generate draft from attached source files")
        draft_btn.clicked.connect(self._generate_draft)
        draft_layout.addWidget(draft_btn)
        form = QFormLayout()
        self.subject_edit = QLineEdit()
        form.addRow("Subject:", self.subject_edit)
        draft_layout.addLayout(form)
        self.body_edit = QTextEdit()
        self.body_edit.setPlaceholderText("Draft body appears here — edit freely before sending.")
        draft_layout.addWidget(self.body_edit)
        root.addWidget(draft_box, stretch=1)

        self.status = QLabel("")
        self.status.setObjectName("dim")
        root.addWidget(self.status)

        send_row = QHBoxLayout()
        send_row.addStretch(1)
        self.send_btn = QPushButton("Send")
        self.send_btn.setObjectName("primaryBtn")
        self.send_btn.clicked.connect(self._send)
        send_row.addWidget(self.send_btn)
        root.addLayout(send_row)

    # ── recipients ────────────────────────────────────────────────────────
    def _find_recipients(self):
        text = self.goal_edit.toPlainText()
        csvs, self.source_files = CB.mailer.split_attachments(self.attachments)
        inline, remainder = CB.mailer.recipients_from_text(text)
        self.goal_edit.setPlainText(remainder)
        found = list(inline)
        for a in csvs:
            found += CB.mailer.parse_recipients(a["path"])
        seen = set()
        self.recipients = [r for r in found if not (r["email"] in seen or seen.add(r["email"]))]
        self._refresh_recipients()
        if not self.recipients:
            self.status.setText("No recipients found — try 'Search for their public email' below.")

    def _refresh_recipients(self):
        self.rec_list.clear()
        for r in self.recipients:
            self.rec_list.addItem(QListWidgetItem(r["email"]))
        has_recipients = bool(self.recipients)
        self.rec_empty.setVisible(not has_recipients)
        self.rec_list.setVisible(has_recipients)
        self.status.setText(f"{len(self.recipients)} recipient(s).")

    def _discover_recipient(self):
        goal = self.goal_edit.toPlainText().strip()
        if not goal:
            QMessageBox.information(self, "Search", "Describe who the recipient is first.")
            return
        agents = CB.config.active_agents(self.cfg)
        finder = next((s for s in ("research", "brains") if agents.get(s)), None)
        if not finder:
            QMessageBox.warning(self, "Search", "No research/brains agent configured.")
            return
        routing = {finder: {"needed": True, "questions": [
            "Your ONLY task is: find the official, public contact email address for "
            f"the recipient described here: {goal}. Search the web. Reply with the "
            "1-3 best addresses, one per line, each followed by a dash and what it "
            "is for (e.g. partnerships, support, general). Prefer official domains "
            "over aggregator sites. If none can be found, reply exactly NONE."
        ]}}
        self.status.setText(f"Searching with {agents[finder]}…")
        self._worker = AutomationWorker(routing, self.cfg, [], goal)
        self._worker.done.connect(self._on_discovery_done)
        self._worker.failed.connect(lambda e: self.status.setText(f"Search failed: {e}"))
        self._worker.start()

    def _on_discovery_done(self, responses: dict, links: dict):
        text = "\n".join(t for ts in responses.values() for t in ts)
        found = list(dict.fromkeys(_EMAIL_RE.findall(text)))
        found = [e for e in found if not e.lower().endswith("example.com")][:5]
        if not found:
            self.status.setText("No email address found — enter one manually instead.")
            return
        for e in found:
            if not any(r["email"] == e for r in self.recipients):
                self.recipients.append({"email": e, "name": ""})
        self._refresh_recipients()
        self.status.setText(f"Found {len(found)} candidate address(es) — remove any you don't want.")

    # ── draft ─────────────────────────────────────────────────────────────
    def _generate_draft(self):
        goal = self.goal_edit.toPlainText().strip()
        if not goal:
            QMessageBox.information(self, "Draft", "Say what the email is about first.")
            return
        agents = CB.config.active_agents(self.cfg)
        avail = [s for s in ("research", "brains", "content") if agents.get(s)]
        if not avail:
            QMessageBox.warning(self, "Draft", "No research/brains/content agent configured.")
            return
        draft_stage = avail[-1]
        self._draft_stage = draft_stage
        routing = {draft_stage: {"needed": True, "questions": [CB.mailer.draft_question(goal)]}}
        self.status.setText(f"Drafting with {agents[draft_stage]}…")
        self._worker = AutomationWorker(routing, self.cfg, self.source_files, f"write an email: {goal}")
        self._worker.done.connect(self._on_draft_done)
        self._worker.failed.connect(lambda e: self.status.setText(f"Draft failed: {e}"))
        self._worker.start()

    def _on_draft_done(self, responses: dict, links: dict):
        texts = responses.get(self._draft_stage) or []
        draft = CB.mailer.parse_draft(texts[0] if texts else "")
        if not draft:
            self.status.setText("Couldn't find a SUBJECT/BODY draft in the response — "
                                "check the run's link and paste it in manually.")
            return
        subject, body = draft
        self.subject_edit.setText(subject)
        self.body_edit.setPlainText(body)
        self.status.setText("Draft ready — review before sending.")

    # ── send ──────────────────────────────────────────────────────────────
    def _send(self):
        if not CB.mailer.is_configured(self.cfg):
            dlg = EmailSetupDialog(self.cfg, self)
            if dlg.exec() != QDialog.Accepted:
                return
            self.cfg = dlg.cfg
        if not self.recipients:
            QMessageBox.warning(self, "Send", "No recipients — find or add some first.")
            return
        subject = self.subject_edit.text().strip()
        body = self.body_edit.toPlainText().strip()
        if not subject or not body:
            QMessageBox.warning(self, "Send", "Generate (or write) a subject and body first.")
            return
        names = ", ".join(r["email"] for r in self.recipients[:5])
        more = f", …" if len(self.recipients) > 5 else ""
        confirm = QMessageBox.question(
            self, "Confirm send",
            f"Send to {len(self.recipients)} recipient(s)?\n{names}{more}",
        )
        if confirm != QMessageBox.Yes:
            return
        sent, failed = CB.mailer.send_bulk(
            self.cfg, self.recipients, subject, body, self.source_files)
        msg = f"Sent to {len(sent)}/{len(self.recipients)} recipient(s)."
        if failed:
            msg += "\nFailed: " + ", ".join(f"{email} ({err})" for email, err in failed)
        QMessageBox.information(self, "Email", msg)
        if sent:
            self.accept()
