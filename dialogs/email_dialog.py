"""Email — sending from your own account, to one person or to a list.

GUI equivalent of the CLI's /email setup and /email <goal>, rebuilt so the
form reads like a letter: To, Subject, Message, top to bottom, all visible
from the moment the window opens. The old window opened on a free-text box
("What email do you want to send?") and folded the address list away under
"Edit the recipient list (optional)" — an owner who wanted to write to one
supplier could not find where the address went.

Recipients come from the To line (typed, any separator), from a CSV
(name, email), or from an attached CSV handed over by the workbench. The
CSV is parsed on this machine and never shown to any AI. Drafting stays
optional: a one-line brief and "Write it for me" runs the same pipeline
stage as before through an ordinary AutomationWorker.
"""
from __future__ import annotations
import os
import re
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFileDialog, QFormLayout, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QSizePolicy,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

import core_bridge as CB
import i18n
import sent_log
import theme
from dialogs.base import PrismDialog
from widgets import controls as C
from workers import AutomationWorker, SendWorker, VerifyWorker

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


class EmailSetupDialog(PrismDialog):
    """One-time sending-account setup (mirrors CLI's /email setup)."""

    def __init__(self, cfg: dict, parent=None):
        super().__init__(
            i18n.t("Email account"),
            i18n.t("Send from your own account, one copy per recipient."),
            icon="mail", parent=parent, closable=False)
        self.setWindowTitle("Email account setup")
        self.setMinimumWidth(560)
        self.cfg = dict(cfg)
        self._verify_worker = None
        root = self.body
        # Kept verbatim. Rewording it would orphan the Hindi and Gujarati
        # translations of this exact sentence — the packs key off the English
        # string — so the chrome around it moved and the words did not.
        note = QLabel(
            "Prism sends through YOUR account via SMTP — nothing is stored "
            "anywhere but ~/.prism/config.json.\n\nGmail: this needs an APP "
            "PASSWORD, not your real one — create one at "
            "myaccount.google.com/apppasswords")
        note.setWordWrap(True)
        note.setStyleSheet(
            f"color: {theme.INFO_INK}; background: {theme.INFO_BG};"
            f" border-radius: {theme.R_CONTROL}px;"
            f" padding: {theme.SPACE_2}px {theme.SPACE_3}px; font-size: 13px;")
        root.addWidget(note)
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
        self.pass_edit.textChanged.connect(self._update_password_status)
        form.addRow("Password:", self.pass_edit)
        self.host_edit = QLineEdit(existing.get("host", ""))
        self.host_edit.setPlaceholderText("auto-detected for Gmail/Outlook/Yahoo")
        form.addRow("SMTP host:", self.host_edit)
        self.port_edit = QLineEdit(str(existing.get("port", "") or ""))
        self.port_edit.setPlaceholderText("465 = SSL, 587 = STARTTLS")
        form.addRow("SMTP port:", self.port_edit)
        root.addLayout(form)

        # The placeholder alone reads as "empty" to anyone who has not
        # stopped to read the grey text — the same misreading that, on the
        # Inquiry Automation side, turned "the password is always shown
        # blank" into a belief that Prism deletes it. See
        # InquirySetupDialog._update_password_status() for the original.
        self.password_status = QLabel("")
        self.password_status.setWordWrap(True)
        root.addWidget(self.password_status)
        self._update_password_status()

        self.status = QLabel("")
        self.status.setObjectName("dim")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        root.addStretch(1)
        # Better to find out the password is wrong here than half way through a
        # blast to fifty people — so Test is a real, findable utility rather
        # than an ActionRole button Qt lays out wherever the platform prefers.
        self.test_btn = self.button(i18n.t("Test connection"), "secondary",
                                    icon_name="check", small=True,
                                    on_click=self._test)
        self.footer.add_utility(self.test_btn)
        self.footer.add_secondary(
            self.button(i18n.t("Cancel"), on_click=self.reject))
        self.footer.set_primary(
            self.button(i18n.t("Save"), "primary", on_click=self._save))
        self.tab_chain(self.addr_edit, self.pass_edit, self.host_edit,
                       self.port_edit)

    def _update_password_status(self):
        """Say, in words nobody can miss, whether the password box being
        blank means "nothing saved" or "already saved, and staying that
        way." Silent once something new has actually been typed — at that
        point the box speaks for itself."""
        if self.pass_edit.text():
            self.password_status.setText("")
            self.password_status.setVisible(False)
            return
        if self._saved_password:
            self.password_status.setText(i18n.t(
                "✓ A password is already saved for this account. Leave this "
                "box blank and it stays exactly as it is — nothing is "
                "removed by opening or saving this screen. Type a new one "
                "here only if you want to replace it."))
            self.password_status.setStyleSheet(
                f"color: {theme.OK_INK}; font-size: 12.5px;")
        else:
            self.password_status.setText(i18n.t(
                "No password saved yet for this account."))
            self.password_status.setStyleSheet(
                f"color: {theme.NEUTRAL[600]}; font-size: 12.5px;")
        self.password_status.setVisible(True)

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

    def closeEvent(self, event):
        """Wind up the sign-in test before this dialog is destroyed.

        "Check this works" starts a VerifyWorker in a blocking SMTP sign-in;
        closing the dialog while it runs would destroy a live QThread and Qt
        qFatal()s on that. VerifyWorker has no stop(), so bounded-wait then
        terminate the overrun.
        """
        w = self._verify_worker
        if w is not None:
            try:
                if w.isRunning():
                    if not w.wait(3000):
                        w.terminate()
                        w.wait(1000)
            except RuntimeError:
                pass
        super().closeEvent(event)


