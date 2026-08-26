"""Email automation — the working screen.

The three phases the customer described, in the order they happen and visibly
separated, because the difference between them is the difference between
software you leave running and software you supervise:

    READ      fetch every mailbox, sort, file the drawings, write the one
              register. Runs on its own. Nothing here can cost anybody money.

    ANSWER    price it, draft the covering mail, send it, read the reply,
              update the register. Prism prepares; a person presses Send.

    MAKE      the order is in — put the PO against the quotation, accept it,
              hand the drawing to BOQ and get the quantities out.

Only the first is automatic, and the tabs say so. Two of the steps move
money — a price going to a customer, and accepting a purchase order — and
those are the two places a human is required. Everything else runs unattended.

Several mailboxes, one register: the check walks the configured accounts one
at a time — never in parallel, because every account's rows land in the same
CSV and two writers racing on one order book is how a row is lost — and each
account carries its own read bookmark. One dead mail server skips to the next
account; one locked register stops the walk, because the same lock would
refuse every account after it and none of their bookmarks have moved.
Several MACHINES writing one register is deliberately not built — the office
PC that stays on does the writing, everyone else reads. docs/DEFERRED.md has
the trigger that would change that.
"""
from __future__ import annotations

import csv
import os
import subprocess
import sys
from datetime import date, timedelta
from decimal import Decimal

from PySide6.QtCore import QDate, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDialog,
    QDialogButtonBox,
    QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QRadioButton, QSizePolicy, QStackedWidget, QTabBar,
    QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout,
    QWidget,
)

import core_bridge as CB
import i18n
import theme
from dialogs.base import PrismDialog
from dialogs.inquiry_setup_dialog import (
    InquirySetupDialog, accounts_of, is_ready, settings_of,
)
from widgets import controls as C
from workers import DraftWorker, InboxCheckWorker, POReadWorker, SendWorker

# What each sorted category is called on screen. The engine's keys are English
# identifiers; these are the words a customer reads.
CATEGORY_LABELS = {
    "inquiry": "Inquiry", "order": "Purchase order", "payment": "Payment",
    "promotion": "Promotion", "vendor": "Supplier", "internal": "Internal",
    "other": "Other", "unsorted": "Needs a look",
}

# The "Show:" date filter — shared by the register tab and the arrived-mail
# log. "week" and "older" split on the same boundary (today minus 6 days) so
# the two are exact complements of each other and nothing between them is
# silently dropped from either.
REGISTER_RANGES = [
    ("all", "All time"), ("today", "Today"), ("yesterday", "Yesterday"),
    ("week", "Last 7 days"), ("older", "Older than that"),
    ("custom", "Pick dates…"),
]


def _parse_iso(text: str) -> date | None:
    """A plain YYYY-MM-DD back into a date, or None for anything blank or
    unreadable — the worklist file's own dates, as opposed to the register's
    hand-typeable ones which go through register.parse_date() instead."""
    try:
        return date.fromisoformat((text or "").strip())
    except ValueError:
        return None


def _in_date_range(when: date | None, filter_key: str, today: date,
                   start: date | None = None, end: date | None = None) -> bool:
    """One rule, used everywhere a "Show:" filter reads a date — the
    register, and the arrived-mail log below it.

    An unreadable or missing date — a hand-typed register the owner edited,
    or an old worklist row from before a field existed — falls under "Older
    than that" rather than every bucket or none: it is shown somewhere,
    which a silent drop is not, and it is not claimed as today's when
    nobody can say that it is. "custom" is the owner's own from/to pair,
    both ends inclusive, which is how a person says "from the 1st to the
    15th".
    """
    if filter_key == "all":
        return True
    if filter_key == "custom":
        if when is None:
            return False
        if start is not None and end is not None and start > end:
            start, end = end, start
        return (start is None or when >= start) and (end is None or when <= end)
    if when is None:
        return filter_key == "older"
    if filter_key == "today":
        return when == today
    if filter_key == "yesterday":
        return when == today - timedelta(days=1)
    if filter_key == "week":
        return today - timedelta(days=6) <= when <= today
    if filter_key == "older":
        return when < today - timedelta(days=6)
    return True

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
# EVERY PAIR BELOW IS A theme.py TOKEN. It did not use to be: the three tables
# here carried sixteen hexes that matched nothing in the palette — three
# different "success greens", two ambers plus a third that was one digit off
# theme.WARN_INK, a blue and a red that duplicated the accent and error ramps
# without matching them, and the only purple in the application. Every one of
# them was invisible to the per-role accent rotation, which is a blunt string
# replace over eleven known hexes: in a manager's green profile the entire
# register stayed Prism blue and amber while the rest of the app moved, and the
# purple stayed purple in all eleven roles.
#
# The semantic tones (OK / WARN / ERR) sit outside the accent ramp on purpose
# and DO NOT rotate, which is exactly what this register needs: "Converted"
# has to stay green and "Not converted" has to stay red in every profile, or
# the one column the owner reads at a glance stops meaning anything. INFO is
# the accent's own mid step and does rotate, by design — it is used here only
# for "this is information", never for an outcome.
_OK = (theme.OK_BG, theme.OK_INK)              # money — won, confirmed
_WARN = (theme.WARN_BG, theme.WARN_INK)        # a person is needed here
_ERR = (theme.ERR_BG, theme.ERR_INK)           # lost
_INFO = (theme.INFO_BG, theme.INFO_INK)        # live, or informational
_NEUTRAL = (theme.NEUTRAL[200], theme.NEUTRAL[800])   # waiting, filed
_QUIET = (theme.NEUTRAL[100], theme.NEUTRAL[700])     # noise

CATEGORY_COLOURS = {
    "inquiry":   _OK,        # the reason they bought this
    "order":     _OK,        # money confirmed
    "payment":   _INFO,      # accounts, not sales
    # Amber is reserved for the one row that genuinely needs a human to look
    # at it. A supplier's mail is filed, not urgent.
    "vendor":    _NEUTRAL,   # someone selling TO them
    "promotion": _QUIET,     # noise
    "internal":  _QUIET,
    "other":     _QUIET,
    "unsorted":  _WARN,      # needs a human glance
}

# The sales pipeline, in order, coloured by whose move it is:
# arrived (live) -> quoted (theirs) -> chased (theirs) -> haggling (YOURS) ->
# won / lost.
STATUS_COLOURS = {
    "New":            _INFO,
    "Quoted":         _QUIET,
    "Following up":   _NEUTRAL,
    "Negotiating":    _WARN,
    "Accepted":       _OK,
    "Converted":      _OK,
    "Not converted":  _ERR,
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
    "accepted":    _OK,
    "rejected":    _ERR,
    "negotiating": _WARN,     # they want something from you
    "needs_info":  _INFO,     # they asked for information
    "unclear":     _NEUTRAL,
}


class _TableOrEmpty(QStackedWidget):
    """A table, or — while it has no rows — a centred empty state.

    All five tabs of this screen open empty and stay empty until a mail check
    runs, and an empty QTableWidget is a column header over several hundred
    pixels of blank white. That is the screen a customer meets the first time
    they open Email automation, and it says nothing about what will appear
    there or how to make it appear.

    Driven off the model's own signals rather than by editing the five places
    that fill these tables: `setRowCount()` emits rowsInserted / rowsRemoved,
    so the swap cannot fall out of step with the data the way a hand-placed
    call would.
    """

    def __init__(self, table, icon: str, title: str, body: str, parent=None):
        super().__init__(parent)
        self._table = table
        self.addWidget(table)
        self.empty = C.EmptyState(icon, title, body)
        self.addWidget(self.empty)
        model = table.model()
        for signal in (model.rowsInserted, model.rowsRemoved,
                       model.modelReset, model.layoutChanged):
            signal.connect(self._sync)
        self._sync()

    def _rows(self) -> int:
        return self._table.model().rowCount()

    def _sync(self, *_args):
        self.setCurrentIndex(0 if self._rows() else 1)


# ── the six tabs, in the order an inquiry lives ──────────────────────────────
# "To quote" first because "2 to quote" is the number the owner opens Prism
# for; the two "All …" tabs last because they are for looking things up, not
# for the day's work. The numbers in the labels are the reading order and
# are what the tests pin.
TABS = [
    ("to_quote", "1 · To quote"),
    ("waiting", "2 · No answer yet"),
    ("replies", "3 · They answered"),
    ("orders", "4 · Order came"),
    ("register", "5 · All inquiries"),
    ("arrived", "6 · All mail"),
]
TAB_INDEX = {key: index for index, (key, _label) in enumerate(TABS)}
# Tabs whose title carries a live count. The reference tabs do not: "All
# inquiries (312)" is not a number anybody acts on.
COUNTED_TABS = ("to_quote", "waiting", "replies", "orders")

DRAWING_EXTENSIONS = (".dwg", ".dxf", ".pdf")

# Every button the Selected-inquiry panel can show, in the words the owner
# reads. The key is what actions_for() returns; the variant is fixed per
# button because a button that is primary on one row and secondary on the
# next is a button nobody learns.
ROW_ACTIONS = [
    ("prepare", "Prepare a quotation", "primary"),
    ("remind", "Send a reminder", "primary"),
    ("win_back", "Write a reply to win them back", "primary"),
    ("record_po", "Record the PO by hand", "primary"),
    ("already_quoted", "Already quoted by phone", "secondary"),
    ("boq", "Count quantities from the drawing", "secondary"),
    ("phone", "They replied by phone…", "secondary"),
    ("lost", "Mark as lost", "secondary"),
    ("revise", "Send a revised quotation", "secondary"),
    ("edit", "Edit details", "tertiary"),
    ("folder", "Open this inquiry's folder", "tertiary"),
    ("delete", "Delete this inquiry", "destructive"),
]


def actions_for(status: str, tab: str = "register",
                has_drawing: bool = False) -> list[str]:
    """Which buttons a register row gets, by where it is in its life.

    The seven-button row this replaces showed every action for every row,
    all the time — "Win this back" on an inquiry nobody had quoted yet,
    "Prepare a quotation" on one already converted. A person who has never
    used a CRM reads that as "which of these am I meant to press?", and the
    honest answer for any one row is two or three of them. So: at most
    three boxed buttons, the first of them the one the row is waiting for,
    plus the two quiet links every row gets.

    Pure — no Qt — so the table below can be tested as a table.
    """
    register = CB.get_register()
    status = (status or "").strip()
    if status in ("", register.NEW):
        keys = (["prepare", "boq", "already_quoted"] if has_drawing
                else ["prepare", "already_quoted"])
    elif status in (register.QUOTED, register.FOLLOWING_UP):
        keys = ["remind", "phone", "lost"]
    elif status == register.NEGOTIATING:
        keys = ["win_back", "revise", "phone"]
    elif status == register.ACCEPTED:
        keys = ["record_po", "phone", "lost"]
    elif status == register.CONVERTED:
        keys = ["boq"] if has_drawing else []
    elif status == register.NOT_CONVERTED:
        keys = ["win_back"]
    else:
        keys = []
    # Every row can be edited, opened, and — the owner asked for this on
    # every row, not only new ones — deleted, with the "block this sender?"
    # question that follows. A newsletter that got itself registered is the
    # commonest reason, and it can be sitting at any status.
    return keys + ["edit", "folder", "delete"]


class _RoomyTabBar(QTabBar):
    """A tab bar that gives every title a few pixels more than Qt thinks it
    needs. Measured with the real stylesheet, Qt's own sizeHint came out
    two pixels short of the semi-bold text the stylesheet paints — enough
    to shave the last letter. Asking for the slack here, rather than
    hunting the exact padding arithmetic, is what makes it impossible to
    regress when the font or the stylesheet moves."""

    SLACK = 8

    def tabSizeHint(self, index: int):      # noqa: N802 — Qt's name
        hint = super().tabSizeHint(index)
        return QSize(hint.width() + self.SLACK, hint.height())


class _Tabs(QTabWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabBar(_RoomyTabBar(self))


class _StatusLine(QLabel):
    """The one-line message under the header. Hides itself when it has
    nothing to say, so an idle screen does not carry an empty band — and
    shows itself the moment it has, so "Checking demo@…" is never written
    into a label nobody can see."""

    def setText(self, text: str):          # noqa: N802 — Qt's name
        super().setText(text)
        self.setVisible(bool(text))


class _SelectedPanel(C.Card):
    """The card under every table: which row is picked, where it stands,
    and only the buttons that make sense for it.

    Buttons are built once and shown or hidden per row, never rebuilt — so
    `remind_btn`, `po_btn` and the rest stay stable objects the rest of the
    dialog (and the tests) can hold on to. The row of buttons is a
    FlowLayout: at any width the two quiet links wrap under the boxed
    buttons instead of being cut off at the edge, which is the failure the
    owner photographed.
    """

    def __init__(self, parent=None):
        super().__init__(stripe=True, parent=parent)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        col = self.body((theme.CARD_PAD, theme.SPACE_3,
                         theme.CARD_PAD, theme.SPACE_3), theme.SPACE_2)
        self.title = C.label("", level="CARD_TITLE", wrap=True)
        col.addWidget(self.title)
        self.info = C.label("", level="META", wrap=True)
        col.addWidget(self.info)
        # A slot a tab can put its own controls in — the reply text and the
        # "Prism thinks" row on the replies tab, the re-sort row on the mail
        # log. Hidden with the rest when nothing is selected.
        self.extra_host = QWidget()
        self.extra = QVBoxLayout(self.extra_host)
        self.extra.setContentsMargins(0, 0, 0, 0)
        self.extra.setSpacing(theme.SPACE_2)
        col.addWidget(self.extra_host)
        self._flow_host = QWidget()
        self.flow = C.FlowLayout(self._flow_host)
        col.addWidget(self._flow_host)
        self.buttons: dict[str, QPushButton] = {}
        self.clear()

    def add_action(self, key: str, text: str, variant: str = "secondary",
                   on_click=None) -> QPushButton:
        btn = C.button(i18n.t(text), variant, on_click=on_click)
        self.buttons[key] = btn
        self.flow.addWidget(btn)
        return btn

    def show_row(self, title: str, info: str, keys, extra: bool = False):
        self.title.setText(title)
        self.info.setText(info)
        self.info.setVisible(bool(info))
        keys = set(keys)
        for key, btn in self.buttons.items():
            btn.setVisible(key in keys)
        self._flow_host.setVisible(bool(keys))
        self.extra_host.setVisible(extra)

    def clear(self):
        self.show_row(i18n.t("Pick a row above."), "", ())


class _TabPage(QWidget):
    """One tab, always the same four parts top to bottom: a sentence saying
    what the list is and what to do; a toolbar (Show: range, search); the
    table, which is the ONLY thing that grows with the window; and the
    Selected-inquiry panel. Six tabs of the same shape is what lets somebody
    who learned one of them use the other five."""

    def __init__(self, sentence: str, table, icon: str, empty_title: str,
                 empty_body: str, *, ranges: bool = True, search: bool = True,
                 on_change=None, parent=None):
        super().__init__(parent)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, theme.SPACE_3, 0, 0)
        col.setSpacing(theme.ROW_GAP)

        self.sentence = C.label(i18n.t(sentence), level="SUPPORT", wrap=True)
        self.sentence.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        col.addWidget(self.sentence)

        self.toolbar = C.Toolbar()
        self.filter = None
        self.search = None
        self.date_from = None
        self.date_to = None
        if ranges:
            self.toolbar.add(QLabel(i18n.t("Show:")))
            self.filter = QComboBox()
            for value, label in REGISTER_RANGES:
                self.filter.addItem(i18n.t(label), value)
            self.filter.setMinimumHeight(C.MIN_TARGET)
            self.toolbar.add(self.filter)
            # The owner's own from/to pair — "from the 1st to the 15th" —
            # shown only once "Pick dates…" is chosen, so the four everyday
            # choices stay one click and the toolbar stays short.
            self._from_label = QLabel(i18n.t("from"))
            self.date_from = QDateEdit(QDate.currentDate().addDays(-30))
            self._to_label = QLabel(i18n.t("to"))
            self.date_to = QDateEdit(QDate.currentDate())
            for box in (self.date_from, self.date_to):
                box.setCalendarPopup(True)
                box.setDisplayFormat("dd-MM-yyyy")
                box.setMinimumHeight(C.MIN_TARGET)
                if on_change is not None:
                    box.dateChanged.connect(lambda *_: on_change())
            for widget in (self._from_label, self.date_from,
                           self._to_label, self.date_to):
                self.toolbar.add(widget)
                widget.setVisible(False)
            self.filter.currentIndexChanged.connect(self._range_picked)
            if on_change is not None:
                self.filter.currentIndexChanged.connect(lambda *_: on_change())
        if search:
            self.search = C.SearchField(
                i18n.t("Find a customer or inquiry number"))
            self.search.setMaximumWidth(320)
            if on_change is not None:
                self.search.changed.connect(lambda *_: on_change())
            self.toolbar.add(self.search)
        self.toolbar.add_stretch()
        col.addWidget(self.toolbar)

        self.table = table
        self.stack = _TableOrEmpty(table, icon, i18n.t(empty_title),
                                   i18n.t(empty_body))
        self.empty = self.stack.empty
        col.addWidget(self.stack, stretch=1)

        self.panel = _SelectedPanel()
        col.addWidget(self.panel)

    def add_tool(self, widget) -> QWidget:
        """A control on the right end of the toolbar."""
        return self.toolbar.add(widget)

    def _range_picked(self, *_):
        custom = self.range_key() == "custom"
        for widget in (self._from_label, self.date_from,
                       self._to_label, self.date_to):
            widget.setVisible(custom)

    def range_key(self) -> str:
        return (self.filter.currentData() if self.filter is not None
                else "all") or "all"

    def range_bounds(self) -> tuple[date | None, date | None]:
        if self.date_from is None or self.range_key() != "custom":
            return None, None
        return (self.date_from.date().toPython(),
                self.date_to.date().toPython())

    def in_range(self, when: date | None, today: date | None = None) -> bool:
        start, end = self.range_bounds()
        return _in_date_range(when, self.range_key(), today or date.today(),
                              start, end)

    def search_text(self) -> str:
        return (self.search.text() if self.search is not None else "").strip()


