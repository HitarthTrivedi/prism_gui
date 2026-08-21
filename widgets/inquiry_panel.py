"""Inquiry Automation, as a screen rather than a dialog.

The design promotes this out of a modal and gives it four lead figures and four
tabs: what arrived, the register, what customers said back, and what has gone
quiet. That order is the working day — you check the post, you look at the book,
you read the replies, you chase the silences.

Every figure and every row is read from the real register CSV through
dashboard_data. The design's spring-manufacturer rows were invented to show the
shape; nothing here invents anything. With no register configured the screen
says so and offers the way in, because zero open inquiries and no register at
all are very different facts and must not look the same.

The existing InquiryDialog is untouched and still does the work — checking the
inbox, quoting, chasing. This screen is the reading surface; the buttons hand
off to it.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

import dashboard_data as DATA
import i18n
import theme
from widgets.controls import Avatar, Card, IconPad, Pill

TABS = [
    ("arrived", "What arrived"),
    ("register", "Inquiries"),
    ("replies", "What they said back"),
    ("waiting", "Waiting on a reply"),
]


def _label(text: str, role: str = "", size: float = 0, colour: str = "",
           weight: int = 0, wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    if role:
        lbl.setObjectName(role)
    bits = []
    if size:
        bits.append(f"font-size: {size}px;")
    if colour:
        bits.append(f"color: {colour};")
    if weight:
        bits.append(f"font-weight: {weight};")
    if bits:
        lbl.setStyleSheet(" ".join(bits) + " background: transparent;")
    lbl.setWordWrap(wrap)
    return lbl


class LeadStat(Card):
    """One of the four figures across the top — icon pad, number, caption."""

    def __init__(self, icon_name: str, hue: str, value: str, caption: str,
                 parent=None):
        super().__init__(parent=parent)
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(IconPad(icon_name, hue, 34, 9, 17))
        stack = QVBoxLayout()
        stack.setSpacing(0)
        stack.addWidget(_label(value, "statSm"))
        stack.addWidget(_label(caption, size=12, colour=theme.NEUTRAL[700]))
        row.addLayout(stack, stretch=1)
        body = self.body((18, 14, 18, 14), spacing=0)
        body.addLayout(row)


class InquiryPanel(QScrollArea):
    open_dialog = Signal()          # hand off to the working dialog
    set_up = Signal()               # no register yet — open setup

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._tab = "arrived"
        self._rows: list | None = None      # register cache; None = never read
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._host = QWidget()
        self.setWidget(self._host)
        self._col = QVBoxLayout(self._host)
        self._col.setContentsMargins(40, 32, 40, 32)
        self._col.setSpacing(18)
        self.refresh()

    # ── build ─────────────────────────────────────────────────────────────
    def refresh(self, reread: bool = True):
        """Rebuild the panel. `reread` False re-renders from the rows already
        in hand — the register is a CSV that may sit on a shared drive, and
        switching tabs is not new information about it."""
        while self._col.count():
            item = self._col.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._drop(item.layout())

        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(_label(i18n.t("Email automation"), "h2"))
        # The blurb carries the mailbox count once there is more than one —
        # "several inboxes, one register" is the whole reason a firm with
        # three addresses bought this, and the screen should say it is true.
        watching = self._watching()
        head.addWidget(_label(
            watching or
            i18n.t("Read the inbox, register every inquiry, quote it, chase "
                   "it, and check the PO."),
            size=13, colour=theme.NEUTRAL[600]))
        self._col.addLayout(head)

        if reread or self._rows is None:
            self._rows = DATA.register_rows(self.cfg)
        stats = DATA.inquiry_stats(self.cfg, self._rows)
        if not stats:
            self._col.addWidget(self._not_set_up())
            self._col.addStretch(1)
            return

        self._col.addLayout(self._leads(stats))
        self._col.addWidget(self._tab_strip(), alignment=Qt.AlignLeft)
        self._col.addWidget(self._tab_body())
        self._col.addStretch(1)

    def _drop(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._drop(item.layout())

    def _not_set_up(self) -> QWidget:
        card = Card(radius=theme.R_HERO)
        col = card.body((30, 40, 30, 44), spacing=0)
        col.setAlignment(Qt.AlignHCenter)
        col.addWidget(IconPad("inbox", theme.OK, 56, 14, 26),
                      alignment=Qt.AlignHCenter)
        col.addSpacing(16)
        col.addWidget(_label(i18n.t("Point Prism at a mailbox to begin"),
                             size=15, weight=500), alignment=Qt.AlignHCenter)
        col.addSpacing(6)
        col.addWidget(_label(
            i18n.t("Once it can read the inbox, every inquiry gets a number, "
                   "a quote and a chase — and shows up here."),
            size=13, colour=theme.NEUTRAL[500], wrap=True),
            alignment=Qt.AlignHCenter)
        col.addSpacing(20)
        btn = QPushButton(i18n.t("Set up Email automation"))
        btn.setObjectName("primaryBtn")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(self.set_up.emit)
        col.addWidget(btn, alignment=Qt.AlignHCenter)
        return card

    def _watching(self) -> str:
        """"Watching sales@… and 2 more — one register." — or "" for one
        mailbox, where the standing blurb says everything already."""
        try:
            from dialogs.inquiry_setup_dialog import accounts_of
            addresses = [a.get("address", "") for a in accounts_of(self.cfg)
                         if a.get("address")]
        except Exception:                   # noqa: BLE001
            return ""
        if len(addresses) < 2:
            return ""
        return (i18n.t("Watching {first} and {n} more — every inquiry lands "
                       "in one register.")
                .replace("{first}", addresses[0])
                .replace("{n}", str(len(addresses) - 1)))

    def _leads(self, stats: dict) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addWidget(LeadStat("inbox", theme.OK, str(stats["open"]),
                               i18n.t("Open inquiries")))
        row.addWidget(LeadStat("file", theme.ACCENT, stats["quoted_value"],
                               i18n.t("Quoted this month")))
        row.addWidget(LeadStat("clock", theme.WARN, str(stats["waiting"]),
                               i18n.t("Waiting on a reply")))
        row.addWidget(LeadStat("chart", theme.OK, f"{stats['win_rate']:g}%",
                               i18n.t("Win rate, 90 days")))
        return row

    def _tab_strip(self) -> QWidget:
        strip = QFrame()
        strip.setObjectName("tabStrip")
        strip.setAttribute(Qt.WA_StyledBackground, True)
        row = QHBoxLayout(strip)
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(4)
        for key, label in TABS:
            btn = QPushButton(i18n.t(label))
            btn.setObjectName("tabBtn")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setProperty("cur", key == self._tab)
            btn.clicked.connect(lambda _=False, k=key: self._pick(k))
            row.addWidget(btn)
        return strip

    def _pick(self, key: str):
        self._tab = key
        # Re-render, do not re-read: every tab is a different view of the same
        # rows, and the register is a CSV that may be on a shared drive, open
        # in Excel, or on a disconnected mount. An explicit refresh() — or the
        # working dialog closing — is what should cost a read.
        self.refresh(reread=False)

    def _tab_body(self) -> QWidget:
        if self._tab == "register":
            return self._register_table()
        if self._tab == "waiting":
            return self._waiting_list()
        if self._tab == "replies":
            return self._replies_list()
        return self._arrived_list()

    # ── tabs ──────────────────────────────────────────────────────────────
    def _register_table(self) -> QWidget:
        card = Card()
        col = card.body((0, 0, 0, 0), spacing=0)

        head = QFrame()
        hrow = QHBoxLayout(head)
        hrow.setContentsMargins(18, 11, 18, 11)
        hrow.setSpacing(0)
        for text, width in ((i18n.t("INQUIRY #"), 150),
                            (i18n.t("CUSTOMER · ITEM"), 0),
                            (i18n.t("QTY"), 90), (i18n.t("AMOUNT"), 110),
                            (i18n.t("STATUS"), 100)):
            lbl = _label(text, "colHead")
            if width:
                lbl.setFixedWidth(width)
                hrow.addWidget(lbl)
            else:
                hrow.addWidget(lbl, stretch=1)
        col.addWidget(head)
        col.addWidget(self._hairline())

        view = DATA.register_view(self.cfg, self._rows)
        for i, row in enumerate(view):
            if i:
                col.addWidget(self._hairline())
            col.addWidget(self._register_row(row))
        if not view:
            col.addWidget(self._empty(i18n.t("No inquiries registered yet.")))
        return card

    def _register_row(self, row: dict) -> QWidget:
        wrap = QFrame()
        wrap.setObjectName("rowFlat")
        line = QHBoxLayout(wrap)
        line.setContentsMargins(18, 12, 18, 12)
        line.setSpacing(0)

        num = _label(row["num"], size=13,
                     colour=theme.NEUTRAL[500])
        num.setFixedWidth(150)
        line.addWidget(num)

        who = QHBoxLayout()
        who.setSpacing(10)
        who.addWidget(Avatar(row["customer"], 28, self._avatar_hue(row["customer"])))
        stack = QVBoxLayout()
        stack.setSpacing(0)
        stack.addWidget(_label(row["customer"], size=13, weight=500))
        stack.addWidget(_label(row["item"], size=11.5, colour=theme.NEUTRAL[500]))
        who.addLayout(stack, stretch=1)
        line.addLayout(who, stretch=1)

        qty = _label(row["qty"], size=13, colour=theme.NEUTRAL[700])
        qty.setFixedWidth(90)
        line.addWidget(qty)
        amount = _label(row["amount"], size=13, weight=500)
        amount.setFixedWidth(110)
        line.addWidget(amount)
        pill_wrap = QWidget()
        pw = QHBoxLayout(pill_wrap)
        pw.setContentsMargins(0, 0, 0, 0)
        pw.addWidget(Pill(row["status"], row["tone"]))
        pw.addStretch(1)
        pill_wrap.setFixedWidth(100)
        line.addWidget(pill_wrap)
        return wrap

    @staticmethod
    def _avatar_hue(name: str) -> str:
        """A stable colour per customer, off three that all read on white.

        Stable so the same customer is the same colour every time the register
        is opened — the avatar is only useful as a recognition cue, and a
        colour that moves between sessions is worse than no colour.
        """
        palette = (theme.OK, theme.ACCENT, theme.WARN)
        return palette[sum(map(ord, name or "?")) % len(palette)]

    def _arrived_list(self) -> QWidget:
        """What the mailbox produced. The register is the record of what Prism
        made of it; this is the raw post, so you can see anything it skipped."""
        card = Card()
        col = card.body((0, 0, 0, 0), spacing=0)
        recent = [r for r in self._rows][:12]
        if not recent:
            col.addWidget(self._empty(i18n.t("Nothing has arrived yet.")))
            return card
        for i, row in enumerate(recent):
            if i:
                col.addWidget(self._hairline())
            col.addWidget(self._arrived_row(row))
        return card

    def _arrived_row(self, row: dict) -> QWidget:
        wrap = QFrame()
        wrap.setObjectName("rowFlat")
        line = QHBoxLayout(wrap)
        line.setContentsMargins(18, 13, 18, 13)
        line.setSpacing(14)
        line.addWidget(IconPad("mail", theme.NEUTRAL[600], 34, 9, 16))
        stack = QVBoxLayout()
        stack.setSpacing(1)
        stack.addWidget(_label(row.get("Email") or row.get("Customer", ""),
                               size=13.5, weight=500))
        stack.addWidget(_label(row.get("Product asked", ""), size=12,
                               colour=theme.NEUTRAL[500]))
        line.addLayout(stack, stretch=1)
        status = (row.get("Status") or "").strip()
        line.addWidget(Pill(status or i18n.t("New"),
                            DATA.status_tone(status)))
        when = _label(row.get("Date received", ""), "faint")
        when.setFixedWidth(90)
        when.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        line.addWidget(when)
        return wrap

    def _replies_list(self) -> QWidget:
        """Rows the customer has answered on, with what Prism thinks follows.

        The design shows a quoted sentence from each reply. The register keeps
        the outcome and the reason, not the message body, so this shows what it
        actually has rather than inventing a quotation.
        """
        wrap = QWidget()
        col = QVBoxLayout(wrap)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(12)
        answered = [r for r in self._rows
                    if (r.get("Result") or r.get("Reason if lost")
                        or (r.get("Status") or "").strip() in
                        ("Negotiating", "Accepted", "Converted",
                         "Not converted"))][:8]
        if not answered:
            card = Card()
            card.body((0, 0, 0, 0), spacing=0).addWidget(
                self._empty(i18n.t("Nobody has replied yet.")))
            col.addWidget(card)
            return wrap
        for row in answered:
            col.addWidget(self._reply_card(row))
        return wrap

    def _reply_card(self, row: dict) -> QWidget:
        card = Card()
        col = card.body((18, 16, 18, 16), spacing=0)
        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(_label(row.get("Customer", ""), size=14, weight=600),
                       stretch=1)
        status = (row.get("Status") or "").strip()
        head.addWidget(Pill(status, DATA.status_tone(status)))
        head.addWidget(_label(row.get("Last contact", ""), "faint"))
        col.addLayout(head)
        col.addSpacing(8)
        detail = (row.get("Reason if lost") or row.get("Result")
                  or row.get("Notes") or "")
        if detail:
            col.addWidget(_label(detail, size=13, colour=theme.NEUTRAL[700],
                                 wrap=True))
            col.addSpacing(10)
        # Through the same formatter the register column uses. Read straight
        # off the row it printed the CSV's raw digits — "quoted 210000" beside
        # a table showing ₹2,10,000 for the same inquiry.
        note = QLabel(i18n.t("Inquiry {num} · quoted {value}").format(
            num=row.get("Inquiry no", ""),
            value=DATA.rupees(row.get("Quotation value"))))
        note.setObjectName("well")
        note.setAttribute(Qt.WA_StyledBackground, True)
        note.setStyleSheet(
            f"background: #f7fafd; border-radius: 8px; padding: 9px 12px;"
            f" font-size: 12.5px; color: {theme.ACCENT_RAMP[700]};")
        col.addWidget(note)
        return card

    def _waiting_list(self) -> QWidget:
        card = Card()
        col = card.body((0, 0, 0, 0), spacing=0)
        due = DATA.waiting_view(self.cfg, self._rows)
        if not due:
            col.addWidget(self._empty(
                i18n.t("Nothing is overdue a chase. ")))
            return card
        for i, row in enumerate(due):
            if i:
                col.addWidget(self._hairline())
            col.addWidget(self._waiting_row(row))
        return card

    def _waiting_row(self, row: dict) -> QWidget:
        wrap = QFrame()
        wrap.setObjectName("rowFlat")
        line = QHBoxLayout(wrap)
        line.setContentsMargins(18, 13, 18, 13)
        line.setSpacing(14)
        stack = QVBoxLayout()
        stack.setSpacing(1)
        stack.addWidget(_label(row["customer"], size=13.5, weight=500))
        stack.addWidget(_label(
            i18n.t("{item} · sent {n} days ago").format(
                item=row["item"], n=row["sent_days"]),
            size=11.5, colour=theme.NEUTRAL[500]))
        line.addLayout(stack, stretch=1)
        line.addWidget(_label(row["reminders"], size=11.5,
                              colour=theme.NEUTRAL[500]))
        chase = QPushButton(i18n.t("Chase again"))
        chase.setObjectName("smallBtn")
        chase.setCursor(Qt.PointingHandCursor)
        chase.setToolTip(i18n.t("Opens Email automation to send the chase"))
        chase.clicked.connect(self.open_dialog.emit)
        line.addWidget(chase)
        return wrap

    # ── bits ──────────────────────────────────────────────────────────────
    @staticmethod
    def _hairline() -> QFrame:
        line = QFrame()
        line.setObjectName("cardLine")
        line.setFixedHeight(1)
        return line

    @staticmethod
    def _empty(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            f"color: {theme.NEUTRAL[500]}; font-size: 13px; padding: 34px 20px;")
        return lbl
