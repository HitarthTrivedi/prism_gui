"""Settings, as one screen with a grouped section list and a page that fills.

The design folds the rail's old WORKSPACE and CONFIGURE groups — nine separate
rows, each opening the same dialog scrolled to a different place — into a single
page. This is that page.

It is deliberately a *reading* surface for anything SetupDialog already owns.
Every value shown here is editable there, and that dialog knows how to validate
a Groq key, probe a Chrome version and write the team file safely; duplicating
that here would mean two code paths that must agree about what a valid API key
looks like. So each section states what is currently true and hands off to the
dialog to change it.

What this screen owns outright, because nothing else offers it:

* **The licence in full** — who it is for, which plan, what that plan includes
  and what it does not, and the two irreversible actions (change the key,
  release this computer's seat), quarantined in their own red group.
* **Privacy & data** — where a member's work is actually written, who else can
  read it, and every folder Prism keeps, with doors to open them.
* **Diagnostics** — what this machine can and cannot do, the licence lease
  state, and the tail of the log, plus the export a support call needs. All of
  it was reachable only from a button in the Setup dialog's footer.
* **Login tabs** and the **"Set your name"** flow — an action rather than a
  setting, but Settings is where you go when something is not connected, and a
  solo install has no other route to a display name at all.

Sections that are NOT here, and why: there is no notification system in the
product (nothing schedules, raises or stores one), so a Notifications page
would be a page of dead switches. Appearance has exactly one honest control —
card shadows — which is folded into Diagnostics beside the other
renderer-dependent facts rather than given a page of its own.
"""
from __future__ import annotations
import os
import platform
import sys
from datetime import datetime

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

import app_meta
import core_bridge as CB
import i18n
import identity
import licensing
import paths
import theme
import workspace
from widgets import controls as C
from widgets.controls import Card, Pill

# Lifted out of the rail (see widgets/sidebar.SECONDARY). These are screens,
# not settings, so they are listed here as doors rather than restated as
# controls — Settings is simply where the rail now keeps the things it used to
# spend a permanent row on each.
MORE_LINKS = [
    ("runs", "History", "Every past run, re-rendered from its record"),
    ("catalog", "AI tools", "Every tool Prism can drive, and whether you're "
     "signed in to it"),
    ("guide", "How to use Prism", "What Prism can do, and what to type"),
    ("support", "Help & support", "The common questions, then our team"),
]

# The glyph each door wears, kept out of MORE_LINKS so that table stays the
# three-column shape tests/test_support.py reads.
MORE_ICONS = {"runs": "clock", "catalog": "grid", "guide": "book",
              "support": "help"}

# (key, label, group, blurb). The group is the kicker the section sits under
# in the list; the key is what show_section() and the rail's direct-jump
# shortcuts address. "status" keeps its name because main_window maps both
# "key" and "chrome" onto it before calling us.
#
# All four strings live in ONE table on purpose: devtools/extract_strings.py
# scans module-level tables by name, and `SECTIONS` is on its list — a second
# dict beside it called SECTION_BLURB would ship untranslatable.
SECTIONS = [
    ("licence", "Licence", "Your copy",
     "What this copy is licensed for, which add-ons come with it, and until "
     "when."),
    ("profile", "Profile", "Your copy",
     "Who this copy files its work under, and where that work is kept."),
    ("agents", "Agents", "Configure",
     "One tool per kind of step. The router suggests; you decide."),
    ("language", "Language", "Configure",
     "Prism's own words, and — separately — what the AI tools write back in."),
    ("status", "Connections", "Configure",
     "Everything Prism has to be able to reach: your key, your browser, your "
     "team folder."),
    ("privacy", "Privacy & data", "Configure",
     "Where your work is written, who else can read it, and every folder "
     "Prism keeps."),
    ("diagnostics", "Diagnostics", "Support",
     "What this machine can do, what the licence server last said, and the "
     "file support will ask you for."),
    ("more", "Help & more", "Support",
     "The screens that used to have a rail row each, and the way to reach "
     "us."),
]

# How each licence status reads to a customer. Named STATUS_COPY because that
# is one of the table names extract_strings.py scans; a status word rendered
# through str.title() would be untranslatable and would also print the
# engine's spelling ("tampered") at somebody who has done nothing wrong.
STATUS_COPY = {
    licensing.NONE: ("Not activated", "neutral"),
    licensing.VALID: ("Active", "ok"),
    licensing.GRACE: ("Payment overdue", "warn"),
    licensing.STALE: ("Not checked recently", "warn"),
    licensing.EXPIRED: ("Expired", "err"),
    licensing.TAMPERED: ("Needs re-checking", "err"),
}


# Feature keys arrive from the licence server in lower case. str.title() turns
# "boq" into "Boq" and "bom" into "Bom" — and BOQ is the word this product is
# sold on. Getting a customer's own vocabulary wrong, on the screen that proves
# what they paid for, reads as carelessness however small it is.
_ACRONYMS = {"boq": "BOQ", "bom": "BOM", "gst": "GST", "ai": "AI",
             "crm": "CRM", "erp": "ERP", "pdf": "PDF", "dxf": "DXF"}


def _amp(text: str) -> str:
    """Escape a literal ampersand for a QAbstractButton label.

    Qt reads "&" in button text as a mnemonic marker, so "Privacy & data"
    renders as "Privacy _data" with the d underlined and Alt+D silently bound
    to it. Every label that reaches a button goes through here; labels that
    reach a QLabel must not, because there the escape would print.
    """
    return (text or "").replace("&", "&&")


def feature_name(key: str) -> str:
    """A licence feature key as a person would write it."""
    key = (key or "").strip()
    if not key:
        return ""
    if key.lower() in _ACRONYMS:
        return _ACRONYMS[key.lower()]
    return key.replace("_", " ").replace("-", " ").title()