def _dmy(iso: str, short: bool = False) -> str:
    """A worklist date (YYYY-MM-DD) the way the register and the owner write
    one: DD-MM-YYYY, or DD-MM when several sit in one cell."""
    when = _parse_iso(iso)
    if when is None:
        return iso or ""
    return when.strftime("%d-%m" if short else "%d-%m-%Y")


def _rupees(value) -> str:
    """"42480.00" → "₹42,480.00"; blank stays blank. The register keeps bare
    digits so Excel reads the column as numbers; the screen is for people."""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        quoting = CB.get_quoting()
        return "₹" + quoting.indian_currency(quoting.to_decimal(text))
    except Exception:               # noqa: BLE001 — an odd cell is shown as typed
        return text


def _matches(text: str, *values) -> bool:
    """Case-insensitive "is this typed text anywhere in the row"."""
    if not text:
        return True
    haystack = " ".join(str(v or "") for v in values).lower()
    return text.lower() in haystack


class _RegisterOnlyItem:
    """A row on the orders tab that has no mail behind it — the customer
    said yes (Status Accepted) and the PO is coming by hand, by phone, or
    on paper. Same shape as _StoredItem for everything the tab reads, with
    an empty message so the "read the PO off the mail" path politely finds
    nothing to read."""

    def __init__(self, row: dict):
        self.message_id = ""
        self.row = row
        self.folder = row.get("Folder", "")
        self.files: list = []
        self.intent = ""
        self.note = i18n.t("Said yes — waiting for the PO")
        self.message = _StoredMessage({"from_addr": row.get("Email", ""),
                                       "subject": ""})

    @property
    def inquiry_no(self) -> str:
        return (self.row or {}).get("Inquiry no", "")


class _PhoneReplyDialog(PrismDialog):
    """"They replied by phone…" — the same four answers Prism would read
    out of a mail, picked by hand. In GIDC most answers come by phone, and
    without this the register could only move when the customer wrote."""

    CHOICES = ("accepted", "negotiating", "needs_info", "rejected")

    def __init__(self, row: dict, parent=None):
        super().__init__(
            i18n.t("They replied by phone"),
            i18n.t("What did they say? The register moves the same way it "
                   "would for a reply by mail."),
            icon="mic", parent=parent, closable=False)
        who = row.get("Customer", "") or row.get("Email", "")
        self.body.addWidget(C.label(
            f"{row.get('Inquiry no', '')} · {who}", level="CARD_TITLE",
            wrap=True))
        self._radios: list[tuple[str, QRadioButton]] = []
        for key in self.CHOICES:
            radio = QRadioButton(i18n.t(INTENT_LABELS[key]))
            radio.setMinimumHeight(C.MIN_TARGET)
            self._radios.append((key, radio))
            self.body.addWidget(radio)
        self._radios[0][1].setChecked(True)
        self.body.addWidget(QLabel(i18n.t("A note, if you want one:")))
        self._note = QLineEdit()
        self._note.setPlaceholderText(i18n.t(
            "e.g. wants delivery in two weeks, will confirm Monday"))
        self.body.addWidget(self._note)
        self.body.addStretch(1)
        self.footer.add_secondary(
            self.button(i18n.t("Cancel"), on_click=self.reject))
        self.footer.set_primary(
            self.button(i18n.t("Update the register"), "primary",
                        icon_name="check", on_click=self.accept))

    def intent(self) -> str:
        for key, radio in self._radios:
            if radio.isChecked():
                return key
        return self.CHOICES[0]

    def note(self) -> str:
        return self._note.text().strip()


def _warning_css() -> str:
    """The tinted "check this before you send it" note.

    There is no `#warning` rule in style.qss and there never was a `[class=…]`
    selector either, so every `setProperty("class", "warning")` in this file
    rendered as ordinary body text — including the one line telling an owner
    that two rows on their rate list matched and Prism might have picked the
    wrong price. That is the highest-consequence sentence in the whole feature
    and it was styled exactly like the paragraph above it.
    """
    return (f"color: {theme.WARN_INK}; background: {theme.WARN_BG};"
            f" border: 1px solid {theme.WARN};"
            f" border-radius: {theme.R_CONTROL}px;"
            f" padding: {theme.SPACE_2}px {theme.SPACE_3}px;")


def paint(item: QTableWidgetItem, colours: dict, key: str) -> QTableWidgetItem:
    """Tint one cell from one of the tables above. Unknown keys stay plain.

    Returns the item so it reads as one line at the call site.
    """
    pair = colours.get((key or "").strip())
    if pair:
        item.setBackground(QColor(pair[0]))
        item.setForeground(QColor(pair[1]))
    return item


# ── the worklist: what keeps arrived mail, replies and purchase orders on
#    screen after the check that found them has long since moved its
#    bookmark past them ────────────────────────────────────────────────────
def _iso_date(when) -> str:
    """A plain YYYY-MM-DD out of whatever a message's date carries, so the
    worklist file — and its "Show:" filter — can compare dates as strings
    without needing the original object back."""
    if when is None:
        return date.today().isoformat()
    try:
        return when.date().isoformat() if hasattr(when, "date") else when.isoformat()
    except (TypeError, ValueError):
        return date.today().isoformat()


def _arrived_entry(message, verdict) -> dict:
    """What one arrived-mail row needs to redraw itself from disk."""
    return {
        "message_id": message.message_id or "",
        "from_name": message.from_name,
        "from_addr": message.from_addr,
        "subject": message.subject,
        "date": _iso_date(message.date),
        "category": verdict.category,
        "reason": verdict.reason,
        "source": verdict.source,
    }


def _worklist_entry(item) -> dict:
    """What one reply or purchase-order Item needs to redraw itself, and to
    be acted on, after the live Message that a check built it from is gone —
    everything _show_reply() and _review_po() would otherwise have read off
    that Message, plus the paths to the files already saved on disk."""
    message = item.message
    return {
        "message_id": getattr(message, "message_id", "") or "",
        "inquiry_no": item.inquiry_no,
        "from_name": getattr(message, "from_name", ""),
        "from_addr": getattr(message, "from_addr", ""),
        "subject": getattr(message, "subject", ""),
        "body": (getattr(message, "body", "") or "")[:4000],
        "attachment_names": list(getattr(message, "attachment_names", None) or []),
        "date": _iso_date(getattr(message, "date", None)),
        "intent": item.intent,
        "note": item.note,
        "folder": item.folder,
        "files": list(item.files or []),
    }


class _StoredMessage:
    """Enough of core.inbox.Message to satisfy _show_reply(), _review_po()
    and _po_file() for a reply or order read back from the worklist file,
    where the real Message from the check that found it no longer exists."""

    def __init__(self, entry: dict):
        self.from_name = entry.get("from_name", "")
        self.from_addr = entry.get("from_addr", "")
        self.subject = entry.get("subject", "")
        self.body = entry.get("body", "")
        self.attachment_names = list(entry.get("attachment_names") or [])

    def snippet(self, limit: int = 1500) -> str:
        text = (self.body or "").strip()
        if len(text) > limit:
            text = text[:limit].rstrip() + " …"
        return f"Subject: {self.subject}\n\n{text}".strip()


class _StoredItem:
    """A reply or order Item, rebuilt from one worklist row rather than from
    a live check. Same shape as mailflow.Item for every attribute the
    working dialog reads — .row, .message, .folder, .files, .intent, .note,
    .inquiry_no, plus .message_id for resolving it — so nothing downstream
    has to know whether an item came from this check or from disk."""

    def __init__(self, entry: dict, row: dict | None):
        self.message_id = entry.get("message_id", "")
        self.row = row
        self._entry_inquiry_no = entry.get("inquiry_no", "")
        self.folder = entry.get("folder", "")
        self.files = list(entry.get("files") or [])
        self.intent = entry.get("intent", "")
        self.note = entry.get("note", "")
        self.message = _StoredMessage(entry)

    @property
    def inquiry_no(self) -> str:
        # The register's own copy when the row still exists there — the
        # freshest source, and the one every other status field comes from
        # — falling back to what was true at the moment this was persisted.
        return (self.row or {}).get("Inquiry no", "") or self._entry_inquiry_no


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


