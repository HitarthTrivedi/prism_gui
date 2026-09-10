"""
Leads & Outreach — the dense cockpit (the "A" direction)
────────────────────────────────────────────────────────
A high-throughput prospecting surface: a dense, multi-select lead TABLE with a
left filter rail, a Total / Net-new / Saved / avg-fit counter strip, a sticky
bulk-actions bar, and an on-demand right DRAWER that carries the dossier plus a
stop-on-reply sequence preview. The list stays scan-dense; the depth is one
click away in the drawer.

This widget is pure presentation + selection: it takes the qualified dossiers
the pipeline produced and emits a signal when the user asks to verify, export,
save or sequence the checked rows. The dialog wires those to the real workers,
so the cockpit is testable on its own with no pipeline and no network.
"""
from __future__ import annotations

import theme
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPushButton, QScrollArea, QSizePolicy,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

_COLS = ("", "Lead", "Focus", "Fit", "Status", "Signal")
# The deliverability statuses a lead can carry, each with its (ink, tint) tone.
_TONE = {
    "Verified":  (theme.OK_INK,   theme.OK_BG),
    "Guessed":   (theme.WARN_INK, theme.WARN_BG),
    "Catch-all": (theme.WARN_INK, theme.WARN_BG),
    "Unknown":   (theme.WARN_INK, theme.WARN_BG),
    "Invalid":   (theme.ERR_INK,  theme.ERR_BG),
    "No email":  (theme.WARN_INK, theme.WARN_BG),
    "Mailed":    (theme.NEUTRAL[700], theme.NEUTRAL[200]),
}
_MONO = theme.FONT_MONO_STACK.split(",")[0].strip().strip('"')


def status_of(dos, draft=None) -> str:
    """The deliverability label for a dossier — the one thing a bulk sender
    must see per row. A lead already sent to reads 'Mailed'; otherwise the free
    verify verdict (or 'Guessed' for an un-checked pattern address)."""
    if draft is not None and getattr(draft, "status", "") == "sent":
        return "Mailed"
    lead = dos.lead
    if not (lead.email or "").strip():
        return "No email"
    ec = (lead.extra or {}).get("email_check") or ""
    return {"valid": "Verified", "invalid": "Invalid",
            "catch-all": "Catch-all", "unknown": "Unknown"}.get(ec, "Guessed")


class _FitItem(QTableWidgetItem):
    """Sorts by the numeric fit score, not the string — so 100 beats 88."""
    def __init__(self, value: float):
        super().__init__(f"{value:g}")
        self._v = float(value)
        self.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setFont(QFont(_MONO))

    def __lt__(self, other):
        return self._v < getattr(other, "_v", 0.0)


