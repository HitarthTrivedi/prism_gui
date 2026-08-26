"""Inquiry Automation, as a screen rather than a dialog.

The design promotes this out of a modal and gives it lead figures and four
tabs: what arrived, the register, what customers said back, and what has gone
quiet. That order is the working day — you check the post, you look at the
book, you read the replies, you chase the silences.

Every figure and every row is read from the real register CSV through
dashboard_data. The design's spring-manufacturer rows were invented to show the
shape; nothing here invents anything. With no register configured the screen
says so and offers the way in, because zero open inquiries and no register at
all are very different facts and must not look the same.

The existing InquiryDialog is untouched and still does the work — checking the
inbox, quoting, chasing. This screen is the reading surface; the buttons hand
off to it.

Two structural notes, because both were defects:

* The page does **not** sit in one long scroll any more. Header, figures and
  tab strip are fixed, and the tab body takes every remaining pixel and scrolls
  inside itself. A register is read in place, twenty rows at a time, the way it
  is read in Tally — not by scrolling the whole screen past it.
* The "nothing here yet" state is `controls.EmptyState`, which centres itself
  in the full height it is given. This panel used to carry a private, hand-
  copied duplicate of `simple_panels._AddonFrontDoor` — card, icon pad, labels
  and button — which top-anchored a small card over a 63% grey field.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

import dashboard_data as DATA
import i18n
import theme
from widgets import controls as C
from widgets.controls import Card, IconPad, Pill
from widgets.register_table import RegisterTable

TABS = [
    ("arrived", "What arrived"),
    ("register", "Inquiries"),
    ("replies", "What they said back"),
    ("waiting", "Waiting on a reply"),
]


class _FrontDoor(C.EmptyState):
    """controls.EmptyState with one quieter action under the primary one.

    This front door needs two ways forward — run a check, or go back into
    setup — and EmptyState carries a single action by design. Borrowing the
    shared one and appending to the column it already centres is the whole of
    the change; the alternative was what shipped before, a private copy of
    `simple_panels._AddonFrontDoor` that could not centre itself because it was
    a fixed-height card in a top-anchored scroll.
    """

    secondary = Signal()

    def __init__(self, icon: str, title: str, body: str, action_text: str,
                 secondary_text: str = "", parent=None):
        super().__init__(icon, title, body, action_text, parent)
        if not secondary_text:
            return
        column = None
        outer = self.layout()
        for index in range(outer.count()):
            item = outer.itemAt(index)
            if item.layout() is not None:
                column = item.layout()
                break
        if column is None:                  # EmptyState changed shape
            return
        button = C.button(secondary_text, "tertiary")
        button.clicked.connect(self.secondary.emit)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        row.addWidget(button)
        row.addStretch(1)
        column.addLayout(row)


class InquiryPanel(QWidget):
    open_dialog = Signal()          # hand off to the working dialog
    set_up = Signal()               # no register yet — open setup

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._tab = "arrived"
        self._rows: list | None = None      # register cache; None = never read
        self.table = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._header = C.PageHeader(i18n.t("Email automation"))
        root.addWidget(self._header)

        # widgetResizable, so the content is stretched to the viewport and the
        # tab body fills the window — but a page that genuinely overflows
        # scrolls instead of compressing its children past their minimum,
        # which is what makes an empty state print its title over its own
        # icon on a short window.
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._host = QWidget()
        self._col = QVBoxLayout(self._host)
        self._col.setContentsMargins(theme.PAGE_PAD, theme.SPACE_5,
                                     theme.PAGE_PAD, theme.PAGE_PAD)
        self._col.setSpacing(theme.CARD_GAP)
        self._scroll.setWidget(self._host)
        root.addWidget(self._scroll, stretch=1)
        self.refresh()

    # ── build ─────────────────────────────────────────────────────────────
    def refresh(self, reread: bool = True):
        """Rebuild the panel. `reread` False re-renders from the rows already
        in hand — the register is a CSV that may sit on a shared drive, and
        switching tabs is not new information about it."""
        self._drop(self._col)
        self.table = None
        self._clear_actions()

        # The blurb carries the mailbox count once there is more than one —
        # "several inboxes, one register" is the whole reason a firm with
        # three addresses bought this, and the screen should say it is true.
        self._header.set_subtitle(self._watching() or i18n.t(
            "Read the inbox, register every inquiry, quote it, chase it, and "
            "check the PO."))

        if reread or self._rows is None:
            self._rows = DATA.register_rows(self.cfg)
        stats = DATA.inquiry_stats(self.cfg, self._rows)
        if not stats:
            self._col.addWidget(self._not_set_up(), stretch=1)
            for widget in self._waiting_room():
                self._col.addWidget(widget)
            return

        # This screen is a REPORT — figures, and four read-only tabs. Reading a
        # mail, editing a register field and preparing a quotation all happen
        # in the working dialog behind it, and until the door moved into the
        # page header the only way in was "Chase again" — a button that exists
        # solely on the "gone quiet" tab, and only once something is actually
        # overdue. Two brand-new inquiries with nothing overdue yet left this
        # whole screen with no way in at all.
        check = C.button(i18n.t("Check my mail now"), "primary",
                         on_click=self.open_dialog.emit)
        check.setToolTip(i18n.t(
            "Opens the working screen — read each mail, edit the register, "
            "prepare and send a quotation."))
        self._header.add_action(check)
        self._header.add_action(C.button(i18n.t("Edit setup"), "secondary",
                                         on_click=self.set_up.emit))

        self._col.addWidget(self._leads(stats))
        self._col.addWidget(self._tab_bar())
        self._col.addWidget(self._tab_body(), stretch=1)

    def _clear_actions(self):
        row = self._header.actions_row
        while row.count():
            item = row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()   # before setParent(None): avoids ghost-window flash
                widget.setParent(None)
                widget.deleteLater()

    def _drop(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()   # before setParent(None): avoids ghost-window flash
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout():
                self._drop(item.layout())

    def _not_set_up(self) -> QWidget:
        """The empty register, told apart from "never configured".

        A mailbox can be fully set up and tested and still have an empty
        register — nobody has pressed Check yet, or the first check has not
        run. Offering "Set up Email automation" here as the ONLY way forward
        sent a working setup back into the setup sheet in a loop: that button
        reopens Setup, Setup saves and returns here, the register is still
        empty because nothing has actually gone and read the inbox, so the
        same screen greets it again. The way out is Check, not Setup — this
        state now offers whichever one is actually missing.
        """
        from dialogs.inquiry_setup_dialog import accounts_of
        configured = any(a.get("address") for a in accounts_of(self.cfg))

        if configured:
            door = _FrontDoor(
                "inbox", i18n.t("Nothing in the register yet"),
                i18n.t("Your mailbox is set up. Run a check and anything "
                       "waiting there gets a number, a quote and a chase."),
                i18n.t("Check my mail now"), i18n.t("Edit setup"))
            door.clicked.connect(self.open_dialog.emit)
            door.secondary.connect(self.set_up.emit)
            return door
        door = _FrontDoor(
            "inbox", i18n.t("Point Prism at a mailbox to begin"),
            i18n.t("Once it can read the inbox, every inquiry gets a number, "
                   "a quote and a chase — and shows up here."),
            i18n.t("Set up Email automation"))
        door.clicked.connect(self.set_up.emit)
        return door

    # ── the empty register, furnished ─────────────────────────────────────
    def _waiting_room(self) -> list:
        """What a configured-but-empty screen can honestly show underneath its
        empty state.

        A centred empty state fixes the *shape* of this screen and not its
        emptiness — the grey simply moves above and below it. Everything here
        is read from the config and from the register module, never described
        from memory: the mailboxes actually being watched and whether each is
        complete, the folder the CSV will be written to, and the register's own
        status vocabulary. A customer waiting for their first check should be
        able to see where it is going to land and what it will say.
        """
        from dialogs.inquiry_setup_dialog import accounts_of, settings_of
        accounts = [a for a in accounts_of(self.cfg) if a.get("address")]
        if not accounts:
            return []                   # nothing configured, nothing to state

        out = []
        settings = settings_of(self.cfg)
        rows = [(i18n.t("Register file"),
                 self._path(settings.get("folder") or "—"))]
        if (settings.get("company") or "").strip():
            rows.insert(0, (i18n.t("Quoting as"), settings["company"].strip()))
        out.append(self._head(
            i18n.t("Where the first check will land"),
            i18n.t("Every mailbox below feeds the same register.")))
        card = Card()
        col = card.body((theme.CARD_PAD, theme.SPACE_2,
                         theme.CARD_PAD, theme.SPACE_2), spacing=0)
        for index, (name, value) in enumerate(rows):
            if index:
                col.addWidget(C.hairline())
            line = QHBoxLayout()
            line.setContentsMargins(0, theme.SPACE_3 - 1, 0,
                                    theme.SPACE_3 - 1)
            line.addWidget(C.label(name, level="SUPPORT",
                                   colour=theme.NEUTRAL[600]))
            line.addStretch(1)
            line.addWidget(value if isinstance(value, QWidget)
                           else C.label(str(value), level="SUPPORT",
                                        colour=theme.TEXT, weight=500))
            col.addLayout(line)
        out.append(card)

        grid = C.CardGrid(min_col_width=300)
        for account in accounts:
            grid.add(self._mailbox_card(account))
        out.append(grid)

        out.append(self._head(
            i18n.t("What the Status column will say"),
            i18n.t("Prism moves an inquiry along this line as you quote it, "
                   "chase it and close it.")))
        out.append(self._status_ladder())

        columns = self._register_columns()
        if columns:
            out.append(self._head(
                i18n.t("What the register keeps for every inquiry"),
                i18n.t("The columns of the CSV Prism writes. It opens in "
                       "Excel and Tally like any other sheet, and it is yours "
                       "— nothing here is stored anywhere else.")))
            out.append(columns)
        return out

    def _register_columns(self) -> QWidget | None:
        """The register's real column list, straight off the register module.

        A firm deciding whether this replaces their paper book asks exactly
        one question first — what does it write down. Naming the columns from
        `REG.COLUMNS` answers it and cannot drift: add a column to the CSV and
        it appears here.
        """
        import core_bridge as CB
        names = list(getattr(CB.get_register(), "COLUMNS", ()) or ())
        if not names:
            return None
        card = Card()
        col = card.body((theme.CARD_PAD, theme.SPACE_4,
                         theme.CARD_PAD, theme.SPACE_4), spacing=0)
        grid = C.CardGrid(min_col_width=150, gap=theme.SPACE_2)
        for name in names:
            grid.add(Pill(name, "quiet"))
        col.addWidget(grid)
        return card

    @staticmethod
    def _head(title: str, subtitle: str = "") -> C.SectionHeader:
        """A SectionHeader whose subtitle WRAPS.

        controls.SectionHeader builds its subtitle as a plain QLabel, so a
        two-clause explanation becomes one unbreakable line, pushes the page
        wider than the viewport and — with the horizontal scrollbar off —
        silently clips the right-hand column off the screen. The label is
        public, so this wraps it without touching the shared component.
        """
        header = C.SectionHeader(title, subtitle)
        header.subtitle.setWordWrap(True)
        return header

    def _mailbox_card(self, account: dict) -> Card:
        """One configured mailbox. `_complete` is the setup dialog's own test
        for a mailbox Prism can actually sign in to — a half-entered one is
        exactly the reason a first check finds nothing."""
        from dialogs.inquiry_setup_dialog import _complete
        card = Card()
        col = card.body((theme.SPACE_4, theme.SPACE_4,
                         theme.SPACE_4, theme.SPACE_4), spacing=0)
        head = QHBoxLayout()
        head.setSpacing(theme.SPACE_3)
        head.addWidget(IconPad("inbox", theme.ACCENT, 30, theme.R_CONTROL, 15))
        head.addWidget(C.label(account.get("address", ""), level="SUPPORT",
                               colour=theme.TEXT, weight=500), stretch=1)
        ready = bool(_complete(account))
        head.addWidget(Pill(i18n.t("Ready") if ready
                            else i18n.t("Needs a password"),
                            "ok" if ready else "warn"))
        col.addLayout(head)
        col.addSpacing(theme.SPACE_2)
        host = (account.get("host") or "").strip()
        detail = f"{host}:{account.get('port') or 993}" if host else ""
        folder = (account.get("folder") or "INBOX").strip()
        col.addWidget(C.label(" · ".join(p for p in (detail, folder) if p),
                              level="MONO"))
        return card

    def _status_ladder(self) -> Card:
        """The register's own status vocabulary, in its own order, wearing the
        same pill the table does. Read off the register module — this screen
        must never teach a word the CSV does not use."""
        import core_bridge as CB
        statuses = list(getattr(CB.get_register(), "STATUSES", ()) or ())
        card = Card()
        col = card.body((theme.CARD_PAD, theme.SPACE_4,
                         theme.CARD_PAD, theme.SPACE_4), spacing=0)
        row = QHBoxLayout()
        row.setSpacing(theme.SPACE_2)
        for index, status in enumerate(statuses):
            if index:
                row.addWidget(C.label("→", level="META"))
            row.addWidget(Pill(status, DATA.status_tone(status)))
        row.addStretch(1)
        col.addLayout(row)
        return card

    @staticmethod
    def _path(text: str) -> QLabel:
        text = str(text)
        label = C.label(text if len(text) <= 52 else "…" + text[-51:],
                        level="MONO", tooltip=text)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        return label

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

    # ── the figures ───────────────────────────────────────────────────────
    def _leads(self, stats: dict) -> QWidget:
        """Six figures, every one of them read out of the register.

        The four the design leads with, plus the two `inquiry_stats` already
        computes and nothing showed — this week's arrivals and this week's
        quotations. The sparkline under "Arrived this week" is the real
        per-day series and its own total, so the bars and the number can never
        disagree.
        """
        series = DATA.inquiries_per_day(self.cfg, self._rows)
        grid = C.CardGrid(min_col_width=250)
        grid.add(C.MetricCard(i18n.t("Open inquiries"), str(stats["open"]),
                              icon="inbox"))
        grid.add(C.MetricCard(i18n.t("Arrived this week"),
                              str(sum(series)), icon="mail",
                              trend=series or None))
        grid.add(C.MetricCard(i18n.t("Quoted this month"),
                              stats["quoted_value"], icon="file"))
        grid.add(C.MetricCard(i18n.t("Quotes sent this week"),
                              str(stats["quoted_week"]), icon="pencil"))
        grid.add(C.MetricCard(i18n.t("Waiting on a reply"),
                              str(stats["waiting"]), icon="clock",
                              hue=theme.WARN))
        grid.add(C.MetricCard(i18n.t("Win rate, 90 days"),
                              f"{stats['win_rate']:g}%", icon="chart",
                              hue=theme.OK))
        return grid

    # ── tabs ──────────────────────────────────────────────────────────────
    def _tab_bar(self) -> QWidget:
        """The tab strip, with a real count on each tab, and the register's
        search box beside it.

        The counts are not decoration: "Waiting on a reply 0" and "Waiting on
        a reply 6" are the difference between a screen you can ignore and one
        you cannot, and reading that used to cost a click on every tab.
        """
        wrap = QWidget()
        wrap.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE_3)

        counts = self._counts()
        labels = [f"{i18n.t(label)}  {counts[key]}" for key, label in TABS]
        keys = [key for key, _label in TABS]
        current = keys.index(self._tab) if self._tab in keys else 0
        tabs = C.Tabs(labels, current)
        tabs.changed.connect(lambda index: self._pick(keys[index]))
        row.addWidget(tabs)
        row.addStretch(1)

        if self._tab == "register":
            search = C.SearchField(i18n.t("Search the register"))
            search.setMaximumWidth(280)
            search.changed.connect(self._filter)
            row.addWidget(search)
        return wrap

    def _counts(self) -> dict:
        rows = self._rows or []
        return {
            "arrived": len(rows),
            "register": len(DATA.register_view(self.cfg, rows)),
            "replies": len(self._answered()),
            "waiting": len(DATA.waiting_view(self.cfg, rows)),
        }

    def _filter(self, text: str):
        if self.table is not None:
            self.table.filter(text)

    def _pick(self, key: str):
        if key == self._tab:
            return
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

    # ── tab bodies ────────────────────────────────────────────────────────
    def _register_table(self) -> QWidget:
        """The register, as a grid rather than a stack of cards.

        See widgets/register_table.py for why this is a QTableView: the people
        reading this screen spend their day in Tally, where a register shows
        twenty rows and answers to the arrow keys. It takes the whole
        remaining height and scrolls inside itself, so the number of rows you
        can see is the number the window can fit.
        """
        view = DATA.register_view(self.cfg, self._rows)
        if not view:
            return self._empty("list", i18n.t("No inquiries registered yet"),
                               i18n.t("Every mail Prism recognises as an "
                                      "inquiry is given a number and lands "
                                      "here."))
        card = Card()
        card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        col = card.body((0, 0, 0, 0), spacing=0)
        table = RegisterTable(view)
        table.opened.connect(lambda _row: self.open_dialog.emit())
        self.table = table
        col.addWidget(table)
        return card

    def _arrived_list(self) -> QWidget:
        """What the mailbox produced. The register is the record of what Prism
        made of it; this is the raw post, so you can see anything it skipped."""
        rows = list(self._rows or [])
        if not rows:
            return self._empty("mail", i18n.t("Nothing has arrived yet"),
                               i18n.t("Run a check and whatever is waiting in "
                                      "the inbox turns up here."))
        return self._scroller([self._arrived_row(row) for row in rows],
                              boxed=True)

    def _arrived_row(self, row: dict) -> QWidget:
        wrap = QFrame()
        wrap.setObjectName("rowFlat")
        wrap.setAttribute(Qt.WA_StyledBackground, True)
        line = QHBoxLayout(wrap)
        line.setContentsMargins(theme.SPACE_4, theme.SPACE_3,
                                theme.SPACE_4, theme.SPACE_3)
        line.setSpacing(theme.SPACE_4)
        line.addWidget(IconPad("mail", theme.NEUTRAL[600], 34,
                               theme.R_CONTROL, 16))
        stack = QVBoxLayout()
        stack.setSpacing(1)
        stack.addWidget(C.label(row.get("Email") or row.get("Customer", ""),
                                level="SUPPORT", colour=theme.TEXT,
                                weight=500))
        stack.addWidget(C.label(row.get("Product asked", ""), level="META"))
        line.addLayout(stack, stretch=1)
        number = (row.get("Inquiry no") or "").strip()
        if number:
            line.addWidget(C.label(number, level="MONO"))
        status = (row.get("Status") or "").strip()
        line.addWidget(Pill(status or i18n.t("New"), DATA.status_tone(status)))
        when = C.label(row.get("Date received", ""), level="META")
        when.setMinimumWidth(84)
        when.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        line.addWidget(when)
        return wrap

    def _answered(self) -> list[dict]:
        """Rows the customer has actually answered on."""
        return [r for r in (self._rows or [])
                if (r.get("Result") or r.get("Reason if lost")
                    or (r.get("Status") or "").strip() in
                    ("Negotiating", "Accepted", "Converted", "Not converted"))]

    def _replies_list(self) -> QWidget:
        """Rows the customer has answered on, with what Prism thinks follows.

        The design shows a quoted sentence from each reply. The register keeps
        the outcome and the reason, not the message body, so this shows what it
        actually has rather than inventing a quotation.
        """
        answered = self._answered()
        if not answered:
            return self._empty("mail", i18n.t("Nobody has replied yet"),
                               i18n.t("When a customer answers a quotation, "
                                      "the outcome and the reason are kept "
                                      "here beside the inquiry."))
        return self._scroller([self._reply_card(row) for row in answered],
                              boxed=False)

    def _reply_card(self, row: dict) -> QWidget:
        card = Card()
        col = card.body((theme.SPACE_4, theme.SPACE_4,
                         theme.SPACE_4, theme.SPACE_4), spacing=0)
        head = QHBoxLayout()
        head.setSpacing(theme.SPACE_3)
        head.addWidget(C.label(row.get("Customer", ""), level="CARD_TITLE"),
                       stretch=1)
        status = (row.get("Status") or "").strip()
        head.addWidget(Pill(status, DATA.status_tone(status)))
        head.addWidget(C.label(row.get("Last contact", ""), level="META"))
        col.addLayout(head)
        detail = (row.get("Reason if lost") or row.get("Result")
                  or row.get("Notes") or "")
        if detail:
            col.addSpacing(theme.SPACE_2)
            col.addWidget(C.label(detail, level="SUPPORT",
                                  colour=theme.NEUTRAL[700], wrap=True))
        col.addSpacing(theme.SPACE_3)
        # Through the same formatter the register column uses. Read straight
        # off the row it printed the CSV's raw digits — "quoted 210000" beside
        # a table showing ₹2,10,000 for the same inquiry.
        note = QLabel(i18n.t("Inquiry {num} · quoted {value}").format(
            num=row.get("Inquiry no", ""),
            value=DATA.rupees(row.get("Quotation value"))))
        note.setObjectName("well")
        note.setAttribute(Qt.WA_StyledBackground, True)
        note.setStyleSheet(
            f"#well {{ background: {theme.INFO_BG};"
            f" border-radius: {theme.R_CONTROL}px;"
            f" padding: {theme.SPACE_2 + 1}px {theme.SPACE_3}px;"
            f" {theme.type_css('META', theme.INFO_INK)} }}")
        col.addWidget(note)
        return card

    def _waiting_list(self) -> QWidget:
        due = DATA.waiting_view(self.cfg, self._rows)
        if not due:
            return self._empty("check", i18n.t("Nothing is overdue a chase"),
                               i18n.t("Every quotation you have sent has "
                                      "either been answered or is still "
                                      "inside its follow-up window."))
        return self._scroller([self._waiting_row(row) for row in due],
                              boxed=True)

    def _waiting_row(self, row: dict) -> QWidget:
        wrap = QFrame()
        wrap.setObjectName("rowFlat")
        wrap.setAttribute(Qt.WA_StyledBackground, True)
        line = QHBoxLayout(wrap)
        line.setContentsMargins(theme.SPACE_4, theme.SPACE_3,
                                theme.SPACE_4, theme.SPACE_3)
        line.setSpacing(theme.SPACE_4)
        line.addWidget(IconPad("clock", theme.WARN, 34, theme.R_CONTROL, 16))
        stack = QVBoxLayout()
        stack.setSpacing(1)
        stack.addWidget(C.label(row["customer"], level="SUPPORT",
                                colour=theme.TEXT, weight=500))
        stack.addWidget(C.label(
            i18n.t("{item} · sent {n} days ago").format(
                item=row["item"], n=row["sent_days"]), level="META"))
        line.addLayout(stack, stretch=1)
        if row.get("num"):
            line.addWidget(C.label(row["num"], level="MONO"))
        line.addWidget(C.label(row["reminders"], level="META"))
        chase = C.button(i18n.t("Chase again"), "secondary", small=True,
                         on_click=self.open_dialog.emit)
        chase.setToolTip(i18n.t("Opens Email automation to send the chase"))
        line.addWidget(chase)
        return wrap

    # ── bits ──────────────────────────────────────────────────────────────
    def _scroller(self, rows: list, boxed: bool) -> QWidget:
        """A list that takes the whole remaining height and scrolls inside
        itself, rather than growing the page. `boxed` puts the rows inside one
        card split by hairlines; otherwise they are already cards."""
        inner = QWidget()
        box = QVBoxLayout(inner)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0 if boxed else theme.CARD_GAP)
        for index, row in enumerate(rows):
            if boxed and index:
                box.addWidget(C.hairline())
            box.addWidget(row)
        box.addStretch(1)

        # style.qss already paints QScrollArea and the widget inside it
        # transparent, so a boxed list shows the Card's white through it and
        # an unboxed one shows the canvas. Setting a background here instead
        # would cascade onto every row and beat #rowFlat's own hover rule.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(inner)
        if not boxed:
            return scroll

        card = Card()
        card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        col = card.body((0, 0, 0, 0), spacing=0)
        col.addWidget(scroll)
        return card

    def _empty(self, icon: str, title: str, body: str) -> QWidget:
        """One tab with nothing in it. Centred in the height it is given —
        never a grey line of text at the top of a short card."""
        return C.EmptyState(icon, title, body)