class InquiryDialog(PrismDialog):

    def __init__(self, cfg: dict, parent=None, tab: int = 0, *,
                 auto_check: bool = False):
        # No subtitle: the sentence at the top of each tab says what THAT
        # list is for, which is the only sentence the owner needs, and the
        # header band's 20px are worth more as table rows.
        super().__init__(i18n.t("Email automation"), "",
                         icon="inbox", parent=parent, closable=False)
        self.setWindowTitle(i18n.t("Email automation"))
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self._size_to_screen()
        self.cfg = dict(cfg)
        # The row the owner last picked, in ANY table — the one every
        # action button acts on. Always one of the dicts in _register_rows,
        # never a copy, so a change lands on the row register.save() writes.
        self._focus_row = None
        self._to_quote_rows: list[dict] = []
        self._waiting_rows: list[dict] = []
        self._pages: dict[str, _TabPage] = {}
        self._worker = None
        self._send_worker = None
        self._draft_worker = None
        self._po_worker = None
        self._draft_row = None
        self._result = None
        self._sorted_mail = []
        self._register_rows = []
        # What the table actually shows once the date filter is applied — the
        # same dict objects as _register_rows, never copies, so a mutation
        # through _selected_row() (which reads this list) still lands on the
        # row register.save() will actually write.
        self._visible_rows = []
        self._replies = []
        self._orders = []
        self._po_row = None
        self._po_item = None
        self._followup_rows = []
        # The walk across the configured mailboxes: the accounts still to
        # check, how far along it is, and every account's result so far.
        self._queue = []
        self._queue_pos = 0
        self._partial = []
        # True only for the duration of a timer-driven check. Reset the moment
        # that check ends, so a later failure the owner DID ask for still gets
        # a dialog rather than disappearing into the status line.
        self._quiet = False
        # Set when this dialog was opened by pressing "Check my mail now" on
        # the report screen behind it, rather than by clicking a row or
        # "Edit setup" — see _first_look(). Without this, that button opened
        # an otherwise-idle dialog and the owner had to find the second
        # button of the same name inside it before anything actually ran.
        self._auto_check_on_open = auto_check

        self._build_header_actions()

        self.body.setContentsMargins(theme.PAGE_PAD, theme.SPACE_3,
                                     theme.PAGE_PAD, theme.SPACE_3)
        self.body.setSpacing(theme.SPACE_3)

        # The message bar: what Prism is doing right now, in one line, with
        # the busy bar beside it. Used to be a label squeezed into the header
        # action row, where "Writing it in your browser — this takes a minute
        # or two…" pushed "Check my mail now" off the right edge.
        bar = QWidget()
        bar_row = QHBoxLayout(bar)
        bar_row.setContentsMargins(0, 0, 0, 0)
        bar_row.setSpacing(theme.SPACE_3)
        self.status = _StatusLine("")
        self.status.setObjectName("meta")
        self.status.setWordWrap(True)
        bar_row.addWidget(self.status, stretch=1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(140)
        self.progress.setVisible(False)
        bar_row.addWidget(self.progress)
        self.body.addWidget(bar)

        self.tabs = _Tabs()
        builders = {
            "to_quote": self._to_quote_tab, "waiting": self._followup_tab,
            "replies": self._replies_tab, "orders": self._orders_tab,
            "register": self._register_tab, "arrived": self._arrived_tab,
        }
        for key, label in TABS:
            page = builders[key]()
            self._pages[key] = page
            self.tabs.addTab(page, i18n.t(label))
        # Three things keep a title from ever being cut to "1 · What arriv…"
        # again: no equal-width splitting (each tab is as wide as its own
        # text), no eliding, and — the one that actually bit — the bar
        # MEASURING with the same font the stylesheet PAINTS with. QSS sets
        # QTabBar::tab to Barlow 13/600; the widget's own font was 14/400,
        # and a rect sized for regular text is too narrow for semi-bold.
        tab_bar = self.tabs.tabBar()
        tab_bar.setExpanding(False)
        tab_bar.setElideMode(Qt.ElideNone)
        tab_bar.setFont(theme.font("SUPPORT", 600))
        self.tabs.setUsesScrollButtons(True)
        self.tabs.currentChanged.connect(
            lambda index: self._sync_panel(TABS[index][0])
            if 0 <= index < len(TABS) else None)
        self.body.addWidget(self.tabs, stretch=1)

        self.footer.add_utility(self.button(
            i18n.t("Open the folder"), "secondary", icon_name="folder",
            small=True,
            on_click=lambda: open_in_file_manager(self._root())))
        self.footer.add_utility(self.button(
            i18n.t("Open the register file"), "secondary", icon_name="file",
            small=True, on_click=self._open_register))
        # Still a plain reject, exactly as the QDialogButtonBox was — the box
        # only ever carried one Close button, and it brought Qt's platform
        # icons with it (a GTK red ✕, the one place the desktop theme leaked
        # into this window).
        self.footer.add_secondary(self.button(
            i18n.t("Close"), "secondary", on_click=self.reject))

        # Checking on a timer is what makes this "runs by itself" rather than
        # "a button somebody remembers". Started here rather than in the
        # constructor of the timer so a saved interval of 0 leaves it stopped.
        # Rejected sign-ins are counted PER ADDRESS: one mailbox's dead
        # password must not stop the others being read — see _note_failure.
        self._auth_failures: dict[str, int] = {}
        self._auto = QTimer(self)
        self._auto.timeout.connect(self._auto_check)
        self._apply_auto_interval()

        self._refresh_register()
        # Draw the three worklist tabs from what is already on disk, before
        # any check has run this session — reopening the dialog tomorrow
        # must show the same pending replies and orders it showed today,
        # not a blank screen waiting for a fresh check to repopulate them.
        self._render_arrived()
        self._render_replies()
        self._render_orders()
        self.tabs.setCurrentIndex(max(0, min(int(tab or 0), len(TABS) - 1)))
        QTimer.singleShot(0, self._first_look)

    def _size_to_screen(self):
        """Open at most of the screen, never less than a size every tab is
        readable at. A 1366×768 laptop — ordinary kit in a drawing office —
        gets 1229×655, which is seven table rows on a text tab; the
        maximise button is there for the rest."""
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else QRect(0, 0, 1280, 800)
        self.setMinimumSize(960, 640)
        self.resize(max(960, min(1440, int(avail.width() * 0.9))),
                    max(640, min(900, int(avail.height() * 0.9))))

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
        # Stop the mailbox walk as well as the workers: a queue with accounts
        # left in it would otherwise start a fresh worker from the done-signal
        # of the one being waited on.
        self._queue = []
        for worker in (self._worker, self._send_worker, self._draft_worker,
                       self._po_worker):
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
    def _build_header_actions(self):
        """The controls that act on the whole screen, in the fixed band.

        `setProperty("class", "primary")` was the old way of asking for the
        solid accent button, and style.qss has never carried a single
        `[class=...]` selector — so the one button this screen exists for, and
        four others like it further down this file, all rendered as plain
        hairline boxes. They are real object names now, through
        `controls.button`, so a variant is picked by name rather than guessed.
        """
        # Three controls, no more: the status text that used to sit here
        # moved to the message bar under the header, because a long message
        # pushed the one primary button off the right edge.
        self.auto_box = QCheckBox(i18n.t("Check by itself"))
        self.auto_box.setMinimumHeight(C.MIN_TARGET)
        self.auto_box.setCursor(Qt.PointingHandCursor)
        self.auto_box.setToolTip(i18n.t(
            "Read the inbox on its own, every few minutes (set under Setup "
            "→ Your terms). Reading sends nothing."))
        self.auto_box.toggled.connect(self._auto_toggled)
        self.header.add_action(self.auto_box)

        setup = self.button(i18n.t("Setup"), "secondary", icon_name="sliders",
                            on_click=self.open_setup)
        self.header.add_action(setup)
        self.check_btn = self.button(i18n.t("Check my mail now"), "primary",
                                     icon_name="inbox",
                                     on_click=self.check_now)
        self.header.add_action(self.check_btn)
        # Hidden until a check is actually running — InboxCheckWorker has no
        # cooperative stop(), so a dead mail server used to leave the button
        # disabled and progress spinning with no way out short of closing the
        # whole dialog (which falls back to the same hard terminate() this
        # calls directly — see closeEvent).
        self.reset_btn = self.button(
            i18n.t("Reset"), "secondary", icon_name="x", small=True,
            on_click=self._reset_check,
            tooltip=i18n.t("Cancel a check that has stopped responding, so "
                           "you can try again."))
        self.reset_btn.setVisible(False)
        self.header.add_action(self.reset_btn)

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
        # Fetching underneath an open money dialog would refresh the register
        # out from under the row being priced — or accepted.
        if self.findChild(QuotationDialog) is not None:
            return
        if self.findChild(_POReviewDialog) is not None:
            return
        self.check_now(quiet=True)

    # ── tab 1: what arrived ───────────────────────────────────────────────
    # ── building the six tabs ─────────────────────────────────────────────
    @staticmethod
    def _make_table(headers: list[str], stretch: int,
                    fit=()) -> QTableWidget:
        """A plain grid, the same on every tab: one column takes the slack,
        the ones named in `fit` size to their text — so a date is never
        "02-08-20…" and an inquiry number is never "INQ/…"."""
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels([i18n.t(h) for h in headers])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        head = table.horizontalHeader()
        head.setSectionResizeMode(stretch, QHeaderView.Stretch)
        for column in fit:
            head.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        return table

    def _add_row_actions(self, panel: _SelectedPanel) -> _SelectedPanel:
        """Every button a register row can have, built once for this panel.
        Which of them show is actions_for()'s decision, per row."""
        handlers = {
            "prepare": self._prepare_quotation, "revise": self._prepare_quotation,
            "remind": self._send_reminder, "win_back": self._win_back,
            "record_po": self._record_po_by_hand,
            "already_quoted": self._mark_already_quoted,
            "boq": self._make_boq, "phone": self._phone_reply,
            "lost": self._mark_lost, "edit": self._edit_row,
            "folder": self._open_inquiry_folder, "delete": self._delete_inquiry,
        }
        for key, text, variant in ROW_ACTIONS:
            panel.add_action(key, text, variant, handlers[key])
        return panel

    # ── tab 6: all mail ───────────────────────────────────────────────────
    def _arrived_tab(self) -> QWidget:
        self.arrived = self._make_table(
            ["From", "Subject", "Sorted as", "Why", "Date"], stretch=1,
            fit=(0, 2, 3, 4))
        page = _TabPage(
            "Every mail Prism has read and how it sorted it. If one is in "
            "the wrong column, correct it here and Prism will remember that "
            "sender.",
            self.arrived, "inbox", "Nothing has come in yet",
            "Press Check my mail now. Everything that arrives is listed here "
            "and stays listed.", on_change=self._render_arrived)
        self.arrived_filter = page.filter
        row = QHBoxLayout()
        row.setSpacing(theme.SPACE_2)
        row.addWidget(QLabel(i18n.t("This one is really a:")))
        self.recategorise = QComboBox()
        self.recategorise.setMinimumHeight(C.MIN_TARGET)
        for key, label in CATEGORY_LABELS.items():
            if key != "unsorted":
                self.recategorise.addItem(i18n.t(label), key)
        row.addWidget(self.recategorise)
        row.addWidget(C.button(i18n.t("Correct it — remember this sender"),
                               "primary", icon_name="check",
                               on_click=self._correct))
        row.addStretch(1)
        page.panel.extra.addLayout(row)
        self.arrived.currentCellChanged.connect(
            lambda *_: self._sync_panel("arrived"))
        return page

    # ── tab 1: to quote ───────────────────────────────────────────────────
    def _to_quote_tab(self) -> QWidget:
        self.to_quote_table = self._make_table(
            ["Inquiry no", "Date", "Customer", "What they want", "Qty",
             "Status"], stretch=3, fit=(0, 1, 4, 5))
        page = _TabPage(
            "These inquiries have no quotation yet. Pick one, then press "
            "Prepare a quotation.",
            self.to_quote_table, "list", "Nothing to quote",
            "Every inquiry has a quotation. New ones appear here as soon as "
            "Prism reads them.", on_change=self._render_to_quote)
        self._add_row_actions(page.panel)
        self.to_quote_table.currentCellChanged.connect(
            lambda *_: self._sync_panel("to_quote"))
        return page

    # ── tab 5: every inquiry ──────────────────────────────────────────────
    def _register_tab(self) -> QWidget:
        self.register_table = self._make_table(
            ["Inquiry no", "Date", "Customer", "What they want", "Status",
             "Value"], stretch=3, fit=(0, 1, 4, 5))
        page = _TabPage(
            "Every inquiry Prism has written in the register, and where each "
            "one stands.",
            self.register_table, "list", "The register is empty",
            "Every inquiry Prism recognises is written here as one row — the "
            "number, the customer, and where it has got to.",
            on_change=self._render_register)
        self.register_filter = page.filter
        self.register_chips = C.FilterChips(
            [("all", i18n.t("All")), ("open", i18n.t("Open")),
             ("won", i18n.t("Won")), ("lost", i18n.t("Lost"))], current="all")
        self.register_chips.changed.connect(lambda *_: self._render_register())
        page.add_tool(self.register_chips)
        # The one rare thing on this screen, kept out of the daily tabs.
        import_btn = C.button(i18n.t("Bring in an old list (CSV)…"),
                              "secondary", small=True,
                              on_click=self._import_csv_into_register)
        import_btn.setToolTip(i18n.t(
            "For a list of inquiries you already kept before using Prism — "
            "added alongside what is already here. Nothing already in the "
            "register is touched, changed or duplicated."))
        page.add_tool(import_btn)
        self._add_row_actions(page.panel)
        self.register_table.currentCellChanged.connect(
            lambda *_: self._sync_panel("register"))
        return page

    # ── tab 3: they answered ──────────────────────────────────────────────
    def _replies_tab(self) -> QWidget:
        """Replies on quotations already out, and what Prism made of them.

        Nothing here applies itself. Prism reading "we will go ahead" and
        silently marking the row Accepted would be a machine changing a sales
        record on the strength of a sentence it might have misread — so it
        proposes, shows the words it read it from, and the owner presses the
        button.
        """
        self.replies_table = self._make_table(
            ["Inquiry no", "Customer", "Subject", "Prism thinks",
             "Register will say"], stretch=2, fit=(0, 3, 4))
        page = _TabPage(
            "The customer wrote back about a quotation. Read what they said, "
            "then tell Prism what it means.",
            self.replies_table, "mail", "No answers to read",
            "When a customer replies to a quotation, it is listed here with "
            "what Prism makes of it.", on_change=self._render_replies)

        panel = page.panel
        self.reply_sent_line = C.label("", level="META", wrap=True)
        panel.extra.addWidget(self.reply_sent_line)
        panel.extra.addWidget(C.label(i18n.t("What they wrote:"),
                                      level="LABEL"))
        self.reply_text = QPlainTextEdit()
        self.reply_text.setReadOnly(True)
        # Four to eight lines, from the font — never a fixed pixel height,
        # which is what squeezed the old tab into illegibility.
        line = self.reply_text.fontMetrics().lineSpacing()
        self.reply_text.setMinimumHeight(line * 4 + 2 * theme.SPACE_2)
        self.reply_text.setMaximumHeight(line * 8 + 2 * theme.SPACE_2)
        panel.extra.addWidget(self.reply_text)
        row = QHBoxLayout()
        row.setSpacing(theme.SPACE_2)
        row.addWidget(QLabel(i18n.t("Prism thinks:")))
        self.intent_picker = QComboBox()
        self.intent_picker.setMinimumHeight(C.MIN_TARGET)
        for key, label in INTENT_LABELS.items():
            if key != "unclear":
                self.intent_picker.addItem(i18n.t(label), key)
        row.addWidget(self.intent_picker)
        self.apply_btn = C.button(i18n.t("Update the register"), "primary",
                                  icon_name="check", on_click=self._apply_reply)
        row.addWidget(self.apply_btn)
        row.addStretch(1)
        panel.extra.addLayout(row)
        panel.add_action("win_back", "Write a reply to win them back",
                         "secondary", self._win_back)
        panel.add_action("folder", "Open this inquiry's folder", "tertiary",
                         self._open_inquiry_folder)
        self.replies_table.currentCellChanged.connect(
            lambda *_: self._sync_panel("replies"))
        return page

    def _fill_replies(self, result):
        """Bank whatever this check found into the worklist file, then draw
        the tab from THAT — never straight from `result`, which only ever
        holds what this one check happened to see. See _render_replies()."""
        entries = [_worklist_entry(item)
                  for item in list(getattr(result, "replies", None) or [])]
        folder = self._root()
        if folder and entries:
            CB.get_worklist().append(folder, "replies", entries)
        self._render_replies()

    def _render_replies(self):
        """Redraw from the worklist file, not from memory — a reply from
        two checks ago that nobody has applied yet is exactly as pending as
        one from thirty seconds ago, and both must still be here after the
        dialog is closed and reopened."""
        worklist = CB.get_worklist()
        register = CB.get_register()
        folder = self._root()
        data = worklist.load(folder) if folder else {"replies": []}
        items = [_StoredItem(entry, register.find(self._register_rows,
                                                   entry.get("inquiry_no", "")))
                for entry in worklist.pending(data, "replies")]
        page = self._pages.get("replies")
        text = page.search_text() if page else ""
        items = [item for item in items
                 if _matches(text, item.inquiry_no,
                             (item.row or {}).get("Customer", ""),
                             item.message.from_addr, item.message.subject)]
        self._replies = items
        self.replies_table.setRowCount(len(items))
        for index, item in enumerate(items):
            row = item.row or {}
            would = register.REPLY_STATUS.get(item.intent, "")
            cells = [row.get("Inquiry no", "") or item.inquiry_no,
                     row.get("Customer", "") or row.get("Email", "")
                     or item.message.from_addr,
                     item.message.subject,
                     i18n.t(INTENT_LABELS.get(item.intent, item.intent)),
                     would or i18n.t("nothing — needs your eye")]
            for column, value in enumerate(cells):
                cell = QTableWidgetItem(str(value))
                if column == 3:
                    paint(cell, INTENT_COLOURS, item.intent)
                elif column == 4 and would:
                    paint(cell, STATUS_COLOURS, would)
                self.replies_table.setItem(index, column, cell)
        if items:
            self.replies_table.setCurrentCell(0, 0)
        self._show_reply()
        self._refresh_counts()

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
                self, i18n.t("Email automation"),
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
                self, i18n.t("Email automation"),
                i18n.t("That inquiry is no longer in the register."))
            return
        register.mark_reply(target, intent)
        try:
            register.save(self._register_rows, self._paths().register_csv)
        except Exception as e:
            self._explain(str(e))
            return
        # Resolved in the worklist file, not just popped from the table — a
        # re-check must never bring an already-applied reply back onto this
        # list, which popping the in-memory row alone would not have
        # prevented once the dialog closed and reopened.
        if item.message_id:
            CB.get_worklist().resolve(self._root(), "replies", item.message_id)
        self._refresh_register()
        self.status.setText(
            i18n.t("{no} is now {status}.")
            .replace("{no}", target.get("Inquiry no", ""))
            .replace("{status}", target.get("Status", "")))
        self._render_replies()

    # ── tab 2: no answer yet ──────────────────────────────────────────────
    def _followup_tab(self) -> QWidget:
        self.followups = self._make_table(
            ["Quotation no", "Customer", "Quoted on", "Value", "Reminder",
             "Inquiry no"], stretch=1, fit=(0, 2, 3, 4, 5))
        page = _TabPage(
            "Quotations you sent that the customer has not answered yet.",
            self.followups, "clock", "Every quotation has been answered",
            "When you send a quotation it waits here until the customer "
            "replies.", on_change=self._render_waiting)
        self.followups_empty = page.empty
        self._add_row_actions(page.panel)
        self.remind_btn = page.panel.buttons["remind"]
        self.followups.currentCellChanged.connect(
            lambda *_: self._sync_panel("waiting"))
        return page

    # ── tab 4: the order came ─────────────────────────────────────────────
    def _orders_tab(self) -> QWidget:
        """Purchase orders, against the quotations they answer.

        The second of the two places money moves, and the last stop of the
        whole workflow: Prism reads the PO into fields, puts it next to the
        quotation that was actually sent, and points at every difference — a
        rate quietly reduced between quote and PO is the classic dispute, and
        this check costs two seconds now or an argument in three weeks.
        Accepting is a button a person presses; nothing here accepts itself.
        """
        self.orders_table = self._make_table(
            ["Inquiry no", "Customer", "Subject", "What Prism noticed"],
            stretch=2, fit=(0, 1, 3))
        page = _TabPage(
            "A purchase order arrived, or a customer said yes. Check it "
            "against your quotation, then record it.",
            self.orders_table, "archive", "No orders waiting",
            "A PO that arrives by mail is read here and checked against what "
            "you quoted.", on_change=self._render_orders)
        panel = page.panel
        self.po_btn = panel.add_action("po", "Read the PO and compare",
                                       "primary", self._review_po)
        panel.add_action("record_po", "Record the PO by hand", "primary",
                         self._record_po_by_hand)
        panel.add_action("phone", "They replied by phone…", "secondary",
                         self._phone_reply)
        panel.add_action("lost", "Mark as lost", "secondary", self._mark_lost)
        panel.add_action("remove_order", "Not an order — remove it",
                         "secondary", self._remove_order)
        panel.add_action("folder", "Open this inquiry's folder", "tertiary",
                         self._open_order_folder)
        self.orders_table.currentCellChanged.connect(
            lambda *_: self._sync_panel("orders"))
        return page

    def _fill_orders(self, result):
        """Bank whatever this check found into the worklist file, then draw
        the tab from THAT — see _fill_replies() for why."""
        entries = [_worklist_entry(item)
                  for item in list(getattr(result, "orders", None) or [])]
        folder = self._root()
        if folder and entries:
            CB.get_worklist().append(folder, "orders", entries)
        self._render_orders()

    def _render_orders(self):
        """Redraw from the worklist file. This is the tab a friend's PO
        went missing from the moment the mailbox's bookmark moved past it —
        an unaccepted order three checks old is still an unaccepted order."""
        worklist = CB.get_worklist()
        register = CB.get_register()
        folder = self._root()
        data = worklist.load(folder) if folder else {"orders": []}
        items = [_StoredItem(entry, register.find(self._register_rows,
                                                   entry.get("inquiry_no", "")))
                for entry in worklist.pending(data, "orders")]
        # Plus every row the customer said yes on and no PO has landed for —
        # it is coming by hand, by phone or on paper, and "Record the PO by
        # hand" is how it gets in. Without these the tab only ever showed
        # POs that happened to arrive by mail.
        covered = {item.inquiry_no for item in items}
        for row in self._register_rows:
            if ((row.get("Status") or "").strip() == register.ACCEPTED
                    and row.get("Inquiry no", "") not in covered):
                items.append(_RegisterOnlyItem(row))
        page = self._pages.get("orders")
        text = page.search_text() if page else ""
        items = [item for item in items
                 if _matches(text, item.inquiry_no,
                             (item.row or {}).get("Customer", ""),
                             item.message.from_addr, item.message.subject)]
        self._orders = items
        self.orders_table.setRowCount(len(items))
        for index, item in enumerate(items):
            row = item.row or {}
            cells = [row.get("Inquiry no", "") or item.inquiry_no,
                     row.get("Customer", "") or row.get("Email", "")
                     or item.message.from_addr,
                     item.message.subject,
                     i18n.t(item.note) if item.note else ""]
            for column, value in enumerate(cells):
                self.orders_table.setItem(index, column,
                                          QTableWidgetItem(str(value)))
        if items:
            self.orders_table.setCurrentCell(0, 0)
        self._refresh_counts()

    def _selected_order(self):
        index = self.orders_table.currentRow()
        rows = getattr(self, "_orders", [])
        return rows[index] if 0 <= index < len(rows) else None

    def _open_order_folder(self):
        item = self._selected_order()
        if item is not None:
            open_in_file_manager(item.folder
                                 or (item.row or {}).get("Folder", "")
                                 or self._root())

    def _po_file(self, item) -> str:
        """The file most likely to be the order, out of what the check filed.

        The engine's own name heuristic picks the attachment ("PO 4471.pdf"
        is not a guess); the saved copy is matched back by name because
        save_attachments de-collides filenames rather than overwriting. Two
        unnamed PDFs is genuinely ambiguous and returns nothing — the mail
        body, or the typed-in form, is the honest fallback.
        """
        po = CB.get_po()
        readable = (".pdf", ".docx", ".docm", ".txt", ".csv")
        candidates = [f for f in (item.files or [])
                      if f.lower().endswith(readable) and os.path.exists(f)]
        if not candidates and item.folder and os.path.isdir(item.folder):
            candidates = [os.path.join(item.folder, name)
                          for name in sorted(os.listdir(item.folder))
                          if name.lower().endswith((".pdf", ".docx", ".docm"))]
        wanted = po.find_attachment(item.message) if item.message else None
        if wanted:
            stem = os.path.splitext(wanted)[0].lower()
            for path in candidates:
                base = os.path.splitext(os.path.basename(path))[0].lower()
                if base == stem or base.startswith(stem) or stem.startswith(base):
                    return path
        return candidates[0] if len(candidates) == 1 else ""

    def _review_po(self):
        item = self._selected_order()
        if item is None:
            QMessageBox.information(
                self, i18n.t("Purchase order"),
                i18n.t("Pick an order from the list first."))
            return
        # Read again in _po_accepted() — the review dialog is modal, so the
        # selection cannot change underneath it, but the item itself (and
        # its message id, needed to resolve it in the worklist file) is not
        # otherwise threaded through _show_po()/_po_read().
        self._po_item = item
        register = CB.get_register()
        row = register.find(self._register_rows, item.inquiry_no) or item.row
        if not row:
            QMessageBox.information(
                self, i18n.t("Purchase order"),
                i18n.t("That inquiry is no longer in the register."))
            return

        settings = self._settings()
        po = CB.get_po()
        text, source, advice = "", "", ""
        path = self._po_file(item)
        if path:
            try:
                text = po.text_from(path)
                source = os.path.basename(path)
            except Exception as e:          # noqa: BLE001 — POError carries advice
                advice = str(e)
        elif getattr(item.message, "body", "").strip():
            # Occasionally the order is simply typed into the mail.
            text = item.message.body
            source = i18n.t("the email itself")
        else:
            advice = i18n.t(
                "No readable file came with this mail — type the fields from "
                "the printed order and everything else carries on as normal.")

        # The privacy switch means every AI call on mail content, and a PO is
        # mail content. With it on — or with no key — the reading is done by
        # the person instead, never silently ignored.
        if text and settings.get("local_only"):
            text = ""
            advice = i18n.t(
                "Keep everything on this computer is switched on, so the "
                "order is not sent out to be read. Type the fields from the "
                "printed order and everything else carries on as normal.")
        elif text and not self.cfg.get("api_key"):
            text = ""
            advice = i18n.t(
                "Reading a PO needs the free key Prism plans with, and there "
                "isn't one saved. Type the fields in, or add the key under "
                "Settings.")

        self._po_row = row
        if not text:
            self._show_po(None, row, advice=advice)
            return
        self.po_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.status.setText(i18n.t("Reading the purchase order…"))
        self._po_worker = POReadWorker(self.cfg, text, source)
        self._po_worker.done.connect(lambda order: self._po_read(order, row))
        self._po_worker.failed.connect(
            lambda message: self._po_read_failed(message, row))
        self._po_worker.start()

    def _po_read(self, order, row: dict):
        self.po_btn.setEnabled(True)
        self.progress.setVisible(False)
        self.status.setText("")
        po = CB.get_po()
        quote = _read_sent_quotation(row)
        differences = po.compare(order, quote) if quote is not None else []
        advice = "" if quote is not None else i18n.t(
            "The quotation that was sent couldn't be read back from the "
            "inquiry's folder, so there is no line-by-line comparison — the "
            "copy in the folder is the record to check against.")
        self._show_po(order, row, advice=advice, differences=differences)

    def _po_read_failed(self, message: str, row: dict):
        """Extraction failed — a scan, a dead key, a rate limit. The POError
        text already says what to do, and the typed-in form is always the way
        through: an unreadable file must never block accepting a real order.
        (OCR for scanned POs is deliberately not built — docs/DEFERRED.md has
        the trigger.)"""
        self.po_btn.setEnabled(True)
        self.progress.setVisible(False)
        self.status.setText("")
        self._show_po(None, row, advice=message)

    def _show_po(self, order, row: dict, advice: str = "",
                 differences: list | None = None):
        dialog = _POReviewDialog(row, order, differences or [], advice, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self._po_accepted(row, dialog.number(), dialog.value_text(),
                          dialog.date_text())

    def _po_accepted(self, row: dict, number: str, value_text: str,
                     po_date: str):
        register = CB.get_register()
        target = register.find(self._register_rows,
                               row.get("Inquiry no", "")) or row
        register.mark_converted(target, number, register.money(value_text))
        if po_date:
            target["PO date"] = po_date
        try:
            register.save(self._register_rows, self._paths().register_csv)
        except Exception as e:
            self._explain(str(e))
            return
        # Resolved in the worklist file — see _apply_reply() for why popping
        # the in-memory row is not enough on its own.
        item = getattr(self, "_po_item", None)
        if item is not None and item.message_id:
            CB.get_worklist().resolve(self._root(), "orders", item.message_id)
        self._refresh_register()
        self._render_orders()
        self.status.setText(
            i18n.t("{no} is converted — PO {po}, ₹{value}.")
            .replace("{no}", target.get("Inquiry no", ""))
            .replace("{po}", number)
            .replace("{value}", target.get("Order value", "") or value_text))

    # ── running a check ───────────────────────────────────────────────────
    def _first_look(self):
        if not is_ready(self.cfg):
            answer = QMessageBox.question(
                self, i18n.t("Email automation"),
                i18n.t("This needs your mailbox set up first — it takes about "
                       "two minutes and only happens once.\n\nSet it up now?"),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if answer == QMessageBox.Yes:
                self.open_setup()
            return
        if self._auto_check_on_open:
            self.check_now()
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
        """Fetch and sort every mailbox. `quiet` is a timer tick rather than
        a button press.

        The only difference a quiet run makes is that failures land in the
        status line instead of a dialog. Somebody running a factory should not
        have a modal appear over their work every ten minutes because a mail
        server had a bad afternoon.

        The mailboxes are walked ONE AT A TIME, never in parallel: every
        account's rows land in the same register, and the engine's own rule —
        one check at a time, because two fetches racing on one bookmark
        registers the same inquiry twice — becomes "N fetches racing on one
        order book" the moment there are N accounts.
        """
        if not is_ready(self.cfg):
            if not quiet:
                self._first_look()
            return
        self._quiet = quiet
        if not quiet:
            # A person pressing the button is asserting the credentials are
            # right — every mailbox gets to try again, which is also how the
            # user gets going after fixing a password.
            self._auth_failures = {}

        accounts = [a for a in accounts_of(self.cfg) if a.get("address")]
        if quiet:
            # A mailbox whose password keeps being refused is skipped by the
            # timer rather than hammered — the provider will throttle and then
            # lock the account, and the customer's report is "Prism locked me
            # out of my email". The others carry on being read.
            accounts = [a for a in accounts
                        if self._auth_failures.get(a["address"], 0)
                        < self.AUTH_FAILURES_BEFORE_STOP]
        if not accounts:
            return

        self._queue = accounts
        self._queue_pos = 0
        self._partial = []
        self._set_checking(True)
        self.progress.setVisible(True)
        self._check_account()

    def _set_checking(self, running: bool):
        self.check_btn.setEnabled(not running)
        self.reset_btn.setVisible(running)

    def _reset_check(self):
        """Give up on the check in progress and let the owner try again.

        Hard termination, not a cooperative stop — InboxCheckWorker has none
        to call, so this is the same fallback closeEvent() already reaches
        for when a worker will not finish on its own. It is the whole story
        here rather than a last resort, because the owner asked for it.
        """
        self._queue = []
        worker, self._worker = self._worker, None
        if worker is not None:
            try:
                if worker.isRunning():
                    worker.terminate()
                    worker.wait(1000)
            except RuntimeError:
                pass        # already deleted; nothing to wait for
        self._quiet = False
        self._set_checking(False)
        self.status.setText(i18n.t(
            "Check cancelled. Press Check my mail now to try again."))

    def _check_account(self):
        """Start the check for the account the walk is standing on."""
        account = self._queue[self._queue_pos]
        if len(self._queue) > 1:
            self.status.setText(
                i18n.t("Reading {who}… ({i} of {n})")
                .replace("{who}", account.get("address", ""))
                .replace("{i}", str(self._queue_pos + 1))
                .replace("{n}", str(len(self._queue))))
        else:
            self.status.setText(i18n.t("Reading your inbox…"))

        settings = self._settings()
        engine_cfg = dict(self.cfg)
        # The engine's inbox module reads cfg["inbox"]; the GUI keeps its
        # accounts under cfg["inquiry"] so this feature's settings travel
        # together and cannot be half-configured by the Email add-on.
        engine_cfg["inbox"] = {k: v for k, v in account.items()
                               if k != "state"}

        inbox = CB.get_inbox()
        triage = CB.get_triage()
        # Each mailbox reads its own bookmark; the sorter's knowledge is
        # shared — a sender is the same sender whichever address they wrote
        # to, and what account one's check learned is saved before account
        # two's check reads it.
        state = inbox.State.from_dict(account.get("state"))
        knowledge = triage.Knowledge.from_dict(settings.get("knowledge"))

        self._worker = InboxCheckWorker(
            engine_cfg, self._root(), state=state, knowledge=knowledge,
            local_only=bool(settings.get("local_only")),
            followup_days=int(settings.get("followup_days", 2) or 2),
            max_reminders=int(settings.get("max_reminders", 3) or 3))
        self._worker.done.connect(self._account_checked)
        self._worker.failed.connect(self._account_failed)
        self._worker.start()

    def _account_failed(self, message: str):
        """mailflow.check() promises never to raise; this is the seatbelt for
        the promise breaking. Treated exactly like a check that returned an
        error, so the walk carries on to the next mailbox."""
        mailflow = CB.get_mailflow()
        self._account_checked(mailflow.Result(error=message))

    def _account_checked(self, result):
        """One mailbox is done — bank it, then walk on or finish."""
        account = (self._queue[self._queue_pos]
                   if self._queue_pos < len(self._queue) else {})
        address = account.get("address", "")
        self._partial.append((address, result))

        if result.error and self._quiet \
                and CB.get_inbox().is_auth_failure(result.error):
            self._auth_failures[address] = \
                self._auth_failures.get(address, 0) + 1
        elif result.fetched or not result.error:
            # Got into the mailbox, so the credentials are good — clear any
            # run of rejections against this address.
            self._auth_failures.pop(address, None)

        # Persist this account's bookmark and what the sorter learned before
        # the next account runs — the learning chains through the config, and
        # a crash mid-walk must not cost the accounts already checked their
        # place. On a locked register the engine hands back the OLD state, so
        # saving it is exactly right: the same mail comes back next time.
        self._remember_account(address, result)

        register_locked = bool(result.error) and "Excel" in result.error
        self._queue_pos += 1
        if register_locked:
            # The same locked file would refuse every account after this one,
            # and none of their bookmarks have moved — stopping loses nothing
            # and spares the owner N copies of the same sentence.
            self._finish_check()
            return
        if self._queue_pos < len(self._queue):
            self._check_account()
            return
        self._finish_check()

    def _finish_check(self):
        self._stamp_mailboxes(self._partial)
        merged = self._merge_results(self._partial)
        self._checked(merged, remember=False)
        self._maybe_stop_timer()

    def _merge_results(self, partial) -> object:
        """Every mailbox's result as one, in the shape _checked() renders.

        Errors are prefixed with the address that had them once there is more
        than one mailbox — "the mail server didn't answer" is only half a
        sentence when there are three servers it could mean.
        """
        mailflow = CB.get_mailflow()
        merged = mailflow.Result()
        counts: dict = {}
        errors = []
        for address, result in partial:
            merged.fetched += int(getattr(result, "fetched", 0) or 0)
            merged.sorted_mail.extend(result.sorted_mail)
            merged.new_inquiries.extend(result.new_inquiries)
            merged.replies.extend(result.replies)
            merged.orders.extend(result.orders)
            for key, value in (result.counts or {}).items():
                counts[key] = counts.get(key, 0) + value
            # The follow-up and SOP lists are computed over the WHOLE register
            # on every check, so the latest successful one is already complete
            # — extending would list the same quiet quotation once per mailbox.
            if not result.error:
                merged.followups = result.followups
                merged.sops = result.sops
            merged.state = result.state
            merged.knowledge = result.knowledge
            if result.error:
                errors.append(f"{address} — {result.error}"
                              if address and len(partial) > 1
                              else result.error)
        merged.counts = counts
        merged.error = "\n\n".join(errors)
        return merged

    def _stamp_mailboxes(self, partial):
        """Write which mailbox each new inquiry arrived at into the register.

        One more column — "Mailbox" — because with sales@, info@ and the
        owner's own address feeding one file, "who is this customer talking
        to" is the first question the sheet gets asked. Stamped only where
        the column is empty: a purchase order landing on a different address
        later must not rewrite where the inquiry originally arrived.

        Best-effort on purpose. The rows themselves were saved by the engine
        moments ago; if Excel took the file in the meantime the stamp waits —
        the register's own lock message has already told the owner what to do,
        and attribution is not worth a second error on top of it.
        """
        stamps: dict[str, str] = {}
        for address, result in partial:
            if not address:
                continue
            for item in list(result.new_inquiries) + list(result.orders):
                if item.inquiry_no:
                    stamps.setdefault(item.inquiry_no, address)
        if not stamps:
            return
        register = CB.get_register()
        try:
            rows = register.load(self._paths().register_csv)
            changed = False
            for row in rows:
                number = row.get("Inquiry no", "")
                if number in stamps and not (row.get("Mailbox") or "").strip():
                    row["Mailbox"] = stamps[number]
                    changed = True
            if changed:
                register.save(rows, self._paths().register_csv)
        except Exception:                   # noqa: BLE001
            pass

    def _maybe_stop_timer(self):
        """Give up the timer only when EVERY mailbox has settled into refusing
        its password — while one still answers, checking carries on and the
        status line names the ones being skipped."""
        locked = [address for address, count in self._auth_failures.items()
                  if count >= self.AUTH_FAILURES_BEFORE_STOP]
        if not locked:
            return
        addresses = ", ".join(locked)
        every = all(
            self._auth_failures.get(a.get("address", ""), 0)
            >= self.AUTH_FAILURES_BEFORE_STOP
            for a in accounts_of(self.cfg) if a.get("address"))
        if every:
            self._auto.stop()
            # Loud, unlike every other quiet-run failure: automatic checking
            # has stopped and will not restart on its own, so saying nothing
            # would leave the register silently going stale.
            self.status.setText(i18n.t(
                "Automatic checking is off — {who} kept refusing the "
                "password. Update it in Setup, then press Check now."
            ).replace("{who}", addresses or i18n.t("the mail server")))
        else:
            self.status.setText(i18n.t(
                "Skipping {who} — the password keeps being refused. Update "
                "it in Setup, then press Check now."
            ).replace("{who}", addresses))

    #: Consecutive rejected sign-ins before a mailbox is given up on. Three,
    #: because one can be a provider hiccup and two can be a password
    #: mid-rotation.
    AUTH_FAILURES_BEFORE_STOP = 3

    def _check_failed(self, message: str):
        self._set_checking(False)
        self.progress.setVisible(False)
        self.status.setText("")
        self._note_failure(message)
        self._explain(message)
        self._quiet = False

    def _note_failure(self, message: str):
        """Count a rejected sign-in against the first mailbox.

        The single-mailbox path — kept because tests and simple callers hand
        a result straight to _checked(); the account walk counts per address
        in _account_checked() instead, where it knows which mailbox it was.

        A network failure never counts: retrying is exactly what the timer is
        for. A rejected password does, because the provider will throttle and
        then lock the account, and the customer's report is "Prism locked me
        out of my email".
        """
        if not getattr(self, "_quiet", False):
            self._auth_failures = {}
            return
        if not CB.get_inbox().is_auth_failure(message):
            return                          # transport, not credentials
        accounts = accounts_of(self.cfg)
        address = accounts[0].get("address", "") if accounts else ""
        self._auth_failures[address] = self._auth_failures.get(address, 0) + 1
        self._maybe_stop_timer()

    def _explain(self, message: str):
        """Plain-English failure, through the same translator as the rest."""
        if getattr(self, "_quiet", False):
            self.status.setText(message.split("\n")[0])
            return
        try:
            from dialogs.problem_dialog import show_problem
            show_problem(self, message)
        except Exception:
            QMessageBox.warning(self, i18n.t("Email automation"), message)

    def _checked(self, result, remember: bool = True):
        """Render one result — a single mailbox's, or the whole walk's merge.

        `remember` is True on the direct path (one result, persist its
        bookmark here); the account walk passes False because it has already
        banked every account's bookmark as it went.
        """
        self._set_checking(False)
        self.progress.setVisible(False)
        self._result = result

        if result.error:
            self.status.setText("")
            if remember:
                self._note_failure(result.error)
            self._explain(result.error)
            # A locked register still leaves the bookmark alone, so the same
            # mail comes back next time. Nothing to save.
            if not result.fetched:
                self._quiet = False
                return
        elif remember:
            # Got in, so the credentials are good — clear any rejections.
            self._auth_failures = {}

        if remember:
            self._remember(result)
        self.status.setText(result.headline())
        self._fill_arrived(result)
        self._fill_replies(result)
        self._fill_orders(result)
        self._refresh_register()
        # Never move the tab out from under somebody on a timer tick. A screen
        # that rearranges itself every ten minutes while you are reading it is
        # the reason people switch automatic checking off.
        if not self._quiet:
            # A purchase order is money confirmed and waiting on an
            # acceptance, so it wins the opening tab; a reply on a live
            # quotation — somebody waiting on an answer — beats a new
            # inquiry, which will still be there this afternoon.
            self.tabs.setCurrentIndex(
                TAB_INDEX["orders"] if result.orders else
                TAB_INDEX["replies"] if result.replies else
                TAB_INDEX["to_quote"])
        self._quiet = False
        # Last, and only after the register has been written: a reminder must
        # never go out to somebody whose reply arrived in this same check and
        # has not been filed yet.
        self._chase_automatically()

    def _remember(self, result):
        """Persist the bookmark and anything the sorter learned — the direct
        single-result path; the walk banks each account itself."""
        accounts = accounts_of(self.cfg)
        address = accounts[0].get("address", "") if accounts else ""
        self._remember_account(address, result)

    def _remember_account(self, address: str, result):
        """Bank one mailbox's bookmark, and what the sorter learned, into the
        account list — mirroring the first account into the legacy keys so a
        config written here still opens in a Prism from before the list."""
        settings = self._settings()
        accounts = accounts_of(self.cfg)
        for account in accounts:
            if account.get("address", "") == address:
                account["state"] = result.state.to_dict()
                break
        settings["accounts"] = accounts
        first = accounts[0] if accounts else {}
        settings["account"] = {k: v for k, v in first.items() if k != "state"}
        settings["state"] = dict(first.get("state") or {})
        knowledge = settings.get("knowledge") or {}
        knowledge["learned"] = dict(result.knowledge.learned)
        settings["knowledge"] = knowledge
        self.cfg["inquiry"] = settings
        CB.config.save(self.cfg)

    def _fill_arrived(self, result):
        """Bank whatever this check sorted into the worklist file, then
        draw the tab from THAT — see _fill_replies() for why: a table
        rebuilt straight from `result` shows only this check's mail, and
        goes blank the moment a later check (or a tab switch, which used to
        force a redraw from nothing) has nothing new to add."""
        entries = [_arrived_entry(message, verdict)
                  for message, verdict in
                  list(getattr(result, "sorted_mail", None) or [])]
        folder = self._root()
        if folder and entries:
            CB.get_worklist().append(folder, "arrived", entries)
        self._render_arrived()

    def _render_arrived(self):
        """Redraw from the worklist file's full log, filtered by the
        "Show:" range — not from memory, and not only "since the last
        check"."""
        worklist = CB.get_worklist()
        folder = self._root()
        data = worklist.load(folder) if folder else {"arrived": []}
        page = self._pages.get("arrived")
        today = date.today()
        text = page.search_text() if page else ""
        rows = [r for r in worklist.history(data, "arrived")
                if (page is None or page.in_range(
                    _parse_iso(r.get("date", "")), today))
                and _matches(text, r.get("from_name"), r.get("from_addr"),
                             r.get("subject"))]
        self.arrived.setRowCount(len(rows))
        for index, entry in enumerate(rows):
            who = entry.get("from_name") or entry.get("from_addr", "")
            self.arrived.setItem(index, 0, QTableWidgetItem(who))
            self.arrived.setItem(index, 1,
                                 QTableWidgetItem(entry.get("subject", "")))
            category = entry.get("category", "")
            label = i18n.t(CATEGORY_LABELS.get(category, category))
            self.arrived.setItem(index, 2, paint(
                QTableWidgetItem(label), CATEGORY_COLOURS, category))
            why = entry.get("reason") or i18n.t(
                SOURCE_LABELS.get(entry.get("source", ""), ""))
            self.arrived.setItem(index, 3, QTableWidgetItem(why))
            self.arrived.setItem(index, 4, QTableWidgetItem(
                _dmy(entry.get("date", ""))))
            self.arrived.item(index, 0).setData(
                Qt.UserRole, entry.get("from_addr", ""))
        self._sorted_mail = rows
        self._refresh_counts()

    def _correct(self):
        row = self.arrived.currentRow()
        if row < 0 or not getattr(self, "_sorted_mail", None):
            return
        entry = self._sorted_mail[row]
        address = entry.get("from_addr", "")
        category = self.recategorise.currentData()
        settings = self._settings()
        knowledge = settings.get("knowledge") or {}
        learned = dict(knowledge.get("learned") or {})
        learned[address] = category
        knowledge["learned"] = learned
        settings["knowledge"] = knowledge
        self.cfg["inquiry"] = settings
        CB.config.save(self.cfg)
        # Update the log entry itself, not just what is on screen right
        # now — otherwise the very next tab switch redraws from disk and
        # the correction looks like it never took.
        reason = i18n.t("sorted here, you taught it")
        if entry.get("message_id"):
            CB.get_worklist().update(
                self._root(), "arrived", entry["message_id"],
                {"category": category, "reason": reason, "source": "learned"})
        entry["category"], entry["reason"] = category, reason
        self.arrived.setItem(row, 2, paint(QTableWidgetItem(
            i18n.t(CATEGORY_LABELS.get(category, category))),
            CATEGORY_COLOURS, category))
        self.arrived.setItem(row, 3, QTableWidgetItem(reason))
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
        """Read the register off disk and redraw every table drawn from it.
        Anything that only changes what is SHOWN — a date filter, a search
        — calls the tab's own _render_*() instead; re-reading a CSV on a
        shared drive to change nothing but which rows are visible would
        make switching the filter cost what a real mail check costs."""
        register = CB.get_register()
        rows = self._rows()
        self._register_rows = rows
        settings = self._settings()
        due = register.awaiting_followup(
            rows,
            after_days=int(settings.get("followup_days", 2) or 2),
            max_reminders=int(settings.get("max_reminders", 3) or 3))
        self._followup_rows = list(due)
        focus_no = (self._focus_row or {}).get("Inquiry no", "")
        self._render_register()
        self._render_to_quote()
        self._render_waiting()
        self._reselect(focus_no)

    def _reselect(self, inquiry_no: str):
        """After a save, land the owner back on the row they were on — in
        whichever tab it now lives — instead of clearing the panel and
        making them find it again."""
        if not inquiry_no:
            return
        current = TABS[self.tabs.currentIndex()][0]
        tables = {"to_quote": (self.to_quote_table, self._to_quote_rows),
                  "waiting": (self.followups, self._waiting_rows),
                  "register": (self.register_table, self._visible_rows)}
        for key in (current, "to_quote", "waiting", "register"):
            table, rows = tables.get(key, (None, []))
            if table is None:
                continue
            for index, row in enumerate(rows):
                if row.get("Inquiry no", "") == inquiry_no:
                    table.setCurrentCell(index, 0)
                    return

    def _register_date_matches(self, row: dict, filter_key: str,
                               today: date) -> bool:
        register = CB.get_register()
        return _in_date_range(register.parse_date(row.get("Date received", "")),
                              filter_key, today)

    def _filtered(self, key: str, rows: list[dict]) -> list[dict]:
        """A tab's Show: range and search box applied to register rows —
        in memory, never a disk read."""
        page = self._pages.get(key)
        if page is None:
            return list(rows)
        register = CB.get_register()
        today = date.today()
        text = page.search_text()
        return [r for r in rows
                if page.in_range(register.parse_date(r.get("Date received", "")),
                                 today)
                and _matches(text, r.get("Inquiry no"), r.get("Customer"),
                             r.get("Email"), r.get("Product asked"),
                             r.get("Quotation no"))]

    @staticmethod
    def _fill_cells(table: QTableWidget, values: list, status_column=None):
        index = table.rowCount()
        table.setRowCount(index + 1)
        for column, value in enumerate(values):
            cell = QTableWidgetItem(str(value))
            if column == status_column:
                paint(cell, STATUS_COLOURS, str(value))
            table.setItem(index, column, cell)

    def _render_register(self):
        """Redraw the All-inquiries table from _register_rows and its
        filters, without touching the disk. _visible_rows becomes the
        table's actual row order — see its definition in __init__ for why
        _selected_row() must read that list and not _register_rows."""
        register = CB.get_register()
        chip = (self.register_chips.current()
                if hasattr(self, "register_chips") else "all") or "all"
        wanted = {"all": None, "open": set(register.OPEN_STATUSES),
                  "won": {register.CONVERTED},
                  "lost": {register.NOT_CONVERTED}}[chip]
        rows = [r for r in self._filtered("register", self._register_rows or [])
                if wanted is None
                or ((r.get("Status") or "").strip() or register.NEW) in wanted]
        self._visible_rows = rows
        self.register_table.setRowCount(0)
        for row in rows:
            when = row.get("Date received", "")
            clock = row.get("Time received", "")
            self._fill_cells(self.register_table, [
                row.get("Inquiry no", ""), f"{when} {clock}".strip(),
                row.get("Customer", "") or row.get("Email", ""),
                row.get("Product asked", ""), row.get("Status", ""),
                _rupees(row.get("Order value") or row.get("Quotation value"))],
                status_column=4)
        self._refresh_counts()

    def _render_to_quote(self):
        register = CB.get_register()
        rows = [r for r in self._filtered("to_quote", self._register_rows or [])
                if ((r.get("Status") or "").strip() or register.NEW)
                == register.NEW]
        self._to_quote_rows = rows
        self.to_quote_table.setRowCount(0)
        for row in rows:
            self._fill_cells(self.to_quote_table, [
                row.get("Inquiry no", ""), row.get("Date received", ""),
                row.get("Customer", "") or row.get("Email", ""),
                row.get("Product asked", ""), row.get("Quantity", ""),
                row.get("Status", "") or register.NEW], status_column=5)
        self._refresh_counts()

    def _render_waiting(self):
        """Every quotation still unanswered, with what has been done about
        it so far — from worklist/sent.json, so the column can say WHEN a
        reminder went, not just how many."""
        register = CB.get_register()
        rows = [r for r in self._filtered("waiting", self._register_rows or [])
                if (r.get("Status") or "").strip()
                in (register.QUOTED, register.FOLLOWING_UP)]
        self._waiting_rows = rows
        due_ids = {id(r) for r in self._followup_rows}
        settings = self._settings()
        max_reminders = int(settings.get("max_reminders", 3) or 3)
        folder = self._root()
        data = CB.get_worklist().load(folder) if folder else {}
        self.followups.setRowCount(0)
        for row in rows:
            sent_count = int((row.get("Reminders sent") or "0").strip() or 0)
            reminders = [e for e in CB.get_worklist().sent_for(
                data, row.get("Inquiry no", "")) if e.get("kind") == "reminder"]
            if sent_count >= max_reminders:
                chased = i18n.t("{n} sent — call them").replace(
                    "{n}", str(sent_count))
            elif id(row) in due_ids:
                chased = i18n.t("Due today")
            elif reminders:
                chased = i18n.t("Sent {dates}").replace(
                    "{dates}", ", ".join(_dmy(e.get("date", ""), short=True)
                                         for e in reminders))
            elif sent_count:
                chased = i18n.t("{n} sent").replace("{n}", str(sent_count))
            else:
                chased = i18n.t("Not yet due")
            self._fill_cells(self.followups, [
                row.get("Quotation no", "") or i18n.t("(no number)"),
                row.get("Customer", "") or row.get("Email", ""),
                row.get("Quotation date", ""),
                _rupees(row.get("Quotation value")), chased,
                row.get("Inquiry no", "")])
            if id(row) in due_ids:
                paint(self.followups.item(self.followups.rowCount() - 1, 4),
                      {"due": _WARN}, "due")
        page = self._pages.get("waiting")
        if page is not None:
            n = len(self._followup_rows)
            page.sentence.setText(
                i18n.t("Quotations you sent that the customer has not "
                       "answered yet. None needs a reminder today.") if not n
                else i18n.t("Quotations you sent that the customer has not "
                            "answered yet. {n} need a reminder today.")
                .replace("{n}", str(n)))
        self._refresh_counts()

    def _refresh_counts(self):
        """The live number in each daily tab's title. Translate the label
        FIRST, then append the count — a string with a number in it is not
        in the catalogue and would never translate."""
        if not hasattr(self, "tabs") or len(self._pages) < len(TABS):
            return
        counts = {"to_quote": len(self._to_quote_rows),
                  "waiting": len(self._followup_rows),
                  "replies": len(self._replies),
                  "orders": len(self._orders)}
        for index, (key, label) in enumerate(TABS):
            text = i18n.t(label)
            if key in COUNTED_TABS:
                text = f"{text} ({counts.get(key, 0)})"
            if self.tabs.tabText(index) != text:
                self.tabs.setTabText(index, text)

    # ── which row, and what it can have done to it ────────────────────────
    def _current_row(self) -> dict | None:
        """The picked register row, or None — silently. The twin of
        _selected_row() for signal handlers, which must never pop a
        message box."""
        row = self._focus_row
        if row is not None and any(row is r for r in self._register_rows):
            return row
        index = self.register_table.currentRow()
        rows = getattr(self, "_visible_rows", [])
        return rows[index] if 0 <= index < len(rows) else None

    def _selected_row(self) -> dict | None:
        row = self._current_row()
        if row is None:
            QMessageBox.information(
                self, i18n.t("Email automation"),
                i18n.t("Pick an inquiry from the list first."))
        return row

    def _has_drawing(self, row: dict) -> bool:
        folder = row.get("Folder", "")
        try:
            return bool(folder) and os.path.isdir(folder) and any(
                name.lower().endswith(DRAWING_EXTENSIONS)
                for name in os.listdir(folder))
        except OSError:
            return False

    def _row_title(self, row: dict) -> str:
        parts = [row.get("Inquiry no", ""),
                 row.get("Customer", "") or row.get("Email", ""),
                 row.get("Product asked", "")]
        if row.get("Quantity"):
            parts.append(row["Quantity"])
        return " · ".join(p for p in parts if p)

    def _row_info(self, row: dict) -> str:
        register = CB.get_register()
        status = (row.get("Status") or "").strip() or register.NEW
        bits = [i18n.t(status)]
        if row.get("Date received"):
            bits.append(i18n.t("came {when}").replace(
                "{when}", row["Date received"]))
        folder = self._root()
        sent = []
        if folder:
            try:
                sent = CB.get_worklist().sent_for(
                    CB.get_worklist().load(folder), row.get("Inquiry no", ""))
            except Exception:           # noqa: BLE001 — a log, not the record
                sent = []
        if sent:
            words = {"quotation": i18n.t("quotation"),
                     "revised": i18n.t("revised quotation"),
                     "reminder": i18n.t("reminder"),
                     "winback": i18n.t("reply")}
            bits.append(i18n.t("Sent so far: {what}").replace("{what}", ", ".join(
                f"{words.get(e.get('kind'), e.get('kind', ''))} "
                f"{_dmy(e.get('date', ''), short=True)}" for e in sent)))
        else:
            bits.append(i18n.t("Sent so far: nothing yet"))
        return " · ".join(bits)

    def _sync_panel(self, key: str):
        """Redraw one tab's Selected-inquiry panel for whatever row is
        picked there. Runs from selection signals, so it never asks
        anything and never pops a box."""
        page = self._pages.get(key)
        if page is None:
            return
        panel = page.panel
        if key == "replies":
            item = self._selected_reply()
            self._show_reply()
            if item is None:
                panel.clear()
                return
            row = item.row or {}
            self._focus_row = row if row else None
            self.reply_sent_line.setText(self._row_info(row) if row else "")
            title = (self._row_title(row) if row else
                     f"{item.inquiry_no} · {item.message.from_addr}")
            panel.show_row(title, "", ["win_back", "folder"] if row else [],
                           extra=True)
            return
        if key == "orders":
            item = self._selected_order()
            if item is None:
                panel.clear()
                return
            row = item.row or {}
            self._focus_row = row if row else None
            keys = (["po", "remove_order", "folder"] if item.message_id
                    else ["record_po", "phone", "lost", "folder"])
            title = (self._row_title(row) if row else
                     f"{item.inquiry_no} · {item.message.from_addr}")
            panel.show_row(title, self._row_info(row) if row else "", keys)
            return
        if key == "arrived":
            index = self.arrived.currentRow()
            rows = self._sorted_mail or []
            if not 0 <= index < len(rows):
                panel.clear()
                return
            entry = rows[index]
            self._focus_row = None
            category = entry.get("category", "")
            panel.show_row(
                f"{entry.get('from_name') or entry.get('from_addr', '')} · "
                f"{entry.get('subject', '')}",
                i18n.t("Sorted as {what} · {when}")
                .replace("{what}", i18n.t(CATEGORY_LABELS.get(category, category)))
                .replace("{when}", _dmy(entry.get("date", ""))),
                (), extra=True)
            return
        table, rows = {"to_quote": (self.to_quote_table, self._to_quote_rows),
                       "waiting": (self.followups, self._waiting_rows),
                       "register": (self.register_table, self._visible_rows)
                       }[key]
        index = table.currentRow()
        row = rows[index] if 0 <= index < len(rows) else None
        self._focus_row = row
        if row is None:
            panel.clear()
            return
        keys = actions_for(row.get("Status", ""), key, self._has_drawing(row))
        panel.show_row(self._row_title(row), self._row_info(row), keys)
        remind = panel.buttons.get("remind")
        if remind is not None and "remind" in keys:
            settings = self._settings()
            sent = int((row.get("Reminders sent") or "0").strip() or 0)
            stop = sent >= int(settings.get("max_reminders", 3) or 3)
            remind.setEnabled(not stop)
            remind.setToolTip(i18n.t("Three reminders have gone. Call them.")
                              if stop else "")

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

    def _delete_inquiry(self):
        """Take a row out of the register — and, since the usual reason is
        a newsletter or a supplier that got itself registered, offer to stop
        that sender ever being treated as an inquiry again. The inquiry's
        folder on disk is left alone: deleting a line from a book is not
        the same as shredding the file."""
        row = self._selected_row()
        if not row:
            return
        no = row.get("Inquiry no", "")
        who = row.get("Customer", "") or row.get("Email", "")
        answer = QMessageBox.question(
            self, i18n.t("Delete this inquiry"),
            i18n.t("Delete {no} ({who}) from the register?\n\nIts folder, "
                   "with the mail and any drawings, stays on disk.")
            .replace("{no}", no).replace("{who}", who),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        address = (row.get("Email") or "").strip().lower()
        block = False
        if address:
            block = QMessageBox.question(
                self, i18n.t("Block this sender?"),
                i18n.t("Also stop treating mail from {who} as inquiries?\n\n"
                       "Prism will file anything from that address as "
                       "\"Other\" from now on and never register it.")
                .replace("{who}", address),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes
        register = CB.get_register()
        self._register_rows = [r for r in self._register_rows if r is not row]
        try:
            register.save(self._register_rows, self._paths().register_csv)
        except Exception as e:
            self._explain(str(e))
            return
        if block:
            self._learn_sender(address, "other")
        self._focus_row = None
        self._refresh_register()
        self.status.setText(
            i18n.t("{no} deleted. Mail from {who} will be filed as Other.")
            .replace("{no}", no).replace("{who}", address) if block
            else i18n.t("{no} deleted.").replace("{no}", no))

    def _learn_sender(self, address: str, category: str):
        """Remember a sender's category — the same knowledge the sorter's
        rules read first, so that address never goes to an AI again."""
        settings = self._settings()
        knowledge = settings.get("knowledge") or {}
        learned = dict(knowledge.get("learned") or {})
        learned[address] = category
        knowledge["learned"] = learned
        settings["knowledge"] = knowledge
        self.cfg["inquiry"] = settings
        CB.config.save(self.cfg)

    def _phone_reply(self):
        """"They replied by phone…" — the register moves exactly as it would
        for a reply by mail, without one."""
        row = self._selected_row()
        if not row:
            return
        dialog = _PhoneReplyDialog(row, self)
        if dialog.exec() != QDialog.Accepted:
            return
        register = CB.get_register()
        intent, note = dialog.intent(), dialog.note()
        if intent == "rejected":
            register.mark_lost(row, note or i18n.t("Declined by phone"))
        else:
            register.mark_reply(row, intent)
            if note:
                row["Notes"] = (row.get("Notes", "") + " " + note).strip()
        try:
            register.save(self._register_rows, self._paths().register_csv)
        except Exception as e:
            self._explain(str(e))
            return
        self._refresh_register()
        self.status.setText(
            i18n.t("{no} is now {status}.")
            .replace("{no}", row.get("Inquiry no", ""))
            .replace("{status}", i18n.t(row.get("Status", ""))))

    def _record_po_by_hand(self):
        """The PO came on paper, or the customer said yes on the phone —
        the same review sheet, with nothing pre-filled."""
        row = self._selected_row()
        if not row:
            return
        self._po_row = row
        self._po_item = None
        self._show_po(None, row, advice=i18n.t(
            "Type the PO number, date and value from the printed order."))

    def _remove_order(self):
        """A mail Prism took for a purchase order and was not one."""
        item = self._selected_order()
        if item is None:
            return
        if item.message_id and self._root():
            CB.get_worklist().resolve(self._root(), "orders", item.message_id)
        self._render_orders()

    def _mark_already_quoted(self):
        """Log a quotation made outside Prism — a phone call, a counter
        sale, or one written before this inquiry ever reached this screen.
        Reuses the same "Quoted" status a real pricing run would set, so it
        gets the same colour and the same follow-up chasing — the only
        difference is that nothing was priced or sent through Prism itself."""
        row = self._selected_row()
        if not row:
            return
        quote_no, value, ok = _ask_already_quoted(self, row)
        if not ok:
            return
        register = CB.get_register()
        register.mark_quoted(row, quote_no, value)
        try:
            register.save(self._register_rows, self._paths().register_csv)
        except Exception as e:
            self._explain(str(e))
            return
        self._refresh_register()
        self.status.setText(i18n.t(
            "Marked as quoted. Prism will remind you if there is no reply."))

    def _import_csv_into_register(self):
        """Bring in a register the owner already kept before Prism, or one a
        colleague built up separately — appended, not swapped in, and
        nothing already here is touched. See register.merge_in() for how a
        row already present is recognised and skipped."""
        if not self._root():
            QMessageBox.information(
                self, i18n.t("Email automation"),
                i18n.t("Set up a mailbox and a folder first."))
            return
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.t("Choose the CSV you already kept"),
            os.path.expanduser("~"), "CSV (*.csv)")
        if not path:
            return
        register = CB.get_register()
        try:
            incoming = register.load(path)
        except Exception as e:
            self._explain(str(e))
            return
        if not incoming:
            QMessageBox.information(
                self, i18n.t("Import"),
                i18n.t("That file has no rows in it."))
            return
        merged, added, skipped = register.merge_in(self._register_rows,
                                                    incoming)
        try:
            register.save(merged, self._paths().register_csv)
        except Exception as e:
            self._explain(str(e))
            return
        self._refresh_register()
        message = i18n.t("Added {n} row(s) to the register.").replace(
            "{n}", str(added))
        if skipped:
            message += " " + i18n.t(
                "{n} looked like ones already in the register, so they "
                "were left out.").replace("{n}", str(skipped))
        QMessageBox.information(self, i18n.t("Import"), message)

    # ── chasing a quiet quotation ─────────────────────────────────────────
    def _send_reminder(self):
        """One polite nudge, shown before it goes.

        Deliberately one at a time and never on the timer. A reminder is Prism
        writing to somebody else's customer in their name, and a loop that
        chases the whole list unattended is one bad afternoon away from
        mailing the same buyer three times.
        """
        row = self._current_row()
        if row is None:
            QMessageBox.information(
                self, i18n.t("Reminder"),
                i18n.t("Pick a quotation from the list first."))
            return
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
            draft.subject(), draft.message(), [])
        self._send_worker.done.connect(
            lambda sent, failed, s=draft.subject():
            self._reminder_sent(row, sent, failed, subject=s))
        self._send_worker.failed.connect(self._reminder_failed)
        self._send_worker.start()

    def _reminder_sent(self, row: dict, sent: list, failed: list,
                       subject: str = ""):
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
        self._log_sent("reminder", row, subject or
                       self._reminder_words(row)[0])
        self._refresh_register()
        self.status.setText(
            i18n.t("Reminder sent to {who}.").replace(
                "{who}", row.get("Email", "")))

    def _log_sent(self, kind: str, row: dict, subject: str):
        """Write one line to worklist/sent.json — the readable history the
        "Sent so far" line and the reminder column are drawn from. The
        register's own "Reminders sent" count stays the engine's schedule;
        this is written in the same breath so the two cannot disagree. A
        failure here must never undo a send that already happened, so it is
        swallowed rather than raised."""
        folder = self._root()
        if not folder:
            return
        try:
            CB.get_worklist().log_sent(
                folder, kind, to=row.get("Email", ""), subject=subject,
                inquiry_no=row.get("Inquiry no", ""),
                quotation_no=row.get("Quotation no", ""))
        except Exception:               # noqa: BLE001 — see docstring
            pass

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
            lambda sent, failed, s=subject:
            self._reminder_sent(row, sent, failed, subject=s))
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
            dialog.subject(), dialog.message(), [])
        self._send_worker.done.connect(
            lambda sent, failed, s=dialog.subject():
            self._winback_sent(row, sent, failed, subject=s))
        self._send_worker.failed.connect(self._reminder_failed)
        self._send_worker.start()

    def _winback_sent(self, row: dict, sent: list, failed: list,
                      subject: str = ""):
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
        self._log_sent("winback", row, subject)
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


