"""Inquiry automation — the settings that stay the same every day.

Asked once, at the start, and then never again. Everything here is a constant
of the business rather than of a particular inquiry: which mailbox, which rate
list, what your terms are, who your customers are.

Laid out as four steps rather than one long form because the person filling it
in has never set up software before, and a screen with twenty boxes on it is
where they stop and telephone somebody.

The password is the one thing worth saying out loud: it goes into
~/.prism/config.json on this computer, the same file the sending account
already uses, and nowhere else. Prism has no server to send it to.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
    QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

import core_bridge as CB
import i18n
from workers import InboxVerifyWorker

DEFAULT_FOLDER = os.path.join(os.path.expanduser("~"), "Prism Inquiries")


def settings_of(cfg: dict) -> dict:
    return dict(cfg.get("inquiry") or {})


def is_ready(cfg: dict) -> bool:
    """Enough set up to run a check. Deliberately only the mailbox and the
    folder — a rate list matters at quoting time, not at reading time, and
    demanding one up front would stop somebody trying the read-only half."""
    s = settings_of(cfg)
    account = s.get("account") or {}
    return bool(account.get("address") and account.get("password")
                and account.get("host") and s.get("folder"))


class _Picker(QWidget):
    """A read-only path box with a Browse button next to it."""

    def __init__(self, value: str = "", *, directory: bool = False,
                 filters: str = "", placeholder: str = "", parent=None):
        super().__init__(parent)
        self.directory, self.filters = directory, filters
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit(value)
        self.edit.setPlaceholderText(placeholder)
        row.addWidget(self.edit, stretch=1)
        browse = QPushButton(i18n.t("Browse…"))
        browse.clicked.connect(self._browse)
        row.addWidget(browse)

    def _browse(self):
        start = self.edit.text().strip() or os.path.expanduser("~")
        if self.directory:
            # Captions are translated at the call site. QFileDialog's statics
            # are deliberately never patched — doing that once broke every
            # attachment in the app. See i18n.install().
            path = QFileDialog.getExistingDirectory(
                self, i18n.t("Choose a folder"), start)
        else:
            path, _ = QFileDialog.getOpenFileName(
                self, i18n.t("Choose a file"), start, self.filters)
        if path:
            self.edit.setText(path)

    def value(self) -> str:
        return self.edit.text().strip()


class InquirySetupDialog(QDialog):

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.t("Inquiry automation — setup"))
        self.resize(680, 620)
        self.cfg = dict(cfg)
        self._verify = None

        saved = settings_of(cfg)
        self._account = dict(saved.get("account") or {})
        self._saved_password = self._account.get("password", "")

        root = QVBoxLayout(self)
        intro = QLabel(i18n.t(
            "Set this up once. Prism then reads your inbox, sorts it, and "
            "keeps your inquiry register — without being asked again."))
        intro.setWordWrap(True)
        intro.setProperty("class", "muted")
        root.addWidget(intro)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._mail_tab(), i18n.t("1 · Mailbox"))
        self.tabs.addTab(self._folder_tab(), i18n.t("2 · Files"))
        self.tabs.addTab(self._terms_tab(), i18n.t("3 · Your terms"))
        self.tabs.addTab(self._people_tab(), i18n.t("4 · Who's who"))
        root.addWidget(self.tabs, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ── 1. the mailbox ────────────────────────────────────────────────────
    def _mail_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        note = QLabel(i18n.t(
            "Prism only READS this mailbox. It never marks anything as read, "
            "never moves anything and never deletes anything — you can keep "
            "using Outlook or your phone exactly as before.\n\n"
            "Your password is saved on this computer only. Prism has no "
            "server to send it to."))
        note.setWordWrap(True)
        layout.addWidget(note)

        form = QFormLayout()
        self.addr = QLineEdit(self._account.get("address", ""))
        self.addr.setPlaceholderText("sales@yourcompany.co.in")
        form.addRow(i18n.t("Email address:"), self.addr)

        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText(i18n.t(
            "leave blank to keep the saved password") if self._saved_password
            else i18n.t("your mail password"))
        form.addRow(i18n.t("Password:"), self.password)

        self.host = QLineEdit(self._account.get("host", ""))
        self.host.setPlaceholderText(i18n.t("found automatically — leave blank"))
        form.addRow(i18n.t("Mail server:"), self.host)

        self.folder_name = QLineEdit(self._account.get("folder", "") or "INBOX")
        form.addRow(i18n.t("Folder to read:"), self.folder_name)
        layout.addLayout(form)

        row = QHBoxLayout()
        self.test_btn = QPushButton(i18n.t("Find my server and test"))
        self.test_btn.clicked.connect(self._test)
        row.addWidget(self.test_btn)
        self.test_result = QLabel("")
        self.test_result.setWordWrap(True)
        row.addWidget(self.test_result, stretch=1)
        layout.addLayout(row)

        gmail = QLabel(i18n.t(
            "Gmail and Outlook need an app password rather than your normal "
            "one. A mailbox on your own company domain usually takes the "
            "normal password."))
        gmail.setWordWrap(True)
        gmail.setProperty("class", "muted")
        layout.addWidget(gmail)
        layout.addStretch(1)
        return page

    def _test(self):
        address = self.addr.text().strip()
        password = self.password.text() or self._saved_password
        if not address or not password:
            self.test_result.setText(i18n.t("Enter the address and password first."))
            return
        self.test_btn.setEnabled(False)
        self.test_result.setText(i18n.t("Looking for your mail server…"))

        def finished(settings: dict, error: str):
            self.test_btn.setEnabled(True)
            if error:
                self.test_result.setText(error)
                return
            self.host.setText(settings.get("host", ""))
            self._account.update(settings)
            self.test_result.setText(
                i18n.t("Connected. Server: {host}").replace(
                    "{host}", settings.get("host", "")))

        self._verify = InboxVerifyWorker(address, password)
        self._verify.done.connect(finished)
        self._verify.start()

    # ── 2. where things are kept ──────────────────────────────────────────
    def _folder_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        saved = settings_of(self.cfg)

        note = QLabel(i18n.t(
            "Everything Prism produces lands in one folder you choose — the "
            "inquiry register, and a folder per inquiry holding the mail and "
            "the drawings. They are ordinary files: the register opens in "
            "Excel, and it stays yours whatever happens to Prism."))
        note.setWordWrap(True)
        layout.addWidget(note)

        form = QFormLayout()
        self.work_folder = _Picker(saved.get("folder", "") or DEFAULT_FOLDER,
                                   directory=True)
        form.addRow(i18n.t("Keep everything in:"), self.work_folder)

        self.rate_file = _Picker(
            saved.get("rate_list", ""),
            filters=i18n.t("Price lists (*.csv *.xlsx *.xlsm);;All files (*)"),
            placeholder=i18n.t("your price list — needed only for quoting"))
        form.addRow(i18n.t("Rate list:"), self.rate_file)

        self.cost_file = _Picker(
            saved.get("cost_sheet", ""),
            filters=i18n.t("Cost sheets (*.csv *.xlsx *.xlsm);;All files (*)"),
            placeholder=i18n.t("optional — your formulas, for made-to-drawing work"))
        form.addRow(i18n.t("Cost sheet:"), self.cost_file)

        # How far the owner will bend, in their own words. Only ever read when
        # they press "Win this back", and the negotiation prompt refuses to
        # offer anything at all when it is missing — the safe direction to
        # fail in is "no discount", not "some discount".
        self.policy_file = _Picker(
            saved.get("pricing_policy", ""),
            filters=i18n.t("Any document (*.pdf *.docx *.txt *.csv *.xlsx);;"
                           "All files (*)"),
            placeholder=i18n.t("optional — how much you can bargain"))
        form.addRow(i18n.t("Bargaining limits:"), self.policy_file)

        # A shop that has been trading for twenty years already keeps an
        # inquiry list. Starting them at row one would mean running two
        # registers side by side until they gave up on ours.
        self.existing_register = _Picker(
            "", filters=i18n.t("Registers (*.csv);;All files (*)"),
            placeholder=i18n.t("optional — the list you already keep"))
        form.addRow(i18n.t("Start from my register:"), self.existing_register)
        layout.addLayout(form)

        self.import_note = QLabel("")
        self.import_note.setWordWrap(True)
        self.import_note.setProperty("class", "muted")
        layout.addWidget(self.import_note)

        hint = QLabel(i18n.t(
            "A rate list needs a heading row with at least a description and "
            "a rate — for example: Code, Description, Unit, Rate. A "
            "letterhead above it is fine. Columns like \"Rate @ 1000\" are "
            "read as quantity discounts."))
        hint.setWordWrap(True)
        hint.setProperty("class", "muted")
        layout.addWidget(hint)

        # Worth spelling out with an example. "Cost sheet" means a dozen
        # different documents in a dozen different factories, and the one
        # Prism can run is a specific and simple shape.
        formulas = QLabel(i18n.t(
            "A cost sheet is your own working, three columns wide: the name "
            "of the charge, how it is charged, and the rate. Prism does the "
            "arithmetic and shows every line — it never invents a rate.\n\n"
            "    Wire,          per_kg,     95\n"
            "    Coiling,       per_piece,  1.20\n"
            "    Tool setting,  per_lot,    800\n"
            "    Overheads,     percent,    12\n\n"
            "Percentages apply to the total of the lines above them, so the "
            "order of your rows is the order of your own calculation."))
        formulas.setWordWrap(True)
        formulas.setProperty("class", "muted")
        layout.addWidget(formulas)
        layout.addStretch(1)
        return page

    # ── 3. terms that go on every quotation ───────────────────────────────
    def _terms_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        saved = settings_of(self.cfg)
        terms = saved.get("terms") or {}

        form = QFormLayout()
        self.company = QLineEdit(saved.get("company", ""))
        self.company.setPlaceholderText(i18n.t("as it should appear on the quotation"))
        form.addRow(i18n.t("Company name:"), self.company)

        self.signature = QLineEdit(saved.get("signature", ""))
        self.signature.setPlaceholderText(i18n.t("who quotations are signed by"))
        form.addRow(i18n.t("Sign off as:"), self.signature)

        self.gst = QSpinBox()
        self.gst.setRange(0, 100)
        self.gst.setSuffix(" %")
        self.gst.setValue(int(terms.get("gst_percent", 18) or 0))
        form.addRow(i18n.t("GST:"), self.gst)

        self.validity = QSpinBox()
        self.validity.setRange(1, 365)
        self.validity.setSuffix(i18n.t(" days"))
        self.validity.setValue(int(terms.get("validity_days", 15) or 15))
        form.addRow(i18n.t("Quotation valid for:"), self.validity)

        self.payment = QLineEdit(terms.get("payment", "") or
                                 "100% against proforma invoice")
        form.addRow(i18n.t("Payment terms:"), self.payment)

        self.delivery = QLineEdit(terms.get("delivery", "") or
                                  "2–3 weeks from receipt of confirmed order")
        form.addRow(i18n.t("Delivery:"), self.delivery)

        self.followup_days = QSpinBox()
        self.followup_days.setRange(1, 60)
        self.followup_days.setSuffix(i18n.t(" days"))
        self.followup_days.setValue(int(saved.get("followup_days", 2) or 2))
        form.addRow(i18n.t("Chase a quiet quotation after:"), self.followup_days)

        self.max_reminders = QSpinBox()
        self.max_reminders.setRange(1, 6)
        self.max_reminders.setSuffix(i18n.t(" times"))
        self.max_reminders.setValue(int(saved.get("max_reminders", 3) or 3))
        form.addRow(i18n.t("Then stop after:"), self.max_reminders)

        self.auto_minutes = QSpinBox()
        self.auto_minutes.setRange(0, 240)
        self.auto_minutes.setSuffix(i18n.t(" minutes"))
        self.auto_minutes.setSpecialValueText(i18n.t("only when I ask"))
        self.auto_minutes.setValue(int(saved.get("auto_minutes", 0) or 0))
        form.addRow(i18n.t("Check the inbox every:"), self.auto_minutes)
        layout.addLayout(form)

        auto_note = QLabel(i18n.t(
            "Automatic checking only ever READS your mail. Ten minutes suits "
            "most offices; below five is more often than any mail server "
            "expects to be asked."))
        auto_note.setWordWrap(True)
        auto_note.setProperty("class", "muted")
        layout.addWidget(auto_note)

        self.auto_followup = QCheckBox(i18n.t(
            "Send the reminders by themselves, without asking me each time"))
        self.auto_followup.setChecked(bool(saved.get("auto_followup", False)))
        layout.addWidget(self.auto_followup)

        chase_note = QLabel(i18n.t(
            "With this ticked, a quotation nobody has replied to is chased on "
            "the schedule above and the register is updated — the whole thing "
            "runs without you. Every reminder is written afresh rather than "
            "the same sentence three times, and Prism stops the moment they "
            "reply.\n\n"
            "It is off to begin with because these are letters going out in "
            "your name. Leave it off for the first week, watch what the "
            "reminders say, then turn it on once you trust them."))
        chase_note.setWordWrap(True)
        chase_note.setProperty("class", "muted")
        layout.addWidget(chase_note)
        layout.addStretch(1)
        return page

    # ── 4. who is who ─────────────────────────────────────────────────────
    def _people_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        saved = settings_of(self.cfg)
        known = saved.get("knowledge") or {}

        note = QLabel(i18n.t(
            "Telling Prism who your customers and suppliers are makes the "
            "sorting right from day one instead of week three — and it keeps "
            "their mail on this computer, because a sender Prism already "
            "recognises never has to be looked at by an AI.\n\n"
            "One line each. A whole company works: type shaktiauto.in and "
            "everybody there is covered."))
        note.setWordWrap(True)
        layout.addWidget(note)

        def box(title: str, values, placeholder: str) -> QPlainTextEdit:
            group = QGroupBox(title)
            inner = QVBoxLayout(group)
            edit = QPlainTextEdit("\n".join(values or []))
            edit.setPlaceholderText(placeholder)
            edit.setFixedHeight(74)
            inner.addWidget(edit)
            layout.addWidget(group)
            return edit

        self.own = box(i18n.t("Your own company's addresses"),
                       known.get("own_domains"), "yourcompany.co.in")
        self.customers = box(i18n.t("Customers"), known.get("customers"),
                             "shaktiauto.in\nbuyer@gujaratmotors.in")
        self.vendors = box(i18n.t("Suppliers"), known.get("vendors"),
                           "steelsupply.co.in")

        self.local_only = QCheckBox(i18n.t(
            "Keep everything on this computer — never send any mail to an AI"))
        self.local_only.setChecked(bool(saved.get("local_only", False)))
        layout.addWidget(self.local_only)

        explain = QLabel(i18n.t(
            "With this ticked, Prism sorts using only the rules above and "
            "anything it cannot place is listed for you to glance at. "
            "Nothing whatsoever leaves the machine. Untick it and only the "
            "few messages from senders Prism does not recognise are sent to "
            "be labelled."))
        explain.setWordWrap(True)
        explain.setProperty("class", "muted")
        layout.addWidget(explain)
        layout.addStretch(1)
        return page

    # ── bringing an existing register in ──────────────────────────────────
    def _import_register(self, folder: str) -> str:
        """Copy the customer's own inquiry list in, once.

        Rules, in the order they matter:

          · **Never overwrite a register that already has rows in it.** That
            file is the only copy of their order book. If one is already
            there, this does nothing and says so.
          · **Never rewrite their columns.** register.load/save keep unknown
            columns untouched, so their "Party Name" or "Remarks" survive
            exactly as typed and sit alongside Prism's.
          · **Say what was recognised.** A register whose columns Prism cannot
            read still imports, but the screen will show blanks in those
            columns, and finding that out on Monday is worse than being told
            now.

        Returns a sentence for the screen, or "" when there was nothing to do.
        """
        source = self.existing_register.value()
        if not source:
            return ""
        register = CB.get_register()
        destination = os.path.join(folder, register.FILENAME)

        if os.path.exists(destination):
            try:
                already = register.load(destination)
            except Exception:
                already = [None]        # unreadable, but present — leave it
            if already:
                return i18n.t(
                    "There is already an inquiry register in that folder with "
                    "{n} row(s), so it was left alone. Nothing was imported."
                ).replace("{n}", str(len(already)))

        try:
            rows = register.load(source)
        except Exception as e:
            return i18n.t("Couldn't read that register: {why}").replace(
                "{why}", str(e))
        if not rows:
            return i18n.t("That file has no rows in it, so nothing was imported.")

        try:
            register.save(rows, destination)
        except Exception as e:
            return i18n.t("Couldn't write the register: {why}").replace(
                "{why}", str(e))

        # Which of ours they already have. Reported rather than corrected: a
        # column-guessing importer that got it wrong would quietly mis-file
        # somebody's twenty-year order book.
        theirs = set(rows[0].keys())
        wanted = ("Inquiry no", "Date received", "Customer", "Status")
        missing = [c for c in wanted if c not in theirs]
        message = i18n.t("Imported {n} row(s) from your register.").replace(
            "{n}", str(len(rows)))
        if missing:
            message += " " + i18n.t(
                "Prism didn't find these columns in it — {cols} — so those "
                "boxes will be empty on the Inquiries screen until you fill "
                "them in. Everything you already had is untouched."
            ).replace("{cols}", ", ".join(missing))
        return message

    # ── saving ────────────────────────────────────────────────────────────
    @staticmethod
    def _lines(edit: QPlainTextEdit) -> list[str]:
        return [line.strip().lower().lstrip("@")
                for line in edit.toPlainText().splitlines() if line.strip()]

    def _save(self):
        address = self.addr.text().strip()
        password = self.password.text() or self._saved_password
        folder = self.work_folder.value()

        if not address or not password:
            QMessageBox.information(
                self, i18n.t("Inquiry automation"),
                i18n.t("Prism needs the email address and password of the "
                       "mailbox to read. Nothing else can start without it."))
            self.tabs.setCurrentIndex(0)
            return
        if not folder:
            QMessageBox.information(
                self, i18n.t("Inquiry automation"),
                i18n.t("Choose a folder for the inquiry register and the "
                       "files that come with each inquiry."))
            self.tabs.setCurrentIndex(1)
            return
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as e:
            QMessageBox.warning(self, i18n.t("Inquiry automation"), str(e))
            self.tabs.setCurrentIndex(1)
            return

        host = self.host.text().strip() or self._account.get("host", "")
        if not host:
            # No Test run and no saved host — work it out now rather than
            # failing on the first check with a message about a server the
            # customer never typed.
            inbox = CB.get_inbox()
            guesses = inbox.guess_hosts(address)
            host = guesses[0] if guesses else ""

        self.cfg["inquiry"] = {
            "account": {"address": address, "password": password,
                        "host": host, "port": 993,
                        "folder": self.folder_name.text().strip() or "INBOX"},
            "folder": folder,
            "rate_list": self.rate_file.value(),
            "cost_sheet": self.cost_file.value(),
            "company": self.company.text().strip(),
            "signature": self.signature.text().strip(),
            "terms": {"gst_percent": self.gst.value(),
                      "validity_days": self.validity.value(),
                      "payment": self.payment.text().strip(),
                      "delivery": self.delivery.text().strip()},
            "pricing_policy": self.policy_file.value(),
            "followup_days": self.followup_days.value(),
            "max_reminders": self.max_reminders.value(),
            "auto_minutes": self.auto_minutes.value(),
            "auto_followup": self.auto_followup.isChecked(),
            "local_only": self.local_only.isChecked(),
            "knowledge": {"own_domains": self._lines(self.own),
                          "customers": self._lines(self.customers),
                          "vendors": self._lines(self.vendors),
                          # Corrections the customer makes as they go. Kept
                          # across saves so re-opening setup never forgets
                          # what Prism has learned about their senders.
                          "learned": ((settings_of(self.cfg).get("knowledge")
                                       or {}).get("learned") or {})},
            "state": settings_of(self.cfg).get("state") or {},
        }
        CB.config.save(self.cfg)

        # Last, and after the config is safely written: an import that fails
        # must not also cost them the settings they just typed in.
        imported = self._import_register(folder)
        if imported:
            self.import_note.setText(imported)
            QMessageBox.information(self, i18n.t("Inquiry register"), imported)
        self.accept()