class SettingsPanel(QWidget):
    edit_requested = Signal(str)     # a FOCUS_SECTIONS key for SetupDialog
    login_tabs = Signal()
    navigate = Signal(str)           # a rail command key — see MORE_LINKS
    rename_requested = Signal()      # set the display name on a solo copy
    tour_requested = Signal()
    licence_changed = Signal()       # this computer's seat was released

    NAV_W = 214

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._section = "licence"
        self._claims_height = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._header = C.PageHeader(i18n.t("Settings"))
        root.addWidget(self._header)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._nav_host = QWidget()
        self._nav_host.setFixedWidth(self.NAV_W)
        self._nav = QVBoxLayout(self._nav_host)
        self._nav.setContentsMargins(theme.PAGE_PAD, theme.SPACE_5,
                                     theme.SPACE_4, theme.SPACE_5)
        self._nav.setSpacing(2)
        body.addWidget(self._nav_host)
        body.addWidget(C.hairline(vertical=True))

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._page = QWidget()
        self._col = QVBoxLayout(self._page)
        self._col.setContentsMargins(theme.PAGE_PAD, theme.SPACE_5,
                                     theme.PAGE_PAD, theme.PAGE_PAD)
        self._col.setSpacing(theme.CARD_GAP)
        self._scroll.setWidget(self._page)
        body.addWidget(self._scroll, stretch=1)

        root.addLayout(body, stretch=1)
        self.refresh()

    def show_section(self, key: str):
        """Jump straight to one section — the rail's direct-jump shortcuts
        still land where they always did, just on the page instead of in a
        dialog."""
        keys = {k for k, _l, _g, _b in SECTIONS}
        self._section = key if key in keys else "licence"
        self.refresh()

    # ── build ─────────────────────────────────────────────────────────────
    def refresh(self):
        self._drop(self._nav)
        self._drop(self._col)
        self._build_nav()
        self._header.set_subtitle(self._who())

        page = {
            "licence": self._licence,
            "profile": self._profile,
            "agents": self._agents,
            "language": self._language,
            "status": self._connections,
            "privacy": self._privacy,
            "diagnostics": self._diagnostics,
            "more": self._more,
        }[self._section]
        label, blurb = next((l, b) for k, l, _g, b in SECTIONS
                            if k == self._section)
        self._col.addWidget(self._head(i18n.t(label), i18n.t(blurb)))
        # A page that hands its slack to an EmptyState sets this, and then the
        # trailing stretch below must NOT be added — two competing stretches
        # is what leaves an empty state floating a third of the way down.
        self._claims_height = False
        page(self._col)
        if not self._claims_height:
            self._col.addStretch(1)

    def _who(self) -> str:
        """The line under the page title: whose copy this is, and on what
        plan. Every part of it is read, never assumed — an unactivated copy
        says so rather than showing a blank."""
        state = licensing.state()
        name = identity.display_name(self.cfg) or i18n.t("This computer")
        plan = (state.plan or "").strip()
        if not plan:
            return i18n.t("{name} · not activated on this computer").format(
                name=name)
        return i18n.t("{name} · {plan} plan").format(
            name=name, plan=self._plan_label(plan))

    @staticmethod
    def _plan_label(plan_key: str) -> str:
        try:
            import plans
            found = plans.PLANS.get((plan_key or "").strip().lower())
            if found:
                return found.label
        except Exception:                            # noqa: BLE001
            pass
        return (plan_key or "").strip().title()

    def _build_nav(self):
        group = ""
        for key, label, section_group, _blurb in SECTIONS:
            if section_group != group:
                group = section_group
                self._nav.addSpacing(theme.SPACE_3 if self._nav.count()
                                     else 0)
                self._nav.addWidget(C.kicker(i18n.t(group), muted=True))
                self._nav.addSpacing(theme.SPACE_1)
            btn = QPushButton(_amp(i18n.t(label)))
            btn.setObjectName("secBtn")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(C.MIN_TARGET)
            btn.setProperty("cur", key == self._section)
            btn.clicked.connect(lambda _=False, k=key: self.show_section(k))
            self._nav.addWidget(btn)
        self._nav.addStretch(1)
        self._nav.addWidget(C.hairline())
        self._nav.addSpacing(theme.SPACE_3)
        self._nav.addWidget(C.label(
            i18n.t("Prism {version}").format(version=app_meta.VERSION),
            level="META"))
        support = C.label(app_meta.SUPPORT_EMAIL, level="META",
                          colour=theme.ACCENT_RAMP[700])
        support.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._nav.addWidget(support)

    def _drop(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # Hide BEFORE unparenting: setParent(None) on a visible widget
                # promotes it to a top-level OS window for the instant before
                # deleteLater() lands — on Windows that's a real titled window
                # plus DWM's open animation, seen as a ghost-window flash on
                # every Settings navigation. A hidden widget promotes silently.
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout():
                self._drop(item.layout())

    # ── shared pieces ─────────────────────────────────────────────────────
    def _facts(self, pairs) -> Card:
        """A card of label / value rows split by hairlines. `value` is either
        a string or an already-built widget."""
        card = Card()
        col = card.body((theme.CARD_PAD, theme.SPACE_2,
                         theme.CARD_PAD, theme.SPACE_2), spacing=0)
        for i, (name, value) in enumerate(pairs):
            if i:
                col.addWidget(C.hairline())
            line = QHBoxLayout()
            line.setContentsMargins(0, theme.SPACE_3 - 1, 0, theme.SPACE_3 - 1)
            line.setSpacing(theme.SPACE_5)
            # Minimum width plus elide, never a fixed width: Hindi and
            # Gujarati run longer than English and a fixed column clips them.
            key_label = C.label(name, level="SUPPORT",
                                colour=theme.NEUTRAL[600], wrap=True)
            key_label.setMinimumWidth(150)
            line.addWidget(key_label, stretch=0)
            if isinstance(value, QWidget):
                line.addStretch(1)
                line.addWidget(value, alignment=Qt.AlignRight)
            else:
                # A long value — the licence's feature list is ten words — has
                # to wrap inside the card instead of running off its right
                # edge, where it was being clipped mid-word.
                text = C.label(str(value), level="SUPPORT",
                               colour=theme.TEXT, weight=500, wrap=True)
                text.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                line.addWidget(text, stretch=1)
            col.addLayout(line)
        return card

    @staticmethod
    def _head(title: str, subtitle: str = "") -> C.SectionHeader:
        """A SectionHeader whose subtitle WRAPS.

        controls.SectionHeader builds its subtitle as a plain QLabel, so a
        two-clause explanation becomes one unbreakable 950px line and pushes
        the whole page wider than the viewport — which, with the horizontal
        scrollbar off, silently clips every status pill off the right edge.
        The label is public, so this wraps it without touching the shared
        component.
        """
        header = C.SectionHeader(title, subtitle)
        header.subtitle.setWordWrap(True)
        return header

    def _note(self, text: str, tone: str = "", kicker: str = "") -> Card:
        """A card carrying one paragraph — the explanations that are the
        difference between a fact and an answer."""
        card = Card()
        if tone == "info":
            card.setStyleSheet(
                f"#card {{ background: {theme.INFO_BG};"
                f" border-radius: {theme.R_CARD}px;"
                f" border: 1px solid {theme.ACCENT_RAMP[200]}; }}")
        col = card.body((theme.CARD_PAD, theme.SPACE_4,
                         theme.CARD_PAD, theme.SPACE_4), spacing=0)
        if kicker:
            col.addWidget(C.kicker(kicker))
            col.addSpacing(theme.SPACE_2)
        col.addWidget(C.label(
            text, level="SUPPORT",
            colour=theme.INFO_INK if tone == "info" else theme.NEUTRAL[700],
            wrap=True))
        return card

    @staticmethod
    def _buttons(widgets) -> QWidget:
        wrap = QWidget()
        wrap.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE_2)
        for widget in widgets:
            row.addWidget(widget)
        row.addStretch(1)
        return wrap

    def _edit_button(self, text: str, key: str, variant: str = "secondary"):
        return C.button(i18n.t(text), variant,
                        on_click=lambda: self.edit_requested.emit(key))

    def _danger(self, title: str, blurb: str, buttons) -> Card:
        """The quarantine. Everything irreversible lives in one red-bordered
        card at the foot of its page, never inline beside a Save."""
        card = Card()
        card.setStyleSheet(
            f"#card {{ background: {theme.ERR_BG};"
            f" border-radius: {theme.R_CARD}px;"
            f" border: 1px solid {theme.ERR_LINE}; }}")
        col = card.body((theme.CARD_PAD, theme.CARD_PAD,
                         theme.CARD_PAD, theme.CARD_PAD), theme.SPACE_2)
        col.addWidget(C.label(title, level="CARD_TITLE", colour=theme.ERR_INK))
        col.addWidget(C.label(blurb, level="SUPPORT",
                              colour=theme.ERR_INK, wrap=True))
        col.addSpacing(theme.SPACE_1)
        col.addWidget(self._buttons(buttons))
        return card

    # ── licence ───────────────────────────────────────────────────────────
    def _licence(self, col):
        state = licensing.state()
        plan = (state.plan or "").strip()
        tone, word = self._licence_tone(state)

        rows = [(i18n.t("Licensed to"), state.customer or "—"),
                (i18n.t("Plan"), self._plan_label(plan) if plan else "—"),
                (i18n.t("Seats"), str(state.seats) if state.seats else "—"),
                (word, self._renews(state)),
                (i18n.t("Status"), Pill(i18n.t(STATUS_COPY.get(
                    state.status, ("Not activated", "neutral"))[0]), tone))]
        col.addWidget(self._facts(rows))

        who = self._plan_who(plan)
        if who:
            col.addWidget(self._note(who, kicker=i18n.t("Who this plan is for")))

        col.addWidget(self._head(
            i18n.t("What's included"),
            i18n.t("Everything Prism does. The padlocked ones are the parts "
                   "this licence does not carry — ask us and we add them to "
                   "the same key.")))
        grid = C.CardGrid(min_col_width=300)
        for key, name, blurb, have in self._features(state):
            grid.add(self._feature_card(key, name, blurb, have))
        col.addWidget(grid)

        col.addWidget(self._head(i18n.t("This computer")))
        col.addWidget(self._facts([
            (i18n.t("Licence id"), self._mono(state.license_id or "—")),
            (i18n.t("Device id"),
             self._mono(self._safe(licensing.device_fingerprint) or "—")),
            (i18n.t("Authorisation"),
             self._safe(licensing.lease_state) or "—"),
        ]))

        col.addWidget(self._danger(
            i18n.t("Careful with these"),
            i18n.t("Both actions stop Prism working on this computer until a "
                   "licence key is entered again. Your settings, your history "
                   "and your files are untouched by either."),
            [self._edit_button("Change licence key", "licence"),
             C.button(i18n.t("Release this computer's seat"), "destructive",
                      on_click=self._release_seat)]))

    @staticmethod
    def _licence_tone(state) -> tuple[str, str]:
        """The pill tone, and the word above the date.

        Semantic tones only — `ok` / `warn` / `err` sit outside the accent
        ramp and never rotate, so a valid licence stays green in a green
        profile and an expired one stays red. That is the one thing this pill
        exists for.

        The date beside it is ALWAYS the licence end the customer was quoted,
        never the token's — somebody told "expires in 4 days" on day 3 of a
        10-day trial will phone you, and be right to.
        """
        tone = STATUS_COPY.get(state.status, ("", "neutral"))[1]
        if state.status in (licensing.VALID, licensing.STALE, licensing.NONE):
            word = (i18n.t("Trial ends") if state.kind == "trial"
                    else i18n.t("Renews"))
        else:
            word = i18n.t("Ended")
        return tone, word

    def _renews(self, state) -> str:
        when = self._when(state.license_ends)
        if state.usable and state.days_left >= 0:
            return i18n.t("{date} · {n} days left").format(
                date=when, n=state.days_left)
        return when

    @staticmethod
    def _plan_who(plan_key: str) -> str:
        try:
            import plans
            found = plans.PLANS.get((plan_key or "").strip().lower())
            return found.who if found else ""
        except Exception:                            # noqa: BLE001
            return ""

    @staticmethod
    def _features(state) -> list[tuple[str, str, str, bool]]:
        """Every add-on Prism sells, with this licence's answer for each.

        Listing the locked ones is deliberate and matches SetupDialog: this is
        the only screen on which a customer can see what else the product
        does.
        """
        try:
            import plans
            table = plans.FEATURES
        except Exception:                            # noqa: BLE001
            table = {}
        keys = list(table.keys())
        for extra in sorted(state.features):
            if extra not in table:
                keys.append(extra)
        out = []
        for key in keys:
            entry = table.get(key)
            out.append((key,
                        entry.label if entry else feature_name(key),
                        entry.blurb if entry else "",
                        key in state.features))
        return out

    def _feature_card(self, key: str, name: str, blurb: str,
                      have: bool) -> Card:
        card = Card()
        col = card.body((theme.SPACE_4, theme.SPACE_4,
                         theme.SPACE_4, theme.SPACE_4), spacing=0)
        head = QHBoxLayout()
        head.setSpacing(theme.SPACE_3)
        head.addWidget(C.IconPad("check" if have else "lock",
                                 theme.OK if have else theme.NEUTRAL[500],
                                 30, theme.R_CONTROL, 15))
        head.addWidget(C.label(i18n.t(name), level="CARD_TITLE", wrap=True),
                       stretch=1)
        head.addWidget(Pill(i18n.t("Included") if have else i18n.t("Locked"),
                            "ok" if have else "quiet"),
                       alignment=Qt.AlignTop)
        col.addLayout(head)
        if blurb:
            col.addSpacing(theme.SPACE_2)
            col.addWidget(C.label(i18n.t(blurb), level="META", wrap=True))
        return card

    def _release_seat(self):
        """Free this machine's seat. The same call SetupDialog makes, behind
        the same confirmation — a seat released by accident costs a support
        call and a re-activation."""
        if QMessageBox.question(
                self, i18n.t("Release this computer's seat"),
                i18n.t("This frees the seat so the licence can be used on "
                       "another computer.\n\nPrism on THIS computer will stop "
                       "until you enter the key again. Your settings, your "
                       "history and your files stay exactly where they are."),
                QMessageBox.Yes | QMessageBox.Cancel) != QMessageBox.Yes:
            return
        try:
            licensing.deactivate()
        except Exception as error:                   # noqa: BLE001
            QMessageBox.warning(self, i18n.t("Licence"), i18n.t(
                "Couldn't release the seat: {error}").format(error=error))
            return
        self.licence_changed.emit()
        self.refresh()
        QMessageBox.information(
            self, i18n.t("Licence"),
            i18n.t("This computer's seat has been released."))

    # ── profile ───────────────────────────────────────────────────────────
    def _profile(self, col):
        me = identity.current()
        import roles as R
        role = R.get(me.get("role") or "") if me.get("role") else None
        shown = identity.display_name(self.cfg)

        col.addWidget(self._facts([
            (i18n.t("Name"), shown or i18n.t("Not set — this computer")),
            (i18n.t("Role"), role.label if role else i18n.t("Personal copy")),
            (i18n.t("What you do"), (self.cfg.get("profile") or "—")),
            (i18n.t("Member folder"), self._mono(me.get("mid") or "—")),
            (i18n.t("Workspace folder"),
             self._path(workspace.root(self.cfg) or "—")),
        ]))

        if role and role.blurb:
            col.addWidget(self._note(i18n.t(role.blurb)))

        col.addWidget(self._head(i18n.t("Who can see your work")))
        col.addWidget(self._note(self._visibility(me), "info"))

        members = self._safe(lambda: workspace.load_team(self.cfg)) or []
        if members:
            col.addWidget(self._head(
                i18n.t("Team members"),
                i18n.t("Everyone this copy has a designation key for.")))
            grid = C.CardGrid(min_col_width=260)
            for member in members:
                grid.add(self._member_card(member))
            col.addWidget(grid)

        col.addWidget(self._head(
            i18n.t("The roles Prism knows"),
            i18n.t("A designation key sets this copy to one of these. The "
                   "role decides its default tools, the window's colour, and "
                   "whether History can open anybody else's work.")))
        grid = C.CardGrid(min_col_width=290)
        for entry in R.ordered():
            grid.add(self._role_card(entry, entry.key == (me.get("role") or "")))
        col.addWidget(grid)

        actions = [self._edit_button("Change what you do", "profile"),
                   self._edit_button("Your role and team", "team")]
        # A team member's name comes from their signed designation key and is
        # not theirs to type; a solo copy has no key, so without this there is
        # no way to be called anything but "This computer".
        if not (me.get("name") or "").strip():
            actions.insert(0, C.button(i18n.t("Set your name"), "primary",
                                       on_click=self.rename_requested.emit))
        col.addWidget(self._buttons(actions))

    def _role_card(self, role, current: bool) -> Card:
        """One row of roles.ordered(), read straight off the table the
        designation keys are minted against — this screen must never invent a
        job title the key format cannot carry."""
        card = Card()
        col = card.body((theme.SPACE_4, theme.SPACE_4,
                         theme.SPACE_4, theme.SPACE_4), spacing=0)
        head = QHBoxLayout()
        head.setSpacing(theme.SPACE_3)
        head.addWidget(C.IconPad(role.icon,
                                 theme.ACCENT if current else theme.NEUTRAL[500],
                                 30, theme.R_CONTROL, 15))
        head.addWidget(C.label(role.label, level="CARD_TITLE", wrap=True),
                       stretch=1)
        if current:
            head.addWidget(Pill(i18n.t("This copy"), "accent"),
                           alignment=Qt.AlignTop)
        col.addLayout(head)
        col.addSpacing(theme.SPACE_2)
        col.addWidget(C.label(role.blurb, level="META", wrap=True))
        return card

    def _member_card(self, member: dict) -> Card:
        import roles as R
        role = R.get(member.get("role") or "")
        card = Card()
        row = card.body((theme.SPACE_4, theme.SPACE_3,
                         theme.SPACE_4, theme.SPACE_3), spacing=0)
        line = QHBoxLayout()
        line.setSpacing(theme.SPACE_3)
        name = member.get("name") or member.get("mid") or "—"
        line.addWidget(C.Avatar(name, 30))
        stack = QVBoxLayout()
        stack.setSpacing(0)
        stack.addWidget(C.label(name, level="SUPPORT", colour=theme.TEXT,
                                weight=500))
        stack.addWidget(C.label(role.label if role else
                                (member.get("role") or "—"), level="META"))
        line.addLayout(stack, stretch=1)
        row.addLayout(line)
        return card

    def _visibility(self, me: dict) -> str:
        """Said plainly, because finding it out later is a much worse day.
        The three cases are exactly the ones SetupDialog words."""
        if me.get("admin"):
            return i18n.t("You are set up as a manager, so you can open any "
                          "member's profile and history from the History "
                          "screen.")
        if workspace.is_shared(self.cfg):
            return i18n.t("Your work is saved in the shared team workspace, "
                          "so your manager can see what you have run. Other "
                          "members cannot.")
        return i18n.t("Your work stays in your own folder on this computer. "
                      "Nobody else on the team can see it.")

    # ── agents ────────────────────────────────────────────────────────────
    def _agents(self, col):
        chosen = dict(self.cfg.get("agents") or {})
        categories = CB.agents.CATEGORIES
        premium = set(self.cfg.get("premium") or [])

        picked = [(stage, chosen.get(stage))
                  for stage in CB.agents.PIPELINE_ORDER
                  if stage != "summary" and stage in categories]
        if not any(tool for _stage, tool in picked):
            empty = C.EmptyState(
                "grid", i18n.t("No tools picked yet"),
                i18n.t("Prism will suggest one per category the first time "
                       "you plan a task — or pick them yourself now."),
                i18n.t("Pick your agents"))
            empty.clicked.connect(lambda: self.edit_requested.emit("agents"))
            col.addWidget(empty, stretch=1)
            self._claims_height = True
            return

        grid = C.CardGrid(min_col_width=300)
        for stage, tool in picked:
            grid.add(self._agent_card(categories.get(stage, {}), stage, tool,
                                      tool in premium))
        col.addWidget(grid)

        col.addWidget(self._head(
            i18n.t("Premium plans"),
            i18n.t("The tools you pay for. Prism routes the bulk of the work "
                   "to those and keeps the free ones for the short steps.")))
        if premium:
            col.addWidget(self._facts(
                [(name, Pill(i18n.t("Paid plan"), "accent"))
                 for name in sorted(premium)]))
        else:
            col.addWidget(self._note(i18n.t(
                "None ticked. Prism spreads the work evenly instead, which is "
                "the right answer while every tool is on its free tier.")))

        col.addWidget(self._buttons([
            self._edit_button("Re-pick agents", "agents", "primary"),
            C.button(i18n.t("Open the AI tools screen"), "secondary",
                     on_click=lambda: self.navigate.emit("catalog")),
            C.button(i18n.t("Open login tabs"), "secondary",
                     on_click=self.login_tabs.emit)]))

    def _agent_card(self, meta: dict, stage: str, tool: str | None,
                    paid: bool) -> Card:
        card = Card()
        col = card.body((theme.SPACE_4, theme.SPACE_4,
                         theme.SPACE_4, theme.SPACE_4), spacing=0)
        head = QHBoxLayout()
        head.setSpacing(theme.SPACE_3)
        if tool:
            head.addWidget(C.ToolBadge(tool, 28))
        head.addWidget(C.label(tool or i18n.t("Not picked"),
                               level="CARD_TITLE"), stretch=1)
        head.addWidget(Pill(i18n.t("Paid") if paid else i18n.t("Free"),
                            "accent" if paid else "quiet")
                       if tool else Pill(i18n.t("Skipped"), "quiet"))
        col.addLayout(head)
        col.addSpacing(theme.SPACE_2)
        col.addWidget(C.kicker(i18n.t(meta.get("label", stage.title()))))
        if meta.get("desc"):
            col.addSpacing(theme.SPACE_1)
            col.addWidget(C.label(i18n.t(meta["desc"]), level="META",
                                  wrap=True))
        return card

    # ── language ──────────────────────────────────────────────────────────
    def _language(self, col):
        packs = self._safe(i18n.available) or []
        names = {code: label for code, label, _native in packs}
        current = i18n.current()
        out = (self.cfg.get("output_language") or "").strip()
        # The key the setup dialog and the engine both write is
        # `output_language`. This screen read `ai_language`, which nothing has
        # ever written, so the AI output row showed the interface language
        # back at you however it was set.
        out_name = (i18n.LANGUAGES.get(out, ("", "", False))[0] if out else "")

        col.addWidget(self._facts([
            (i18n.t("Prism's own language"), names.get(current, current)),
            (i18n.t("AI writes back in"),
             out_name or i18n.t("Same language as you asked in")),
        ]))
        col.addWidget(self._note(i18n.t(
            "These are two different wishes. An owner who wants Prism in "
            "Gujarati may still want the proposal it produces in English, so "
            "changing one never changes the other. A new interface language "
            "applies from the next start.")))

        if packs:
            col.addWidget(self._head(
                i18n.t("Language packs on this copy"),
                i18n.t("A pack that is not finished falls back to English "
                       "line by line, so the gaps never look like a fault.")))
            rows = []
            for code, label, native in packs:
                done, total = self._safe(lambda c=code: i18n.coverage(c)) \
                    or (0, 0)
                shown = label if native == label else f"{native} — {label}"
                if total and done < total:
                    value = i18n.t("{percent}% translated").format(
                        percent=done * 100 // total)
                    tone = "warn"
                else:
                    value = i18n.t("Complete")
                    tone = "ok"
                if code == current:
                    tone = "accent"
                    value = i18n.t("In use")
                rows.append((shown, Pill(value, tone)))
            col.addWidget(self._facts(rows))

        col.addWidget(self._buttons(
            [self._edit_button("Change language", "language", "primary")]))

    # ── connections ───────────────────────────────────────────────────────
    def _connections(self, col):
        key_set = bool((self.cfg.get("api_key") or "").strip())
        chrome = (self.cfg.get("chrome_version") or "").strip()
        offline = workspace.unreachable(self.cfg)
        ok, why = self._safe(CB.automation_available) or (False, "")

        col.addWidget(self._facts([
            (i18n.t("Groq key"),
             Pill(i18n.t("Set") if key_set else i18n.t("Not set"),
                  "ok" if key_set else "warn")),
            (i18n.t("Chrome"), chrome or i18n.t("Auto-detect")),
            (i18n.t("Browser automation"),
             Pill(i18n.t("Ready") if ok else i18n.t("Unavailable"),
                  "ok" if ok else "err")),
            (i18n.t("Team folder"),
             Pill(i18n.t("Unreachable") if offline else i18n.t("Reachable"),
                  "err" if offline else "ok")),
        ]))
        if not key_set:
            col.addWidget(self._note(i18n.t(
                "Prism cannot route anything without a Groq key. It is free "
                "at console.groq.com — API Keys, then Create API Key.")))
        if not ok and why:
            col.addWidget(self._note(str(why).splitlines()[0]))
        if offline:
            col.addWidget(self._note(offline))

        col.addWidget(self._head(
            i18n.t("Your browser"),
            i18n.t("Prism drives your own Chrome, signed in as you. It keeps "
                   "a separate profile so those logins survive between "
                   "runs — which is also why a login done in your everyday "
                   "Chrome does not reach it.")))
        col.addWidget(self._facts(self._browser_rows()))

        sites = self._login_sites()
        if sites:
            col.addWidget(self._head(
                i18n.t("Where 'Open login tabs' will take you"),
                i18n.t("One tab per tool you have picked, opened in Prism's "
                       "own Chrome profile so the sign-in sticks.")))
            grid = C.CardGrid(min_col_width=300)
            for tool, url in sites:
                grid.add(self._site_card(tool, url))
            col.addWidget(grid)

        col.addWidget(self._buttons([
            C.button(i18n.t("Open login tabs"), "primary",
                     on_click=self.login_tabs.emit),
            self._edit_button("Change API key", "key"),
            self._edit_button("Pin Chrome version", "chrome"),
        ]))

    def _login_sites(self) -> list[tuple[str, str]]:
        """The tools this copy is set up to drive, and the address each one
        signs in at — read from the agent registry, in the order the pipeline
        uses them, de-duplicated the same way SetupDialog does it."""
        registry = getattr(CB.agents, "AGENT_REGISTRY", {}) or {}
        chosen = dict(self.cfg.get("agents") or {})
        seen, out = set(), []
        for stage in CB.agents.PIPELINE_ORDER:
            tool = chosen.get(stage)
            if not tool or tool in seen:
                continue
            seen.add(tool)
            out.append((tool, (registry.get(tool) or {}).get("url", "")))
        return out

    def _site_card(self, tool: str, url: str) -> Card:
        card = Card()
        col = card.body((theme.SPACE_4, theme.SPACE_4,
                         theme.SPACE_4, theme.SPACE_4), spacing=0)
        head = QHBoxLayout()
        head.setSpacing(theme.SPACE_3)
        head.addWidget(C.ToolBadge(tool, 28))
        head.addWidget(C.label(tool, level="CARD_TITLE"), stretch=1)
        col.addLayout(head)
        if url:
            col.addSpacing(theme.SPACE_2)
            col.addWidget(self._path(url))
        return card

    def _browser_rows(self) -> list:
        rows = []
        automation = self._safe(CB.get_automation)
        if automation is None:
            rows.append((i18n.t("Prism's browser profile"),
                         i18n.t("Not created yet")))
            return rows
        folder = getattr(automation, "PROFILE_DIR", "") or ""
        rows.append((i18n.t("Prism's browser profile"),
                     self._path(folder) if folder else "—"))
        seeded = self._safe(automation.profile_is_seeded)
        rows.append((i18n.t("Your logins copied in"),
                     Pill(i18n.t("Yes") if seeded else i18n.t("Not yet"),
                          "ok" if seeded else "quiet")))
        return rows

    # ── privacy & data ────────────────────────────────────────────────────
    def _privacy(self, col):
        me = identity.current()
        root = workspace.root(self.cfg)
        shared = workspace.is_shared(self.cfg)
        prism_dir = self._safe(paths.user_dir) or ""
        logs = self._safe(self._log_dir) or ""

        col.addWidget(self._facts([
            (i18n.t("Your work is written to"), self._path(root or "—")),
            (i18n.t("This folder is"),
             Pill(i18n.t("Shared with the team") if shared
                  else i18n.t("On this computer only"),
                  "accent" if shared else "quiet")),
            (i18n.t("Filed under"), self._mono(me.get("mid") or "—")),
            (i18n.t("Prism's own folder"), self._path(prism_dir or "—")),
            (i18n.t("Logs"), self._path(logs or "—")),
            (i18n.t("Log files on disk"), self._safe(self._log_size) or "—"),
            (i18n.t("Licence server"),
             self._path(self._safe(licensing.client.server_url) or "—")),
        ]))

        col.addWidget(self._head(i18n.t("Who can read it")))
        col.addWidget(self._note(self._visibility(me), "info"))

        col.addWidget(self._head(i18n.t("What leaves this computer")))
        col.addWidget(self._note(i18n.t(
            "Your task text goes to the AI tools you have chosen, through "
            "your own signed-in browser and your own accounts — exactly as if "
            "you had typed it there yourself. Prism itself contacts only the "
            "licence server above, and sends it nothing but this machine's id "
            "and your licence key. Your files, your register and your run "
            "history never leave the folders listed here.")))

        col.addWidget(self._head(
            i18n.t("What a support export never contains"),
            i18n.t("Diagnostics is scrubbed as it is written, not as it is "
                   "sent, so nothing sensitive is ever in the file to leak.")))
        grid = C.CardGrid(min_col_width=280)
        for label in ("Your Groq API key", "Your mailbox password",
                      "Your licence key and designation key",
                      "The authorisation lease", "Every email address"):
            grid.add(self._redacted_card(label))
        col.addWidget(grid)

        buttons = []
        if root and os.path.isdir(root):
            buttons.append(C.button(
                i18n.t("Open the workspace folder"), "secondary",
                on_click=lambda: self._open_folder(root)))
        if prism_dir and os.path.isdir(prism_dir):
            buttons.append(C.button(
                i18n.t("Open Prism's folder"), "secondary",
                on_click=lambda: self._open_folder(prism_dir)))
        buttons.append(self._edit_button("Change the workspace folder",
                                         "team"))
        col.addWidget(self._buttons(buttons))

    def _redacted_card(self, label: str) -> Card:
        """One thing diagnostics._scrub() removes. The list is short and it is
        the answer to the only question a customer has before emailing a log
        file to a supplier."""
        card = Card()
        row = card.body((theme.SPACE_4, theme.SPACE_3,
                         theme.SPACE_4, theme.SPACE_3), spacing=0)
        line = QHBoxLayout()
        line.setSpacing(theme.SPACE_3)
        line.addWidget(C.IconPad("lock", theme.OK, 30, theme.R_CONTROL, 15))
        line.addWidget(C.label(i18n.t(label), level="SUPPORT",
                               colour=theme.TEXT, wrap=True), stretch=1)
        row.addLayout(line)
        return card

    @staticmethod
    def _log_dir() -> str:
        import diagnostics
        return diagnostics.log_dir()

    @staticmethod
    def _log_size() -> str:
        """How much disk the rolling log is actually using, and the ceiling it
        cannot pass. Read off diagnostics' own constants, so a change to the
        rotation policy cannot leave this page describing the old one."""
        import diagnostics
        total = 0
        for index in range(diagnostics.KEEP):
            path = (diagnostics.log_path() if index == 0
                    else f"{diagnostics.log_path()}.{index}")
            try:
                total += os.path.getsize(path)
            except OSError:
                pass
        cap = diagnostics.MAX_BYTES * diagnostics.KEEP
        return i18n.t("{used} KB of at most {cap} KB").format(
            used=total // 1024, cap=cap // 1024)

    def _open_folder(self, path: str):
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # ── diagnostics ───────────────────────────────────────────────────────
    def _diagnostics(self, col):
        col.addWidget(self._head(
            i18n.t("What this machine can do"),
            i18n.t("An add-on needs its own libraries as well as its licence. "
                   "This is what is actually installed here.")))
        grid = C.CardGrid(min_col_width=270)
        for label, ok, detail in self._capabilities():
            grid.add(self._capability_card(label, ok, detail))
        col.addWidget(grid)

        col.addWidget(self._head(i18n.t("This installation")))
        col.addWidget(self._facts([
            (i18n.t("Version"), app_meta.VERSION),
            (i18n.t("Packaged build"),
             i18n.t("Yes") if self._safe(paths.is_frozen) else i18n.t("No")),
            (i18n.t("Platform"), platform.platform()),
            (i18n.t("Python"), sys.version.split()[0]),
            (i18n.t("Device id"),
             self._mono(self._safe(licensing.device_fingerprint) or "—")),
            (i18n.t("Authorisation"),
             self._safe(licensing.lease_state) or "—"),
            (i18n.t("Card shadows"),
             Pill(i18n.t("On") if C.shadows_enabled() else i18n.t("Off"),
                  "accent" if C.shadows_enabled() else "quiet")),
        ]))
        col.addWidget(self._note(i18n.t(
            "Card shadows and entrance animations are drawn through a "
            "separate graphics path that renders nothing at all on some "
            "drivers, virtual machines and remote desktops — which is why "
            "they are off unless this computer is known to handle them. Set "
            "\"shadows\": true in Prism's config.json to turn them back on.")))

        tail = (self._safe(lambda: self._log_tail(14)) or "").strip()
        col.addWidget(self._head(
            i18n.t("Recent activity"),
            i18n.t("The last few lines Prism wrote to its log. Keys, "
                   "passwords and addresses are removed as it is written.")))
        col.addWidget(self._log_card(tail))

        col.addWidget(self._buttons([
            C.button(i18n.t("Export diagnostics…"), "primary",
                     on_click=self._export_diagnostics),
            C.button(i18n.t("Open the log folder"), "secondary",
                     on_click=lambda: self._open_folder(
                         self._safe(self._log_dir) or "")),
            C.button(_amp(i18n.t("Help & support")), "secondary",
                     on_click=lambda: self.navigate.emit("support")),
        ]))

    def _capabilities(self) -> list[tuple[str, bool, str]]:
        """The same probes diagnostics.report() runs, as cards. Nothing here
        is asserted — every row is the answer a real probe just gave."""
        out = []
        probes = [("Browser automation", CB.automation_available),
                  ("BOQ measuring", CB.boq_available),
                  ("Reel & Studio", CB.reel_available)]
        try:
            import wakeword
            probes.append(("Voice input", wakeword.available))
        except Exception:                            # noqa: BLE001
            pass
        for label, probe in probes:
            answer = self._safe(probe)
            if isinstance(answer, tuple) and len(answer) == 2:
                ok, why = bool(answer[0]), str(answer[1] or "")
            else:
                ok, why = False, i18n.t("Could not be checked")
            out.append((label, ok, "" if ok else why.splitlines()[0][:110]))
        sources = self._safe(self._cloud_sources)
        if sources is not None:
            out.append(("Cloud folders", bool(sources),
                        ", ".join(sources) if sources
                        else i18n.t("None found on this computer")))
        return out

    @staticmethod
    def _cloud_sources() -> list[str]:
        import cloud
        return [s["label"] for s in cloud.sources()]

    def _capability_card(self, label: str, ok: bool, detail: str) -> Card:
        card = Card()
        col = card.body((theme.SPACE_4, theme.SPACE_4,
                         theme.SPACE_4, theme.SPACE_4), spacing=0)
        head = QHBoxLayout()
        head.setSpacing(theme.SPACE_3)
        head.addWidget(C.IconPad("check" if ok else "alert",
                                 theme.OK if ok else theme.WARN,
                                 30, theme.R_CONTROL, 15))
        head.addWidget(C.label(i18n.t(label), level="CARD_TITLE"), stretch=1)
        head.addWidget(Pill(i18n.t("Ready") if ok else i18n.t("Missing"),
                            "ok" if ok else "warn"))
        col.addLayout(head)
        if detail:
            col.addSpacing(theme.SPACE_2)
            col.addWidget(C.label(detail, level="META", wrap=True))
        return card

    @staticmethod
    def _log_tail(lines: int) -> str:
        import diagnostics
        text = diagnostics.tail(lines) or ""
        # One line per row, clipped: the log carries whole tracebacks and a
        # 400-character line would push the card off the right of the screen.
        return "\n".join(row[:150] for row in text.splitlines()[-lines:])

    def _log_card(self, tail: str) -> Card:
        card = Card()
        col = card.body((theme.CARD_PAD, theme.SPACE_4,
                         theme.CARD_PAD, theme.SPACE_4), spacing=0)
        if not tail:
            col.addWidget(C.label(
                i18n.t("Nothing logged yet on this computer."),
                level="SUPPORT", wrap=True))
            return card
        body = QLabel(tail)
        body.setObjectName("well")
        body.setAttribute(Qt.WA_StyledBackground, True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.setStyleSheet(
            f"#well {{ background: {theme.WELL};"
            f" border-radius: {theme.R_CONTROL}px;"
            f" padding: {theme.SPACE_3}px;"
            f" {theme.type_css('MONO', theme.NEUTRAL[700])} }}")
        col.addWidget(body)
        return card

    def _export_diagnostics(self):
        """The one button that makes a support call short. Same call the Setup
        dialog's footer makes; this is simply the door somebody looking for it
        would open."""
        import time

        import diagnostics
        suggested = os.path.join(
            os.path.expanduser("~"),
            f"prism-diagnostics-{time.strftime('%Y%m%d-%H%M')}.txt")
        target, _filter = QFileDialog.getSaveFileName(
            self, i18n.t("Save diagnostics"), suggested, "Text (*.txt)")
        if not target:
            return
        try:
            diagnostics.export(target)
        except Exception as error:                   # noqa: BLE001
            QMessageBox.warning(self, i18n.t("Diagnostics"), i18n.t(
                "Couldn't write the file: {error}").format(error=error))
            return
        QMessageBox.information(self, i18n.t("Diagnostics"), i18n.t(
            "Saved to {path}\n\nEmail it to support and they'll be able to "
            "see what happened. Your API key, passwords and licence key are "
            "not in it.").format(path=target))

    # ── help & more ───────────────────────────────────────────────────────
    def _more(self, col):
        grid = C.CardGrid(min_col_width=300)
        for key, label, blurb in MORE_LINKS:
            grid.add(self._door_card(key, label, blurb))
        col.addWidget(grid)

        col.addWidget(self._head(i18n.t("New to Prism?")))
        col.addWidget(self._note(i18n.t(
            "The tour walks through where everything lives, in six steps. It "
            "takes about a minute and you can stop it at any point.")))
        col.addWidget(self._buttons([
            C.button(i18n.t("Take a tour"), "primary",
                     on_click=self.tour_requested.emit)]))

        col.addWidget(self._head(i18n.t("Still stuck?")))
        col.addWidget(self._facts([
            (i18n.t("Email us"), app_meta.SUPPORT_EMAIL),
            (i18n.t("Website"), app_meta.WEBSITE),
            (i18n.t("Version"), app_meta.VERSION),
        ]))

    def _door_card(self, key: str, label: str, blurb: str) -> Card:
        card = Card()
        col = card.body((theme.SPACE_4, theme.SPACE_4,
                         theme.SPACE_4, theme.SPACE_4), spacing=0)
        head = QHBoxLayout()
        head.setSpacing(theme.SPACE_3)
        head.addWidget(C.IconPad(MORE_ICONS.get(key, "grid"), theme.ACCENT,
                                 30, theme.R_CONTROL, 15))
        head.addWidget(C.label(i18n.t(label), level="CARD_TITLE"), stretch=1)
        col.addLayout(head)
        col.addSpacing(theme.SPACE_2)
        col.addWidget(C.label(i18n.t(blurb), level="META", wrap=True))
        col.addSpacing(theme.SPACE_3)
        col.addWidget(self._buttons([
            C.button(i18n.t("Open"), "secondary", small=True,
                     on_click=lambda _=False, k=key: self.navigate.emit(k))]))
        return card

    # ── bits ──────────────────────────────────────────────────────────────
    @staticmethod
    def _safe(fn, default=None):
        """Run a probe, or hand back `default`. Settings is a screen a stuck
        customer opens; a section that raises because a shared drive is down
        is the one moment it must not."""
        try:
            return fn()
        except Exception:                            # noqa: BLE001
            return default

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
        label = C.label(str(text), level="MONO")
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        return label

    @staticmethod
    def _path(text: str) -> QLabel:
        """Elided from the left — the tail of a path is what identifies it,
        and a shared-drive prefix is the same on every row."""
        text = str(text)
        label = C.label(text if len(text) <= 46 else "…" + text[-45:],
                        level="MONO", tooltip=text)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        return label