def _ask_already_quoted(parent, row: dict) -> tuple[str, str, bool]:
    """Both fields optional — an owner who just wants the chase to stop
    should not be blocked on a quotation number they may never have
    written down."""
    dialog = QDialog(parent)
    dialog.setWindowTitle(i18n.t("Mark as already quoted"))
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel(i18n.t(
        "For {who} — logs it as quoted, without opening the pricing "
        "screen.").replace(
        "{who}", row.get("Customer", "") or row.get("Email", ""))))
    form = QFormLayout()
    number = QLineEdit()
    number.setPlaceholderText(i18n.t("optional"))
    form.addRow(i18n.t("Quotation no:"), number)
    value = QLineEdit()
    value.setPlaceholderText(i18n.t("optional"))
    form.addRow(i18n.t("Value:"), value)
    layout.addLayout(form)
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    ok = dialog.exec() == QDialog.Accepted
    return number.text().strip(), value.text().strip(), ok


class _ReminderDialog(PrismDialog):
    """The reminder, shown before it goes. Editable, because the right words
    for a customer of fifteen years are not the right words for a new one."""

    def __init__(self, subject: str, body: str, address: str, parent=None,
                 note: str = ""):
        super().__init__(
            i18n.t("Send a reminder"),
            i18n.t("Prism wrote this. Edit anything before it goes."),
            icon="mail", parent=parent, closable=False)
        self.setWindowTitle(i18n.t("Send a reminder"))
        self.resize(620, 480)
        layout = self.body
        layout.setSpacing(theme.ROW_GAP)
        layout.addWidget(QLabel(
            i18n.t("To: {who}").replace("{who}", address)))
        if note:
            caption = QLabel(note)
            caption.setWordWrap(True)
            caption.setObjectName("meta")
            layout.addWidget(caption)
        self._subject = QLineEdit(subject)
        layout.addWidget(self._subject)
        self._body = C.PlainPasteTextEdit(body)
        layout.addWidget(self._body, stretch=1)
        self.footer.add_secondary(
            self.button(i18n.t("Cancel"), on_click=self.reject))
        self.footer.set_primary(
            self.button(i18n.t("Send it"), "primary", icon_name="mail",
                        on_click=self.accept))

    def subject(self) -> str:
        return self._subject.text().strip()

    def message(self) -> str:
        """The reminder text. Named `message`, not `body`, because
        PrismDialog puts the dialog's content layout on `self.body` and an
        instance attribute shadows a method of the same name — `draft.body()`
        would have tried to call a QVBoxLayout."""
        return self._body.toPlainText()


