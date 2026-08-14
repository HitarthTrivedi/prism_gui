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
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout,
    QWidget,
)

import core_bridge as CB
import i18n
from dialogs.inquiry_setup_dialog import InquirySetupDialog, is_ready, settings_of
from workers import DraftWorker, InboxCheckWorker, SendWorker

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

# ── colour ───────────────────────────────────────────────────────────────────
# A tinted background and a dark ink for each category and each status, so a
# hundred-row register can be read at arm's length: green is money coming in,
# amber wants you, grey can wait.
#
# The colour is never the only signal. Every cell that is tinted also carries
# the word, because roughly one man in twelve cannot tell the red from the
# green — and because a register printed on the office laser comes out grey.
#
# Tints are pale on purpose (they sit under black text at a comfortable
# contrast) and the palette is warm/cool rather than red/green alone, so the
# two ends stay distinguishable to the commonest colour blindness.
CATEGORY_COLOURS = {
    "inquiry":   ("#dff3e4", "#14532d"),   # green — the reason they bought this
    "order":     ("#c9ebd6", "#0f3d22"),   # deeper green — money confirmed
    "payment":   ("#dbe9f7", "#17365d"),   # blue — accounts, not sales
    "vendor":    ("#fdeccd", "#6b4708"),   # amber — someone selling TO them
    "promotion": ("#ececee", "#5d5d60"),   # grey — noise
    "internal":  ("#ececee", "#5d5d60"),
    "other":     ("#ececee", "#5d5d60"),
    "unsorted":  ("#fde8d4", "#7c3a06"),   # warm — needs a human glance
}

STATUS_COLOURS = {
    "New":            ("#dbe9f7", "#17365d"),
    "Quoted":         ("#e2e5f5", "#2f3572"),
    "Following up":   ("#fdeccd", "#6b4708"),
    "Negotiating":    ("#fde8d4", "#7c3a06"),
    "Accepted":       ("#dff3e4", "#14532d"),
    "Converted":      ("#c9ebd6", "#0f3d22"),
    "Not converted":  ("#f5dcdc", "#7a1f1f"),
}

# What Prism made of a customer's reply, in the owner's words rather than the
# engine's identifiers.
INTENT_LABELS = {
    "accepted": "They accepted",
    "rejected": "They declined",
    "negotiating": "They want a better rate",
    "needs_info": "They asked a question",
    "unclear": "Prism can't tell — read it yourself",
}

INTENT_COLOURS = {
    "accepted":    ("#dff3e4", "#14532d"),
    "rejected":    ("#f5dcdc", "#7a1f1f"),
    "negotiating": ("#fde8d4", "#7c3a06"),
    "needs_info":  ("#fdeccd", "#6b4708"),
    "unclear":     ("#ececee", "#5d5d60"),
}


