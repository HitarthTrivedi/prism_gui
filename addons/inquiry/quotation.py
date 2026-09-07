"""Quoting: the price that goes out, and the two windows around it.

Peeled out of addons/inquiry/dialog.py, which was 4,622 lines and four or
five distinct screens welded together. QuotationDialog alone is a whole
second product surface -- the customer never thinks of "quoting" as part of
"reading the inbox", and it did not need to live in the same file.

Nothing here changed on the way out; this is a move. addons/inquiry/dialog.py
imports these names back and re-exports them, so every existing
`UI.QuotationDialog` in the tests keeps resolving and findChild() keeps
working (it matches on the class object, not on where it was defined).

DRAWING_EXTENSIONS and _warning_css came along because they are the only two
names this surface needed from the parent. Taking them makes the dependency
one-way -- inquiry_dialog imports quotation_dialog and never the reverse --
rather than a cycle held together by deferred imports.
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from decimal import Decimal
from PySide6.QtCore import QDate, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor
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
from addons.inquiry.setup import (
    InquirySetupDialog, accounts_of, is_ready, settings_of,
)
from widgets import controls as C
from workers import DraftWorker, InboxCheckWorker, POReadWorker, SendWorker


DRAWING_EXTENSIONS = (".dwg", ".dxf", ".pdf")


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
        # The quotation is the literal deliverable this dialog exists to
        # produce — it belongs in Artifacts the same way a rendered reel
        # does, not only in the inquiry's own job folder. Grouped under the
        # inquiry number rather than the quote number: the inquiry number is
        # the stable thread ID across quote → order → payment, so a chase or
        # revision later lands in the SAME folder as the original quote.
        try:
            task = self.row.get("Inquiry no", "") or self.quote.number
            CB.config.save_artifact(written, self.quote.number, kind="quote",
                                    task=task)
        except Exception:                               # noqa: BLE001
            pass

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
                    self.subject.text(), body=self.mail_body.toPlainText())


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