def _read_sent_quotation(row: dict):
    """The quotation actually sent, rebuilt from the CSV written at send time.

    That CSV is the only record of the figures as the customer saw them —
    rebuilding from today's rate list could compare their PO against a price
    they were never quoted. This mirrors quoting.write_csv column for column
    (a reader belongs beside that writer in the engine eventually; until the
    engine grows one, it lives here where its only caller is).

    The reconstruction is checked against the file's own Total row and
    refused on any mismatch: comparing a PO against a misparsed quotation
    would flag differences the customer never made, and a confidently wrong
    comparison is worse than saying there is none.
    """
    quoting = CB.get_quoting()
    register = CB.get_register()
    folder = row.get("Folder", "")
    number = (row.get("Quotation no", "") or "").replace("/", "-")
    if not folder or not number:
        return None
    path = os.path.join(folder, f"{number}.csv")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            records = list(csv.reader(f))
    except OSError:
        return None

    head: dict = {}
    lines = []
    gst = None
    freight = Decimal(0)
    discount = Decimal(0)
    total = None
    section = "head"
    try:
        for record in records:
            cells = [c.strip() for c in record]
            if not any(cells):
                continue
            first = cells[0]
            if section == "head":
                if first == "Sr":
                    section = "lines"
                elif len(cells) >= 2:
                    head[first] = cells[1]
                continue
            if first:
                # A numbered line: Sr, Description, HSN, Qty, Unit, Rate,
                # Amount, Rate source — the order write_csv puts them in.
                lines.append(quoting.QuoteLine(
                    cells[1], quoting.to_decimal(cells[3]), cells[4],
                    quoting.to_decimal(cells[5]), cells[2],
                    basis=cells[7] if len(cells) > 7 else ""))
                continue
            label = cells[5] if len(cells) > 5 else ""
            value = cells[6] if len(cells) > 6 else ""
            if label.startswith("GST"):
                gst = quoting.to_decimal(label[4:].rstrip("%"))
            elif label.startswith("Discount"):
                discount = quoting.to_decimal(label[9:].rstrip("%"))
            elif label == "Freight":
                freight = quoting.to_decimal(value)
            elif label == "Total":
                total = quoting.to_decimal(value)
    except Exception:                       # noqa: BLE001 — hand-edited file
        return None

    if not lines or gst is None or total is None:
        return None
    quote = quoting.Quotation(
        number=head.get("Quotation no", ""),
        date=register.parse_date(head.get("Date", "")) or date.today(),
        customer=head.get("Customer", ""),
        inquiry_no=head.get("Inquiry no", ""),
        lines=lines,
        terms=quoting.Terms(gst_percent=gst, freight=freight,
                            discount_percent=discount))
    if quote.total != total:
        return None
    return quote


