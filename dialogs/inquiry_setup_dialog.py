"""Email automation — the settings that stay the same every day.

Asked once, at the start, and then never again. Everything here is a constant
of the business rather than of a particular inquiry: which mailboxes, which
rate list, what your terms are, who your customers are.

Laid out as four steps rather than one long form because the person filling it
in has never set up software before, and a screen with twenty boxes on it is
where they stop and telephone somebody.

The password is the one thing worth saying out loud: it goes into
~/.prism/config.json on this computer, the same file the sending account
already uses, and nowhere else. Prism has no server to send it to.

────────────────────────────────────────────────────────────────────────────
Several mailboxes, one register
────────────────────────────────────────────────────────────────────────────
The firms this is sold to do not have one inbox. Inquiries land on sales@,
info@ and the owner's own address, and today somebody copies all three into
one Excel sheet by hand. So the mailbox step takes a LIST, and every mailbox
feeds the same register in the same folder — point that folder at a shared
drive and the whole office reads one file, which is the system they already
run, minus the typing.

The config grew a shape for it: `cfg["inquiry"]["accounts"]` is the list,
and each entry carries its own `state` (the read bookmark), because two
mailboxes sharing one bookmark would skip or re-import each other's mail.
The old single-mailbox keys — `account` and `state` — are still written,
mirroring the first entry, so a config saved by this version opens cleanly
in the previous one and everything that still reads the old shape keeps
working. `accounts_of()` is the one reader that understands both.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QTabWidget,
    QVBoxLayout, QWidget,
)

import core_bridge as CB
import i18n
import theme
from widgets import icons
from workers import InboxVerifyWorker

DEFAULT_FOLDER = os.path.join(os.path.expanduser("~"), "Prism Inquiries")


def settings_of(cfg: dict) -> dict:
    return dict(cfg.get("inquiry") or {})


def accounts_of(cfg: dict) -> list[dict]:
    """Every configured mailbox, in the order they were added.

    Reads the list form first; a config from before mailboxes were a list is
    wrapped on the way out — the legacy `account` becomes entry one and
    brings the legacy `state` bookmark with it, so an existing customer's
    first multi-mailbox check carries on from where their last single-mailbox
    check stopped instead of re-importing a month of mail.

    Copies, not references: callers edit these freely and save what they
    mean to save.
    """
    s = settings_of(cfg)
    accounts = [dict(a) for a in (s.get("accounts") or []) if a]
    if not accounts and s.get("account"):
        legacy = dict(s["account"])
        legacy["state"] = dict(s.get("state") or {})
        accounts = [legacy]
    return accounts


def _complete(account: dict) -> bool:
    return bool(account.get("address") and account.get("password")
                and account.get("host"))


def is_ready(cfg: dict) -> bool:
    """Enough set up to run a check. Deliberately only a mailbox and the
    folder — a rate list matters at quoting time, not at reading time, and
    demanding one up front would stop somebody trying the read-only half."""
    s = settings_of(cfg)
    return bool(any(_complete(a) for a in accounts_of(cfg))
                and s.get("folder"))


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


def _scrolled(page: QWidget) -> QScrollArea:
    """Let a step scroll rather than crush its own fields.

    Grouping the settings made each step taller than the dialog, and Qt's
    response to that is to compress the layouts until they fit: on "Your
    terms" the four quotation rows overlapped and their text was sliced in
    half. It also matters on a 1366x768 laptop — ordinary kit in a drawing
    office — where this dialog was already close to the ceiling.
    """
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    area.setWidget(page)
    return area


def _group(title: str) -> tuple[QGroupBox, QFormLayout]:
    """A titled block with a form inside it.

    The three later steps were flat lists — nine boxes on "Your terms" with
    nothing to say that GST belongs with the quotation and "check every N
    minutes" does not. Grouping is the whole difference between a form you
    read and a form you survey.
    """
    box = QGroupBox(i18n.t(title))
    form = QFormLayout(box)
    form.setContentsMargins(14, 8, 14, 12)
    form.setSpacing(9)
    return box, form


class _Disclosure(QWidget):
    """A link-styled toggle with a body that folds away underneath it.

    Used for the long format explainers. They are genuinely useful — a cost
    sheet means a different document in every factory — but printed
    permanently they turned a five-field step into a page of grey prose, and
    the field somebody actually had to fill in scrolled off the bottom.
    """

    def __init__(self, label: str, body: str, parent=None):
        super().__init__(parent)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)

        self.button = QPushButton(i18n.t(label))
        self.button.setObjectName("linkBtn")
        self.button.setCheckable(True)
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.setLayoutDirection(Qt.RightToLeft)
        icons.button_icon(self.button, "chevron-right", 13,
                          theme.ACCENT_RAMP[700])
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.button)
        row.addStretch(1)
        column.addLayout(row)

        self.body = QLabel(i18n.t(body))
        self.body.setWordWrap(True)
        self.body.setProperty("class", "muted")
        self.body.setVisible(False)
        column.addWidget(self.body)

        def toggle(open_: bool):
            icons.button_icon(self.button,
                              "chevron-down" if open_ else "chevron-right",
                              13, theme.ACCENT_RAMP[700])
            self.body.setVisible(open_)
        self.button.toggled.connect(toggle)


class InquirySetupDialog(QDialog):

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.t("Email automation — setup"))
        self.resize(680, 620)
        self.cfg = dict(cfg)
        self._verify = None

        # Working copies of every configured mailbox, each carrying its own
        # read bookmark. One blank entry when nothing is configured yet, so
        # the first-run flow is still "type the address, type the password,
        # Save" with no list to understand first.
        self._accounts = accounts_of(cfg) or [{}]
        self._current = 0
        self._saved_password = self._accounts[0].get("password", "")

        root = QVBoxLayout(self)
        intro = QLabel(i18n.t(
            "Set this up once. Prism then reads your inbox, sorts it, and "
            "keeps your inquiry register — without being asked again."))
        intro.setWordWrap(True)
        intro.setProperty("class", "muted")
        root.addWidget(intro)

        self.tabs = QTabWidget()
        self.tabs.addTab(_scrolled(self._mail_tab()), i18n.t("1 · Mailbox"))
        self.tabs.addTab(_scrolled(self._folder_tab()), i18n.t("2 · Files"))
        self.tabs.addTab(_scrolled(self._terms_tab()), i18n.t("3 · Your terms"))
        self.tabs.addTab(_scrolled(self._people_tab()), i18n.t("4 · Who's who"))
        # Only the first two are needed to start reading mail — is_ready()
        # says so, and the customer had no way to know it. Somebody who
        # believes all four are compulsory stops at "Your terms" because they
        # have not decided their payment wording yet, and never gets to see
        # the thing work at all.
        for index, tip in ((0, i18n.t("Required — which mailbox to read")),
                           (1, i18n.t("Required — where to keep the register")),
                           (2, i18n.t("Optional — needed before you send a "
                                      "quotation, not before reading")),
                           (3, i18n.t("Optional — helps Prism tell customers "
                                      "from suppliers"))):
            self.tabs.setTabToolTip(index, tip)
        root.addWidget(self.tabs, stretch=1)

        self.step_hint = QLabel("")
        self.step_hint.setWordWrap(True)
        self.step_hint.setProperty("class", "muted")
        root.addWidget(self.step_hint)
        self.tabs.currentChanged.connect(self._describe_step)
        self._describe_step(0)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _describe_step(self, index: int):
        """Say what this step is for, and whether it can be skipped.

        Under the tabs rather than inside each one, so the sentence is in the
        same place every time and reads as guidance about the form rather than
        as one more instruction competing with the fields.
        """
        self.step_hint.setText({
            0: i18n.t("Required. Every mailbox your customers write to — "
                      "they all feed the same register."),
            1: i18n.t("Required. One folder holds the register and a folder "
                      "per inquiry — ordinary files that stay yours."),
            2: i18n.t("Optional for now. These go on quotations, so they are "
                      "needed before you send one — not before reading mail."),
            3: i18n.t("Optional. Listing your customers' domains helps Prism "
                      "tell an inquiry from a supplier's mail on day one."),
        }.get(index, ""))

    # ── 1. the mailboxes ──────────────────────────────────────────────────
    def _mail_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        note = QLabel(i18n.t(
            "Prism only READS these mailboxes. It never marks anything as "
            "read, never moves anything and never deletes anything — "
            "everyone keeps using Outlook or their phone exactly as before."
            "\n\nPasswords are saved on this computer only. Prism has no "
            "server to send them to."))
        note.setWordWrap(True)
        layout.addWidget(note)

        # The list. Hidden while there is only the one mailbox: a list of one,
        # above a form asking for that same one, reads as two steps where the
        # customer has only one thing to do — and one mailbox is every
        # existing customer on the day they update.
        self.mailboxes = QListWidget()
        self.mailboxes.setFixedHeight(84)
        self.mailboxes.currentRowChanged.connect(self._mailbox_picked)
        layout.addWidget(self.mailboxes)

        list_row = QHBoxLayout()
        list_row.setSpacing(10)
        self.add_mailbox_btn = QPushButton(i18n.t("Add another mailbox"))
        self.add_mailbox_btn.setToolTip(i18n.t(
            "sales@, info@, the owner's own — inquiries from every one land "
            "in the same register"))
        self.add_mailbox_btn.clicked.connect(self._add_mailbox)
        list_row.addWidget(self.add_mailbox_btn)
        self.remove_mailbox_btn = QPushButton(i18n.t("Remove this mailbox"))
        self.remove_mailbox_btn.clicked.connect(self._remove_mailbox)
        list_row.addWidget(self.remove_mailbox_btn)
        list_row.addStretch(1)
        layout.addLayout(list_row)

        # Two questions, both of which the owner can answer without asking
        # anyone. Everything technical moved behind the disclosure below —
        # "Mail server" was the field that generated the support calls, and
        # asking for it up front contradicts this app's own rule that no
        # jargon reaches the screen.
        form = QFormLayout()
        form.setSpacing(10)
        self.addr = QLineEdit(self._accounts[0].get("address", ""))
        self.addr.setPlaceholderText("sales@yourcompany.co.in")
        self.addr.textChanged.connect(self._mail_input_changed)
        form.addRow(i18n.t("Email address:"), self.addr)

        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText(i18n.t(
            "leave blank to keep the saved password") if self._saved_password
            else i18n.t("your mail password"))
        self.password.textChanged.connect(self._mail_input_changed)
        # Enter in either box runs the check, rather than silently triggering
        # the dialog's default button and saving something untested.
        for box in (self.addr, self.password):
            box.returnPressed.connect(self._test)
        form.addRow(i18n.t("Password:"), self.password)
        layout.addLayout(form)

        layout.addSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.test_btn = QPushButton(i18n.t("Check this works"))
        self.test_btn.setObjectName("primaryBtn")
        self.test_btn.setCursor(Qt.PointingHandCursor)
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

        # ── behind the disclosure ────────────────────────────────────────
        layout.addSpacing(6)
        self.advanced_btn = QPushButton(i18n.t("Server settings"))
        self.advanced_btn.setObjectName("linkBtn")
        self.advanced_btn.setCheckable(True)
        self.advanced_btn.setCursor(Qt.PointingHandCursor)
        self.advanced_btn.setLayoutDirection(Qt.RightToLeft)
        self.advanced_btn.setToolTip(i18n.t(
            "Only needed if the check above cannot find your server"))
        icons.button_icon(self.advanced_btn, "chevron-right", 14,
                          theme.ACCENT_RAMP[700])
        # RightToLeft puts the chevron after the label, but it also mirrors
        # the alignment QBoxLayout would apply — passing AlignLeft pinned the
        # row to the right edge. The stretch does the aligning instead.
        adv_row = QHBoxLayout()
        adv_row.setContentsMargins(0, 0, 0, 0)
        adv_row.addWidget(self.advanced_btn)
        adv_row.addStretch(1)
        layout.addLayout(adv_row)

        self.advanced = QWidget()
        adv = QFormLayout(self.advanced)
        adv.setContentsMargins(0, 6, 0, 0)
        self.host = QLineEdit(self._accounts[0].get("host", ""))
        self.host.setPlaceholderText(i18n.t("found automatically — leave blank"))
        adv.addRow(i18n.t("Mail server:"), self.host)
        self.folder_name = QLineEdit(
            self._accounts[0].get("folder", "") or "INBOX")
        adv.addRow(i18n.t("Folder to read:"), self.folder_name)
        self.advanced.setVisible(False)
        layout.addWidget(self.advanced)

        def _toggle(open_: bool):
            icons.button_icon(self.advanced_btn,
                              "chevron-down" if open_ else "chevron-right",
                              14, theme.ACCENT_RAMP[700])
            self.advanced.setVisible(open_)
        self.advanced_btn.toggled.connect(_toggle)
        # Opened on arrival when a server was set by hand, so a setting that
        # is in force is never hidden from the person who set it.
        if self._accounts[0].get("host"):
            self.advanced_btn.setChecked(True)

        layout.addStretch(1)
        self._set_test_state("")
        self._loading = False
        self._refresh_mailboxes()
        return page

    # ── the mailbox list ──────────────────────────────────────────────────
    def _refresh_mailboxes(self):
        """Redraw the list to match the working copies, without re-entering
        the selection handler on the way past."""
        self._loading = True
        self.mailboxes.clear()
        for account in self._accounts:
            address = account.get("address", "").strip()
            host = account.get("host", "").strip()
            label = (f"{address}   ·   {host}" if address and host
                     else address or i18n.t("(new mailbox — type the address "
                                            "below)"))
            self.mailboxes.addItem(QListWidgetItem(label))
        self.mailboxes.setCurrentRow(self._current)
        # A list of one, above a form asking for that same one, reads as two
        # steps where there is only one thing to do.
        several = len(self._accounts) > 1
        self.mailboxes.setVisible(several)
        self.remove_mailbox_btn.setVisible(several)
        self._loading = False

    def _commit_form(self):
        """Fold whatever is typed into the mailbox being edited.

        Lenient on purpose: an entry can sit half-filled while another is
        edited — Save is where completeness is checked, with the same message
        it has always shown. The bookmark (`state`) is never touched here, so
        editing an address cannot cost the account its place in the mailbox;
        a genuinely different mailbox behind the same entry is caught by the
        server's own UIDVALIDITY and starts over safely.
        """
        account = self._accounts[self._current]
        account["address"] = self.addr.text().strip()
        password = self.password.text() or self._saved_password
        if password:
            account["password"] = password
        account["host"] = self.host.text().strip() or account.get("host", "")
        account["folder"] = self.folder_name.text().strip() or "INBOX"
        account.setdefault("port", 993)

    def _load_form(self, index: int):
        """Show one mailbox in the form. The password box is always cleared —
        a saved password is kept by leaving it blank, never displayed."""
        self._loading = True
        account = self._accounts[index]
        self._saved_password = account.get("password", "")
        self.addr.setText(account.get("address", ""))
        self.password.clear()
        self.password.setPlaceholderText(i18n.t(
            "leave blank to keep the saved password") if self._saved_password
            else i18n.t("your mail password"))
        self.host.setText(account.get("host", ""))
        self.folder_name.setText(account.get("folder", "") or "INBOX")
        self._tested_ok = False
        self._set_test_state("")
        if account.get("host"):
            self.advanced_btn.setChecked(True)
        self._loading = False

    def _mailbox_picked(self, row: int):
        if self._loading or row < 0 or row == self._current:
            return
        self._commit_form()
        self._current = row
        self._load_form(row)
        self._refresh_mailboxes()

    def _add_mailbox(self):
        self._commit_form()
        current = self._accounts[self._current]
        if not current.get("address"):
            # Two blank entries help nobody — finish this one first.
            self.addr.setFocus()
            self._set_test_state(i18n.t(
                "Type this mailbox's address first, then add the next one."))
            return
        self._accounts.append({})
        self._current = len(self._accounts) - 1
        self._load_form(self._current)
        self._refresh_mailboxes()
        self.addr.setFocus()

    def _remove_mailbox(self):
        account = self._accounts[self._current]
        address = account.get("address", "").strip()
        if address:
            answer = QMessageBox.question(
                self, i18n.t("Email automation"),
                i18n.t("Stop reading {who}?\n\nPrism simply stops checking "
                       "that mailbox. Nothing already in the register is "
                       "touched.").replace("{who}", address),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
        if len(self._accounts) == 1:
            self._accounts[0] = {}
        else:
            self._accounts.pop(self._current)
            self._current = max(0, self._current - 1)
        self._load_form(self._current)
        self._refresh_mailboxes()

    # ── the connection check ──────────────────────────────────────────────
    def _mail_input_changed(self):
        """Editing the address or password invalidates the last result. A
        green "Connected" left standing over changed details is a lie, and
        it is the one the customer would rely on."""
        if getattr(self, "_tested_ok", False):
            self._tested_ok = False
            self._set_test_state("")

    def _set_test_state(self, text: str, tone: str = ""):
        """One place that paints the result, so success and failure cannot
        drift into looking alike."""
        colour = {"ok": theme.OK_INK, "err": theme.ERR,
                  "busy": theme.NEUTRAL[600]}.get(tone, theme.NEUTRAL[600])
        self.test_result.setText(text)
        self.test_result.setStyleSheet(
            f"color: {colour}; font-size: 12.5px;"
            f"{' font-weight: 600;' if tone == 'ok' else ''}")

    def _test(self):
        address = self.addr.text().strip()
        password = self.password.text() or self._saved_password
        # The Mail server box was being ignored entirely: someone who already
        # knew their server could type it in, press this, and get "the mail
        # server didn't answer" about three hosts they never named.
        typed_host = self.host.text().strip()
        if not address or not password:
            self._set_test_state(
                i18n.t("Enter the address and password first."), "err")
            return
        self.test_btn.setEnabled(False)
        self._set_test_state(
            i18n.t("Testing {host}…").replace("{host}", typed_host)
            if typed_host else i18n.t("Checking your mailbox…"), "busy")

        def finished(settings: dict, error: str):
            self.test_btn.setEnabled(True)
            if error:
                self._tested_ok = False
                self._set_test_state(error, "err")
                # Detection genuinely could not place the server, so the box
                # for typing it stops being an advanced setting and becomes
                # the next thing to do. Opened rather than merely mentioned:
                # a disclosure nobody opens is a dead end.
                if not typed_host:
                    self.advanced_btn.setChecked(True)
                    self.host.setFocus()
                return
            self._tested_ok = True
            self.host.setText(settings.get("host", ""))
            self._accounts[self._current].update(settings)
            self._set_test_state(
                i18n.t("Connected to {host}. You can Save.").replace(
                    "{host}", settings.get("host", "")), "ok")

        self._verify = InboxVerifyWorker(address, password, typed_host)
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

        # The one thing this step actually requires, on its own. It used to sit
        # first in a flat list of five pickers, four of which are optional and
        # none of which said so — a client filled in all five or stopped.
        need, need_form = _group("The one folder Prism needs")
        self.work_folder = _Picker(saved.get("folder", "") or DEFAULT_FOLDER,
                                   directory=True)
        need_form.addRow(i18n.t("Keep everything in:"), self.work_folder)

        # The centralised half of the feature, said where the folder is
        # chosen: the register is one file, so putting the folder on the
        # shared drive IS the whole team seeing the same sheet. When a team
        # workspace is already set up, offer it in one click rather than a
        # sentence of directions.
        import workspace
        if workspace.is_shared(self.cfg):
            shared_row = QHBoxLayout()
            shared_note = QLabel(i18n.t(
                "Your team workspace is set up — keep this folder in it and "
                "every member sees the same register."))
            shared_note.setWordWrap(True)
            shared_note.setProperty("class", "muted")
            shared_row.addWidget(shared_note, stretch=1)
            use_shared = QPushButton(i18n.t("Use the team folder"))
            use_shared.clicked.connect(lambda: self.work_folder.edit.setText(
                os.path.join(workspace.company_dir(self.cfg), "inquiries")))
            shared_row.addWidget(use_shared)
            need_form.addRow(shared_row)
        else:
            shared_note = QLabel(i18n.t(
                "Several people? Choose a folder on your shared drive and "
                "everyone opens the same register — the same sheet you keep "
                "by hand today, kept by Prism instead."))
            shared_note.setWordWrap(True)
            shared_note.setProperty("class", "muted")
            need_form.addRow(shared_note)
        layout.addWidget(need)

        # Everything below is for QUOTING. Reading the inbox and building the
        # register works with none of it, and saying so is what lets somebody
        # finish setup today and add their price list next week.
        later, later_form = _group("For quoting — add these when you're ready")
        self.rate_file = _Picker(
            saved.get("rate_list", ""),
            filters=i18n.t("Price lists (*.csv *.xlsx *.xlsm);;All files (*)"),
            placeholder=i18n.t("your price list — needed only for quoting"))
        later_form.addRow(i18n.t("Rate list:"), self.rate_file)

        self.cost_file = _Picker(
            saved.get("cost_sheet", ""),
            filters=i18n.t("Cost sheets (*.csv *.xlsx *.xlsm);;All files (*)"),
            placeholder=i18n.t("optional — your formulas, for made-to-drawing work"))
        later_form.addRow(i18n.t("Cost sheet:"), self.cost_file)

        # How far the owner will bend, in their own words. Only ever read when
        # they press "Win this back", and the negotiation prompt refuses to
        # offer anything at all when it is missing — the safe direction to
        # fail in is "no discount", not "some discount".
        self.policy_file = _Picker(
            saved.get("pricing_policy", ""),
            filters=i18n.t("Any document (*.pdf *.docx *.txt *.csv *.xlsx);;"
                           "All files (*)"),
            placeholder=i18n.t("optional — how much you can bargain"))
        later_form.addRow(i18n.t("Bargaining limits:"), self.policy_file)
        layout.addWidget(later)

        # The long format explainers, folded away. They are worth having —
        # "cost sheet" means a different document in every factory — but
        # printed permanently they pushed the fields off the bottom.
        layout.addWidget(_Disclosure(
            "What should a rate list look like?",
            "A rate list needs a heading row with at least a description and "
            "a rate — for example: Code, Description, Unit, Rate. A "
            "letterhead above it is fine. Columns like \"Rate @ 1000\" are "
            "read as quantity discounts."))
        layout.addWidget(_Disclosure(
            "What should a cost sheet look like?",
            "A cost sheet is your own working, three columns wide: the name "
            "of the charge, how it is charged, and the rate. Prism does the "
            "arithmetic and shows every line — it never invents a rate.\n\n"
            "    Wire,          per_kg,     95\n"
            "    Coiling,       per_piece,  1.20\n"
            "    Tool setting,  per_lot,    800\n"
            "    Overheads,     percent,    12\n\n"
            "Percentages apply to the total of the lines above them, so the "
            "order of your rows is the order of your own calculation."))

        # A shop that has been trading for twenty years already keeps an
        # inquiry list. Starting them at row one would mean running two
        # registers side by side until they gave up on ours.
        already, already_form = _group("Already keep a list?")
        self.existing_register = _Picker(
            "", filters=i18n.t("Registers (*.csv);;All files (*)"),
            placeholder=i18n.t("optional — the list you already keep"))
        already_form.addRow(i18n.t("Import it once:"), self.existing_register)
        self.import_note = QLabel("")
        self.import_note.setWordWrap(True)
        self.import_note.setProperty("class", "muted")
        already_form.addRow(self.import_note)
        layout.addWidget(already)

        layout.addStretch(1)
        return page

    # ── 3. terms that go on every quotation ───────────────────────────────
    def _terms_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        saved = settings_of(self.cfg)
        terms = saved.get("terms") or {}

        # Three unrelated things used to sit in one nine-row list: who you
        # are, what your quotation says, and how often Prism does things by
        # itself. Nothing said which was which, so all nine read as equally
        # consequential — and the two that change Prism's *behaviour* were the
        # least visible of the lot.
        head, head_form = _group("Who the quotation comes from")
        self.company = QLineEdit(saved.get("company", ""))
        self.company.setPlaceholderText(i18n.t("as it should appear on the quotation"))
        head_form.addRow(i18n.t("Company name:"), self.company)

        self.signature = QLineEdit(saved.get("signature", ""))
        self.signature.setPlaceholderText(i18n.t("who quotations are signed by"))
        head_form.addRow(i18n.t("Sign off as:"), self.signature)
        layout.addWidget(head)

        quote, quote_form = _group("What goes on every quotation")
        self.gst = QSpinBox()
        self.gst.setRange(0, 100)
        self.gst.setSuffix(" %")
        self.gst.setValue(int(terms.get("gst_percent", 18) or 0))
        quote_form.addRow(i18n.t("GST:"), self.gst)

        self.validity = QSpinBox()
        self.validity.setRange(1, 365)
        self.validity.setSuffix(i18n.t(" days"))
        self.validity.setValue(int(terms.get("validity_days", 15) or 15))
        quote_form.addRow(i18n.t("Quotation valid for:"), self.validity)

        self.payment = QLineEdit(terms.get("payment", "") or
                                 "100% against proforma invoice")
        quote_form.addRow(i18n.t("Payment terms:"), self.payment)

        self.delivery = QLineEdit(terms.get("delivery", "") or
                                  "2–3 weeks from receipt of confirmed order")
        quote_form.addRow(i18n.t("Delivery:"), self.delivery)
        layout.addWidget(quote)

        # The two settings that make Prism act on its own. Grouped and named
        # so that "it emailed my customer without asking" can never be a
        # surprise — it is set here, in a box that says so.
        chase, chase_form = _group("When Prism chases a quiet quotation")
        self.followup_days = QSpinBox()
        self.followup_days.setRange(1, 60)
        self.followup_days.setSuffix(i18n.t(" days"))
        self.followup_days.setValue(int(saved.get("followup_days", 2) or 2))
        chase_form.addRow(i18n.t("Chase after:"), self.followup_days)

        self.max_reminders = QSpinBox()
        self.max_reminders.setRange(1, 6)
        self.max_reminders.setSuffix(i18n.t(" times"))
        self.max_reminders.setValue(int(saved.get("max_reminders", 3) or 3))
        chase_form.addRow(i18n.t("Then stop after:"), self.max_reminders)

        self.auto_minutes = QSpinBox()
        self.auto_minutes.setRange(0, 240)
        self.auto_minutes.setSuffix(i18n.t(" minutes"))
        self.auto_minutes.setSpecialValueText(i18n.t("only when I ask"))
        self.auto_minutes.setValue(int(saved.get("auto_minutes", 0) or 0))
        chase_form.addRow(i18n.t("Check the inbox every:"), self.auto_minutes)
        layout.addWidget(chase)

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

        # Its own titled block. This decides whether any of the customer's
        # mail ever leaves their machine, which makes it the most consequential
        # control in the whole dialog — and it was a bare tickbox under three
        # text areas, reading like a preference about notifications.
        privacy = QGroupBox(i18n.t("Privacy"))
        privacy_box = QVBoxLayout(privacy)
        privacy_box.setContentsMargins(14, 8, 14, 12)
        privacy_box.setSpacing(6)
        self.local_only = QCheckBox(i18n.t(
            "Keep everything on this computer — never send any mail to an AI"))
        self.local_only.setChecked(bool(saved.get("local_only", False)))
        privacy_box.addWidget(self.local_only)

        explain = QLabel(i18n.t(
            "With this ticked, Prism sorts using only the rules above and "
            "anything it cannot place is listed for you to glance at. "
            "Nothing whatsoever leaves the machine. Untick it and only the "
            "few messages from senders Prism does not recognise are sent to "
            "be labelled."))
        explain.setWordWrap(True)
        explain.setProperty("class", "muted")
        privacy_box.addWidget(explain)
        layout.addWidget(privacy)
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
        self._commit_form()
        folder = self.work_folder.value()

        # Blank entries are scaffolding, not mistakes — somebody pressed "Add
        # another" and changed their mind. Dropped without comment.
        accounts = [dict(a) for a in self._accounts if a.get("address")]

        incomplete = next((a for a in accounts if not a.get("password")),
                          None)
        if not accounts or incomplete is not None:
            who = (incomplete or {}).get("address", "")
            QMessageBox.information(
                self, i18n.t("Email automation"),
                i18n.t("Prism needs the email address and password of every "
                       "mailbox to read. Nothing else can start without "
                       "them.") + (f"\n\n{who}" if who else ""))
            self.tabs.setCurrentIndex(0)
            return
        if not folder:
            QMessageBox.information(
                self, i18n.t("Email automation"),
                i18n.t("Choose a folder for the inquiry register and the "
                       "files that come with each inquiry."))
            self.tabs.setCurrentIndex(1)
            return
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as e:
            QMessageBox.warning(self, i18n.t("Email automation"), str(e))
            self.tabs.setCurrentIndex(1)
            return

        inbox = CB.get_inbox()
        for account in accounts:
            if not account.get("host"):
                # No Test run and no saved host — work it out now rather than
                # failing on the first check with a message about a server the
                # customer never typed.
                guesses = inbox.guess_hosts(account["address"])
                account["host"] = guesses[0] if guesses else ""
            account["port"] = int(account.get("port") or 993)
            account["folder"] = account.get("folder") or "INBOX"
            # Each mailbox keeps its own read bookmark. Two mailboxes sharing
            # one would skip or re-import each other's mail — see accounts_of.
            account["state"] = dict(account.get("state") or {})

        first = accounts[0]
        self.cfg["inquiry"] = {
            "accounts": accounts,
            # The single-mailbox keys, mirroring the first entry. Everything
            # that predates the list — including a Prism from before this
            # version reading the same config — keeps working; accounts_of()
            # prefers the list and never reads these when it is present.
            "account": {k: v for k, v in first.items() if k != "state"},
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
                          # Shared across every mailbox on purpose: a sender
                          # is the same sender whichever address they wrote
                          # to, and teaching Prism twice would be a chore.
                          "learned": ((settings_of(self.cfg).get("knowledge")
                                       or {}).get("learned") or {})},
            # The first mailbox's bookmark, mirrored — see "account" above.
            "state": dict(first.get("state") or {}),
        }
        CB.config.save(self.cfg)

        # Last, and after the config is safely written: an import that fails
        # must not also cost them the settings they just typed in.
        imported = self._import_register(folder)
        if imported:
            self.import_note.setText(imported)
            QMessageBox.information(self, i18n.t("Inquiry register"), imported)
        self.accept()
