"""Settings, as one screen with a section list.

The design folds the rail's old WORKSPACE and CONFIGURE groups — nine separate
rows, each opening the same dialog scrolled to a different place — into a single
page with five sections. This is that page.

It is deliberately a *reading* surface. Every value shown here is already
editable in SetupDialog, which knows how to validate a Groq key, probe a Chrome
version and write the team file safely; duplicating that here would mean two
code paths that must agree about what a valid API key looks like. So each
section states what is currently true and hands off to the dialog to change it.

Four things the design's Settings page does not have are kept, because dropping
them would remove the only route to them:

* **Your role** — which job this copy is set up for, and the shared workspace.
* **API key** and **Chrome** — both reachable only through Setup otherwise.
* **Login tabs** — re-open the AI tools in Chrome to sign in. It is an action
  rather than a setting, but Status is where you go when something is not
  connected, so it sits with the connection facts it fixes.
"""
from __future__ import annotations
import os
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

import core_bridge as CB
import i18n
import identity
import licensing
import theme
import workspace
from widgets.controls import Card, Pill

SECTIONS = [
    ("licence", "Licence"),
    ("agents", "Agents"),
    ("profile", "Profile"),
    ("language", "Language"),
    ("status", "Status"),
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


class SettingsPanel(QScrollArea):
    edit_requested = Signal(str)     # a FOCUS_SECTIONS key for SetupDialog
    login_tabs = Signal()

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._section = "licence"
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._host = QWidget()
        self.setWidget(self._host)
        self._row = QHBoxLayout(self._host)
        self._row.setContentsMargins(40, 32, 40, 32)
        self._row.setSpacing(28)
        self.refresh()

    def show_section(self, key: str):
        """Jump straight to one section — the rail's direct-jump shortcuts
        still land where they always did, just on the page instead of in a
        dialog."""
        self._section = key if key in dict(SECTIONS) else "licence"
        self.refresh()

    # ── build ─────────────────────────────────────────────────────────────
    def refresh(self):
        while self._row.count():
            item = self._row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._drop(item.layout())

        left = QVBoxLayout()
        left.setSpacing(2)
        left.addWidget(_label(i18n.t("Settings"), "h2"))
        left.addSpacing(14)
        for key, label in SECTIONS:
            btn = QPushButton(i18n.t(label))
            btn.setObjectName("secBtn")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setProperty("cur", key == self._section)
            btn.clicked.connect(lambda _=False, k=key: self.show_section(k))
            left.addWidget(btn)
        left.addStretch(1)
        holder = QWidget()
        holder.setFixedWidth(190)
        holder.setLayout(left)
        self._row.addWidget(holder)

        body = QVBoxLayout()
        body.addWidget(self._body())
        body.addStretch(1)
        self._row.addLayout(body, stretch=1)

    def _drop(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._drop(item.layout())

    def _body(self) -> QWidget:
        return {
            "licence": self._licence,
            "agents": self._agents,
            "profile": self._profile,
            "language": self._language,
            "status": self._status,
        }[self._section]()

    # ── sections ──────────────────────────────────────────────────────────
    def _card(self, title: str, blurb: str = ""):
        card = Card()
        col = card.body((26, 24, 26, 24), spacing=0)
        col.addWidget(_label(title, "h4"))
        if blurb:
            col.addSpacing(4)
            col.addWidget(_label(blurb, size=12.5, colour=theme.NEUTRAL[500],
                                 wrap=True))
        col.addSpacing(14)
        return card, col

    def _rows(self, col, pairs, last_line: bool = False):
        """label / value pairs split by hairlines, as the design draws them."""
        for i, (name, value) in enumerate(pairs):
            if i:
                col.addWidget(self._hairline())
            line = QHBoxLayout()
            line.setContentsMargins(0, 11, 0, 11)
            line.addWidget(_label(name, size=13.5, colour=theme.NEUTRAL[500]))
            line.addStretch(1)
            if isinstance(value, QWidget):
                line.addWidget(value)
            else:
                line.addWidget(_label(str(value), size=13.5, weight=500))
            col.addLayout(line)
        if last_line:
            col.addWidget(self._hairline())

    def _edit(self, col, label: str, key: str):
        col.addSpacing(18)
        btn = QPushButton(i18n.t(label))
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda: self.edit_requested.emit(key))
        row = QHBoxLayout()
        row.addWidget(btn)
        row.addStretch(1)
        col.addLayout(row)

    def _licence(self) -> QWidget:
        state = licensing.state()
        card, col = self._card(i18n.t("Licence"))
        plan = (state.plan or "").strip() or i18n.t("No plan")
        seats = (i18n.t("{plan} · {n} seat{s}").format(
            plan=plan, n=state.seats, s="s" if state.seats != 1 else "")
            if state.seats else plan)
        included = ", ".join(sorted(f.title() for f in state.features)) or "—"
        self._rows(col, [
            (i18n.t("Plan"), seats),
            (i18n.t("Renews"), self._when(state.license_ends)),
            (i18n.t("Included"), included),
            (i18n.t("This device"), self._mono(state.license_id or "—")),
        ])
        self._edit(col, "Change licence key", "licence")
        return card

    def _agents(self) -> QWidget:
        card, col = self._card(
            i18n.t("Agents"),
            i18n.t("One tool per category — the router suggests, you decide."))
        chosen = dict(self.cfg.get("agents") or {})
        categories = CB.agents.CATEGORIES
        pairs = []
        for stage in CB.agents.PIPELINE_ORDER:
            if stage == "summary":
                continue
            tool = chosen.get(stage)
            if not tool:
                continue
            pairs.append((categories.get(stage, {}).get("label", stage.title()),
                          tool))
        if not pairs:
            col.addWidget(_label(
                i18n.t("No tools picked yet — Prism will suggest one per "
                       "category the first time you plan a task."),
                size=13, colour=theme.NEUTRAL[500], wrap=True))
        else:
            self._rows(col, pairs)
        self._edit(col, "Re-pick agents", "agents")
        return card

    def _profile(self) -> QWidget:
        me = identity.current()
        card, col = self._card(i18n.t("Profile"))
        root = workspace.root(self.cfg) or "—"
        self._rows(col, [
            (i18n.t("Name"), me.get("name") or i18n.t("This computer")),
            (i18n.t("Role"), (me.get("role") or "—").title()),
            (i18n.t("What you do"), (self.cfg.get("profile") or "—")),
            (i18n.t("Workspace folder"), self._path(root)),
        ])
        self._edit(col, "Change what-you-do", "profile")
        # "Your role" is the Prism-only one the design has no equivalent for:
        # it decides which team member this copy files its work under, which
        # is a different question from "what do you do".
        self._edit(col, "Your role and team", "team")
        return card

    def _language(self) -> QWidget:
        card, col = self._card(
            i18n.t("Language"),
            i18n.t("Prism's own interface, and what the AI tools answer in, "
                   "are set separately."))
        names = {code: label for code, label, _native in i18n.available()} \
            if hasattr(i18n, "available") else {}
        current = i18n.current()
        self._rows(col, [
            (i18n.t("Interface language"), names.get(current, current)),
            (i18n.t("AI output language"),
             names.get(self.cfg.get("ai_language") or current,
                       self.cfg.get("ai_language") or names.get(current, current))),
        ])
        self._edit(col, "Change language", "language")
        return card

    def _status(self) -> QWidget:
        card, col = self._card(i18n.t("Status"))
        key_set = bool((self.cfg.get("api_key") or "").strip())
        chrome = (self.cfg.get("chrome_version") or "").strip()
        offline = workspace.unreachable(self.cfg)
        self._rows(col, [
            (i18n.t("Groq key"),
             Pill(i18n.t("Set") if key_set else i18n.t("Not set"),
                  "accent" if key_set else "warn")),
            (i18n.t("Chrome"), chrome or i18n.t("Auto-detect")),
            (i18n.t("Team folder"),
             Pill(i18n.t("Unreachable") if offline else i18n.t("Reachable"),
                  "err" if offline else "ok")),
        ])
        self._edit(col, "Change API key", "key")
        self._edit(col, "Pin Chrome version", "chrome")

        # Login tabs: an action, not a setting, but this is the screen you are
        # on when a tool says you are not signed in.
        col.addSpacing(18)
        col.addWidget(self._hairline())
        col.addSpacing(14)
        col.addWidget(_label(
            i18n.t("Signed out of a tool? Re-open them all in Chrome and log "
                   "in — Prism drives your own browser, so your sessions are "
                   "the ones it uses."),
            size=12.5, colour=theme.NEUTRAL[500], wrap=True))
        col.addSpacing(12)
        btn = QPushButton(i18n.t("Open login tabs"))
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(self.login_tabs.emit)
        row = QHBoxLayout()
        row.addWidget(btn)
        row.addStretch(1)
        col.addLayout(row)
        return card

    # ── bits ──────────────────────────────────────────────────────────────
    @staticmethod
    def _when(stamp: int) -> str:
        if not stamp or stamp >= 2**31 - 1:
            return "—"
        try:
            return datetime.fromtimestamp(stamp).strftime("%d %B %Y")
        except (OSError, ValueError, OverflowError):
            return "—"

    @staticmethod
    def _mono(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-family: monospace; font-size: 12px;"
                          " background: transparent;")
        return lbl

    @staticmethod
    def _path(text: str) -> QLabel:
        """Elided from the left — the tail of a path is what identifies it,
        and a shared-drive prefix is the same on every row."""
        lbl = QLabel(text if len(text) <= 42 else "…" + text[-41:])
        lbl.setToolTip(text)
        lbl.setStyleSheet("font-size: 13.5px; font-weight: 500;"
                          " background: transparent;")
        return lbl

    @staticmethod
    def _hairline() -> QFrame:
        line = QFrame()
        line.setObjectName("cardLine")
        line.setFixedHeight(1)
        return line