def paint(item: QTableWidgetItem, colours: dict, key: str) -> QTableWidgetItem:
    """Tint one cell from one of the tables above. Unknown keys stay plain.

    Returns the item so it reads as one line at the call site.
    """
    pair = colours.get((key or "").strip())
    if pair:
        item.setBackground(QColor(pair[0]))
        item.setForeground(QColor(pair[1]))
    return item


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
        self._draft_worker = None
        self._draft_row = None
        self._result = None
        self._sorted_mail = []
        self._register_rows = []
        self._replies = []
        self._followup_rows = []
        # True only for the duration of a timer-driven check. Reset the moment
        # that check ends, so a later failure the owner DID ask for still gets
        # a dialog rather than disappearing into the status line.
        self._quiet = False

        root = QVBoxLayout(self)
        root.addLayout(self._header())

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._arrived_tab(), i18n.t("1 · What arrived"))
        self.tabs.addTab(self._register_tab(), i18n.t("2 · Inquiries"))
        self.tabs.addTab(self._replies_tab(), i18n.t("3 · What they said back"))
        self.tabs.addTab(self._followup_tab(), i18n.t("4 · Waiting on a reply"))
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

        # Checking on a timer is what makes this "runs by itself" rather than
        # "a button somebody remembers". Started here rather than in the
        # constructor of the timer so a saved interval of 0 leaves it stopped.
        self._auto = QTimer(self)
        self._auto.timeout.connect(self._auto_check)
        self._apply_auto_interval()

        self._refresh_register()
        QTimer.singleShot(0, self._first_look)

    def closeEvent(self, event):
        """Wind up every worker before this dialog is destroyed.

        A QThread destroyed while still running aborts the whole process — Qt
        calls qFatal() from ~QThread. Reel and BOQ have guarded this since they
        were written; this screen did not, and it has more workers than either:
        a mailbox check, a send, and a browser draft that runs for minutes.

        The timer is stopped first. Otherwise it can fire while the waits are
        running and start a fresh check on a dialog that is closing.
        """
        self._auto.stop()
        for worker in (self._worker, self._send_worker, self._draft_worker):
            if worker is None:
                continue
            try:
                if not worker.isRunning():
                    continue
            except RuntimeError:
                continue        # already deleted; nothing to wait for
            stop = getattr(worker, "stop", None)
            if callable(stop):
                stop()
            # A browser draft sits in a Selenium poll that is seconds wide, so
            # a short wait would expire and terminate a thread that was about
            # to finish on its own.
            if not worker.wait(10_000):
                worker.terminate()
                worker.wait(1000)
        super().closeEvent(event)

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
        self.auto_box = QCheckBox(i18n.t("Keep checking"))
        self.auto_box.setToolTip(i18n.t(
            "Check the inbox by itself, on the interval set under Setup → "
            "Your terms. Reading costs nothing and sends nothing."))
        self.auto_box.toggled.connect(self._auto_toggled)
        row.addWidget(self.auto_box)
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

    # ── checking on its own ───────────────────────────────────────────────
    def _apply_auto_interval(self):
        """Start or stop the timer to match what is saved.

        Called on open and after every Setup, so changing the interval takes
        effect without reopening the screen.
        """
        minutes = int(self._settings().get("auto_minutes", 0) or 0)
        # Blocked so setting the checkbox from saved state does not re-enter
        # _auto_toggled and write the config back on the way past.
        self.auto_box.blockSignals(True)
        self.auto_box.setChecked(minutes > 0)
        self.auto_box.blockSignals(False)
        if minutes > 0 and is_ready(self.cfg):
            self._auto.start(minutes * 60_000)
        else:
            self._auto.stop()

    def _auto_toggled(self, on: bool):
        settings = self._settings()
        if on:
            # Turning it on without an interval saved has to mean something.
            # Ten minutes is the number in the engine's own docstring and is
            # far below any provider's idea of hammering an IMAP server.
            minutes = int(settings.get("auto_minutes", 0) or 0) or 10
        else:
            minutes = 0
        settings["auto_minutes"] = minutes
        self.cfg["inquiry"] = settings
        CB.config.save(self.cfg)
        self._apply_auto_interval()
        self.status.setText(
            i18n.t("Checking every {n} minutes.").replace("{n}", str(minutes))
            if minutes else i18n.t("Automatic checking is off."))

    def _auto_check(self):
        """A timer tick. Silent about everything a person did not ask for.

        Skipped outright while a check is already running or while a
        quotation is open on top: fetching underneath an open Send dialog
        would refresh the register out from under the row being priced.
        """
        if self._worker is not None and self._worker.isRunning():
            return
        if not is_ready(self.cfg):
            return
        if self.findChild(QuotationDialog) is not None:
            return
        self.check_now(quiet=True)

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
        edit = QPushButton(i18n.t("Edit this row"))
        edit.clicked.connect(self._edit_row)
        row.addWidget(edit)
        folder = QPushButton(i18n.t("Open this inquiry's folder"))
        folder.clicked.connect(self._open_inquiry_folder)
        row.addWidget(folder)
        boq = QPushButton(i18n.t("Make a BOQ from the drawing"))
        boq.clicked.connect(self._make_boq)
        row.addWidget(boq)
        win = QPushButton(i18n.t("Win this back"))
        win.setToolTip(i18n.t(
            "For a customer who said no, or wants a better rate. Prism writes "
            "the reply using the AI tools in your browser and your own "
            "bargaining limits — then shows it to you before anything is "
            "sent."))
        win.clicked.connect(self._win_back)
        row.addWidget(win)
        lost = QPushButton(i18n.t("Mark as not converted"))
        lost.clicked.connect(self._mark_lost)
        row.addWidget(lost)
        row.addStretch(1)
        layout.addLayout(row)
        return page

    # ── tab 3: what the customer said back ────────────────────────────────
    def _replies_tab(self) -> QWidget:
        """Replies on quotations already out, and what Prism made of them.

        Nothing here applies itself. Prism reading "we will go ahead" and
        silently marking the row Accepted would be a machine changing a sales
        record on the strength of a sentence it might have misread — so it
        proposes, shows the words it read it from, and the owner presses the
        button.
        """
        page = QWidget()
        layout = QVBoxLayout(page)
        note = QLabel(i18n.t(
            "Replies to quotations you have sent. Prism reads each one and "
            "says what it thinks the customer means — check it, then apply "
            "it to the register. Nothing changes until you press the button."))
        note.setWordWrap(True)
        note.setProperty("class", "muted")
        layout.addWidget(note)

        self.replies_table = QTableWidget(0, 5)
        self.replies_table.setHorizontalHeaderLabels(
            [i18n.t("Inquiry no"), i18n.t("Customer"), i18n.t("Subject"),
             i18n.t("Prism reads this as"), i18n.t("Register will say")])
        self.replies_table.verticalHeader().setVisible(False)
        self.replies_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.replies_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        head = self.replies_table.horizontalHeader()
        head.setSectionResizeMode(2, QHeaderView.Stretch)
        self.replies_table.currentCellChanged.connect(
            lambda *_: self._show_reply())
        layout.addWidget(self.replies_table, stretch=2)

        layout.addWidget(QLabel(i18n.t("What they actually wrote:")))
        self.reply_text = QPlainTextEdit()
        self.reply_text.setReadOnly(True)
        self.reply_text.setFixedHeight(120)
        layout.addWidget(self.reply_text)

        row = QHBoxLayout()
        row.addWidget(QLabel(i18n.t("Treat this reply as:")))
        self.intent_picker = QComboBox()
        for key, label in INTENT_LABELS.items():
            if key != "unclear":
                self.intent_picker.addItem(i18n.t(label), key)
        row.addWidget(self.intent_picker)
        apply_btn = QPushButton(i18n.t("Update the register"))
        apply_btn.setProperty("class", "primary")
        apply_btn.clicked.connect(self._apply_reply)
        row.addWidget(apply_btn)
        row.addStretch(1)
        layout.addLayout(row)
        return page

    def _fill_replies(self, result):
        rows = list(getattr(result, "replies", None) or [])
        register = CB.get_register()
        self._replies = rows
        self.replies_table.setRowCount(len(rows))
        for index, item in enumerate(rows):
            row = item.row or {}
            would = register.REPLY_STATUS.get(item.intent, "")
            cells = [row.get("Inquiry no", ""),
                     row.get("Customer", "") or row.get("Email", ""),
                     getattr(item.message, "subject", ""),
                     i18n.t(INTENT_LABELS.get(item.intent, item.intent)),
                     would or i18n.t("nothing — needs your eye")]
            for column, value in enumerate(cells):
                cell = QTableWidgetItem(str(value))
                if column == 3:
                    paint(cell, INTENT_COLOURS, item.intent)
                elif column == 4 and would:
                    paint(cell, STATUS_COLOURS, would)
                self.replies_table.setItem(index, column, cell)
        if rows:
            self.replies_table.setCurrentCell(0, 0)
        self._show_reply()

    def _selected_reply(self):
        index = self.replies_table.currentRow()
        rows = getattr(self, "_replies", [])
        return rows[index] if 0 <= index < len(rows) else None

    def _show_reply(self):
        item = self._selected_reply()
        if item is None:
            self.reply_text.setPlainText("")
            return
        message = item.message
        self.reply_text.setPlainText(
            message.snippet(1200) if hasattr(message, "snippet")
            else getattr(message, "body", ""))
        # Preselect what Prism thought, so agreeing with it is one click and
        # disagreeing is two. An unclear reply leaves the box where it is
        # rather than nominating a guess the owner might accept by reflex.
        position = self.intent_picker.findData(item.intent)
        if position >= 0:
            self.intent_picker.setCurrentIndex(position)

    def _apply_reply(self):
        item = self._selected_reply()
        if item is None:
            QMessageBox.information(
                self, i18n.t("Inquiry automation"),
                i18n.t("Pick a reply from the list first."))
            return
        intent = self.intent_picker.currentData()
        register = CB.get_register()
        # Work on the copy in the register we just loaded, not on the copy
        # carried by the worker's Item — saving writes self._register_rows,
        # and a change made to a detached dict would be written over.
        target = register.find(self._register_rows,
                               (item.row or {}).get("Inquiry no", ""))
        if target is None:
            QMessageBox.information(
                self, i18n.t("Inquiry automation"),
                i18n.t("That inquiry is no longer in the register."))
            return
        register.mark_reply(target, intent)
        try:
            register.save(self._register_rows, self._paths().register_csv)
        except Exception as e:
            self._explain(str(e))
            return
        self._refresh_register()
        self.status.setText(
            i18n.t("{no} is now {status}.")
            .replace("{no}", target.get("Inquiry no", ""))
            .replace("{status}", target.get("Status", "")))
        # Take it off the list — it has been dealt with, and leaving it there
        # invites applying the same reply twice.
        row_index = self.replies_table.currentRow()
        if row_index >= 0:
            self.replies_table.removeRow(row_index)
            self._replies.pop(row_index)
        self._show_reply()

    # ── tab 4: chasing ────────────────────────────────────────────────────
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

        row = QHBoxLayout()
        self.remind_btn = QPushButton(i18n.t("Send a reminder"))
        self.remind_btn.setProperty("class", "primary")
        self.remind_btn.clicked.connect(self._send_reminder)
        row.addWidget(self.remind_btn)
        row.addStretch(1)
        layout.addLayout(row)
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
            # A changed interval takes effect now rather than next time the
            # screen is opened — otherwise turning it on appears to do nothing.
            self._apply_auto_interval()
            self._refresh_register()
            self.status.setText(i18n.t("Saved. Press Check my mail now."))

    def check_now(self, quiet: bool = False):
        """Fetch and sort. `quiet` is a timer tick rather than a button press.

        The only difference a quiet run makes is that failures land in the
        status line instead of a dialog. Somebody running a factory should not
        have a modal appear over their work every ten minutes because the mail
        server had a bad afternoon.
        """
        if not is_ready(self.cfg):
            if not quiet:
                self._first_look()
            return
        self._quiet = quiet
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
            followup_days=int(settings.get("followup_days", 2) or 2),
            max_reminders=int(settings.get("max_reminders", 3) or 3))
        self._worker.done.connect(self._checked)
        self._worker.failed.connect(self._check_failed)
        self._worker.start()

    def _check_failed(self, message: str):
        self.check_btn.setEnabled(True)
        self.progress.setVisible(False)
        self.status.setText("")
        self._explain(message)
        self._quiet = False

    def _explain(self, message: str):
        """Plain-English failure, through the same translator as the rest."""
        if getattr(self, "_quiet", False):
            self.status.setText(message.split("\n")[0])
            return
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
                self._quiet = False
                return

        self._remember(result)
        self.status.setText(result.headline())
        self._fill_arrived(result)
        self._fill_replies(result)
        self._refresh_register()
        # Never move the tab out from under somebody on a timer tick. A screen
        # that rearranges itself every ten minutes while you are reading it is
        # the reason people switch automatic checking off.
        if not self._quiet:
            # A reply on a live quotation is the most perishable thing in the
            # run — somebody is waiting on an answer — so it wins the opening
            # tab over a new inquiry, which will still be there this afternoon.
            self.tabs.setCurrentIndex(
                2 if result.replies else (0 if result.fetched else 1))
        self._quiet = False
        # Last, and only after the register has been written: a reminder must
        # never go out to somebody whose reply arrived in this same check and
        # has not been filed yet.
        self._chase_automatically()

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
            self.arrived.setItem(index, 2, paint(
                QTableWidgetItem(label), CATEGORY_COLOURS, verdict.category))
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
        self.arrived.setItem(row, 2, paint(QTableWidgetItem(
            i18n.t(CATEGORY_LABELS.get(category, category))),
            CATEGORY_COLOURS, category))
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
            when = row.get("Date received", "")
            clock = row.get("Time received", "")
            values = [row.get("Inquiry no", ""),
                      f"{when} {clock}".strip(),
                      row.get("Customer", "") or row.get("Email", ""),
                      row.get("Product asked", ""), row.get("Status", ""),
                      row.get("Order value") or row.get("Quotation value", "")]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                if column == 4:
                    paint(cell, STATUS_COLOURS, str(value))
                self.register_table.setItem(index, column, cell)

        self.followups.clear()
        settings = self._settings()
        due = register.awaiting_followup(
            rows,
            after_days=int(settings.get("followup_days", 2) or 2),
            max_reminders=int(settings.get("max_reminders", 3) or 3))
        self._followup_rows = list(due)
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

    # ── chasing a quiet quotation ─────────────────────────────────────────
    def _send_reminder(self):
        """One polite nudge, shown before it goes.

        Deliberately one at a time and never on the timer. A reminder is Prism
        writing to somebody else's customer in their name, and a loop that
        chases the whole list unattended is one bad afternoon away from
        mailing the same buyer three times.
        """
        index = self.followups.currentRow()
        rows = getattr(self, "_followup_rows", [])
        if index < 0 or index >= len(rows):
            QMessageBox.information(
                self, i18n.t("Reminder"),
                i18n.t("Pick a quotation from the list first."))
            return
        row = rows[index]
        address = row.get("Email", "")
        if not address:
            QMessageBox.information(
                self, i18n.t("Reminder"),
                i18n.t("This inquiry has no email address to write to."))
            return
        if not CB.mailer.is_configured(self.cfg):
            QMessageBox.information(
                self, i18n.t("Reminder"),
                i18n.t("Sending needs your outgoing account set up — open the "
                       "Email add-on once and enter it."))
            return

        settings = self._settings()
        subject = (i18n.t("Reminder: our quotation {no}")
                   .replace("{no}", row.get("Quotation no", "")))
        body = (i18n.t(
            "Dear Sir,\n\nWe sent you our quotation {no} on {when} and have "
            "not yet heard back. Please let us know if you need anything "
            "clarified, or if the requirement has changed.\n\n"
            "Regards,\n{signature}")
            .replace("{no}", row.get("Quotation no", ""))
            .replace("{when}", row.get("Quotation date", ""))
            .replace("{signature}", settings.get("signature", "")
                     or settings.get("company", "")))

        draft = _ReminderDialog(subject, body, address, self)
        if draft.exec() != QDialog.Accepted:
            return

        self.remind_btn.setEnabled(False)
        self.status.setText(i18n.t("Sending the reminder…"))
        self._send_worker = SendWorker(
            self.cfg, [{"email": address,
                        "name": row.get("Contact person", "")}],
            draft.subject(), draft.body(), [])
        self._send_worker.done.connect(
            lambda sent, failed: self._reminder_sent(row, sent, failed))
        self._send_worker.failed.connect(self._reminder_failed)
        self._send_worker.start()

    def _reminder_sent(self, row: dict, sent: list, failed: list):
        self.remind_btn.setEnabled(True)
        self.status.setText("")
        if failed:
            self._explain(failed[0][1])
            return
        register = CB.get_register()
        # Count it against the row in the loaded register, not the copy the
        # list is holding, so the increment survives the save.
        target = register.find(self._register_rows,
                               row.get("Inquiry no", "")) or row
        register.note_reminder(target)
        try:
            register.save(self._register_rows, self._paths().register_csv)
        except Exception as e:
            self._explain(str(e))
            return
        self._refresh_register()
        self.status.setText(
            i18n.t("Reminder sent to {who}.").replace(
                "{who}", row.get("Email", "")))

    def _reminder_failed(self, message: str):
        self.remind_btn.setEnabled(True)
        self.status.setText("")
        self._explain(message)

    # ── chasing without being asked ───────────────────────────────────────
    def _chase_automatically(self):
        """Send the reminders that are due, one per check, unattended.

        Everything about this is deliberately conservative, because these are
        letters going out in somebody else's name to their own customers:

          · **One per check, never a batch.** Three reminders leaving in the
            same second, to three customers who talk to each other, reads as a
            machine. Spread over the day's checks, it reads as a person
            working through a list.
          · **The register is the schedule.** Who is due comes from Reminders
            sent and Last contact in the CSV — the same two columns the owner
            can see and edit. There is no second, hidden queue to get out of
            step with it.
          · **Counted only when the send succeeds**, or Prism gives up after
            three reminders that never left the building.
          · **Off unless they turned it on.**
        """
        settings = self._settings()
        if not settings.get("auto_followup"):
            return
        if self._send_worker is not None and self._send_worker.isRunning():
            return
        if not CB.mailer.is_configured(self.cfg):
            return
        due = [r for r in getattr(self, "_followup_rows", []) if r.get("Email")]
        if not due:
            return

        row = due[0]
        subject, body = self._reminder_words(row)
        self.status.setText(
            i18n.t("Sending a reminder to {who}…").replace(
                "{who}", row.get("Email", "")))
        self._send_worker = SendWorker(
            self.cfg, [{"email": row.get("Email", ""),
                        "name": row.get("Contact person", "")}],
            subject, body, [])
        self._send_worker.done.connect(
            lambda sent, failed: self._reminder_sent(row, sent, failed))
        self._send_worker.failed.connect(self._reminder_failed)
        self._send_worker.start()

    def _reminder_words(self, row: dict) -> tuple[str, str]:
        """Subject and body for the next reminder on this row.

        The attempt number changes the wording. Three identical nudges in six
        days is not persistence, it is a mail merge, and the customer can
        tell — so the first is a light touch and the third asks straight out
        whether to close the file.
        """
        settings = self._settings()
        try:
            sent = int(str(row.get("Reminders sent") or "0").strip() or 0)
        except ValueError:
            sent = 0
        attempt = sent + 1
        signature = settings.get("signature", "") or settings.get("company", "")
        subject = (i18n.t("Reminder: our quotation {no}")
                   .replace("{no}", row.get("Quotation no", "")))
        openers = {
            1: i18n.t("We sent you our quotation {no} on {when}. Just making "
                      "sure it reached you."),
            2: i18n.t("Following up on our quotation {no} of {when}. If any "
                      "part of it does not suit, we are glad to revise it."),
            3: i18n.t("This is our last note about quotation {no} of {when}. "
                      "Would you like us to keep this enquiry open, or close "
                      "it for now? Either is perfectly all right."),
        }
        opener = openers.get(attempt, openers[3])
        body = (i18n.t("Dear Sir,\n\n{opener}\n\nRegards,\n{signature}")
                .replace("{opener}", opener
                         .replace("{no}", row.get("Quotation no", ""))
                         .replace("{when}", row.get("Quotation date", "")))
                .replace("{signature}", signature))
        return subject, body

    # ── winning back a customer who said no ───────────────────────────────
    def _win_back(self):
        """Draft a reply to a decline or a haggle, using the browser tools.

        This one email is worth the wait. It has to know what was quoted, what
        they objected to, and exactly how far this owner will move — and it is
        read out loud by somebody before it goes. That is a completely
        different job from labelling an inbox, and it goes to the best writer
        available rather than the fastest one.
        """
        row = self._selected_row()
        if not row:
            return
        settings = self._settings()
        status = (row.get("Status") or "").strip()
        register = CB.get_register()
        if status not in (register.NOT_CONVERTED, register.NEGOTIATING,
                          register.QUOTED, register.FOLLOWING_UP):
            QMessageBox.information(
                self, i18n.t("Win this back"),
                i18n.t("There is nothing to win back yet — this one has not "
                       "been quoted and turned down."))
            return

        drafting = CB.get_drafting()
        ready, why = drafting.available(self.cfg)
        if not ready:
            self._explain(why)
            return

        policy_path = settings.get("pricing_policy", "")
        policy_text, policy_files = drafting.load_policy(policy_path)
        if not policy_text and not policy_files:
            if QMessageBox.question(
                    self, i18n.t("Win this back"),
                    i18n.t("You have not given Prism your bargaining limits, "
                           "so it will not offer any discount at all — it will "
                           "argue on quality, delivery and service only.\n\n"
                           "Add the file under Setup → Files to let it "
                           "negotiate on price. Carry on without it?"),
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes) != QMessageBox.Yes:
                return

        prompt = drafting.negotiation_prompt(
            quotation_text=self._quotation_text(row),
            customer_reply=self._last_reply_text(row),
            policy_text=policy_text,
            customer_name=row.get("Customer", "") or row.get("Email", ""),
            product=row.get("Product asked", ""),
            signature=settings.get("signature", "") or settings.get("company", ""),
            language=self.cfg.get("output_language", "") or "")

        self._draft_row = row
        self.progress.setVisible(True)
        self.status.setText(i18n.t(
            "Writing it in your browser — this takes a minute or two. Chrome "
            "will open by itself; leave it alone until it finishes."))
        self._draft_worker = DraftWorker(self.cfg, prompt, purpose="negotiate",
                                         attachments=policy_files)
        self._draft_worker.progress.connect(self.status.setText)
        self._draft_worker.done.connect(self._drafted)
        self._draft_worker.failed.connect(self._draft_failed)
        self._draft_worker.start()

    def _quotation_text(self, row: dict) -> str:
        """What we actually sent them, read back off the disk.

        The quotation CSV written at send time is the only record of the
        figures as the customer saw them; rebuilding it from today's rate list
        could quote them something different from what they are holding.
        """
        folder = row.get("Folder", "")
        number = (row.get("Quotation no", "") or "").replace("/", "-")
        if folder and number:
            path = os.path.join(folder, f"{number}.csv")
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8-sig") as f:
                        return f.read()[:6000]
                except OSError:
                    pass
        return (i18n.t("Quotation {no} dated {when}, value Rs.{value}")
                .replace("{no}", row.get("Quotation no", ""))
                .replace("{when}", row.get("Quotation date", ""))
                .replace("{value}", row.get("Quotation value", "")))

    def _last_reply_text(self, row: dict) -> str:
        """Their own words, from this check if we have them.

        Falls back to the reason recorded when the row was closed. Thin, but
        an honest "they said the rate was too high" beats inventing an
        objection for the tool to answer.
        """
        for item in getattr(self, "_replies", []):
            if (item.row or {}).get("Inquiry no") == row.get("Inquiry no"):
                message = item.message
                if hasattr(message, "snippet"):
                    return message.snippet(2000)
        reason = row.get("Reason if lost", "") or row.get("Notes", "")
        return reason or i18n.t("(they have not said why)")

    def _drafted(self, result):
        self.progress.setVisible(False)
        self.status.setText("")
        if result.error:
            self._explain(result.error)
            return
        if not result.ok:
            self._explain(i18n.t(
                "The AI tool did not answer. Its tab is still open in Chrome "
                "— the reply may have arrived after Prism stopped waiting."))
            return
        row = getattr(self, "_draft_row", None) or {}
        subject = (i18n.t("Regarding our quotation {no}")
                   .replace("{no}", row.get("Quotation no", "")))
        dialog = _ReminderDialog(subject, result.text, row.get("Email", ""),
                                 self, note=i18n.t(
                                     "Written by {agent}. Read it before it "
                                     "goes — it is your name on it.")
                                 .replace("{agent}", result.agent))
        if dialog.exec() != QDialog.Accepted:
            return
        if not CB.mailer.is_configured(self.cfg):
            QMessageBox.information(
                self, i18n.t("Win this back"),
                i18n.t("Sending needs your outgoing account set up — open the "
                       "Email add-on once and enter it."))
            return
        self._send_worker = SendWorker(
            self.cfg, [{"email": row.get("Email", ""),
                        "name": row.get("Contact person", "")}],
            dialog.subject(), dialog.body(), [])
        self._send_worker.done.connect(
            lambda sent, failed: self._winback_sent(row, sent, failed))
        self._send_worker.failed.connect(self._reminder_failed)
        self._send_worker.start()

    def _winback_sent(self, row: dict, sent: list, failed: list):
        if failed:
            self._explain(failed[0][1])
            return
        register = CB.get_register()
        target = register.find(self._register_rows,
                               row.get("Inquiry no", "")) or row
        # Reopened. A row we are actively arguing with is not a lost one, and
        # leaving it closed would drop it off every list Prism keeps.
        target["Status"] = register.NEGOTIATING
        target["Result"] = ""
        target["Last contact"] = date.today().strftime("%d-%m-%Y")
        try:
            register.save(self._register_rows, self._paths().register_csv)
        except Exception as e:
            self._explain(str(e))
            return
        self._refresh_register()
        self.status.setText(i18n.t("Sent. This inquiry is open again."))

    def _draft_failed(self, message: str):
        self.progress.setVisible(False)
        self.status.setText("")
        self._explain(message)

    # ── correcting the register by hand ───────────────────────────────────
    def _edit_row(self):
        """Let the owner fix what Prism got wrong, in Prism.

        They can always edit the CSV in Excel — it is their file. But an
        register that can only be corrected by closing the app, opening Excel
        and remembering to close it again is one they will stop correcting.
        """
        row = self._selected_row()
        if not row:
            return
        dialog = _EditRowDialog(row, self)
        if dialog.exec() != QDialog.Accepted:
            return
        row.update(dialog.changes())
        register = CB.get_register()
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
        quoting = CB.get_quoting()

        # Either source will do. A shop that sells from a catalogue has a rate
        # list; a shop that quotes made-to-drawing work has a cost sheet of
        # their own formulas; plenty have both and pick per job. Demanding the
        # rate list, as this once did, locked out the second kind entirely.
        rate_path = settings.get("rate_list", "")
        cost_path = settings.get("cost_sheet", "")
        items, cost_lines, problems = [], [], []

        if rate_path and os.path.exists(rate_path):
            try:
                items = quoting.load_rates(rate_path)
            except Exception as e:
                problems.append(str(e))
        if cost_path and os.path.exists(cost_path):
            try:
                cost_lines = quoting.load_cost_lines(cost_path)
            except Exception as e:
                problems.append(str(e))

        if not items and not cost_lines:
            self._explain("\n\n".join(problems) if problems else i18n.t(
                "Prism needs either your rate list or your cost sheet before "
                "it can price anything. Add one under Setup → Files."))
            return

        dialog = QuotationDialog(self.cfg, row, items, self,
                                 cost_lines=cost_lines)
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


