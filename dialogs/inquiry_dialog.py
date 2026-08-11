"""Inquiry automation — the screen.

The three phases the customer described, in the order they happen and visibly
separated, because the difference between them is the difference between
software you leave running and software you supervise:

    READ      fetch, sort, file the drawings, write the register.
              Runs on its own. Nothing here can cost anybody money.

    ANSWER    price it, draft the covering mail, send it, read the reply,
              update the register. Prism prepares; a person presses Send.

    MAKE      the order is in — hand the drawing to BOQ and get the
              quantities out.

Only the first is automatic, and the tabs say so. Two of the steps in ANSWER
move money — a price going to a customer, and accepting a purchase order — and
those are the two places a human is required. Everything else runs unattended.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import date
from decimal import Decimal

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSplitter,
    QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout,
    QWidget,
)

import core_bridge as CB
import i18n
from dialogs.inquiry_setup_dialog import InquirySetupDialog, is_ready, settings_of
from workers import InboxCheckWorker, SendWorker

# What each sorted category is called on screen. The engine's keys are English
# identifiers; these are the words a customer reads.
CATEGORY_LABELS = {
    "inquiry": "Inquiry", "order": "Purchase order", "payment": "Payment",
    "promotion": "Promotion", "vendor": "Supplier", "internal": "Internal",
    "other": "Other", "unsorted": "Needs a look",
}

SOURCE_LABELS = {
    "rule": "sorted here, by a rule",
    "learned": "sorted here, you taught it",
    "ai": "sorted by Prism's brain",
    "none": "not sorted",
}


def open_in_file_manager(path: str) -> None:
    """Reveal a folder or file in Finder/Explorer.

    Worth having: the register and the inquiry folders are the product as far
    as the customer is concerned, and "where did it put it?" is the first
    question. A button beats a path they have to copy.
    """
    if not path or not os.path.exists(path):
        return
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif sys.platform.startswith("win"):
            os.startfile(path)             # noqa: S606  (Windows-only API)
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


class InquiryDialog(QDialog):

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.t("Inquiry automation"))
        self.resize(980, 700)
        self.cfg = dict(cfg)
        self._worker = None
        self._send_worker = None
        self._result = None
        self._sorted_mail = []
        self._register_rows = []

        root = QVBoxLayout(self)
        root.addLayout(self._header())

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._arrived_tab(), i18n.t("1 · What arrived"))
        self.tabs.addTab(self._register_tab(), i18n.t("2 · Inquiries"))
        self.tabs.addTab(self._followup_tab(), i18n.t("3 · Waiting on a reply"))
        root.addWidget(self.tabs, stretch=1)

        footer = QHBoxLayout()
        self.summary = QLabel("")
        self.summary.setProperty("class", "muted")
        footer.addWidget(self.summary, stretch=1)
        open_folder = QPushButton(i18n.t("Open the folder"))
        open_folder.clicked.connect(lambda: open_in_file_manager(self._root()))
        footer.addWidget(open_folder)
        open_register = QPushButton(i18n.t("Open the register"))
        open_register.clicked.connect(self._open_register)
        footer.addWidget(open_register)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        footer.addWidget(close)
        root.addLayout(footer)

        self._refresh_register()
        QTimer.singleShot(0, self._first_look)

    # ── chrome ────────────────────────────────────────────────────────────
    def _header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        title = QLabel(i18n.t("Read the inbox, register the inquiries"))
        title.setProperty("class", "h2")
        row.addWidget(title)
        row.addStretch(1)
        self.status = QLabel("")
        self.status.setProperty("class", "muted")
        row.addWidget(self.status)
        self.check_btn = QPushButton(i18n.t("Check my mail now"))
        self.check_btn.setProperty("class", "primary")
        self.check_btn.clicked.connect(self.check_now)
        row.addWidget(self.check_btn)
        setup = QPushButton(i18n.t("Setup"))
        setup.clicked.connect(self.open_setup)
        row.addWidget(setup)
        return row

    def _settings(self) -> dict:
        return settings_of(self.cfg)

    def _root(self) -> str:
        return self._settings().get("folder", "")

    def _paths(self):
        return CB.get_mailflow().Paths(self._root())

    # ── tab 1: what arrived ───────────────────────────────────────────────
    def _arrived_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        note = QLabel(i18n.t(
            "Everything that came in since the last check, and what Prism "
            "made of it. If something is in the wrong column, change it — "
            "Prism remembers that sender and never asks again."))
        note.setWordWrap(True)
        note.setProperty("class", "muted")
        layout.addWidget(note)

        self.arrived = QTableWidget(0, 4)
        self.arrived.setHorizontalHeaderLabels(
            [i18n.t("From"), i18n.t("Subject"), i18n.t("Sorted as"),
             i18n.t("Why")])
        self.arrived.verticalHeader().setVisible(False)
        self.arrived.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.arrived.setSelectionBehavior(QAbstractItemView.SelectRows)
        header = self.arrived.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        layout.addWidget(self.arrived, stretch=1)

        row = QHBoxLayout()
        row.addWidget(QLabel(i18n.t("This one is really a:")))
        self.recategorise = QComboBox()
        for key, label in CATEGORY_LABELS.items():
            if key != "unsorted":
                self.recategorise.addItem(i18n.t(label), key)
        row.addWidget(self.recategorise)
        fix = QPushButton(i18n.t("Correct it, and remember this sender"))
        fix.clicked.connect(self._correct)
        row.addWidget(fix)
        row.addStretch(1)
        layout.addLayout(row)
        return page

    # ── tab 2: the register ───────────────────────────────────────────────
    def _register_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self.register_table = QTableWidget(0, 6)
        self.register_table.setHorizontalHeaderLabels(
            [i18n.t("Inquiry no"), i18n.t("Date"), i18n.t("Customer"),
             i18n.t("What they want"), i18n.t("Status"), i18n.t("Value")])
        self.register_table.verticalHeader().setVisible(False)
        self.register_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.register_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        head = self.register_table.horizontalHeader()
        head.setSectionResizeMode(3, QHeaderView.Stretch)
        layout.addWidget(self.register_table, stretch=1)

        row = QHBoxLayout()
        quote = QPushButton(i18n.t("Prepare a quotation"))
        quote.setProperty("class", "primary")
        quote.clicked.connect(self._prepare_quotation)
        row.addWidget(quote)
        folder = QPushButton(i18n.t("Open this inquiry's folder"))
        folder.clicked.connect(self._open_inquiry_folder)
        row.addWidget(folder)
        boq = QPushButton(i18n.t("Make a BOQ from the drawing"))
        boq.clicked.connect(self._make_boq)
        row.addWidget(boq)
        lost = QPushButton(i18n.t("Mark as not converted"))
        lost.clicked.connect(self._mark_lost)
        row.addWidget(lost)
        row.addStretch(1)
        layout.addLayout(row)
        return page

    # ── tab 3: chasing ────────────────────────────────────────────────────
    def _followup_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        note = QLabel(i18n.t(
            "Quotations that have gone quiet. This is the money already "
            "earned and not yet collected on — the list nobody keeps."))
        note.setWordWrap(True)
        note.setProperty("class", "muted")
        layout.addWidget(note)
        self.followups = QListWidget()
        layout.addWidget(self.followups, stretch=1)
        return page

    # ── running a check ───────────────────────────────────────────────────
    def _first_look(self):
        if not is_ready(self.cfg):
            answer = QMessageBox.question(
                self, i18n.t("Inquiry automation"),
                i18n.t("This needs your mailbox set up first — it takes about "
                       "two minutes and only happens once.\n\nSet it up now?"),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if answer == QMessageBox.Yes:
                self.open_setup()
            return
        self.status.setText(i18n.t("Ready. Press Check my mail now."))

    def open_setup(self):
        dialog = InquirySetupDialog(self.cfg, self)
        if dialog.exec() == QDialog.Accepted:
            self.cfg = dialog.cfg
            self._refresh_register()
            self.status.setText(i18n.t("Saved. Press Check my mail now."))

    def check_now(self):
        if not is_ready(self.cfg):
            self._first_look()
            return
        settings = self._settings()
        engine_cfg = dict(self.cfg)
        # The engine's inbox module reads cfg["inbox"]; the GUI keeps its
        # account under cfg["inquiry"]["account"] so this feature's settings
        # travel together and cannot be half-configured by the Email add-on.
        engine_cfg["inbox"] = settings.get("account") or {}

        inbox = CB.get_inbox()
        triage = CB.get_triage()
        state = inbox.State.from_dict(settings.get("state"))
        knowledge = triage.Knowledge.from_dict(settings.get("knowledge"))

        self.check_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.status.setText(i18n.t("Reading your inbox…"))

        self._worker = InboxCheckWorker(
            engine_cfg, self._root(), state=state, knowledge=knowledge,
            local_only=bool(settings.get("local_only")),
            followup_days=int(settings.get("followup_days", 3) or 3))
        self._worker.done.connect(self._checked)
        self._worker.failed.connect(self._check_failed)
        self._worker.start()

    def _check_failed(self, message: str):
        self.check_btn.setEnabled(True)
        self.progress.setVisible(False)
        self.status.setText("")
        self._explain(message)

    def _explain(self, message: str):
        """Plain-English failure, through the same translator as the rest."""
        try:
            from dialogs.problem_dialog import show_problem
            show_problem(self, message)
        except Exception:
            QMessageBox.warning(self, i18n.t("Inquiry automation"), message)

    def _checked(self, result):
        self.check_btn.setEnabled(True)
        self.progress.setVisible(False)
        self._result = result

        if result.error:
            self.status.setText("")
            self._explain(result.error)
            # A locked register still leaves the bookmark alone, so the same
            # mail comes back next time. Nothing to save.
            if not result.fetched:
                return

        self._remember(result)
        self.status.setText(result.headline())
        self._fill_arrived(result)
        self._refresh_register()
        self.tabs.setCurrentIndex(0 if result.fetched else 1)

    def _remember(self, result):
        """Persist the bookmark and anything the sorter learned."""
        settings = self._settings()
        settings["state"] = result.state.to_dict()
        knowledge = settings.get("knowledge") or {}
        knowledge["learned"] = dict(result.knowledge.learned)
        settings["knowledge"] = knowledge
        self.cfg["inquiry"] = settings
        CB.config.save(self.cfg)

    def _fill_arrived(self, result):
        rows = list(getattr(result, "sorted_mail", None) or [])
        self.arrived.setRowCount(len(rows))
        for index, (message, verdict) in enumerate(rows):
            who = message.from_name or message.from_addr
            self.arrived.setItem(index, 0, QTableWidgetItem(who))
            self.arrived.setItem(index, 1, QTableWidgetItem(message.subject))
            label = i18n.t(CATEGORY_LABELS.get(verdict.category, verdict.category))
            self.arrived.setItem(index, 2, QTableWidgetItem(label))
            why = verdict.reason or i18n.t(SOURCE_LABELS.get(verdict.source, ""))
            self.arrived.setItem(index, 3, QTableWidgetItem(why))
            self.arrived.item(index, 0).setData(Qt.UserRole, message.from_addr)
        self._sorted_mail = rows

    def _correct(self):
        row = self.arrived.currentRow()
        if row < 0 or not getattr(self, "_sorted_mail", None):
            return
        address = self.arrived.item(row, 0).data(Qt.UserRole)
        category = self.recategorise.currentData()
        settings = self._settings()
        knowledge = settings.get("knowledge") or {}
        learned = dict(knowledge.get("learned") or {})
        learned[address] = category
        knowledge["learned"] = learned
        settings["knowledge"] = knowledge
        self.cfg["inquiry"] = settings
        CB.config.save(self.cfg)
        self.arrived.setItem(row, 2, QTableWidgetItem(
            i18n.t(CATEGORY_LABELS.get(category, category))))
        self.arrived.setItem(row, 3, QTableWidgetItem(
            i18n.t("sorted here, you taught it")))
        self.status.setText(
            i18n.t("Remembered. Mail from {who} will be sorted that way from "
                   "now on.").replace("{who}", address))

    # ── the register ──────────────────────────────────────────────────────
    def _rows(self) -> list[dict]:
        if not self._root():
            return []
        register = CB.get_register()
        try:
            return register.load(self._paths().register_csv)
        except Exception:
            return []

    def _refresh_register(self):
        register = CB.get_register()
        rows = self._rows()
        self._register_rows = rows
        self.register_table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            values = [row.get("Inquiry no", ""), row.get("Date received", ""),
                      row.get("Customer", "") or row.get("Email", ""),
                      row.get("Product asked", ""), row.get("Status", ""),
                      row.get("Order value") or row.get("Quotation value", "")]
            for column, value in enumerate(values):
                self.register_table.setItem(index, column,
                                            QTableWidgetItem(str(value)))

        self.followups.clear()
        due = register.awaiting_followup(
            rows, after_days=int(self._settings().get("followup_days", 3) or 3))
        for row in due:
            # The QUOTATION number leads. That is the document the customer is
            # sitting on and the one they will quote back on the phone; the
            # inquiry number is our filing reference and comes second.
            # "Reminders sent" is blank in a freshly quoted row, and a bare
            # "reminders sent" with no number in front of it reads as broken.
            sent = (row.get("Reminders sent") or "0").strip() or "0"
            chased = (i18n.t("not chased yet") if sent == "0" else
                      i18n.t("{n} reminder(s) sent").replace("{n}", sent))
            self.followups.addItem(QListWidgetItem(
                f"{row.get('Quotation no','') or i18n.t('(no quotation number)')}"
                f"  ·  {row.get('Customer','') or row.get('Email','')}"
                f"  ·  {i18n.t('quoted')} {row.get('Quotation date','')}"
                f"  ·  {chased}"
                f"  ·  {row.get('Inquiry no','')}"))
        if not due:
            self.followups.addItem(QListWidgetItem(
                i18n.t("Nothing is waiting — every quotation has been answered.")))

        if rows:
            summary = CB.get_mailflow().day_summary(self._paths())
            self.summary.setText(summary.replace("\n", "   ").replace("  ", " "))

    def _selected_row(self) -> dict | None:
        index = self.register_table.currentRow()
        rows = getattr(self, "_register_rows", [])
        if index < 0 or index >= len(rows):
            QMessageBox.information(
                self, i18n.t("Inquiry automation"),
                i18n.t("Pick an inquiry from the list first."))
            return None
        return rows[index]

    def _open_register(self):
        if not self._root():
            return
        path = self._paths().register_csv
        if os.path.exists(path):
            open_in_file_manager(path)
        else:
            open_in_file_manager(self._root())

    def _open_inquiry_folder(self):
        row = self._selected_row()
        if row:
            open_in_file_manager(row.get("Folder", "") or self._root())

    def _mark_lost(self):
        row = self._selected_row()
        if not row:
            return
        reason, ok = _ask_reason(self)
        if not ok:
            return
        register = CB.get_register()
        register.mark_lost(row, reason)
        try:
            register.save(self._register_rows, self._paths().register_csv)
        except Exception as e:
            self._explain(str(e))
            return
        self._refresh_register()

    def _make_boq(self):
        """Hand this inquiry's drawings to the BOQ add-on.

        The join the customer asked for: the drawing already arrived with the
        inquiry and is already filed, so making the quantities out of it should
        not involve finding the file again.
        """
        row = self._selected_row()
        if not row:
            return
        folder = row.get("Folder", "")
        drawings = []
        if folder and os.path.isdir(folder):
            for name in sorted(os.listdir(folder)):
                if name.lower().endswith((".dwg", ".dxf", ".pdf")):
                    drawings.append(os.path.join(folder, name))
        if not drawings:
            QMessageBox.information(
                self, i18n.t("BOQ"),
                i18n.t("There is no drawing filed against this inquiry. BOQ "
                       "also works from a written specification — open it from "
                       "the sidebar and describe the job instead."))
            return
        files = CB.get_files()
        attachments = []
        for path in drawings:
            try:
                attachments.append(files.attach(path))
            except Exception:
                continue
        from dialogs.boq_dialog import BoqDialog
        BoqDialog(self.cfg, attachments, self).exec()

    # ── preparing a quotation ─────────────────────────────────────────────
    def _prepare_quotation(self):
        row = self._selected_row()
        if not row:
            return
        settings = self._settings()
        rate_path = settings.get("rate_list", "")
        if not rate_path or not os.path.exists(rate_path):
            QMessageBox.information(
                self, i18n.t("Quotation"),
                i18n.t("Prism needs your rate list before it can price "
                       "anything. Add it under Setup → Files."))
            return
        quoting = CB.get_quoting()
        try:
            items = quoting.load_rates(rate_path)
        except Exception as e:
            self._explain(str(e))
            return
        dialog = QuotationDialog(self.cfg, row, items, self)
        if dialog.exec() == QDialog.Accepted:
            self._refresh_register()


def _ask_reason(parent) -> tuple[str, bool]:
    """Why the inquiry was lost. Four choices, because a free-text box gets
    left empty and three months later the report says nothing."""
    dialog = QDialog(parent)
    dialog.setWindowTitle(i18n.t("Not converted"))
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel(i18n.t("Why did this one not convert?")))
    picker = QComboBox()
    for reason in ("Rate too high", "Delivery time", "No reply",
                   "Went to a competitor", "Customer's project dropped"):
        picker.addItem(i18n.t(reason), reason)
    picker.setEditable(True)
    layout.addWidget(picker)
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    ok = dialog.exec() == QDialog.Accepted
    return picker.currentText().strip(), ok


class QuotationDialog(QDialog):
    """Price one inquiry, review it, and send it.

    The one screen in this feature where a person is genuinely required. Prism
    picks the rate-list row, does the arithmetic and writes the covering mail;
    what it will not do is put a price in front of a customer on its own.
    """

    def __init__(self, cfg: dict, row: dict, items: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.t("Prepare a quotation"))
        self.resize(760, 640)
        self.cfg, self.row, self.items = dict(cfg), row, items
        self.parent_dialog = parent
        self._send_worker = None
        self.quote = None

        quoting = CB.get_quoting()
        self.matches = quoting.match_item(row.get("Product asked", ""), items)

        layout = QVBoxLayout(self)
        asked = QLabel(i18n.t("They asked for: {what}").replace(
            "{what}", row.get("Product asked", "")[:120]))
        asked.setWordWrap(True)
        layout.addWidget(asked)

        form = QFormLayout()
        self.item_picker = QComboBox()
        for match in self.matches:
            self.item_picker.addItem(
                f"{match.item.label}   ·   ₹{quoting.indian_currency(match.item.rate)}"
                f"   ·   {match.reason}", match.item)
        for item in items:
            if all(item is not m.item for m in self.matches):
                self.item_picker.addItem(
                    f"{item.label}   ·   ₹{quoting.indian_currency(item.rate)}", item)
        form.addRow(i18n.t("Item:"), self.item_picker)

        self.quantity = QLineEdit(_quantity_of(row))
        form.addRow(i18n.t("Quantity:"), self.quantity)
        layout.addLayout(form)

        confident = quoting.is_confident(self.matches)
        verdict = QLabel(i18n.t(
            "Prism is confident about this match." if confident else
            "Two rows on your rate list are close — check the one Prism "
            "picked before this goes out."))
        verdict.setWordWrap(True)
        verdict.setProperty("class", "muted" if confident else "warning")
        layout.addWidget(verdict)

        recalc = QPushButton(i18n.t("Work out the price"))
        recalc.clicked.connect(self._recalculate)
        layout.addWidget(recalc)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setProperty("class", "mono")
        layout.addWidget(self.preview, stretch=1)

        layout.addWidget(QLabel(i18n.t("The email that carries it:")))
        self.subject = QLineEdit()
        layout.addWidget(self.subject)
        self.body = QTextEdit()
        self.body.setFixedHeight(130)
        layout.addWidget(self.body)

        row_buttons = QHBoxLayout()
        self.save_btn = QPushButton(i18n.t("Save without sending"))
        self.save_btn.clicked.connect(lambda: self._finish(send=False))
        row_buttons.addWidget(self.save_btn)
        row_buttons.addStretch(1)
        self.send_btn = QPushButton(i18n.t("Send it"))
        self.send_btn.setProperty("class", "primary")
        self.send_btn.clicked.connect(lambda: self._finish(send=True))
        row_buttons.addWidget(self.send_btn)
        cancel = QPushButton(i18n.t("Cancel"))
        cancel.clicked.connect(self.reject)
        row_buttons.addWidget(cancel)
        layout.addLayout(row_buttons)

        self._recalculate()

    def _recalculate(self):
        quoting = CB.get_quoting()
        settings = settings_of(self.cfg)
        terms_cfg = settings.get("terms") or {}
        item = self.item_picker.currentData()
        if item is None:
            return
        quantity = quoting.to_decimal(self.quantity.text()) or Decimal(1)

        terms = quoting.Terms(
            gst_percent=Decimal(str(terms_cfg.get("gst_percent", 18))),
            validity_days=int(terms_cfg.get("validity_days", 15) or 15),
            payment=terms_cfg.get("payment", "") or "",
            delivery=terms_cfg.get("delivery", "") or "")

        rows = getattr(self.parent_dialog, "_register_rows", []) or []
        self.quote = quoting.Quotation(
            number=quoting.next_quote_number(rows), date=date.today(),
            customer=self.row.get("Customer", "") or self.row.get("Email", ""),
            contact=self.row.get("Contact person", ""),
            email=self.row.get("Email", ""),
            inquiry_no=self.row.get("Inquiry no", ""),
            lines=[quoting.QuoteLine(item.description, quantity, item.unit,
                                     item.rate_for(quantity), item.hsn,
                                     basis="rate list")],
            terms=terms)
        self.preview.setPlainText(
            quoting.render_text(self.quote, settings.get("company", "")))
        if not self.subject.text().strip():
            self.subject.setText(
                f"{i18n.t('Quotation')} {self.quote.number} — "
                f"{item.description[:50]}")
        if not self.body.toPlainText().strip():
            self.body.setPlainText(_default_body(self.quote, settings))

    def _finish(self, *, send: bool):
        if self.quote is None:
            return
        quoting = CB.get_quoting()
        register = CB.get_register()
        parent = self.parent_dialog
        paths = parent._paths()

        folder = self.row.get("Folder", "") or paths.root
        try:
            os.makedirs(folder, exist_ok=True)
            written = quoting.write_csv(self.quote, os.path.join(
                folder, f"{self.quote.number.replace('/', '-')}.csv"))
        except Exception as e:
            parent._explain(str(e))
            return

        if send:
            address = self.row.get("Email", "")
            if not address:
                QMessageBox.information(
                    self, i18n.t("Quotation"),
                    i18n.t("This inquiry has no email address to reply to."))
                return
            if QMessageBox.question(
                    self, i18n.t("Send the quotation"),
                    i18n.t("Send this quotation to {who} for "
                           "₹{total}?").replace("{who}", address).replace(
                        "{total}", quoting.indian_currency(self.quote.total)),
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No) != QMessageBox.Yes:
                return
            if not CB.mailer.is_configured(self.cfg):
                QMessageBox.information(
                    self, i18n.t("Quotation"),
                    i18n.t("Sending needs your outgoing account set up — "
                           "open the Email add-on once and enter it. Reading "
                           "and sending are separate accounts on purpose."))
                return
            self.send_btn.setEnabled(False)
            self._send_worker = SendWorker(
                self.cfg, [{"email": address,
                            "name": self.row.get("Contact person", "")}],
                self.subject.text(), self.body.toPlainText(),
                [{"path": written, "name": os.path.basename(written),
                  "mime": "text/csv"}])
            self._send_worker.done.connect(
                lambda sent, failed: self._sent(sent, failed))
            self._send_worker.failed.connect(self._send_failed)
            self._send_worker.start()
            return

        self._record(register, paths, sent=False)
        self.accept()

    def _sent(self, sent: list, failed: list):
        self.send_btn.setEnabled(True)
        if failed:
            self.parent_dialog._explain(failed[0][1])
            return
        self._record(CB.get_register(), self.parent_dialog._paths(), sent=True)
        QMessageBox.information(
            self, i18n.t("Quotation"),
            i18n.t("Sent. The register now shows this inquiry as quoted, and "
                   "Prism will remind you if there is no reply."))
        self.accept()

    def _send_failed(self, message: str):
        self.send_btn.setEnabled(True)
        self.parent_dialog._explain(message)

    def _record(self, register, paths, *, sent: bool):
        register.mark_quoted(self.row, self.quote.number, self.quote.total)
        if not sent:
            # Saved but not sent is not "Quoted" — the customer has not seen a
            # price, so it must not go on the chase list.
            self.row["Status"] = register.NEW
            self.row["Notes"] = (self.row.get("Notes", "") + " " +
                                 i18n.t("quotation prepared, not sent")).strip()
        try:
            register.save(getattr(self.parent_dialog, "_register_rows", []),
                          paths.register_csv)
        except Exception as e:
            self.parent_dialog._explain(str(e))


def _quantity_of(row: dict) -> str:
    """The number out of "5000 nos", or 1 when they did not say."""
    import re
    match = re.search(r"[\d,]+", row.get("Quantity", "") or "")
    return match.group(0).replace(",", "") if match else "1"


def _default_body(quote, settings: dict) -> str:
    return i18n.t(
        "Dear Sir,\n\nThank you for your enquiry. Our quotation "
        "{number} is attached, valid for {days} days.\n\n"
        "Delivery: {delivery}\nPayment: {payment}\n\n"
        "Please let us know if you need anything clarified.\n\n"
        "Regards,\n{signature}"
    ).replace("{number}", quote.number).replace(
        "{days}", str(quote.terms.validity_days)).replace(
        "{delivery}", quote.terms.delivery).replace(
        "{payment}", quote.terms.payment).replace(
        "{signature}", settings.get("signature", "") or
        settings.get("company", ""))