class EmailComposeDialog(PrismDialog):
    """To, Subject, Message — then Send. Everything else is optional and
    says so.

    `mode` is "one" (the default) or "list": the same window either way; a
    list opens straight into the CSV picker so the second click the owner
    made on the launcher is honoured.
    """

    def __init__(self, cfg: dict, attachments: list, parent=None,
                 mode: str = "one"):
        address = (cfg.get("email") or {}).get("address", "")
        super().__init__(
            i18n.t("Send an email"),
            i18n.t("From {address}. Fill in To, Subject and Message, then "
                   "press Send. Nothing goes out until you press it."
                   ).format(address=address or i18n.t("your account")),
            icon="mail", parent=parent, closable=False)
        self.setWindowTitle(i18n.t("Send an email"))
        self.resize(820, 760)
        self.setMinimumSize(640, 620)
        self.cfg = cfg
        self.mode = mode
        self._list: list[dict] = []          # recipients from a CSV
        self._list_name = ""
        self.source_files: list[dict] = []   # attached to every email
        self._worker = None
        self._send_worker = None
        self._draft_stage = ""
        self._last_run: dict = {}
        self._sent_ok: list[str] = []
        self._sent_bad: list[tuple] = []
        self._subject = self._body = ""

        self.header.add_action(C.button(
            i18n.t("Change account"), "secondary", icon_name="key",
            small=True, on_click=self._change_account))

        root = self.body
        root.setSpacing(theme.ROW_GAP)

        # ── the letter: To / Subject / Message ────────────────────────────
        form = QGridLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(theme.SPACE_3)
        form.setVerticalSpacing(theme.SPACE_2)
        form.setColumnMinimumWidth(0, 78)
        form.setColumnStretch(1, 1)

        to_row = QHBoxLayout()
        to_row.setContentsMargins(0, 0, 0, 0)
        to_row.setSpacing(theme.SPACE_2)
        self.to_edit = QLineEdit()
        self.to_edit.setPlaceholderText(i18n.t(
            "rajesh@acme.in — for more than one, separate with commas"))
        self.to_edit.textChanged.connect(self._sync)
        to_row.addWidget(self.to_edit, stretch=1)
        self.list_btn = C.button(i18n.t("Add a list (CSV)"), "secondary",
                                 icon_name="list", small=True,
                                 on_click=self._add_list)
        to_row.addWidget(self.list_btn)
        form.addWidget(self._field_label(i18n.t("To")), 0, 0)
        form.addLayout(to_row, 0, 1)

        # Who this is going to, in words, right under the To line — and the
        # list itself when there is one, so nobody has to open a panel to
        # see who "42 people" are.
        who_row = QHBoxLayout()
        who_row.setContentsMargins(0, 0, 0, 0)
        who_row.setSpacing(theme.SPACE_3)
        self.who_label = C.label("", level="SUPPORT", wrap=True)
        who_row.addWidget(self.who_label, stretch=1)
        self.search_btn = C.button(i18n.t("Don't know the address? Search the web"),
                                   "tertiary", icon_name="search", small=True,
                                   on_click=self._discover_recipient)
        who_row.addWidget(self.search_btn, alignment=Qt.AlignTop)
        form.addLayout(who_row, 1, 1)

        self.list_box = QWidget()
        list_col = QVBoxLayout(self.list_box)
        list_col.setContentsMargins(0, 0, 0, 0)
        list_col.setSpacing(theme.SPACE_2)
        self.list_table = QTableWidget(0, 2)
        self.list_table.setHorizontalHeaderLabels([i18n.t("Name"), i18n.t("Email")])
        self.list_table.verticalHeader().setVisible(False)
        self.list_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.list_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.list_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list_table.setAlternatingRowColors(True)
        head = self.list_table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        head.setSectionResizeMode(1, QHeaderView.Stretch)
        # Four rows visible, always; more scroll. A table that shows only
        # its header is a table nobody can read.
        row_h = self.list_table.verticalHeader().defaultSectionSize()
        head_h = head.sizeHint().height()
        self.list_table.setMinimumHeight(head_h + 4 * row_h + 4)
        self.list_table.setMaximumHeight(head_h + 6 * row_h + 4)
        list_col.addWidget(self.list_table)
        list_btns = QHBoxLayout()
        list_btns.setContentsMargins(0, 0, 0, 0)
        list_btns.setSpacing(theme.SPACE_2)
        self.remove_btn = C.button(i18n.t("Remove selected"), "secondary",
                                   small=True, on_click=self._remove_selected)
        list_btns.addWidget(self.remove_btn)
        self.clear_list_btn = C.button(i18n.t("Clear the list"), "tertiary",
                                       small=True, on_click=self._clear_list)
        list_btns.addWidget(self.clear_list_btn)
        list_btns.addStretch(1)
        list_col.addLayout(list_btns)
        self.list_box.setVisible(False)
        form.addWidget(self.list_box, 2, 1)

        self.subject_edit = QLineEdit()
        self.subject_edit.setPlaceholderText(i18n.t("What the email is about"))
        self.subject_edit.textChanged.connect(self._sync)
        form.addWidget(self._field_label(i18n.t("Subject")), 3, 0)
        form.addWidget(self.subject_edit, 3, 1)

        self.body_edit = C.PlainPasteTextEdit()
        self.body_edit.setAcceptRichText(False)
        self.body_edit.setPlaceholderText(i18n.t(
            "Type the message here, or ask Prism to write it below.\n"
            "Write {name} anywhere and each person gets their own name."))
        self.body_edit.setMinimumHeight(160)
        self.body_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.body_edit.textChanged.connect(self._sync)
        form.addWidget(self._field_label(i18n.t("Message")), 4, 0,
                       alignment=Qt.AlignTop)
        form.addWidget(self.body_edit, 4, 1)
        form.setRowStretch(4, 1)

        files_row = QHBoxLayout()
        files_row.setContentsMargins(0, 0, 0, 0)
        files_row.setSpacing(theme.SPACE_2)
        self.attach_btn = C.button(i18n.t("Attach a file"), "secondary",
                                   icon_name="paperclip", small=True,
                                   on_click=self._attach)
        files_row.addWidget(self.attach_btn)
        self.files_label = C.label(i18n.t("No files attached."), level="SUPPORT",
                                   wrap=True)
        files_row.addWidget(self.files_label, stretch=1)
        self.clear_files_btn = C.button(i18n.t("Remove files"), "tertiary",
                                        small=True, on_click=self._clear_files)
        self.clear_files_btn.setVisible(False)
        files_row.addWidget(self.clear_files_btn)
        form.addWidget(self._field_label(i18n.t("Files")), 5, 0)
        form.addLayout(files_row, 5, 1)
        root.addLayout(form, stretch=1)

        # ── optional: let Prism write it ──────────────────────────────────
        card = C.Card()
        card_col = card.body(margins=(theme.SPACE_4, theme.SPACE_3,
                                      theme.SPACE_4, theme.SPACE_3),
                             spacing=theme.SPACE_2)
        card_col.addWidget(C.label(
            i18n.t("Want Prism to write the message for you? (optional)"),
            level="CARD_TITLE"))
        brief_row = QHBoxLayout()
        brief_row.setContentsMargins(0, 0, 0, 0)
        brief_row.setSpacing(theme.SPACE_2)
        self.brief_edit = QLineEdit()
        self.brief_edit.setPlaceholderText(i18n.t(
            "Say what it should say — e.g. introduce our spring range and "
            "ask for a meeting next week"))
        self.brief_edit.returnPressed.connect(self._write_for_me)
        brief_row.addWidget(self.brief_edit, stretch=1)
        self.write_btn = C.button(i18n.t("Write it for me"), "secondary",
                                  icon_name="pencil", small=True,
                                  on_click=self._write_for_me)
        brief_row.addWidget(self.write_btn)
        card_col.addLayout(brief_row)
        card_col.addWidget(C.label(i18n.t(
            "Attached files are read for the draft. The draft lands in the "
            "Message box above; change anything before you send."),
            level="SUPPORT", wrap=True))
        root.addWidget(card)

        self.status = QLabel("")
        self.status.setObjectName("dim")
        self.status.setWordWrap(True)
        self.status.setOpenExternalLinks(True)
        root.addWidget(self.status)

        self.footer.add_secondary(
            self.button(i18n.t("Close"), on_click=self.reject))
        self.send_btn = self.button(i18n.t("Send"), "primary",
                                    icon_name="mail", on_click=self._send)
        self.footer.set_primary(self.send_btn)
        self.tab_chain(self.to_edit, self.subject_edit, self.body_edit,
                       self.brief_edit)

        # What the workbench handed over: a CSV is the list, the rest ride
        # along as attachments.
        if attachments:
            self._take_attachments(attachments)
        self._sync()
        if mode == "list" and not self._list:
            QTimer.singleShot(0, self._add_list)
        else:
            self.to_edit.setFocus()

    # ── small builders ──────────────────────────────────────────────────
    @staticmethod
    def _field_label(text: str) -> QLabel:
        lbl = C.label(text, level="BODY", weight=600)
        lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return lbl

    # ── recipients ──────────────────────────────────────────────────────
    def _typed(self) -> list[dict]:
        """Addresses in the To line, in order, deduplicated."""
        seen, out = set(), []
        for email in _EMAIL_RE.findall(self.to_edit.text()):
            key = email.lower()
            if key not in seen:
                seen.add(key)
                out.append({"email": key, "name": ""})
        return out

    @property
    def recipients(self) -> list[dict]:
        """The list first (it carries names), then the typed ones; one entry
        per address."""
        seen, out = set(), []
        for r in list(self._list) + self._typed():
            key = r["email"].lower()
            if key not in seen:
                seen.add(key)
                out.append({"email": key, "name": (r.get("name") or "").strip()})
        return out

    def _add_list(self):
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.t("Choose the list of addresses"), "",
            "CSV (*.csv);;All files (*)")
        if path:
            self._load_list(path)

    def _load_list(self, path: str):
        """Read a CSV of recipients on this machine. Adds to any list already
        loaded; the first entry per address wins, so a name from the CSV is
        never replaced by a bare address."""
        try:
            found = CB.mailer.parse_recipients(path)
        except Exception as e:                                # noqa: BLE001
            self.status.setText(i18n.t("Could not read {name}: {error}").format(
                name=os.path.basename(path), error=e))
            return
        if not found:
            self.status.setText(i18n.t(
                "{name} has no email addresses in it.").format(
                name=os.path.basename(path)))
            return
        have = {r["email"].lower() for r in self._list}
        for r in found:
            if r["email"].lower() not in have:
                have.add(r["email"].lower())
                self._list.append({"email": r["email"].lower(),
                                   "name": (r.get("name") or "").strip()})
        self._list_name = os.path.basename(path)
        self._fill_list_table()
        self.status.setText(i18n.t("{n} addresses read from {name}.").format(
            n=len(found), name=self._list_name))
        self._sync()

    def _fill_list_table(self):
        self.list_table.setRowCount(0)
        for r in self._list:
            row = self.list_table.rowCount()
            self.list_table.insertRow(row)
            self.list_table.setItem(row, 0, QTableWidgetItem(r.get("name") or ""))
            self.list_table.setItem(row, 1, QTableWidgetItem(r["email"]))
        self.list_box.setVisible(bool(self._list))

    def _remove_selected(self):
        rows = sorted({i.row() for i in self.list_table.selectedIndexes()},
                      reverse=True)
        if not rows:
            self.status.setText(i18n.t("Click a row in the list first."))
            return
        for row in rows:
            if 0 <= row < len(self._list):
                del self._list[row]
        if not self._list:
            self._list_name = ""
        self._fill_list_table()
        self._sync()

    def _clear_list(self):
        self._list, self._list_name = [], ""
        self._fill_list_table()
        self._sync()

    def _discover_recipient(self):
        """No address to hand: ask the research/leads tool to find the
        public one, from the description in the brief box."""
        goal = self.brief_edit.text().strip()
        if not goal:
            self.status.setText(i18n.t(
                "Say who they are in the box at the bottom (for example "
                "\"purchase manager at Acme Forgings, Rajkot\"), then press "
                "this again."))
            self.brief_edit.setFocus()
            return
        agents = CB.config.active_agents(self.cfg)
        finder = next((s for s in ("leads", "research", "brains")
                       if agents.get(s)), None)
        if not finder:
            self.status.setText(i18n.t(
                "No research tool is set up, so Prism cannot search. Type "
                "the address in To instead."))
            return
        routing = {finder: {"needed": True, "questions": [
            "Your ONLY task is: find the official, public contact email address for "
            f"the recipient described here: {goal}. Search the web. Reply with the "
            "1-3 best addresses, one per line, each followed by a dash and what it "
            "is for (e.g. partnerships, support, general). Prefer official domains "
            "over aggregator sites. If none can be found, reply exactly NONE."
        ]}}
        self.status.setText(i18n.t("Searching with {tool}…").format(tool=agents[finder]))
        self._worker = AutomationWorker(routing, self.cfg, [], goal)
        self._worker.done.connect(self._on_discovery_done)
        self._worker.failed.connect(
            lambda e: self.status.setText(i18n.t("Search failed: {error}").format(error=e)))
        self._worker.start()

    def _on_discovery_done(self, responses: dict, links: dict):
        text = "\n".join(t for ts in responses.values() for t in ts)
        found = list(dict.fromkeys(_EMAIL_RE.findall(text)))
        found = [e for e in found if not e.lower().endswith("example.com")][:5]
        if not found:
            self.status.setText(i18n.t(
                "No address found — type one in To instead."))
            return
        current = self.to_edit.text().strip()
        joined = ", ".join(found)
        self.to_edit.setText(f"{current}, {joined}" if current else joined)
        self.status.setText(i18n.t(
            "Found {n} address(es) and put them in To — delete any you do "
            "not want.").format(n=len(found)))

    # ── files ───────────────────────────────────────────────────────────
    def _attach(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, i18n.t("Attach to every email"), "", "All files (*)")
        if paths:
            self._on_files_added(paths)

    def _on_files_added(self, paths: list):
        """A CSV is the list; anything else is attached to every email."""
        atts = []
        for p in paths:
            try:
                atts.append(CB.files.attach(p))
            except Exception:                                 # noqa: BLE001
                continue
        self._take_attachments(atts)

    def _take_attachments(self, attachments: list):
        csvs, others = CB.mailer.split_attachments(attachments)
        for a in csvs:
            self._load_list(a["path"])
        known = {f["path"] for f in self.source_files}
        self.source_files += [f for f in others if f["path"] not in known]
        self._sync()

    def _clear_files(self):
        self.source_files = []
        self._sync()

    # ── the one place the screen is kept truthful ─────────────────────────
    def _sync(self, *_args):
        recipients = self.recipients
        n = len(recipients)
        if n == 0:
            who = ""
        elif n == 1:
            r = recipients[0]
            who = i18n.t("Going to {who}.").format(
                who=f"{r['name']} <{r['email']}>" if r["name"] else r["email"])
        elif self._list_name:
            who = i18n.t("Going to {n} people — {m} from {name}{extra}.").format(
                n=n, m=len(self._list), name=self._list_name,
                extra=(i18n.t(", the rest typed above")
                       if n > len(self._list) else ""))
        else:
            who = i18n.t("Going to {n} people.").format(n=n)
        self.who_label.setText(who)
        self.who_label.setVisible(bool(who))

        names = ", ".join(f["name"] for f in self.source_files)
        self.files_label.setText(
            i18n.t("Attached to every email: {names}").format(names=names)
            if names else i18n.t("No files attached."))
        self.clear_files_btn.setVisible(bool(self.source_files))

        missing = []
        if n == 0:
            missing.append(i18n.t("an address in To"))
        if not self.subject_edit.text().strip():
            missing.append(i18n.t("a subject"))
        if not self.body_edit.toPlainText().strip():
            missing.append(i18n.t("the message"))
        sending = bool(self._send_worker and self._send_worker.isRunning())
        if sending:
            return
        if missing:
            self.send_btn.setText(i18n.t("Send"))
            self.send_btn.setEnabled(False)
            self.send_btn.setToolTip(i18n.t("Still needed: {what}").format(
                what=", ".join(missing)))
        else:
            self.send_btn.setEnabled(True)
            self.send_btn.setToolTip("")
            if n == 1:
                self.send_btn.setText(i18n.t("Send to {who}").format(
                    who=recipients[0]["email"]))
            else:
                self.send_btn.setText(i18n.t("Send to {n} people").format(n=n))

    # ── draft ───────────────────────────────────────────────────────────
    def _write_for_me(self):
        goal = self.brief_edit.text().strip()
        if not goal:
            self.status.setText(i18n.t(
                "Say what the email should say in the box first."))
            self.brief_edit.setFocus()
            return
        agents = CB.config.active_agents(self.cfg)
        avail = [s for s in ("research", "brains", "content") if agents.get(s)]
        if not avail:
            self.status.setText(i18n.t(
                "No writing tool is set up (Settings → AI tools), so Prism "
                "cannot write this. Type the message yourself instead."))
            return
        draft_stage = avail[-1]
        self._draft_stage = draft_stage
        routing = {draft_stage: {
            "needed": True,
            "reason": "write the email draft — and ONLY the draft",
            "expect": "SUBJECT:",
            "questions": [CB.mailer.draft_question(goal)]}}
        self._last_run = {"routing": routing, "agent": agents[draft_stage]}
        self.write_btn.setEnabled(False)
        self.status.setText(i18n.t("Writing with {tool}… this takes a minute or "
                                   "two.").format(tool=agents[draft_stage]))
        self._worker = AutomationWorker(routing, self.cfg, self.source_files,
                                        f"write an email: {goal}")
        self._worker.done.connect(self._on_draft_done)
        self._worker.failed.connect(self._on_draft_failed)
        self._worker.start()

    def _on_draft_failed(self, error: str):
        self.write_btn.setEnabled(True)
        self.status.setText(i18n.t("Could not write it: {error}").format(error=error))

    def _on_draft_done(self, responses: dict, links: dict):
        self.write_btn.setEnabled(True)
        texts = responses.get(self._draft_stage) or []
        self._last_run.update({"responses": responses, "links": links})
        usable = [t for t in texts if not CB.mailer.is_prompt_echo(t)]
        draft = CB.mailer.parse_draft(usable[0] if usable else "")
        if not draft:
            url = (links or {}).get(self._draft_stage, "")
            note = i18n.t("Could not read a finished draft back — the tool may "
                          "still be writing it. ")
            if url:
                note += (f'<a href="{url}" style="color:{theme.ACCENT_RAMP[700]}">'
                         + i18n.t("Open it in the tool") + "</a> "
                         + i18n.t("and paste the text into Message."))
            else:
                note += i18n.t("Type the message yourself instead.")
            self.status.setText(note)
            return
        subject, body = draft
        self.subject_edit.setText(subject)
        self.body_edit.setPlainText(body)
        self.status.setText(i18n.t(
            "Draft ready — read it, change anything, then press Send."))

    # ── send ────────────────────────────────────────────────────────────
    def _change_account(self):
        dlg = EmailSetupDialog(self.cfg, self)
        if dlg.exec() == QDialog.Accepted:
            self.cfg = dlg.cfg
            address = (self.cfg.get("email") or {}).get("address", "")
            self.header.set_subtitle(i18n.t(
                "From {address}. Fill in To, Subject and Message, then press "
                "Send. Nothing goes out until you press it.").format(address=address))

    def _send(self):
        # Second press while a blast is running means stop, not send again.
        if self._send_worker and self._send_worker.isRunning():
            self._send_worker.stop()
            self.send_btn.setEnabled(False)
            self.send_btn.setText(i18n.t("Stopping…"))
            return
        if not CB.mailer.is_configured(self.cfg):
            dlg = EmailSetupDialog(self.cfg, self)
            if dlg.exec() != QDialog.Accepted:
                return
            self.cfg = dlg.cfg
        recipients = self.recipients
        subject = self.subject_edit.text().strip()
        body = self.body_edit.toPlainText().strip()
        if not recipients or not subject or not body:
            self._sync()
            return
        files = ", ".join(f["name"] for f in self.source_files) or i18n.t("none")
        if len(recipients) == 1:
            question = i18n.t(
                "Send this email to {to}?\n\nSubject: {subject}\n"
                "Files: {files}\nFrom: {sender}").format(
                to=recipients[0]["email"], subject=subject, files=files,
                sender=self.cfg["email"]["address"])
        else:
            shown = ", ".join(r["email"] for r in recipients[:5])
            more = ", …" if len(recipients) > 5 else ""
            question = i18n.t(
                "Send to {n} people?\n\nTo: {to}\nSubject: {subject}\n"
                "Files: {files}\nFrom: {sender}\n\nEach person gets their own "
                "copy. This cannot be undone.").format(
                n=len(recipients), to=f"{shown}{more}", subject=subject,
                files=files, sender=self.cfg["email"]["address"])
        confirm = QMessageBox.question(
            self, i18n.t("Send"), question,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No)   # nobody should send a blast by pressing Enter
        if confirm != QMessageBox.Yes:
            return

        self._sent_ok, self._sent_bad = [], []
        self._subject, self._body = subject, body
        self._recipients_sent = recipients
        self._set_sending(True)
        self.status.setText(i18n.t("Signing in to {host}…").format(
            host=self.cfg["email"]["host"]))
        self._send_worker = SendWorker(self.cfg, list(recipients), subject,
                                       body, self.source_files)
        self._send_worker.progress.connect(self._on_send_progress)
        self._send_worker.done.connect(self._on_send_done)
        self._send_worker.failed.connect(self._on_send_failed)
        self._send_worker.start()

    def _set_sending(self, sending: bool):
        """A list takes minutes. Everything that would change what is being
        sent is locked while it runs, and Send becomes the way to stop."""
        for w in (self.to_edit, self.subject_edit, self.body_edit,
                  self.brief_edit, self.list_btn, self.attach_btn,
                  self.remove_btn, self.clear_list_btn, self.write_btn):
            w.setEnabled(not sending)
        self.send_btn.setEnabled(True)
        if sending:
            self.send_btn.setText(i18n.t("Stop sending"))
        else:
            self._sync()

    def _on_send_progress(self, i: int, total: int, email: str, ok: bool, error: str):
        (self._sent_ok if ok else self._sent_bad).append(
            email if ok else (email, error))
        tail = "" if ok else f" — {error[:60]}"
        line = i18n.t("{i}/{total} · {state} {email}").format(
            i=i, total=total, email=email,
            state=i18n.t("sent") if ok else i18n.t("FAILED")) + tail
        if self._sent_bad and ok:
            line += "  " + i18n.t("({n} failed so far)").format(n=len(self._sent_bad))
        self.status.setText(line)

    def _on_send_done(self, sent: list, failed: list):
        self._set_sending(False)
        stopped = bool(self._send_worker and self._send_worker.stopped)
        recipients = getattr(self, "_recipients_sent", self.recipients)
        try:
            sent_log.record(
                self.cfg, to=recipients, subject=self._subject, body=self._body,
                sent=sent, failed=failed,
                attachments=[f["name"] for f in self.source_files],
                list_name=self._list_name, stopped=stopped)
        except Exception as e:                                # noqa: BLE001
            self.status.setText(i18n.t(
                "Sent, but could not write it down in {path}: {error}").format(
                path=sent_log.path(self.cfg), error=e))
        self._save_run(sent, failed)
        if len(recipients) == 1 and sent and not failed:
            msg = i18n.t("Sent to {who}.").format(who=sent[0])
        else:
            msg = i18n.t("Sent to {n} of {total}.").format(
                n=len(sent), total=len(recipients))
        if stopped:
            msg += "\n" + i18n.t("Stopped early — the rest were not attempted.")
        if failed:
            shown = "\n".join(f"· {email} — {err[:120]}" for email, err in failed[:8])
            msg += "\n\n" + i18n.t("{n} failed:").format(n=len(failed)) + "\n" + shown
            hint = CB.mailer.explain_error(failed[0][1], self.cfg["email"]["address"])
            if hint != failed[0][1]:
                msg += f"\n\n{hint}"
        self.status.setText(msg.split("\n")[0])
        QMessageBox.information(self, i18n.t("Email"), msg)
        if sent and not failed and not stopped:
            self.accept()

    def _on_send_failed(self, error: str):
        """Login or connection died — nothing went out at all."""
        self._set_sending(False)
        hint = CB.mailer.explain_error(error, self.cfg["email"]["address"])
        self.status.setText(i18n.t("Could not send: {hint}").format(hint=hint))
        again = QMessageBox.question(
            self, i18n.t("Send failed"),
            i18n.t("{hint}\n\nThe server said: {error}\n\n"
                   "Open account setup now?").format(hint=hint, error=error))
        if again == QMessageBox.Yes:
            self._change_account()

    def _save_run(self, sent: list, failed: list):
        """The same record the CLI's /email writes, so the send also shows
        in History. The "/email " prefix is what History and the old front
        door key on — keep it."""
        goal = self.brief_edit.text().strip() or self._subject
        record = {
            "query": f"/email {goal}",
            "routing": self._last_run.get("routing") or {},
            "responses": self._last_run.get("responses") or {},
            "links": self._last_run.get("links") or {},
            "attachments": [f["name"] for f in self.source_files],
            "email": {"subject": self._subject, "sent": sent, "failed": failed,
                      "recipients": len(getattr(self, "_recipients_sent", []))},
        }
        if self._draft_stage and self._last_run.get("agent"):
            record["agents"] = {self._draft_stage: self._last_run["agent"]}
        try:
            CB.config.save_run(record)
        except Exception as e:                                # noqa: BLE001
            self.status.setText(i18n.t(
                "Sent, but could not save to History: {error}").format(error=e))

    def closeEvent(self, event):
        """Wind up every worker before this dialog is destroyed — a QThread
        destroyed while running aborts the whole process."""
        if self._send_worker and self._send_worker.isRunning():
            leave = QMessageBox.question(
                self, i18n.t("Still sending"),
                i18n.t("Emails are still going out. Stop and close?"))
            if leave != QMessageBox.Yes:
                event.ignore()
                return
        for worker in (self._worker, self._send_worker):
            if worker is None:
                continue
            try:
                if not worker.isRunning():
                    continue
                if hasattr(worker, "stop"):
                    worker.stop()
                if not worker.wait(8000):
                    worker.terminate()
                    worker.wait(1000)
            except RuntimeError:
                pass
        super().closeEvent(event)