class _ReminderDialog(QDialog):
    """The reminder, shown before it goes. Editable, because the right words
    for a customer of fifteen years are not the right words for a new one."""

    def __init__(self, subject: str, body: str, address: str, parent=None,
                 note: str = ""):
        super().__init__(parent)
        self.setWindowTitle(i18n.t("Send a reminder"))
        self.resize(560, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            i18n.t("To: {who}").replace("{who}", address)))
        if note:
            caption = QLabel(note)
            caption.setWordWrap(True)
            caption.setProperty("class", "muted")
            layout.addWidget(caption)
        self._subject = QLineEdit(subject)
        layout.addWidget(self._subject)
        self._body = QTextEdit(body)
        layout.addWidget(self._body, stretch=1)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        send = buttons.addButton(i18n.t("Send it"),
                                 QDialogButtonBox.AcceptRole)
        send.setProperty("class", "primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def subject(self) -> str:
        return self._subject.text().strip()

    def body(self) -> str:
        return self._body.toPlainText()


class _EditRowDialog(QDialog):
    """Correct one register row by hand.

    Only the fields a person can sensibly know better than Prism. The inquiry
    number, the quotation number and the dates are not here on purpose: those
    are the register's own bookkeeping, and letting them be retyped is how two
    rows end up sharing a number.
    """

    FIELDS = ("Customer", "Contact person", "Email", "Phone",
              "Product asked", "Quantity", "Notes")

    def __init__(self, row: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.t("Edit inquiry {no}").replace(
            "{no}", row.get("Inquiry no", "")))
        self.resize(520, 400)
        self._edits = {}

        layout = QVBoxLayout(self)
        form = QFormLayout()
        for field in self.FIELDS:
            edit = QLineEdit(str(row.get(field, "") or ""))
            self._edits[field] = edit
            form.addRow(i18n.t(field) + ":", edit)

        self._status = QComboBox()
        register = CB.get_register()
        for status in register.STATUSES:
            self._status.addItem(i18n.t(status), status)
        current = self._status.findData((row.get("Status") or "").strip())
        if current >= 0:
            self._status.setCurrentIndex(current)
        form.addRow(i18n.t("Status") + ":", self._status)
        layout.addLayout(form)

        note = QLabel(i18n.t(
            "Changing the status here does not send anything — it only "
            "corrects the record."))
        note.setWordWrap(True)
        note.setProperty("class", "muted")
        layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def changes(self) -> dict:
        out = {f: e.text().strip() for f, e in self._edits.items()}
        status = self._status.currentData()
        out["Status"] = status
        # Result is what the month-end summary counts, and a status set by
        # hand has to move it too — otherwise a row marked Converted here is
        # still counted as open, and the conversion figure quietly disagrees
        # with the list the owner is looking at.
        register = CB.get_register()
        if status in register.CLOSED_STATUSES:
            out["Result"] = status
        else:
            out["Result"] = ""
        return out


class QuotationDialog(QDialog):
    """Price one inquiry, review it, and send it.

    The one screen in this feature where a person is genuinely required. Prism
    picks the rate-list row, does the arithmetic and writes the covering mail;
    what it will not do is put a price in front of a customer on its own.
    """

    def __init__(self, cfg: dict, row: dict, items: list, parent=None, *,
                 cost_lines: list | None = None):
        super().__init__(parent)
        self.setWindowTitle(i18n.t("Prepare a quotation"))
        self.resize(760, 720)
        self.cfg, self.row, self.items = dict(cfg), row, items
        self.cost_lines = list(cost_lines or [])
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

        # Where the rate comes from. Shown even when only one source is
        # configured, so the printed quotation's "basis" line is never a
        # surprise — the owner picked it.
        self.source = QComboBox()
        if items:
            self.source.addItem(i18n.t("My rate list"), "rates")
        if self.cost_lines:
            self.source.addItem(i18n.t("My cost sheet (work it out)"), "cost")
        self.source.currentIndexChanged.connect(self._source_changed)
        form.addRow(i18n.t("Price from:"), self.source)

        self.item_picker = QComboBox()
        for match in self.matches:
            self.item_picker.addItem(
                f"{match.item.label}   ·   ₹{quoting.indian_currency(match.item.rate)}"
                f"   ·   {match.reason}", match.item)
        for item in items:
            if all(item is not m.item for m in self.matches):
                self.item_picker.addItem(
                    f"{item.label}   ·   ₹{quoting.indian_currency(item.rate)}", item)
        self.item_row_label = QLabel(i18n.t("Item:"))
        form.addRow(self.item_row_label, self.item_picker)

        # Only the cost-sheet route needs a weight: it is what the per-kg
        # lines multiply. Blank is not zero-by-accident — a cost sheet with a
        # material line and no weight would quote the labour alone, so the
        # recalculation refuses rather than under-quoting.
        self.description = QLineEdit(row.get("Product asked", "")[:120])
        self.weight = QLineEdit("")
        self.weight.setPlaceholderText(i18n.t("kg per piece — from the drawing"))
        self.desc_label = QLabel(i18n.t("Describe it:"))
        self.weight_label = QLabel(i18n.t("Weight each:"))
        form.addRow(self.desc_label, self.description)
        form.addRow(self.weight_label, self.weight)

        self.quantity = QLineEdit(_quantity_of(row))
        form.addRow(i18n.t("Quantity:"), self.quantity)
        layout.addLayout(form)

        confident = quoting.is_confident(self.matches)
        self.verdict = QLabel(i18n.t(
            "Prism is confident about this match." if confident else
            "Two rows on your rate list are close — check the one Prism "
            "picked before this goes out."))
        self.verdict.setWordWrap(True)
        self.verdict.setProperty("class", "muted" if confident else "warning")
        layout.addWidget(self.verdict)

        self.workings = QPlainTextEdit()
        self.workings.setReadOnly(True)
        self.workings.setFixedHeight(160)
        self.workings.setProperty("class", "mono")
        self.workings.setVisible(False)
        layout.addWidget(self.workings)

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

        self._source_changed()

    # ── which pricing route ───────────────────────────────────────────────
    def _mode(self) -> str:
        return self.source.currentData() or "rates"

    def _source_changed(self, *_):
        """Show only the boxes the chosen route actually uses."""
        cost = self._mode() == "cost"
        for widget in (self.item_picker, self.item_row_label):
            widget.setVisible(not cost)
        for widget in (self.description, self.weight,
                       self.desc_label, self.weight_label):
            widget.setVisible(cost)
        self.verdict.setVisible(not cost)
        self.workings.setVisible(cost)
        self._recalculate()

    def _recalculate(self):
        if self._mode() == "cost":
            self._recalculate_from_cost()
        else:
            self._recalculate_from_rates()

    def _finalise(self, line, description: str):
        """Everything the two routes share: number it, wrap it in the terms,
        render it, and fill the covering mail if it is still untouched."""
        quoting = CB.get_quoting()
        settings = settings_of(self.cfg)
        terms_cfg = settings.get("terms") or {}
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
            lines=[line], terms=terms)
        self.preview.setPlainText(
            quoting.render_text(self.quote, settings.get("company", "")))
        if not self.subject.text().strip():
            self.subject.setText(
                f"{i18n.t('Quotation')} {self.quote.number} — {description[:50]}")
        if not self.body.toPlainText().strip():
            self.body.setPlainText(_default_body(self.quote, settings))

    def _recalculate_from_rates(self):
        quoting = CB.get_quoting()
        item = self.item_picker.currentData()
        if item is None:
            return
        quantity = quoting.to_decimal(self.quantity.text()) or Decimal(1)
        self._finalise(
            quoting.QuoteLine(item.description, quantity, item.unit,
                              item.rate_for(quantity), item.hsn,
                              basis="rate list"),
            item.description)

    def _recalculate_from_cost(self):
        """Run the owner's own formulas and show every line of the working.

        The breakdown is on screen rather than folded into one number because
        this is the number they will be asked to justify on the phone, and a
        rate they cannot explain is a rate they will not send.
        """
        quoting = CB.get_quoting()
        quantity = quoting.to_decimal(self.quantity.text()) or Decimal(1)
        weight = quoting.to_decimal(self.weight.text())
        needs_weight = any(line.basis == quoting.PER_KG
                           for line in self.cost_lines)
        if needs_weight and weight <= 0:
            self.workings.setPlainText(i18n.t(
                "Your cost sheet charges for material by the kilogram, so "
                "Prism needs the weight of one piece before it can work "
                "anything out."))
            self.preview.setPlainText("")
            self.quote = None
            return

        breakdown = quoting.cost_sheet(self.cost_lines, weight_kg=weight,
                                       quantity=quantity)
        # The label is translated; the quantity is substituted into it. Passing
        # "For 5000" to i18n.t() would put one catalogue entry per quantity
        # anybody ever quotes, and none of them would ever be translated.
        for_all = i18n.t("For all {n}").replace("{n}", f"{quantity:,.0f}")
        # What the QUOTATION will total, which is the rounded rate multiplied
        # out — not the cost. Those two differ by the rounding, and the gap
        # grows with the quantity: at 5,000 pieces a rate rounded down by half
        # a paisa is ₹25 the owner never charged for. Showing only the cost
        # here would have them reading one number on screen and sending
        # another, which is the fastest way to lose their trust in the whole
        # calculation.
        charged = quoting.rupees(breakdown.per_piece * quantity)
        rows = [f"{name:<28} ₹{quoting.indian_currency(amount)}"
                for name, amount in breakdown.lines]
        rows += ["—" * 44,
                 f"{i18n.t('Costs you'):<28} ₹{quoting.indian_currency(breakdown.total)}",
                 f"{i18n.t('Per piece'):<28} ₹{quoting.indian_currency(breakdown.per_piece)}",
                 f"{for_all:<28} ₹{quoting.indian_currency(charged)}"]
        if charged != breakdown.total:
            difference = charged - breakdown.total
            rows.append(i18n.t(
                "The rate is rounded to the paisa, so the quotation comes to "
                "₹{gap} {direction} than the cost above.")
                .replace("{gap}", quoting.indian_currency(abs(difference)))
                .replace("{direction}", i18n.t("more") if difference > 0
                         else i18n.t("less")))
        self.workings.setPlainText("\n".join(rows))

        description = self.description.text().strip() or self.row.get(
            "Product asked", "")
        self._finalise(
            quoting.QuoteLine(description, quantity, "nos",
                              breakdown.per_piece, "", basis="cost sheet"),
            description)

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
