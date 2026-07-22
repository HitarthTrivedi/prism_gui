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
import theme
from workers import AutomationWorker, SendWorker, VerifyWorker

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


class EmailSetupDialog(QDialog):
    """One-time sending-account setup (mirrors CLI's /email setup)."""

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Email account setup")
        self.cfg = dict(cfg)
        self._verify_worker = None
        root = QVBoxLayout(self)
        root.addWidget(QLabel(
            "Prism sends through YOUR account via SMTP — nothing is stored "
            "anywhere but ~/.prism/config.json.\n\nGmail: this needs an APP "
            "PASSWORD, not your real one — create one at "
            "myaccount.google.com/apppasswords"))
        form = QFormLayout()
        existing = cfg.get("email") or {}
        self._saved_password = existing.get("password", "")
        self.addr_edit = QLineEdit(existing.get("address", ""))
        self.addr_edit.textChanged.connect(self._autofill_server)
        form.addRow("Your email address:", self.addr_edit)
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.Password)
        # Re-opening setup to fix a typo'd port shouldn't cost you a trip to
        # Google's app-password page — blank means "keep the saved one".
        self.pass_edit.setPlaceholderText(
            "leave blank to keep the saved password" if self._saved_password
            else "16-character app password — spaces are fine, paste as shown")
        form.addRow("Password:", self.pass_edit)
        self.host_edit = QLineEdit(existing.get("host", ""))
        self.host_edit.setPlaceholderText("auto-detected for Gmail/Outlook/Yahoo")
        form.addRow("SMTP host:", self.host_edit)
        self.port_edit = QLineEdit(str(existing.get("port", "") or ""))
        self.port_edit.setPlaceholderText("465 = SSL, 587 = STARTTLS")
        form.addRow("SMTP port:", self.port_edit)
        root.addLayout(form)

        self.status = QLabel("")
        self.status.setObjectName("dim")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        # Better to find out the password is wrong here than half way through a
        # blast to fifty people.
        self.test_btn = buttons.addButton("Test connection",
                                          QDialogButtonBox.ActionRole)
        self.test_btn.clicked.connect(self._test)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _autofill_server(self, address: str):
        """Fill host/port the moment the domain is recognisable, so the two
        fields most people can't answer are usually already answered."""
        known = CB.mailer.smtp_for(address.strip())
        if not known:
            return
        if not self.host_edit.text().strip():
            self.host_edit.setText(known[0])
        if not self.port_edit.text().strip():
            self.port_edit.setText(str(known[1]))

    def _account(self) -> dict | None:
        """Validate the form into an email config block, or complain and
        return None."""
        address = self.addr_edit.text().strip()
        if not address or "@" not in address:
            QMessageBox.warning(self, "Email setup", "That doesn't look like an email address.")
            return None
        password = CB.mailer.clean_password(self.pass_edit.text()) or self._saved_password
        if not password:
            QMessageBox.warning(self, "Email setup", "Enter your app password.")
            return None
        known = CB.mailer.smtp_for(address)
        host = self.host_edit.text().strip() or (known[0] if known else "")
        port_txt = self.port_edit.text().strip() or (str(known[1]) if known else "587")
        if not host:
            QMessageBox.warning(self, "Email setup", "Enter an SMTP host — couldn't auto-detect one.")
            return None
        try:
            port = int(port_txt)
        except ValueError:
            QMessageBox.warning(self, "Email setup", "Port must be a number.")
            return None
        return {"address": address, "password": password, "host": host, "port": port}

    def _test(self):
        account = self._account()
        if not account:
            return
        self.test_btn.setEnabled(False)
        self.status.setText(f"Signing in to {account['host']}…")
        self._verify_worker = VerifyWorker({"email": account})
        self._verify_worker.done.connect(self._on_verified)
        self._verify_worker.start()

    def _on_verified(self, error: str):
        self.test_btn.setEnabled(True)
        if error:
            self.status.setText(f"✗  {error}")
        else:
            self.status.setText("✓  Signed in — this account can send.")

    def _save(self):
        account = self._account()
        if not account:
            return
        self.cfg["email"] = account
        CB.config.save(self.cfg)
        self.accept()