class _POReviewDialog(PrismDialog):
    """The purchase order against the quotation — the second stop.

    The screen the runtime plan always named as the missing one. Everything
    on it is either read off the order or typed by the owner; accepting
    writes the register and nothing else — no mail moves, nothing is sent.

    The typed-in boxes are not a fallback that appears on failure: they are
    always there, pre-filled when reading worked. Half of real POs are scans
    with no text in them, and the owner holding a printed order must never be
    blocked by Prism's inability to read it.
    """

    def __init__(self, row: dict, order=None, differences: list | None = None,
                 advice: str = "", parent=None):
        super().__init__(
            i18n.t("The order, against the quotation"),
            i18n.t("Check the figures, then accept. Accepting writes the "
                   "register and sends nothing."),
            icon="archive", parent=parent, closable=False)
        self.setWindowTitle(i18n.t("The order, against the quotation"))
        self.resize(720, 620)
        self.setMinimumSize(560, 480)
        layout = self.body
        layout.setSpacing(theme.ROW_GAP)

        who = QLabel("   ·   ".join(part for part in (
            row.get("Inquiry no", ""),
            row.get("Customer", "") or row.get("Email", ""),
            (i18n.t("quoted ₹{value} on {when}")
             .replace("{value}", row.get("Quotation value", ""))
             .replace("{when}", row.get("Quotation date", ""))
             if row.get("Quotation value") else "")) if part))
        who.setWordWrap(True)
        who.setObjectName("h2")
        layout.addWidget(who)

        if advice:
            note = QLabel(advice)
            note.setWordWrap(True)
            note.setStyleSheet(_warning_css())
            layout.addWidget(note)

        if order is not None:
            po = CB.get_po()
            summary = QLabel(po.summary(order, differences or []))
            summary.setWordWrap(True)
            layout.addWidget(summary)

        if differences:
            table = QTableWidget(len(differences), 3)
            table.setHorizontalHeaderLabels(
                [i18n.t("What"), i18n.t("We quoted"),
                 i18n.t("The order says")])
            table.verticalHeader().setVisible(False)
            table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            table.horizontalHeader().setSectionResizeMode(
                0, QHeaderView.Stretch)
            # The money columns get their full width — "₹1,38,000.…" with the
            # thousands clipped off is the one truncation this dialog exists
            # to prevent.
            table.horizontalHeader().setSectionResizeMode(
                1, QHeaderView.ResizeToContents)
            table.horizontalHeader().setSectionResizeMode(
                2, QHeaderView.ResizeToContents)
            po = CB.get_po()
            for index, diff in enumerate(differences):
                for column, value in enumerate(
                        (diff.field, diff.quoted, diff.ordered)):
                    cell = QTableWidgetItem(str(value))
                    if diff.kind == po.MONEY:
                        # The word is in the cells; the tint says "money"
                        # at arm's length, same palette as everywhere else.
                        # WARN, because a purchase order whose figures differ
                        # from the quotation is precisely the row a person has
                        # to look at before accepting it.
                        cell.setBackground(QColor(theme.WARN_BG))
                        cell.setForeground(QColor(theme.WARN_INK))
                    table.setItem(index, column, cell)
            layout.addWidget(table, stretch=1)
        elif order is not None and not advice:
            matches = QLabel(i18n.t(
                "Nothing differs from the quotation — the numbers are the "
                "numbers you sent."))
            matches.setWordWrap(True)
            matches.setObjectName("meta")
            layout.addWidget(matches)

        form = QFormLayout()
        self._number = QLineEdit(getattr(order, "number", "") or "")
        self._number.setPlaceholderText(i18n.t("as printed on the order"))
        form.addRow(i18n.t("PO number:"), self._number)
        when = getattr(order, "date", None)
        self._date = QLineEdit(when.strftime("%d-%m-%Y") if when else "")
        self._date.setPlaceholderText("DD-MM-YYYY")
        form.addRow(i18n.t("PO date:"), self._date)
        value = getattr(order, "value", None)
        self._value = QLineEdit(str(value) if value else "")
        self._value.setPlaceholderText(
            i18n.t("order value — digits only, as printed"))
        form.addRow(i18n.t("Order value:"), self._value)
        layout.addLayout(form)

        note = QLabel(i18n.t(
            "Accepting only writes the register — nothing is sent. The "
            "production sheet comes from the BOQ button on the Inquiries "
            "tab."))
        note.setWordWrap(True)
        note.setObjectName("meta")
        layout.addWidget(note)

        layout.addStretch(1)
        self.footer.add_secondary(
            self.button(i18n.t("Not now"), on_click=self.reject))
        self.footer.set_primary(self.button(
            i18n.t("Accept — mark converted"), "primary", icon_name="check",
            on_click=self._accept))

    def _accept(self):
        if not self.number() or not self.value_text():
            QMessageBox.information(
                self, i18n.t("Purchase order"),
                i18n.t("The PO number and the order value are the two things "
                       "the register cannot do without — they are what the "
                       "month-end figures are made of."))
            return
        self.accept()

    def number(self) -> str:
        return self._number.text().strip()

    def date_text(self) -> str:
        return self._date.text().strip()

    def value_text(self) -> str:
        return self._value.text().strip()