class LeadsCockpit(QWidget):
    """The dense results surface. `set_dossiers` fills it; the four *Requested
    signals carry the checked dossiers out to the dialog's workers."""

    verifyRequested = Signal(list)
    exportRequested = Signal(list)
    saveListRequested = Signal(list)
    sequenceRequested = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dossiers: list = []
        self._draft_by: dict = {}
        self._build()

    # ── construction ──────────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._counter_strip())
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._filter_rail())
        body.addWidget(self._center(), 1)
        body.addWidget(self._drawer())
        holder = QWidget()
        holder.setLayout(body)
        root.addWidget(holder, 1)
        self._refresh_bulk()

    def _counter_strip(self) -> QWidget:
        bar = QFrame()
        bar.setStyleSheet(
            f"QFrame{{background:{theme.CARD};border-bottom:1px solid {theme.HAIRLINE};}}")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(theme.SPACE_5, theme.SPACE_2, theme.SPACE_5, theme.SPACE_2)
        lay.setSpacing(theme.SPACE_5)
        self._c_total = self._counter("Total", "0")
        self._c_new = self._counter("Net-new", "0", accent=True)
        self._c_saved = self._counter("Saved", "0")
        self._c_fit = self._counter("Avg fit", "0")
        for c in (self._c_total, self._c_new, self._c_saved, self._c_fit):
            lay.addWidget(c)
        lay.addStretch(1)
        edge = QLabel("Local · BYO-key · your inbox")
        edge.setStyleSheet(
            f"QLabel{{color:{theme.INFO_INK};background:{theme.INFO_BG};"
            f"border-radius:{theme.R_PILL}px;padding:4px 12px;font-size:11px;"
            f"font-weight:600;}}")
        lay.addWidget(edge)
        return bar

    def _counter(self, label: str, value: str, accent=False) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        lab = QLabel(label)
        lab.setStyleSheet(f"color:{theme.NEUTRAL[600]};font-size:11px;")
        num = QLabel(value)
        ink = theme.ACCENT if accent else theme.TEXT
        num.setStyleSheet(f"color:{ink};font-family:'{_MONO}';font-size:19px;font-weight:600;")
        w._num = num
        v.addWidget(lab)
        v.addWidget(num)
        return w

    def _filter_rail(self) -> QWidget:
        rail = QFrame()
        rail.setFixedWidth(206)
        rail.setStyleSheet(
            f"QFrame{{background:{theme.CARD};border-right:1px solid {theme.HAIRLINE};}}")
        lay = QVBoxLayout(rail)
        lay.setContentsMargins(theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4)
        lay.setSpacing(theme.SPACE_4)

        lay.addWidget(self._rail_head("Search"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("Name, company, title")
        self._search.textChanged.connect(self._apply_filters)
        lay.addWidget(self._search)

        lay.addWidget(self._rail_head("Minimum fit"))
        self._fit_min = QSpinBox()
        self._fit_min.setRange(0, 100)
        self._fit_min.setValue(0)
        self._fit_min.setSuffix("  / 100")
        self._fit_min.valueChanged.connect(self._apply_filters)
        lay.addWidget(self._fit_min)

        lay.addWidget(self._rail_head("Status"))
        self._status_boxes: dict = {}
        for name in ("Verified", "Guessed", "Catch-all", "Unknown", "Invalid",
                     "No email", "Mailed"):
            cb = QCheckBox(name)
            cb.setChecked(True)
            cb.stateChanged.connect(self._apply_filters)
            self._status_boxes[name] = cb
            lay.addWidget(cb)

        lay.addStretch(1)
        note = QLabel("Manual, 1:1 — Prism drafts and queues the touches; you "
                      "send from your own inbox. No auto-DMs.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{theme.NEUTRAL[600]};font-size:11px;")
        lay.addWidget(note)
        return rail

    def _rail_head(self, text: str) -> QLabel:
        lab = QLabel(text.upper())
        lab.setStyleSheet(
            f"color:{theme.NEUTRAL[600]};font-family:'{theme.FONT_HEADING}';"
            f"font-size:11px;letter-spacing:1px;font-weight:600;")
        return lab

    def _center(self) -> QWidget:
        wrap = QWidget()
        col = QVBoxLayout(wrap)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        tb = QFrame()
        tb.setStyleSheet(f"QFrame{{background:{theme.CARD};border-bottom:1px solid {theme.HAIRLINE};}}")
        tlay = QHBoxLayout(tb)
        tlay.setContentsMargins(theme.SPACE_3, theme.SPACE_2, theme.SPACE_3, theme.SPACE_2)
        tlay.setSpacing(theme.SPACE_2)
        self._count_lbl = QLabel("0 of 0")
        self._count_lbl.setStyleSheet(f"color:{theme.NEUTRAL[700]};font-size:12px;")
        tlay.addWidget(self._count_lbl)
        tlay.addStretch(1)
        tlay.addWidget(QLabel("Sort"))
        self._sort = QComboBox()
        self._sort.addItems(["Best fit", "Name A–Z"])
        self._sort.currentIndexChanged.connect(self._resort)
        tlay.addWidget(self._sort)
        col.addWidget(tb)

        self._table = QTableWidget(0, len(_COLS))
        self._table.setHorizontalHeaderLabels(list(_COLS))
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        head = self._table.horizontalHeader()
        head.setSectionResizeMode(1, QHeaderView.Stretch)
        head.setSectionResizeMode(2, QHeaderView.Stretch)
        for c in (0, 3, 4, 5):
            head.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self._table.setColumnWidth(0, 30)
        self._table.itemChanged.connect(self._on_item_changed)
        self._table.currentCellChanged.connect(lambda *_: self._show_selected())
        self._table.setStyleSheet(
            f"QTableWidget{{background:{theme.CARD};border:none;"
            f"gridline-color:{theme.HAIRLINE};}}"
            f"QTableWidget::item{{padding:6px 8px;border-bottom:1px solid {theme.HAIRLINE};}}"
            f"QHeaderView::section{{background:{theme.CARD};color:{theme.NEUTRAL[600]};"
            f"border:none;border-bottom:1px solid {theme.HAIRLINE};padding:7px 8px;"
            f"font-family:'{theme.FONT_HEADING}';font-size:11px;font-weight:600;}}")
        col.addWidget(self._table, 1)

        col.addWidget(self._bulk_bar())
        return wrap

    def _bulk_bar(self) -> QWidget:
        bar = QFrame()
        bar.setStyleSheet(
            f"QFrame{{background:{theme.RAIL};}}"
            f"QLabel{{color:#dfe7f2;font-size:13px;font-weight:600;}}"
            f"QPushButton{{color:#eaf1f8;background:transparent;"
            f"border:1px solid #2c4a68;border-radius:{theme.R_CONTROL}px;padding:7px 13px;"
            f"font-size:12px;font-weight:600;}}"
            f"QPushButton:hover{{background:#1a3550;}}"
            f"QPushButton:disabled{{color:#5f7488;border-color:#233c56;}}"
            f"QPushButton#primary{{background:{theme.ACCENT};border-color:{theme.ACCENT};color:#fff;}}")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(theme.SPACE_4, theme.SPACE_2, theme.SPACE_4, theme.SPACE_2)
        lay.setSpacing(theme.SPACE_2)
        self._sel_lbl = QLabel("0 selected")
        lay.addWidget(self._sel_lbl)
        lay.addStretch(1)
        self._b_verify = QPushButton("Verify free")
        self._b_save = QPushButton("Save to list")
        self._b_export = QPushButton("Export")
        self._b_seq = QPushButton("Add to sequence →")
        self._b_seq.setObjectName("primary")
        self._b_verify.clicked.connect(lambda: self.verifyRequested.emit(self.selected()))
        self._b_save.clicked.connect(lambda: self.saveListRequested.emit(self.selected()))
        self._b_export.clicked.connect(lambda: self.exportRequested.emit(self.selected()))
        self._b_seq.clicked.connect(lambda: self.sequenceRequested.emit(self.selected()))
        for b in (self._b_verify, self._b_save, self._b_export, self._b_seq):
            lay.addWidget(b)
        return bar

    def _drawer(self) -> QWidget:
        self._drawer_w = QScrollArea()
        self._drawer_w.setFixedWidth(340)
        self._drawer_w.setWidgetResizable(True)
        self._drawer_w.setFrameShape(QFrame.NoFrame)
        self._drawer_w.setStyleSheet(
            f"QScrollArea{{background:{theme.CARD};border-left:1px solid {theme.HAIRLINE};}}")
        inner = QWidget()
        self._drawer_lay = QVBoxLayout(inner)
        self._drawer_lay.setContentsMargins(theme.SPACE_4, theme.SPACE_4,
                                            theme.SPACE_4, theme.SPACE_4)
        self._drawer_lay.setSpacing(theme.SPACE_3)
        self._drawer_lay.addStretch(1)
        self._drawer_w.setWidget(inner)
        return self._drawer_w

    # ── data ──────────────────────────────────────────────────────────────────
    def set_dossiers(self, dossiers: list, drafts=None) -> None:
        self._dossiers = list(dossiers or [])
        self._draft_by = {id(d.dossier): d for d in (drafts or [])}
        self._fill_table()
        self._update_counters()
        if self._table.rowCount():
            self._table.setCurrentCell(0, 1)
        self._show_selected()

    def _fill_table(self):
        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)
        self._table.blockSignals(True)
        for idx, dos in enumerate(self._dossiers):
            lead = dos.lead
            row = self._table.rowCount()
            self._table.insertRow(row)

            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            chk.setCheckState(Qt.Unchecked)
            chk.setData(Qt.UserRole, idx)          # sort-safe dossier pointer
            self._table.setItem(row, 0, chk)

            who = lead.name or "(no name)"
            if lead.company:
                who += f"\n{lead.company}"
            name_it = QTableWidgetItem(who)
            self._table.setItem(row, 1, name_it)
            self._table.setItem(row, 2, QTableWidgetItem(
                lead.title or lead.industry or ""))
            self._table.setItem(row, 3, _FitItem(getattr(lead, "fit_score", 0) or 0))

            status = status_of(dos, self._draft_by.get(id(dos)))
            st_it = QTableWidgetItem(status)
            ink, _bg = _TONE.get(status, (theme.NEUTRAL[700], theme.CARD))
            st_it.setForeground(QColor(ink))
            f = QFont(theme.FONT_BODY); f.setWeight(QFont.DemiBold); st_it.setFont(f)
            self._table.setItem(row, 4, st_it)

            sig = "why-now" if getattr(dos, "signal_status", "") == "found" else ""
            sig_it = QTableWidgetItem(sig)
            sig_it.setForeground(QColor(theme.INFO_INK if sig else theme.NEUTRAL[400]))
            self._table.setItem(row, 5, sig_it)
        self._table.blockSignals(False)
        self._table.setSortingEnabled(True)
        self._resort()
        self._apply_filters()
        self._refresh_bulk()

    def _dossier_at(self, row: int):
        it = self._table.item(row, 0)
        return self._dossiers[it.data(Qt.UserRole)] if it is not None else None

    # ── interaction ───────────────────────────────────────────────────────────
    def _resort(self):
        col, order = (3, Qt.DescendingOrder) if self._sort.currentIndex() == 0 \
            else (1, Qt.AscendingOrder)
        self._table.sortItems(col, order)

    def _apply_filters(self):
        fmin = self._fit_min.value()
        q = self._search.text().strip().lower()
        allowed = {n for n, cb in self._status_boxes.items() if cb.isChecked()}
        shown = 0
        for row in range(self._table.rowCount()):
            dos = self._dossier_at(row)
            if dos is None:
                continue
            lead = dos.lead
            ok = (getattr(lead, "fit_score", 0) or 0) >= fmin
            if ok and status_of(dos, self._draft_by.get(id(dos))) not in allowed:
                ok = False
            if ok and q:
                blob = f"{lead.name} {lead.company} {lead.title} {lead.email}".lower()
                ok = q in blob
            self._table.setRowHidden(row, not ok)
            shown += int(ok)
        self._count_lbl.setText(f"{shown} of {len(self._dossiers)}")

    def _on_item_changed(self, item):
        if item.column() == 0:
            self._refresh_bulk()

    def _refresh_bulk(self):
        n = len(self.selected())
        self._sel_lbl.setText(f"{n} selected")
        for b in (self._b_verify, self._b_save, self._b_export, self._b_seq):
            b.setEnabled(n > 0)

    def selected(self) -> list:
        out = []
        for row in range(self._table.rowCount()):
            it = self._table.item(row, 0)
            if it is not None and it.checkState() == Qt.Checked \
                    and not self._table.isRowHidden(row):
                out.append(self._dossiers[it.data(Qt.UserRole)])
        return out

    def _update_counters(self):
        n = len(self._dossiers)
        mailed = sum(1 for d in self._dossiers
                     if status_of(d, self._draft_by.get(id(d))) == "Mailed")
        fits = [getattr(d.lead, "fit_score", 0) or 0 for d in self._dossiers]
        avg = round(sum(fits) / len(fits)) if fits else 0
        self._c_total._num.setText(str(n))
        self._c_new._num.setText(str(n - mailed))
        self._c_saved._num.setText(str(n))
        self._c_fit._num.setText(str(avg))

    # ── drawer ────────────────────────────────────────────────────────────────
    def _show_selected(self):
        row = self._table.currentRow()
        dos = self._dossier_at(row) if row >= 0 else None
        self._render_drawer(dos)

    def _render_drawer(self, dos):
        lay = self._drawer_lay
        while lay.count():
            it = lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        if dos is None:
            lay.addStretch(1)
            return
        lead = dos.lead
        draft = self._draft_by.get(id(dos))

        head = QLabel(f"<b style='font-size:15px'>{lead.name or '(no name)'}</b>")
        lay.addWidget(head)
        sub = QLabel(lead.company or lead.email or "")
        sub.setStyleSheet(f"color:{theme.NEUTRAL[600]};font-size:12px;")
        lay.addWidget(sub)

        lay.addWidget(self._d_card("Fit", f"{getattr(lead,'fit_score',0) or 0:g} / 100 · "
                                          f"{lead.fit_reason or ''}"))
        status = status_of(dos, draft)
        lay.addWidget(self._d_card("Deliverability", status))
        if lead.email:
            em = QLabel(lead.email)
            em.setStyleSheet(f"color:{theme.INFO_INK};font-family:'{_MONO}';font-size:11px;")
            lay.addWidget(em)
        opener = (draft.body if draft is not None else "") or dos.opener or ""
        if opener:
            lay.addWidget(self._d_card("Drafted opener", opener, mono=False, well=True))

        seq = QLabel("STOP-ON-REPLY SEQUENCE · 3 touches")
        seq.setStyleSheet(f"color:{theme.NEUTRAL[600]};font-family:'{theme.FONT_HEADING}';"
                          f"font-size:11px;letter-spacing:1px;font-weight:600;margin-top:6px;")
        lay.addWidget(seq)
        for i, (t, when) in enumerate((("First touch", "today"),
                                       ("Follow-up", "+3 days"),
                                       ("Last touch", "+7 days")), 1):
            step = QLabel(f"<b>{i}</b>  {t} · <span style='color:{theme.NEUTRAL[600]}'>{when}</span>")
            lay.addWidget(step)
        stop = QLabel("↩ Stops automatically the moment they reply")
        stop.setStyleSheet(f"color:{theme.OK_INK};background:{theme.OK_BG};"
                           f"border-radius:{theme.R_CONTROL}px;padding:7px 10px;font-size:11px;")
        stop.setWordWrap(True)
        lay.addWidget(stop)
        guard = QLabel("Target reply 2–4% · auto-stop if bounce > 2% · re-verify 60d")
        guard.setStyleSheet(f"color:{theme.NEUTRAL[600]};font-size:11px;")
        guard.setWordWrap(True)
        lay.addWidget(guard)
        lay.addStretch(1)

    def _d_card(self, label: str, body: str, mono=False, well=False) -> QWidget:
        w = QFrame()
        bg = theme.WELL if well else "transparent"
        w.setStyleSheet(
            f"QFrame{{background:{bg};border:1px solid {theme.HAIRLINE};"
            f"border-radius:{theme.R_CONTROL}px;}}")
        v = QVBoxLayout(w)
        v.setContentsMargins(theme.SPACE_3, theme.SPACE_2, theme.SPACE_3, theme.SPACE_2)
        v.setSpacing(3)
        lab = QLabel(label.upper())
        lab.setStyleSheet(f"color:{theme.NEUTRAL[600]};font-family:'{theme.FONT_HEADING}';"
                          f"font-size:10px;letter-spacing:1px;font-weight:600;")
        v.addWidget(lab)
        val = QLabel(body)
        val.setWordWrap(True)
        val.setStyleSheet(f"color:{theme.TEXT};font-size:12px;"
                          + (f"font-family:'{_MONO}';" if mono else ""))
        v.addWidget(val)
        return w