class EmailComposeDialog(QDialog):
    def __init__(self, cfg: dict, attachments: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Compose Email")
        self.resize(640, 700)
        self.cfg = cfg
        self.attachments = attachments
        self.recipients: list[dict] = []
        # Split the attachments up front, not on a button press: CSVs are the
        # recipient list, everything else rides along as a real attachment and
        # feeds the draft. Doing this lazily meant a user who never pressed
        # "Find recipients" silently sent an email with no files on it.
        self._csvs, self.source_files = CB.mailer.split_attachments(attachments)
        self._worker = None
        self._send_worker = None
        self._draft_stage = ""
        self._last_run: dict = {}   # routing/responses/links of the draft run
        self._sent_ok: list[str] = []
        self._sent_bad: list[tuple] = []
        self._subject = self._body = ""

        root = QVBoxLayout(self)

        goal_box = QGroupBox("What is this email about?")
        goal_layout = QVBoxLayout(goal_box)
        self.goal_edit = QTextEdit()
        self.goal_edit.setPlaceholderText(
            "e.g. \"pitch our new brochure to investors — jane@fund.com, "
            "mark@fund.com\" (mention addresses here, or attach a recipients CSV)")
        self.goal_edit.setFixedHeight(70)
        goal_layout.addWidget(self.goal_edit)
        root.addWidget(goal_box)

        rec_box = QGroupBox("Recipients")
        rec_layout = QVBoxLayout(rec_box)
        self.rec_empty = QLabel("No recipients yet — Find recipients or search below.")
        self.rec_empty.setObjectName("emptyState")
        self.rec_empty.setWordWrap(True)
        rec_layout.addWidget(self.rec_empty)
        self.rec_list = QListWidget()
        self.rec_list.setMaximumHeight(120)
        self.rec_list.setVisible(False)
        rec_layout.addWidget(self.rec_list)

        add_row = QHBoxLayout()
        self.add_edit = QLineEdit()
        self.add_edit.setPlaceholderText("type an address and press Enter to add it")
        self.add_edit.returnPressed.connect(self._add_recipient)
        add_row.addWidget(self.add_edit, stretch=1)
        self.remove_btn = QPushButton("Remove selected")
        self.remove_btn.clicked.connect(self._remove_recipient)
        add_row.addWidget(self.remove_btn)
        rec_layout.addLayout(add_row)

        rec_btns = QHBoxLayout()
        find_btn = QPushButton("Find recipients (from text + attached CSV)")
        find_btn.clicked.connect(self._find_recipients)
        rec_btns.addWidget(find_btn)
        discover_btn = QPushButton("No address? Search for their public email")
        discover_btn.clicked.connect(self._discover_recipient)
        rec_btns.addWidget(discover_btn)
        rec_layout.addLayout(rec_btns)
        root.addWidget(rec_box)

        draft_box = QGroupBox("Draft")
        draft_layout = QVBoxLayout(draft_box)
        files_note = QLabel(self._files_note())
        files_note.setObjectName("dim")
        files_note.setWordWrap(True)
        draft_layout.addWidget(files_note)
        draft_btn = QPushButton("Generate draft from attached source files")
        draft_btn.clicked.connect(self._generate_draft)
        draft_layout.addWidget(draft_btn)
        form = QFormLayout()
        self.subject_edit = QLineEdit()
        form.addRow("Subject:", self.subject_edit)
        draft_layout.addLayout(form)
        self.body_edit = QTextEdit()
        self.body_edit.setPlaceholderText(
            "Draft body appears here — edit freely before sending.\n"
            "Write {name} anywhere and each recipient gets their own name "
            "(or 'there' when the list has no name for them).")
        draft_layout.addWidget(self.body_edit)
        root.addWidget(draft_box, stretch=1)

        self.status = QLabel("")
        self.status.setObjectName("dim")
        self.status.setWordWrap(True)
        # Some statuses hand back the tool's tab (see _on_draft_done) — a link
        # you can't click is just an apology.
        self.status.setOpenExternalLinks(True)
        root.addWidget(self.status)

        send_row = QHBoxLayout()
        send_row.addStretch(1)
        self.send_btn = QPushButton("Send")
        self.send_btn.setObjectName("primaryBtn")
        self.send_btn.clicked.connect(self._send)
        send_row.addWidget(self.send_btn)
        root.addLayout(send_row)

    # ── recipients ────────────────────────────────────────────────────────
    def _files_note(self) -> str:
        names = ", ".join(f["name"] for f in self.source_files)
        csvs = ", ".join(a["name"] for a in self._csvs)
        parts = []
        parts.append(f"Attached to every email: {names}" if names
                     else "No files attached — the email goes out as text only.")
        if csvs:
            parts.append(f"{csvs} is read locally for addresses and never "
                         "attached or shown to any AI.")
        return "  ".join(parts)

    def _find_recipients(self):
        text = self.goal_edit.toPlainText()
        inline, remainder = CB.mailer.recipients_from_text(text)
        self.goal_edit.setPlainText(remainder)
        found = list(inline)
        for a in self._csvs:
            found += CB.mailer.parse_recipients(a["path"])
        self._merge_recipients(found)
        if not self.recipients:
            self.status.setText("No recipients found — type one in below, or "
                                "search for their public email.")

    def _merge_recipients(self, found: list[dict]):
        """Add to what's already listed, first entry per address wins — the
        CSV usually carries the name, so it must not be replaced by a bare
        address picked up from the goal text."""
        merged = list(self.recipients) + list(found)
        seen = set()
        self.recipients = [r for r in merged
                           if not (r["email"] in seen or seen.add(r["email"]))]
        self._refresh_recipients()

    def _add_recipient(self):
        typed = self.add_edit.text().strip()
        addresses = _EMAIL_RE.findall(typed)
        if not addresses:
            self.status.setText("That isn't an email address.")
            return
        self.add_edit.clear()
        self._merge_recipients([{"email": a.lower(), "name": ""} for a in addresses])

    def _remove_recipient(self):
        rows = sorted((i.row() for i in self.rec_list.selectedIndexes()), reverse=True)
        if not rows:
            self.status.setText("Select an address in the list first.")
            return
        for row in rows:
            if 0 <= row < len(self.recipients):
                del self.recipients[row]
        self._refresh_recipients()

    def _refresh_recipients(self):
        self.rec_list.clear()
        for r in self.recipients:
            name = (r.get("name") or "").strip()
            self.rec_list.addItem(QListWidgetItem(
                f"{name}  <{r['email']}>" if name else r["email"]))
        has_recipients = bool(self.recipients)
        self.rec_empty.setVisible(not has_recipients)
        self.rec_list.setVisible(has_recipients)
        named = sum(1 for r in self.recipients if (r.get("name") or "").strip())
        note = f"{len(self.recipients)} recipient(s)."
        if named:
            note += f" {named} with a name for {{name}}."
        self.status.setText(note)

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
        self._merge_recipients([{"email": e, "name": ""} for e in found])
        self.status.setText(f"Found {len(found)} candidate address(es) — remove "
                            "any you don't want with the button above.")

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
        routing = {draft_stage: {
            "needed": True,
            "reason": "write the email draft — and ONLY the draft",
            # Don't call the answer finished until the draft's own marker is on
            # the page: these tools pause mid-answer, and a pause used to be
            # read as "done" and scraped into the subject/body half-written.
            "expect": "SUBJECT:",
            "questions": [CB.mailer.draft_question(goal)]}}
        self._last_run = {"routing": routing, "agent": agents[draft_stage]}
        self.status.setText(f"Drafting with {agents[draft_stage]}…")
        self._worker = AutomationWorker(routing, self.cfg, self.source_files, f"write an email: {goal}")
        self._worker.done.connect(self._on_draft_done)
        self._worker.failed.connect(lambda e: self.status.setText(f"Draft failed: {e}"))
        self._worker.start()

    def _on_draft_done(self, responses: dict, links: dict):
        texts = responses.get(self._draft_stage) or []
        # Kept for the run record written after the send, so an /email from the
        # GUI lands in History with the same shape the CLI writes.
        self._last_run.update({"responses": responses, "links": links})
        # Belt and braces: automation already drops prompt echoes, but a tool
        # that restates the brief before answering must never become the email.
        usable = [t for t in texts if not CB.mailer.is_prompt_echo(t)]
        draft = CB.mailer.parse_draft(usable[0] if usable else "")
        if not draft:
            # The tool may simply have been slower than Prism's wait — its tab
            # is where the finished draft shows up, so hand it over.
            url = (links or {}).get(self._draft_stage, "")
            note = ("Couldn't read a SUBJECT/BODY draft back — the tool may "
                    "still be writing it. ")
            if url:
                note += (f'<a href="{url}" style="color:{theme.ACCENT_RAMP[700]}">'
                         "Open the draft in the tool</a> and paste it in here.")
            else:
                note += "Write the email manually instead."
            self.status.setText(note)
            return
        subject, body = draft
        self.subject_edit.setText(subject)
        self.body_edit.setPlainText(body)
        self.status.setText("Draft ready — review before sending.")

    # ── send ──────────────────────────────────────────────────────────────
    def _send(self):
        # Second press while a blast is running means stop, not send again.
        if self._send_worker and self._send_worker.isRunning():
            self._send_worker.stop()
            self.send_btn.setEnabled(False)
            self.send_btn.setText("Stopping…")
            return

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
        more = ", …" if len(self.recipients) > 5 else ""
        files = ", ".join(f["name"] for f in self.source_files) or "none"
        confirm = QMessageBox.question(
            self, "Confirm send",
            f"Send to {len(self.recipients)} recipient(s)?\n\n"
            f"To: {names}{more}\n"
            f"Subject: {subject}\n"
            f"Attachments: {files}\n"
            f"From: {self.cfg['email']['address']}\n\n"
            "Each address gets its own message — this can't be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No)   # nobody should send a blast by pressing Enter
        if confirm != QMessageBox.Yes:
            return

        self._sent_ok, self._sent_bad = [], []
        self._subject, self._body = subject, body
        self._set_sending(True)
        self.status.setText(f"Signing in to {self.cfg['email']['host']}…")
        self._send_worker = SendWorker(self.cfg, list(self.recipients),
                                       subject, body, self.source_files)
        self._send_worker.progress.connect(self._on_send_progress)
        self._send_worker.done.connect(self._on_send_done)
        self._send_worker.failed.connect(self._on_send_failed)
        self._send_worker.start()

    def _set_sending(self, sending: bool):
        """A blast is minutes long — everything that would change what is being
        sent is locked while it runs, and Send becomes the way to stop."""
        for w in (self.subject_edit, self.body_edit, self.goal_edit,
                  self.add_edit, self.remove_btn):
            w.setEnabled(not sending)
        self.send_btn.setEnabled(True)
        self.send_btn.setText("Stop sending" if sending else "Send")

    def _on_send_progress(self, i: int, total: int, email: str, ok: bool, error: str):
        (self._sent_ok if ok else self._sent_bad).append(
            email if ok else (email, error))
        tail = "" if ok else f" — {error[:60]}"
        self.status.setText(
            f"{i}/{total} · {'sent' if ok else 'FAILED'} {email}{tail}"
            + (f"  ({len(self._sent_bad)} failed so far)"
               if self._sent_bad and ok else ""))

    def _on_send_done(self, sent: list, failed: list):
        self._set_sending(False)
        stopped = bool(self._send_worker and self._send_worker.stopped)
        self._save_run(sent, failed)
        msg = f"Sent to {len(sent)}/{len(self.recipients)} recipient(s)."
        if stopped:
            msg += "\nStopped early — the rest were not attempted."
        if failed:
            shown = "\n".join(f"· {email} — {err[:120]}" for email, err in failed[:8])
            msg += f"\n\n{len(failed)} failed:\n{shown}"
            hint = CB.mailer.explain_error(failed[0][1],
                                           self.cfg["email"]["address"])
            if hint != failed[0][1]:
                msg += f"\n\n{hint}"
        self.status.setText(msg.split("\n")[0])
        QMessageBox.information(self, "Email", msg)
        if sent and not failed and not stopped:
            self.accept()

    def _on_send_failed(self, error: str):
        """Login/connection died — nothing went out at all."""
        self._set_sending(False)
        hint = CB.mailer.explain_error(error, self.cfg["email"]["address"])
        self.status.setText(f"Couldn't send: {hint}")
        again = QMessageBox.question(
            self, "Send failed",
            f"{hint}\n\nThe server said: {error}\n\nOpen account setup now?")
        if again == QMessageBox.Yes:
            dlg = EmailSetupDialog(self.cfg, self)
            if dlg.exec() == QDialog.Accepted:
                self.cfg = dlg.cfg

    def _save_run(self, sent: list, failed: list):
        """Same record the CLI's /email writes, so the blast shows up in
        History next to every other run instead of vanishing."""
        goal = self.goal_edit.toPlainText().strip()
        record = {
            "query": f"/email {goal}",
            "routing": self._last_run.get("routing") or {},
            "responses": self._last_run.get("responses") or {},
            "links": self._last_run.get("links") or {},
            "attachments": [f["name"] for f in self.source_files],
            "email": {"subject": self._subject, "sent": sent, "failed": failed,
                      "recipients": len(self.recipients)},
        }
        if self._draft_stage and self._last_run.get("agent"):
            record["agents"] = {self._draft_stage: self._last_run["agent"]}
        try:
            CB.config.save_run(record)
        except Exception as e:
            self.status.setText(f"Sent, but couldn't save to History: {e}")

    def closeEvent(self, event):
        if self._send_worker and self._send_worker.isRunning():
            leave = QMessageBox.question(
                self, "Still sending",
                "Emails are still going out. Stop the blast and close?")
            if leave != QMessageBox.Yes:
                event.ignore()
                return
            self._send_worker.stop()
            self._send_worker.wait(15000)
        super().closeEvent(event)