class _EditRowDialog(PrismDialog):
    """Correct one register row by hand.

    Only the fields a person can sensibly know better than Prism. The inquiry
    number, the quotation number and the dates are not here on purpose: those
    are the register's own bookkeeping, and letting them be retyped is how two
    rows end up sharing a number.
    """

    FIELDS = ("Customer", "Contact person", "Email", "Phone",
              "Product asked", "Quantity", "Notes")

    def __init__(self, row: dict, parent=None):
        super().__init__(
            i18n.t("Edit this row"),
            i18n.t("Only the fields a person knows better than Prism. The "
                   "numbers and dates are the register's own bookkeeping."),
            icon="pencil", parent=parent, closable=False)
        self.setWindowTitle(i18n.t("Edit inquiry {no}").replace(
            "{no}", row.get("Inquiry no", "")))
        self.resize(600, 480)
        self._edits = {}

        layout = self.body
        layout.setSpacing(theme.ROW_GAP)
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
        note.setObjectName("meta")
        layout.addWidget(note)

        layout.addStretch(1)
        self.footer.add_secondary(
            self.button(i18n.t("Cancel"), on_click=self.reject))
        self.footer.set_primary(
            self.button(i18n.t("Save"), "primary", icon_name="check",
                        on_click=self.accept))

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


