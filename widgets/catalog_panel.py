"""The Catalog screen: every agent Prism can route to."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QVBoxLayout, QWidget,
)

import core_bridge as CB
import i18n
import theme
from addons import registry
from widgets import controls as C
from widgets.panel_base import (
    LABELS, Page, _CATEGORY_ICONS, _Elided, _categories_of, _clip, _tool_line, _wrapped,
)


class CatalogPanel(Page):
    """The tool registry, as a registry.

    Two cuts of the same data, and both are needed.

    The pipeline grid at the top is the per-CATEGORY cut the old screen had,
    and the reason it stays is the reason the old comment gave: it is the same
    list Settings → Agents edits, so what you read here is what you change
    there. It is also the only place the ORDER is visible — stages run
    top-to-bottom and each feeds the next.

    The tool grid underneath is the per-TOOL cut, which the old screen could
    not show at all: 32 tools exist and nine were on screen. A tool card names
    every category that offers it, so the pipeline above and the grid below
    read as two views of one list rather than two lists.

    On status, and this is deliberate: Prism CANNOT know whether you are
    signed in to Perplexity without driving the browser to find out. So no
    card claims a connection. "In your pipeline" means this copy is set to
    send that stage here; "Built in" means the tool runs inside Prism with no
    account at all, which is the one connectivity fact that is knowable. The
    old screen's green "In use" pill said neither — it was on every card
    unconditionally.
    """

    TITLE = "AI tools"
    BLURB = ("Prism opens each of these in your own Chrome and works it as "
             "you. It cannot check a sign-in from here.")

    open_directory = Signal()       # kept: AIDirectoryDialog's entry point
    navigate = Signal(str)          # a key for MainWindow._handle_command

    def header_actions(self):
        return [C.button(i18n.t("Change which tool runs what"), "secondary",
                         icon_name="sliders",
                         on_click=lambda: self.navigate.emit("agents"))]

    def build(self):
        self._chosen = {stage: tool
                        for stage, tool in (self.cfg.get("agents") or {}).items()
                        if tool}
        stages = [s for s in CB.agents.PIPELINE_ORDER if s != "summary"]
        picked = sum(1 for s in stages if self._chosen.get(s))

        self._col.addWidget(C.SectionHeader(
            i18n.t("Your pipeline"),
            i18n.t("{done} of {total} stages have a tool. Stages run in this "
                   "order and each feeds the next — the same list "
                   "Settings → Agents edits.").format(done=picked,
                                                      total=len(stages))))
        pipeline = C.CardGrid(min_col_width=196)
        pipeline.add_all(
            [self._stage_card(i + 1, stage, self._chosen.get(stage))
             for i, stage in enumerate(stages)]
            + [self._summary_card(len(stages) + 1)])
        self._col.addWidget(pipeline)

        self._col.addWidget(C.SectionHeader(
            i18n.t("Every tool Prism can drive"),
            i18n.t("A tool is offered under more than one category when it is "
                   "genuinely good at both. That is intentional, not a "
                   "duplicate.")))

        bar = C.Toolbar()
        self._search = C.SearchField(
            i18n.t("Search a tool, a category, or what it is good at"))
        self._search.changed.connect(lambda _text: self._populate())
        bar.add(self._search, stretch=1)
        self._count = C.label("", role="meta")
        bar.add(self._count)
        self._col.addWidget(bar)

        chips = [("all", i18n.t("All"))]
        chips += [(stage, i18n.t(LABELS[stage]))
                  for stage in CB.agents.PIPELINE_ORDER if stage in LABELS]
        self._chips = C.FilterChips(chips, "all")
        self._chips.changed.connect(lambda _value: self._populate())
        self._col.addWidget(self._chips)

        self._grid = C.CardGrid(min_col_width=286)
        self._col.addWidget(self._grid)
        self._empty = C.EmptyState(
            "search", i18n.t("No tool matches that"),
            i18n.t("Try a different word, or show every category again."))
        self._empty.setVisible(False)
        self._col.addWidget(self._empty)
        self._empty_at = self._col.count() - 1
        self._col.addStretch(1)
        self._populate()

    # -- the pipeline cut -------------------------------------------------
    def _stage_card(self, index: int, stage: str, tool: str | None):
        meta = CB.agents.CATEGORIES.get(stage, {})
        card = C.Card()
        col = card.body((theme.SPACE_4, theme.SPACE_4,
                         theme.SPACE_4, theme.SPACE_4), theme.SPACE_2)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(theme.SPACE_2)
        top.addWidget(C.IconPad(_CATEGORY_ICONS.get(stage, "grid"),
                                theme.ACCENT, 26, theme.R_CHIP, 14))
        top.addWidget(C.kicker(f"{index:02d}"))
        top.addStretch(1)
        col.addLayout(top)
        col.addWidget(_Elided(i18n.t(LABELS.get(stage, stage)), "CARD_TITLE"))
        col.addWidget(_Elided(meta.get("label", ""), "META"))
        col.addWidget(C.hairline())
        col.addWidget(_tool_line(tool))
        return card

    def _summary_card(self, index: int):
        """The final stage. The old screen skipped it with a `continue`, which
        left the pipeline reading as if it ended at Presentations — it does
        not: summary_agent_name() reuses whichever tool is set for Reasoning,
        then Writing, then Research."""
        card = C.Card()
        col = card.body((theme.SPACE_4, theme.SPACE_4,
                         theme.SPACE_4, theme.SPACE_4), theme.SPACE_2)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(theme.SPACE_2)
        top.addWidget(C.IconPad("list", theme.ACCENT, 26, theme.R_CHIP, 14))
        top.addWidget(C.kicker(f"{index:02d}"))
        top.addStretch(1)
        col.addLayout(top)
        col.addWidget(_Elided(i18n.t("Final summary"), "CARD_TITLE"))
        col.addWidget(_Elided(i18n.t("Reuses your Reasoning tool"), "META"))
        col.addWidget(C.hairline())
        col.addWidget(_tool_line(CB.agents.summary_agent_name(self._chosen)))
        return card

    # -- the per-tool cut -------------------------------------------------
    def _populate(self):
        query = (self._search.text() or "").strip().lower()
        want = self._chips.current()
        self._grid.clear()

        cards, total = [], 0
        for name, entry in CB.agents.AGENT_REGISTRY.items():
            categories = _categories_of(name)
            total += 1
            if want != "all" and want not in categories:
                continue
            if query and not self._matches(name, entry, categories, query):
                continue
            cards.append(self._tool_card(name, entry, categories))
        self._grid.add_all(cards)
        self._grid.setVisible(bool(cards))
        self._empty.setVisible(not cards)
        # Handing the slack to the empty state is what keeps a filter that
        # matches nothing from being a small line of text over a grey field.
        self._col.setStretch(self._empty_at, 0 if cards else 1)
        self._count.setText(i18n.t("{shown} of {total} tools").format(
            shown=len(cards), total=total))

    def _matches(self, name, entry, categories, query) -> bool:
        haystack = [name.lower(), (entry.get("specialty") or "").lower(),
                    (entry.get("cost") or "").lower()]
        for stage in categories:
            haystack.append(LABELS.get(stage, stage).lower())
            haystack.append(
                (CB.agents.CATEGORIES.get(stage, {}).get("label") or "").lower())
        return any(query in part for part in haystack)

    def _tool_card(self, name: str, entry: dict, categories: list) -> QWidget:
        assigned = [stage for stage in CB.agents.PIPELINE_ORDER
                    if self._chosen.get(stage) == name and stage in LABELS]
        local = bool(entry.get("local"))

        card = C.Card()
        col = card.body((theme.CARD_PAD, theme.CARD_PAD,
                         theme.CARD_PAD, theme.CARD_PAD), theme.SPACE_3)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(theme.SPACE_3)
        head.addWidget(C.ToolBadge(name, 28), alignment=Qt.AlignTop)
        stack = QVBoxLayout()
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(0)
        stack.addWidget(_Elided(name, "CARD_TITLE"))
        access = " · ".join(x for x in (
            entry.get("cost", ""), entry.get("avg", ""),
            i18n.t("runs in Prism") if local else i18n.t("opens in Chrome"),
        ) if x)
        stack.addWidget(_Elided(access, "META"))
        head.addLayout(stack, stretch=1)
        # Never a green "Connected": see the class docstring.
        if local:
            head.addWidget(C.Pill(i18n.t("Built in"), "ok"),
                           alignment=Qt.AlignTop)
        elif assigned:
            head.addWidget(C.Pill(i18n.t("In your pipeline"), "accent"),
                           alignment=Qt.AlignTop)
        else:
            head.addWidget(C.Pill(i18n.t("Available"), "quiet"),
                           alignment=Qt.AlignTop)
        col.addLayout(head)

        good_at = _wrapped(_clip(entry.get("specialty", "")), "SUPPORT")
        good_at.setToolTip(" ".join((entry.get("specialty") or "").split()))
        col.addWidget(good_at)

        col.addWidget(C.hairline())
        col.addWidget(C.kicker(i18n.t("Offered under"), muted=True))
        col.addWidget(_Elided(
            " · ".join(i18n.t(LABELS[s]) for s in categories) or i18n.t("None"),
            "META", theme.NEUTRAL[700]))
        if assigned:
            col.addWidget(_Elided(
                i18n.t("Set to run: {stages}").format(
                    stages=", ".join(i18n.t(LABELS[s]) for s in assigned)),
                "META", theme.ACCENT_RAMP[700]))
        return card


# ── History ─────────────────────────────────────────────────────────────────
