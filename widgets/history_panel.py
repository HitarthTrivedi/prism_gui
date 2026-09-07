"""The History screen: every past run, re-rendered from its record."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget,
)

import dashboard_data as DATA
import i18n
import theme
from widgets import controls as C
from widgets.panel_base import (
    _RunRow,
    ADDONS, _Elided, _kind_of, _plain_title, _state_of, bucket_for, _focusable_row, Page,
)


class _AbortedRow(QFrame):
    """A run of consecutive never-started records, folded into one line.

    Six identical "Untitled task / No tool recorded / Failed" rows is what
    made History look broken; on this machine there are eighty-six. Nothing is
    hidden — the count is stated, the "Never ran" filter chip lists them
    individually, and clicking here expands them in place.
    """

    expand = Signal()

    def __init__(self, count: int, parent=None):
        super().__init__(parent)
        self.setObjectName("rowFlat")
        self.setAttribute(Qt.WA_StyledBackground, True)
        _focusable_row(self)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setMinimumHeight(C.MIN_TARGET + 22)

        row = QHBoxLayout(self)
        row.setContentsMargins(theme.SPACE_4, theme.SPACE_3,
                               theme.SPACE_4, theme.SPACE_3)
        row.setSpacing(theme.SPACE_3)
        row.addWidget(C.IconPad("archive", theme.NEUTRAL[600], 26,
                                theme.R_CHIP, 14))
        stack = QVBoxLayout()
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(1)
        stack.addWidget(_Elided(
            i18n.t("{n} runs that never started").format(n=count),
            "SUPPORT", theme.TEXT, weight=500))
        stack.addWidget(_Elided(
            i18n.t("No task text and no tool was recorded for any of them."),
            "META"))
        row.addLayout(stack, stretch=1)
        row.addWidget(C.button(i18n.t("Show them"), "tertiary",
                               icon_name="chevron-down",
                               on_click=self.expand.emit))

        self.setAccessibleName(i18n.t("{n} runs that never started").format(
            n=count))

    def mousePressEvent(self, event):
        self.expand.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.expand.emit()
            return
        super().keyPressEvent(event)


class HistoryPanel(Page):
    """Every run, grouped by date, searchable and filterable by outcome.

    Reads the disk only when the screen is opened. MainWindow builds all
    eleven screens inside its own __init__, and this one used to open forty
    JSON files there — on a shared or synced workspace folder that is startup
    latency for a screen nobody has asked for yet.
    """

    TITLE = "History"
    BLURB = "Every past run, re-rendered out of its stored record."

    open_run = Signal(str)          # path of the run record
    navigate = Signal(str)          # a key for MainWindow._handle_command

    LAZY = True
    LIMIT = 200
    COLLAPSE_AT = 3                 # fold this many consecutive aborts

    def __init__(self, cfg: dict = None, parent=None):
        self._runs = []
        self._expanded = set()
        self._chips = None
        self._chip_counts = None
        super().__init__(cfg, parent)

    def header_actions(self):
        return [C.button(i18n.t("New task"), "primary", icon_name="plus",
                         on_click=lambda: self.navigate.emit("workbench"))]

    def build(self):
        self._runs = DATA.recent_runs(self.cfg, self.LIMIT) or []
        self._expanded = set()
        self._chips = None
        self._chip_counts = None

        bar = C.Toolbar()
        self._search = C.SearchField(
            i18n.t("Search a task, or a tool that ran it"))
        self._search.changed.connect(lambda _text: self._render())
        bar.add(self._search, stretch=1)
        self._count = C.label("", role="meta")
        bar.add(self._count)
        self._col.addWidget(bar)

        self._chip_host = QWidget()
        self._chip_col = QVBoxLayout(self._chip_host)
        self._chip_col.setContentsMargins(0, 0, 0, 0)
        self._chip_col.setSpacing(0)
        self._col.addWidget(self._chip_host)

        self._list = QWidget()
        self._list_col = QVBoxLayout(self._list)
        self._list_col.setContentsMargins(0, 0, 0, 0)
        self._list_col.setSpacing(theme.CARD_GAP)
        self._col.addWidget(self._list, stretch=1)
        self._render()

    # -- filters ----------------------------------------------------------
    def _sync_chips(self, counts: dict):
        """Rebuilt only when the COUNTS change, never on a click — a chip row
        that deletes itself from inside its own clicked handler is a crash
        waiting for a slow machine."""
        if self._chips is not None and counts == self._chip_counts:
            return
        current = self._chips.current() if self._chips else "all"
        self._chip_counts = dict(counts)
        self._drop(self._chip_col)
        self._chips = C.FilterChips([
            ("all", i18n.t("All"), counts["all"]),
            ("completed", i18n.t("Completed"), counts["completed"]),
            ("failed", i18n.t("Failed"), counts["failed"]),
            ("cancelled", i18n.t("Never ran"), counts["cancelled"]),
        ], current)
        self._chips.changed.connect(lambda _value: self._render())
        self._chip_col.addWidget(self._chips)

    def _hits(self, run: dict, query: str) -> bool:
        parts = [(run.get("title") or "").lower()]
        parts += [t.lower() for t in (run.get("tools") or [])]
        kind = _kind_of(run.get("title", ""))
        if kind:
            parts.append(ADDONS[kind].lower())
        return any(query in part for part in parts)

    # -- render -----------------------------------------------------------
    def _render(self):
        self._drop(self._list_col)
        runs = self._runs
        counts = {"all": len(runs), "completed": 0, "failed": 0, "cancelled": 0}
        states = []
        for run in runs:
            state = _state_of(run)
            states.append(state)
            counts[state] += 1
        self._sync_chips(counts)

        want = self._chips.current() if self._chips else "all"
        query = (self._search.text() or "").strip().lower()
        rows = [(run, state) for run, state in zip(runs, states)
                if (want == "all" or state == want)
                and (not query or self._hits(run, query))]
        self._count.setText(i18n.t("{shown} of {total} runs").format(
            shown=len(rows), total=len(runs)))

        if not runs:
            self._list_col.addWidget(C.EmptyState(
                "inbox", i18n.t("No runs yet"),
                i18n.t("Every task you start is kept here — what you asked "
                       "for, which tools ran it, and what came back. Use "
                       "“New task” at the top of this screen to begin.")),
                stretch=1)
            return
        if not rows:
            self._list_col.addWidget(C.EmptyState(
                "search", i18n.t("Nothing matches that"),
                i18n.t("Try a different word, or show every run again.")),
                stretch=1)
            return

        groups: list[tuple[str, list]] = []
        for run, state in rows:
            bucket = bucket_for(run.get("when", ""), run.get("stamp", 0.0))
            if not groups or groups[-1][0] != bucket:
                groups.append((bucket, []))
            groups[-1][1].append((run, state))

        folding = want == "all" and not query
        for bucket, items in groups:
            self._list_col.addWidget(C.SectionHeader(
                i18n.t(bucket),
                i18n.t("1 run") if len(items) == 1
                else i18n.t("{n} runs").format(n=len(items))))
            card = C.Card()
            col = card.body((0, 0, 0, 0), spacing=0)

            # Real work first, in date order; the runs that never started
            # gathered into ONE row at the foot of the group.
            #
            # This used to fold each CONSECUTIVE stretch of aborts where it
            # sat, which on real data produced folds of 52, then 3, then 11
            # scattered between single real runs — and because a fold row
            # carries no date, the column read as though it had no order at
            # all. Aborted runs are also the overwhelming majority here (66 of
            # 82, every one the same Chrome failure), so leaving them inline
            # buried the fifteen runs that actually did something.
            #
            # Nothing is hidden: the count is stated, "Show them" expands the
            # group, and the "Never ran" chip lists them on their own.
            aborted = sum(1 for _r, s in items if s == "cancelled")
            fold_them = (folding and bucket not in self._expanded
                         and aborted >= self.COLLAPSE_AT)
            shown = ([(r, s) for r, s in items if s != "cancelled"]
                     if fold_them else items)

            first = True
            for run, state in shown:
                if not first:
                    col.addWidget(C.hairline())
                row = _RunRow(run, state)
                row.activated.connect(
                    lambda p=run.get("path", ""): p and self.open_run.emit(p))
                col.addWidget(row)
                first = False
            if fold_them:
                if not first:
                    col.addWidget(C.hairline())
                fold = _AbortedRow(aborted)
                fold.expand.connect(lambda b=bucket: self._expand(b))
                col.addWidget(fold)
            self._list_col.addWidget(card)
        self._list_col.addStretch(1)

    def _expand(self, bucket: str):
        self._expanded.add(bucket)
        self._render()


# ── the add-on front doors ──────────────────────────────────────────────────