class QuotationDialog(PrismDialog):
    """Price one inquiry, review it, and send it.

    The one screen in this feature where a person is genuinely required. Prism
    picks the rate-list row, does the arithmetic and writes the covering mail;
    what it will not do is put a price in front of a customer on its own.
    """

    def __init__(self, cfg: dict, row: dict, items: list, parent=None, *,
                 cost_lines: list | None = None):
        super().__init__(
            i18n.t("Prepare a quotation"),
            i18n.t("Prism prices it and writes the covering mail. You check "
                   "the figure and press Send."),
            icon="file", parent=parent, closable=False, scrollable=True)
        self.setWindowTitle(i18n.t("Prepare a quotation"))
        self.resize(860, 820)
        # Lower than before now that the body scrolls (scrollable=True) — a
        # short laptop screen shrinks the window and scrolls the form instead
        # of Qt compressing every row into the one above it, which is what
        # produced the overlapping labels the previous fixed-height body did.
        self.setMinimumSize(620, 460)
        self.cfg, self.row, self.items = dict(cfg), row, items
        self.cost_lines = list(cost_lines or [])
        self.parent_dialog = parent
        self._send_worker = None
        self.quote = None
        # Whether the rate box holds something Prism suggested or something
        # the owner typed over it. A fresh item pick clears this — see
        # _item_picked() — because a different item earns a fresh suggestion,
        # not the last one's leftover override.
        self._rate_dirty = False
        # True only while code, not the owner, is writing into rate_edit —
        # otherwise _set_rate_text()'s own write would set _rate_dirty right
        # back to True the instant it finished clearing it.
        self._populating = False

        quoting = CB.get_quoting()
        self.matches = quoting.match_item(row.get("Product asked", ""), items)

        layout = self.body
        layout.setSpacing(theme.ROW_GAP)

        self._confident = quoting.is_confident(self.matches)

        # Side by side, because the one judgement this whole dialog exists
        # for is comparing these two: what the customer wrote, against what
        # Prism is about to put a price on. Burying the ask in a one-line
        # label above a plain form made that comparison something the owner
        # had to hold in their head; here it stays on screen the whole time.
        compare = QHBoxLayout()
        compare.setSpacing(theme.SPACE_4)

        ask_card = C.Card()
        ask_col = ask_card.body(margins=(16, 14, 16, 16), spacing=theme.SPACE_1)
        ask_title = QLabel(i18n.t("They asked for"))
        ask_title.setObjectName("h6")
        ask_col.addWidget(ask_title)
        asked = QLabel(row.get("Product asked", "")[:220]
                       or i18n.t("(no detail given)"))
        asked.setWordWrap(True)
        ask_col.addWidget(asked)
        ask_qty = QLabel(i18n.t("Quantity: {n}").replace(
            "{n}", row.get("Quantity", "") or _quantity_of(row)))
        ask_qty.setObjectName("meta")
        ask_col.addWidget(ask_qty)
        ask_col.addStretch(1)
        compare.addWidget(ask_card, stretch=1)

        quote_card = C.Card(stripe=True)
        quote_col = quote_card.body(margins=(16, 14, 16, 16),
                                    spacing=theme.SPACE_1)
        quote_head = QHBoxLayout()
        quote_title = QLabel(i18n.t("You're quoting"))
        quote_title.setObjectName("h6")
        quote_head.addWidget(quote_title, stretch=1)
        # Pill, not a plain label: this is the one signal in the dialog that
        # tells the owner whether to slow down and check Prism's pick, and it
        # needs to read at a glance the way every other status in the app
        # does.
        self.verdict = C.Pill(
            i18n.t("Confident match") if self._confident
            else i18n.t("Check this"),
            "ok" if self._confident else "warn")
        quote_head.addWidget(self.verdict)
        quote_col.addLayout(quote_head)
        self.verdict_detail = QLabel(i18n.t(
            "Two rows on your rate list are close — check the one Prism "
            "picked before this goes out."))
        self.verdict_detail.setWordWrap(True)
        self.verdict_detail.setStyleSheet(_warning_css())
        self.verdict_detail.setVisible(not self._confident)
        quote_col.addWidget(self.verdict_detail)
        self.quote_line_label = QLabel(i18n.t("Pick an item to see the price."))
        self.quote_line_label.setWordWrap(True)
        quote_col.addWidget(self.quote_line_label)
        self.total_label = QLabel("")
        self.total_label.setStyleSheet(theme.type_css("PAGE_TITLE", theme.ACCENT))
        quote_col.addWidget(self.total_label)
        quote_col.addStretch(1)
        compare.addWidget(quote_card, stretch=1)

        layout.addLayout(compare)

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
        # Picking here is a starting point, not the last word — everything
        # below is editable afterwards, and a fresh pick clears any typed-in
        # rate so it doesn't silently carry over onto a different item.
        self.item_picker.currentIndexChanged.connect(self._item_picked)

        # Rate and unit are what used to be locked inside item.rate_for() and
        # item.unit with no way to see or touch them. A newbie whose customer
        # asked to round to a friendly number, or whose rate list doesn't
        # cover a one-off, had no field to type into — only the item picker,
        # which offers exactly the rates already on the list and nothing
        # else. Prism still suggests a number; this is where it stops being
        # the only number.
        self.rate_edit = QLineEdit()
        self.rate_edit.setPlaceholderText(i18n.t("Prism suggests one — type "
                                                  "over it to use your own"))
        self.rate_edit.textChanged.connect(self._rate_edited)
        form.addRow(i18n.t("Rate (per unit):"), self.rate_edit)
        self.unit_edit = QLineEdit()
        self.unit_edit.setPlaceholderText(i18n.t("nos, kg, mtr…"))
        self.unit_edit.textChanged.connect(self._recalculate)
        form.addRow(i18n.t("Unit:"), self.unit_edit)

        # Only the cost-sheet route needs a weight: it is what the per-kg
        # lines multiply. Blank is not zero-by-accident — a cost sheet with a
        # material line and no weight would quote the labour alone, so the
        # recalculation refuses rather than under-quoting, unless a rate has
        # been typed in by hand instead — see _recalculate_from_cost().
        self.description = QLineEdit(row.get("Product asked", "")[:120])
        self.description.textChanged.connect(self._recalculate)
        self.weight = QLineEdit("")
        self.weight.setPlaceholderText(i18n.t("kg per piece — from the drawing"))
        self.weight.textChanged.connect(self._recalculate)
        self.desc_label = QLabel(i18n.t("Describe it:"))
        self.weight_label = QLabel(i18n.t("Weight each:"))
        form.addRow(self.desc_label, self.description)
        form.addRow(self.weight_label, self.weight)

        self.quantity = QLineEdit(_quantity_of(row))
        self.quantity.textChanged.connect(self._recalculate)
        form.addRow(i18n.t("Quantity:"), self.quantity)
        layout.addLayout(form)

        self.workings = QPlainTextEdit()
        self.workings.setReadOnly(True)
        self.workings.setFixedHeight(160)
        self.workings.setObjectName("mono")
        self.workings.setVisible(False)
        layout.addWidget(self.workings)

        recalc = QPushButton(i18n.t("Work out the price"))
        recalc.clicked.connect(self._recalculate)
        layout.addWidget(recalc)

        preview_title = QLabel(i18n.t("The quotation document:"))
        preview_title.setObjectName("h6")
        layout.addWidget(preview_title)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setObjectName("mono")
        # The quotation itself. A floor on it, because everything else in this
        # column has a fixed height and the stretch alone let the one thing the
        # owner is meant to CHECK collapse to three lines on a short window.
        self.preview.setMinimumHeight(170)
        layout.addWidget(self.preview, stretch=1)

        layout.addWidget(QLabel(i18n.t("The email that carries it:")))
        self.subject = QLineEdit()
        layout.addWidget(self.subject)
        # `mail_body`, not `body`: PrismDialog owns `self.body` (the content
        # layout), and quietly rebinding it here would break any later use of
        # the scaffold from this class.
        self.mail_body = C.PlainPasteTextEdit()
        self.mail_body.setFixedHeight(130)
        layout.addWidget(self.mail_body)

        # Order matters more here than anywhere else in the app: the old row
        # put Cancel to the RIGHT of the solid accent "Send it", so the last
        # thing under the cursor on the screen that emails a price to a
        # customer was the one button that throws the work away. Primary last,
        # always.
        # The owner asked for this in so many words: before a price goes
        # out, see the customer's ask, our rates, what the job takes, and
        # the quotation, all on one screen.
        self.compare_btn = self.button(i18n.t("Compare side by side"),
                                       "secondary", icon_name="grid",
                                       small=True, on_click=self._compare)
        self.footer.add_utility(self.compare_btn)
        self.save_btn = self.button(i18n.t("Save without sending"),
                                    "secondary", icon_name="file",
                                    small=True,
                                    on_click=lambda: self._finish(send=False))
        self.footer.add_utility(self.save_btn)
        self.footer.add_secondary(
            self.button(i18n.t("Cancel"), on_click=self.reject))
        self.send_btn = self.button(i18n.t("Send it"), "primary",
                                    icon_name="mail",
                                    on_click=lambda: self._finish(send=True))
        self.footer.set_primary(self.send_btn)

        self._source_changed()

    def _compare(self):
        _CompareDialog(self).exec()

    # ── which pricing route ───────────────────────────────────────────────
    def _mode(self) -> str:
        return self.source.currentData() or "rates"

    def _source_changed(self, *_):
        """Show only the boxes the chosen route actually uses.

        Rate, unit and description stay visible either way — see the comment
        above rate_edit — because "let me type the final number myself" is
        just as real a need on the cost-sheet route as on the rate list.
        Only weight is route-specific: it means nothing outside a per-kg
        cost-sheet line."""
        cost = self._mode() == "cost"
        for widget in (self.item_picker, self.item_row_label):
            widget.setVisible(not cost)
        for widget in (self.weight, self.weight_label):
            widget.setVisible(cost)
        self.verdict.setVisible(not cost)
        self.verdict_detail.setVisible(not cost and not self._confident)
        self.workings.setVisible(cost)
        self._recalculate()

    def _recalculate(self, *_):
        if self._mode() == "cost":
            self._recalculate_from_cost()
        else:
            self._recalculate_from_rates()

    def _item_picked(self, *_):
        """A fresh pick from the list is a fresh start: the description, unit
        and any typed-over rate all reset to what this item actually says,
        rather than keeping the previous item's hand-typed leftovers."""
        item = self.item_picker.currentData()
        if item is not None:
            self._populating = True
            self.description.setText(item.description)
            self.unit_edit.setText(item.unit)
            self._populating = False
            self._rate_dirty = False
        self._recalculate()

    def _rate_edited(self, *_):
        """Distinguish the owner typing a number from Prism writing one in —
        only the former should stick through the next recalculation."""
        if self._populating:
            return
        self._rate_dirty = True
        self._recalculate()

    def _set_rate_text(self, rate):
        self._populating = True
        self.rate_edit.setText(f"{rate:.2f}")
        self._populating = False

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
        self.quote_line_label.setText(
            f"{description[:80]}\n{line.quantity} {line.unit} × "
            f"₹{quoting.indian_currency(line.rate)} = "
            f"₹{quoting.indian_currency(line.amount)}")
        self.total_label.setText(f"₹{quoting.indian_currency(self.quote.total)}")
        if not self.subject.text().strip():
            self.subject.setText(
                f"{i18n.t('Quotation')} {self.quote.number} — {description[:50]}")
        if not self.mail_body.toPlainText().strip():
            self.mail_body.setPlainText(_default_body(self.quote, settings))

    def _recalculate_from_rates(self):
        quoting = CB.get_quoting()
        item = self.item_picker.currentData()
        if item is None:
            self.total_label.setText("")
            self.quote_line_label.setText(i18n.t("Pick an item to see the price."))
            return
        quantity = quoting.to_decimal(self.quantity.text()) or Decimal(1)
        suggested = item.rate_for(quantity)
        if self._rate_dirty:
            rate, basis = quoting.to_decimal(self.rate_edit.text()) or suggested, \
                "entered by hand"
        else:
            rate, basis = suggested, "rate list"
            self._set_rate_text(rate)
        description = self.description.text().strip() or item.description
        unit = self.unit_edit.text().strip() or item.unit
        self._finalise(
            quoting.QuoteLine(description, quantity, unit, rate, item.hsn,
                              basis=basis),
            description)

    def _recalculate_from_cost(self):
        """Run the owner's own formulas and show every line of the working.

        The breakdown is on screen rather than folded into one number because
        this is the number they will be asked to justify on the phone, and a
        rate they cannot explain is a rate they will not send.
        """
        quoting = CB.get_quoting()
        quantity = quoting.to_decimal(self.quantity.text()) or Decimal(1)
        description = self.description.text().strip() or self.row.get(
            "Product asked", "")
        unit = self.unit_edit.text().strip() or "nos"

        # A rate typed by hand skips the formula entirely — the cost sheet is
        # a way to WORK a rate out, not the only way to have one, and an item
        # the sheet has no line for (a one-off, an odd size) should not be
        # stuck without a price just because there is no formula for it.
        if self._rate_dirty:
            rate = quoting.to_decimal(self.rate_edit.text())
            self.workings.setPlainText(i18n.t(
                "Rate entered by hand — the cost-sheet working below is not "
                "shown for a rate you typed yourself. Clear the rate box to "
                "let Prism work it out again."))
            self._finalise(
                quoting.QuoteLine(description, quantity, unit, rate, "",
                                  basis="entered by hand"),
                description)
            return

        weight = quoting.to_decimal(self.weight.text())
        needs_weight = any(line.basis == quoting.PER_KG
                           for line in self.cost_lines)
        if needs_weight and weight <= 0:
            self.workings.setPlainText(i18n.t(
                "Your cost sheet charges for material by the kilogram, so "
                "Prism needs the weight of one piece before it can work "
                "anything out — or type a rate below yourself."))
            self.preview.setPlainText("")
            self.quote = None
            self.total_label.setText("")
            self.quote_line_label.setText(
                i18n.t("Enter the weight to see the price."))
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

        self._set_rate_text(breakdown.per_piece)
        self._finalise(
            quoting.QuoteLine(description, quantity, unit,
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
            # Built rather than QMessageBox.question(...), for one reason:
            # the static helpers give no way to set a text format, and they
            # default to AutoText. `address` is the customer's own From header,
            # so markup in it would render as markup — in the dialog that
            # confirms who is being sent a quotation, and for how much. The
            # confirmation has to say what is actually about to happen.
            confirm = QMessageBox(
                QMessageBox.Question, i18n.t("Send the quotation"),
                i18n.t("Send this quotation to {who} for "
                       "₹{total}?").replace("{who}", address).replace(
                    "{total}", quoting.indian_currency(self.quote.total)),
                QMessageBox.Yes | QMessageBox.No, self)
            confirm.setTextFormat(Qt.PlainText)
            confirm.setDefaultButton(QMessageBox.No)
            if confirm.exec() != QMessageBox.Yes:
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
                self.subject.text(), self.mail_body.toPlainText(),
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
        # A second quotation on a row that already had one is a revision —
        # said so in the sent log, because "we quoted them twice" and "we
        # revised our quotation" are different stories on the phone.
        revised = bool((self.row.get("Quotation no") or "").strip())
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
            return
        if sent:
            log = getattr(self.parent_dialog, "_log_sent", None)
            if log is not None:
                log("revised" if revised else "quotation", self.row,
                    self.subject.text())


class _CompareDialog(PrismDialog):
    """Four panels side by side, so the owner can hold the customer's ask
    against their own numbers before a price goes out:

        what they asked for  ·  our rates
        materials this job needs  ·  our quotation

    Everything here is read off what the quotation screen already holds —
    the register row, the rate-list matches or cost-sheet lines, the live
    quotation — so it can never disagree with the figure about to be sent.
    Where something is not set up (no cost sheet, no drawing), the panel
    says so in a sentence rather than showing an empty box.
    """

    def __init__(self, quote_dialog, parent=None):
        super().__init__(
            i18n.t("Compare side by side"),
            i18n.t("What they asked for, against what you charge and what "
                   "it takes to make — and the quotation that comes out."),
            icon="grid", parent=parent or quote_dialog, closable=True,
            scrollable=True)
        self.setWindowTitle(i18n.t("Compare side by side"))
        self.resize(1080, 760)
        self.setMinimumSize(760, 520)
        q = quote_dialog
        grid = QGridLayout()
        grid.setHorizontalSpacing(theme.CARD_GAP)
        grid.setVerticalSpacing(theme.CARD_GAP)
        panels = [
            ("mail", i18n.t("What they asked for"), self._asked(q)),
            ("file", i18n.t("Our rates"), self._rates(q)),
            ("archive", i18n.t("Materials this job needs"), self._materials(q)),
            ("pencil", i18n.t("Our quotation"), self._quotation(q)),
        ]
        for index, (icon, title, text) in enumerate(panels):
            grid.addWidget(self._panel(icon, title, text),
                           index // 2, index % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self.body.addLayout(grid)
        self.body.addStretch(1)
        self.footer.set_primary(
            self.button(i18n.t("Back to the quotation"), "primary",
                        icon_name="check", on_click=self.accept))

    # ── the four panels ───────────────────────────────────────────────────
    @staticmethod
    def _panel(icon: str, title: str, text: str) -> QWidget:
        card = C.Card()
        col = card.body((theme.CARD_PAD, theme.SPACE_4,
                         theme.CARD_PAD, theme.SPACE_4), theme.SPACE_2)
        head = QHBoxLayout()
        head.setSpacing(theme.SPACE_2)
        head.addWidget(C.IconPad(icon, theme.ACCENT, 28, theme.R_CONTROL, 14))
        head.addWidget(C.label(title, level="SECTION"), stretch=1)
        col.addLayout(head)
        col.addWidget(C.hairline())
        box = QPlainTextEdit()
        box.setReadOnly(True)
        box.setObjectName("mono")
        box.setPlainText(text)
        box.setMinimumHeight(180)
        box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        col.addWidget(box, stretch=1)
        return card

    @staticmethod
    def _asked(q) -> str:
        row = q.row or {}
        lines = []

        def put(label: str, value):
            value = str(value or "").strip()
            if value:
                lines.append(f"{i18n.t(label):<16} {value}")
        put("Inquiry", row.get("Inquiry no"))
        put("Customer", row.get("Customer"))
        put("Contact", row.get("Contact person"))
        put("Email", row.get("Email"))
        put("Phone", row.get("Phone"))
        put("Received", " ".join(p for p in (row.get("Date received"),
                                             row.get("Time received")) if p))
        lines.append("")
        put("They want", row.get("Product asked"))
        put("Quantity", row.get("Quantity"))
        drawings = _CompareDialog._drawings(row)
        put("Drawing", (", ".join(os.path.basename(d) for d in drawings)
                        if drawings else
                        (row.get("Drawing") or i18n.t("No"))))
        if row.get("Notes"):
            lines += ["", i18n.t("Notes"), "  " + row["Notes"]]
        return "\n".join(lines) or i18n.t("Nothing was recorded for this inquiry.")

    @staticmethod
    def _rates(q) -> str:
        quoting = CB.get_quoting()
        lines = []
        if q.matches:
            lines.append(i18n.t("From your rate list — the rows closest to "
                                "what they asked for:"))
            lines.append("")
            for match in q.matches:
                item = match.item
                lines.append(f"  {item.label}")
                lines.append(f"    ₹{quoting.indian_currency(item.rate)} "
                             f"{i18n.t('per')} {item.unit or 'nos'}"
                             + (f"   HSN {item.hsn}" if item.hsn else ""))
                if item.slabs:
                    slabs = ", ".join(
                        f"₹{quoting.indian_currency(rate)} @ {int(minimum):,}"
                        for minimum, rate in sorted(item.slabs))
                    lines.append(f"    {i18n.t('Quantity slabs')}: {slabs}")
                lines.append(f"    {i18n.t('why')}: {match.reason}")
                lines.append("")
        elif q.items:
            lines.append(i18n.t("Nothing on your rate list matches what they "
                                "asked for. Pick a row by hand on the "
                                "quotation screen, or price it from the cost "
                                "sheet."))
            lines.append("")
        if q.cost_lines:
            lines.append(i18n.t("From your cost sheet:"))
            lines.append("")
            basis_words = {quoting.PER_KG: i18n.t("per kg"),
                           quoting.PER_PIECE: i18n.t("per piece"),
                           quoting.PER_LOT: i18n.t("per lot"),
                           quoting.PERCENT: "%"}
            for line in q.cost_lines:
                unit = basis_words.get(line.basis, line.basis)
                figure = (f"{line.rate:g}%" if line.basis == quoting.PERCENT
                          else f"₹{quoting.indian_currency(line.rate)} {unit}")
                lines.append(f"  {line.name:<28} {figure}")
        if not q.items and not q.cost_lines:
            lines.append(i18n.t("No rate list or cost sheet is set up. Add "
                                "one under Setup → Files."))
        rate_now = (q.rate_edit.text() or "").strip()
        if rate_now:
            lines += ["", i18n.t("Rate on the quotation screen now: ₹{rate} "
                                 "per unit").replace("{rate}", rate_now)]
        return "\n".join(lines).rstrip()

    @staticmethod
    def _materials(q) -> str:
        quoting = CB.get_quoting()
        row = q.row or {}
        lines = []
        materials = [l for l in q.cost_lines if l.basis == quoting.PER_KG]
        processes = [l for l in q.cost_lines if l.basis == quoting.PER_PIECE]
        setup = [l for l in q.cost_lines if l.basis == quoting.PER_LOT]
        overheads = [l for l in q.cost_lines if l.basis == quoting.PERCENT]
        weight = quoting.to_decimal(q.weight.text()) if q.weight.text() else None
        quantity = quoting.to_decimal(q.quantity.text()) or Decimal(1)

        if materials:
            lines.append(i18n.t("Material, from your cost sheet:"))
            for line in materials:
                text = f"  {line.name:<28} ₹{quoting.indian_currency(line.rate)} {i18n.t('per kg')}"
                if weight:
                    total_kg = weight * quantity
                    # "225 kg", not "225.000 kg" — Decimal keeps the places
                    # it was typed with, and a kilogram figure read aloud on
                    # the phone does not carry three noughts.
                    kg = f"{total_kg.normalize():f}"
                    text += (f"   → {kg} kg {i18n.t('for')} "
                             f"{quantity:,.0f} {i18n.t('pieces')} = "
                             f"₹{quoting.indian_currency(line.rate * total_kg)}")
                lines.append(text)
            if not weight:
                lines.append("  " + i18n.t("(type the weight of one piece on "
                                           "the quotation screen to see the "
                                           "total material)"))
            lines.append("")
        if processes:
            lines.append(i18n.t("Work on each piece:"))
            for line in processes:
                lines.append(f"  {line.name:<28} ₹{quoting.indian_currency(line.rate)}")
            lines.append("")
        if setup:
            lines.append(i18n.t("Once per order:"))
            for line in setup:
                lines.append(f"  {line.name:<28} ₹{quoting.indian_currency(line.rate)}")
            lines.append("")
        if overheads:
            lines.append(i18n.t("On top:"))
            for line in overheads:
                lines.append(f"  {line.name:<28} {line.rate:g}%")
            lines.append("")
        drawings = _CompareDialog._drawings(row)
        if drawings:
            lines.append(i18n.t("Drawings filed with this inquiry:"))
            for path in drawings:
                lines.append(f"  {os.path.basename(path)}")
            lines.append("  " + i18n.t("(Count quantities from the drawing "
                                       "on the Inquiries tab gives the "
                                       "take-off)"))
        if not q.cost_lines and not drawings:
            lines.append(i18n.t(
                "Your rate list gives a finished price, so the materials "
                "behind it are not listed here. Add a cost sheet under "
                "Setup → Files — material per kg, work per piece, setup per "
                "order — and this panel will show what the job takes."))
        return "\n".join(lines).rstrip()

    @staticmethod
    def _quotation(q) -> str:
        if q.quote is None:
            return i18n.t("Nothing has been priced yet — fill in the "
                          "quotation screen first.")
        quoting = CB.get_quoting()
        settings = settings_of(q.cfg)
        return quoting.render_text(q.quote, settings.get("company", ""))

    @staticmethod
    def _drawings(row: dict) -> list[str]:
        folder = (row or {}).get("Folder", "")
        try:
            if folder and os.path.isdir(folder):
                return [os.path.join(folder, n) for n in sorted(os.listdir(folder))
                        if n.lower().endswith(DRAWING_EXTENSIONS)]
        except OSError:
            pass
        return []


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
