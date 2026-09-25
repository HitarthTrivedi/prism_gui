"""What's on the Leads screen, and what each button costs.

The Alphakore team read the new Leads workbench as a wall of controls with no
statement of which ones spend money. That is the real hesitation: searching is
free and drafting is not, and nothing on the screen said so. So this is a
reading panel — six short sections, plain sentences, no settings of its own —
that slides over the right edge of the screen from the "?" in the page header
(F1 works too, Esc shuts it).

Reading it was not enough on its own: the same team then asked which control
each paragraph was about. So the panel's primary button is "Show me on screen",
which shuts it and starts the walkthrough (addons/leads/tour.py) that rings
each real control in turn. The panel stays because it is the version you can
read end to end, and search, without stepping through sixty cards.

It floats OVER the workbench rather than sitting beside it in the layout. The
same reason the dossier drawer floats on a narrow window: the rail plus the
table already own every pixel of a 1366px laptop, and a panel that pushed them
sideways would make the screen harder to read at the moment someone asked for
help understanding it.

The copy lives in SECTIONS, one module-level tuple of (title, body) pairs, for
two reasons. It is the only thing here anyone will want to edit — a sentence
changes without touching a widget — and `SECTIONS` is a name
devtools/extract_strings.py already scans (COPY_TABLES), so every line of it
reaches the catalogue and can be translated. Keep the copy free of braces,
angle brackets and semicolons: _is_copy() reads those as stylesheet or HTML
and drops the string.

A body is ONE string literal, bullets written into it by hand rather than
concatenated from a constant: the extractor reads the source, so a body built
with `BULLET + "..."` would reach the catalogue as fragments while t() asked it
for the whole paragraph, and every line would silently ship untranslated. A
line starting with a bullet or "1." is drawn as a marker plus a hanging-
indented sentence, so the wrapped half of a long bullet lines up under the
first half instead of under the dot.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget,
)

import i18n
import theme
from widgets import controls as C

BULLET = "• "
_STEP = 20                  # one wheel step in the body, in px


# The whole of the help text. Titles are the headings, bodies the prose under
# them. Order matters: it is the order of a working day, so someone reading
# top to bottom is also being walked through the screen left to right.
SECTIONS = (
    ("The page",
     "This is Find people, laid out the way Apollo lays it out, over everyone "
     "Prism already holds — the people you imported, saved, or found with a "
     "search.\n"
     "• Import, at the top right, brings a sheet in. People come in as "
     "contacts, companies as accounts. Nothing is searched: the import becomes "
     "a filter on the left, and the page shows what came in.\n"
     "• The filters narrow the page the moment you click them, and cost "
     "nothing.\n"
     "• Find new people, under the filters, is the one button that spends. It "
     "says what the search will cost and asks before it runs.\n"
     "Nothing is sent to anybody until you press Send yourself."),

    ("The filters",
     "Every filter is a chip you add, and most have an exclude side as well. "
     "The page applies them to everyone Prism holds, and a search applies "
     "them to everyone it finds.\n"
     "• Total is everyone who passes. Saved is your contacts among them, Net "
     "New is everyone else.\n"
     "• Industry and Keywords only steer a search. They are hints to the "
     "database, so the people a search found for them stay under them — read "
     "those as likely rather than certain. Their exclusions are always "
     "enforced.\n"
     "• Location, Job title, Seniority, Function, Company headcount, Annual "
     "revenue, Current company, Company HQ location and Years in current role "
     "are checked on every person, on the page and in every search.\n"
     "• Contact CSV import and Account CSV import show the people an import "
     "brought in, or the people Prism holds at its companies.\n"
     "• Only find people no earlier search found, in Search settings, means a "
     "search never pulls the same person twice. The same filters twice give "
     "you new names, not the old ones again."),

    ("What each thing costs",
     "Leads runs on your Prism credits. You never enter an API key: every paid "
     "lookup is charged to your credits, and the number in the page header is "
     "what you have left. This is the part worth knowing before you click "
     "anything.\n"
     "• Filtering, sorting and paging the people Prism holds is free, and so "
     "are Import and Save.\n"
     "• Find new people is charged per search, not per person. It says how "
     "many searches it will run and what that comes to in credits, and asks "
     "before it runs. A search that finds nobody is not charged.\n"
     "• Find e-mails is charged per person. Looking up a company's website, "
     "finding an address and checking an address each cost credits, and an "
     "address is charged only when a finder knows the person. It checks every "
     "row you ticked, not a sample of them. That is why it is a separate "
     "button on the rows you tick, and not something a search quietly does "
     "for everyone it found.\n"
     "• Qualify and draft is charged per lead: a why-now news search, a score "
     "and a draft. Spend it on the people you actually want.\n"
     "• Click your balance in the page header to see how many credits are "
     "left, what they were spent on, what each thing costs, and to ask "
     "Alphakore for a plan or a top-up. When your credits run out a run stops "
     "and says so.\n"
     "• Send is free. It goes out of your own mailbox, one message per "
     "person, after you have read every draft."),

    ("The results table",
     "Everyone who passes the filters is listed, twenty-five to a page, "
     "whether or not Prism knows anything about them yet.\n"
     "• Not qualified means exactly that. Found, not researched. The row is "
     "there so you can pick it.\n"
     "• Fit score is a cheap ranking off the title and the company. It sorts "
     "the list. It is not a promise about anybody.\n"
     "• Status is deliverability, not interest. Verified, Unverified, "
     "Catch-all, Invalid, No email, Mailed. Addresses are found by a finder, "
     "never guessed.\n"
     "• Tick rows with the box on the left, or the box in the header for the "
     "whole page. The arrow beside it picks all of them, or a number with at "
     "most so many from one company, and picks stay when you turn the page. "
     "The action bar acts on who you picked, and only on them. Save makes "
     "them contacts. Set stage moves them along. Remove takes them off the "
     "list, and the line under the three tabs brings them back. Clear "
     "selection only unticks.\n"
     "• Table and Cards are the same people in two shapes. Click a row to "
     "open the person: their details, stage, tasks, company and notes, then "
     "why they fit, their activity, their e-mail and every field. A note, a "
     "task, a stage or a logged call there saves them first."),

    ("The tabs",
     "• People is this page — everyone Prism holds, filtered as you click.\n"
     "• Sessions keeps every search you have run, with its filters and its "
     "results. Open one to see only its people.\n"
     "• Lists holds the sheets written to disk. Real files, on your machine, "
     "that you can send to anyone.\n"
     "• Saved searches keeps a set of filters under a name, to use again next "
     "week.\n"
     "• Sequences is the follow-up steps a lead walks through after the first "
     "mail.\n"
     "• Analytics counts what the last search produced. Found, verified, "
     "drafted, sent."),

    ("How a day goes",
     "1. Import a sheet, or set your filters.\n"
     "2. Find new people, and read the list that comes back.\n"
     "3. Tick the ones you actually want, and Save them.\n"
     "4. Find e-mails, on those ticked rows only.\n"
     "5. Qualify and draft, so Prism writes an opener for each.\n"
     "6. Read every draft and change whatever needs changing.\n"
     "7. Send."),
)


def _marker(line: str) -> tuple[str, str]:
    """Split one body line into its list marker and the sentence after it.

    Returns ("", line) for a plain paragraph. Done on the TRANSLATED line, so
    a language that numbers its steps differently still lines up.
    """
    if line.startswith(BULLET):
        return "•", line[len(BULLET):]
    head, _, rest = line.partition(" ")
    if rest and head.endswith(".") and head[:-1].isdigit():
        return head, rest
    return "", line


class LeadsHelp(QFrame):
    """The help panel. Parent it to the region it should cover — `place()`
    pins it to that parent's right edge and the full height of it.

    Built but not shown: `open_panel()` shows it, `close_panel()` hides it,
    `toggle()` does whichever is next. It is a child widget, never a window,
    so it can be built and opened in a test without anything reaching a screen.
    """

    WIDTH = 420             # wide enough for a 4-line bullet, narrow enough
                            # to leave the table readable behind it
    MIN_W = 300

    closed = Signal()       # so the opener can take its focus ring back
    tourRequested = Signal()    # "Show me on screen" — addons/leads/tour.py

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("leadsHelp")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QFrame#leadsHelp{{background:{theme.CARD};border:none;"
            f"border-left:1px solid {theme.DIVIDER};}}")
        self.setFocusPolicy(Qt.StrongFocus)

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        head = QHBoxLayout()
        head.setContentsMargins(theme.SPACE_5, theme.SPACE_4,
                                theme.SPACE_3, theme.SPACE_3)
        head.setSpacing(theme.SPACE_3)
        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(2)
        # Literals, not constants, at every one of these three call sites:
        # extract_strings reads the source, and a name it has to resolve is a
        # name it cannot catalogue. SECTIONS is the exception it already scans.
        title_col.addWidget(C.label(i18n.t("What's on this screen"),
                                    level="SECTION"))
        title_col.addWidget(C.label(i18n.t("The Leads screen in six short "
                                           "answers."), level="META", wrap=True))
        head.addLayout(title_col, 1)
        self.close_btn = C.icon_button("x", i18n.t("Close"),
                                       on_click=self.close_panel)
        head.addWidget(self.close_btn, alignment=Qt.AlignTop)
        col.addLayout(head)

        # The primary way out of this panel, above the reading: the team who
        # asked for help could not match a paragraph to a control, and the
        # walkthrough is the answer to exactly that. Reading is the fallback.
        walk = QHBoxLayout()
        walk.setContentsMargins(theme.SPACE_5, 0, theme.SPACE_5, theme.SPACE_4)
        walk.setSpacing(theme.SPACE_2)
        self.tour_btn = C.button(i18n.t("Show me on screen"), "primary",
                                 icon_name="play", on_click=self._start_tour)
        walk.addWidget(self.tour_btn)
        walk.addStretch(1)
        col.addLayout(walk)
        col.addWidget(C.hairline())

        self._scroll = QScrollArea()
        self._scroll.setObjectName("helpScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        # Horizontal scrolling off: every label in here wraps, so a sideways
        # bar would only ever mean a label that failed to.
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.verticalScrollBar().setSingleStep(_STEP)
        self._scroll.setStyleSheet(
            "QScrollArea#helpScroll{background:transparent;border:none;}")
        inner = QWidget()
        inner.setObjectName("helpInner")
        inner.setAttribute(Qt.WA_StyledBackground, True)
        inner.setStyleSheet(f"QWidget#helpInner{{background:{theme.CARD};}}")
        self._body_lay = QVBoxLayout(inner)
        self._body_lay.setContentsMargins(theme.SPACE_5, theme.SPACE_4,
                                          theme.SPACE_5, theme.SPACE_6)
        self._body_lay.setSpacing(theme.SPACE_5)
        for title, body in SECTIONS:
            self._body_lay.addWidget(self._section(title, body))
        self._body_lay.addStretch(1)
        self._scroll.setWidget(inner)
        col.addWidget(self._scroll, 1)

        # Esc, while the focus is anywhere inside the panel. The "?" button is
        # a toggle for everyone else, and F1 belongs to the screen, not here.
        shut = QShortcut(QKeySequence(Qt.Key_Escape), self)
        shut.setContext(Qt.WidgetWithChildrenShortcut)
        shut.activated.connect(self.close_panel)
        self.hide()

    # -- content ---------------------------------------------------------------
    def _section(self, title: str, body: str) -> QWidget:
        block = QWidget()
        col = QVBoxLayout(block)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_2)
        col.addWidget(C.label(i18n.t(title), level="CARD_TITLE", wrap=True))
        for line in i18n.t(body).split("\n"):
            if not line.strip():
                continue
            mark, text = _marker(line)
            if not mark:
                col.addWidget(C.label(text, level="SUPPORT", wrap=True))
                continue
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(theme.SPACE_2)
            glyph = C.label(mark, level="SUPPORT", colour=theme.NEUTRAL[500])
            # Fixed, and aligned to the top: the marker column has to stay put
            # while the sentence beside it wraps to four lines.
            glyph.setFixedWidth(16)
            row.addWidget(glyph, alignment=Qt.AlignTop)
            row.addWidget(C.label(text, level="SUPPORT", wrap=True), 1)
            col.addLayout(row)
        return block

    def sections(self) -> tuple:
        """The copy this panel is showing — the tests read it from here."""
        return SECTIONS

    def _start_tour(self) -> None:
        """Shut, then ask. The walkthrough rings controls this panel is sitting
        on top of, so it cannot start while the panel is still over them."""
        self.close_panel()
        self.tourRequested.emit()

    # -- open, close, place ----------------------------------------------------
    def place(self) -> None:
        """Pin to the right edge of whatever this panel was parented to."""
        par = self.parentWidget()
        if par is None:
            return
        wide = max(self.MIN_W, min(self.WIDTH, par.width()))
        self.setGeometry(par.width() - wide, 0, wide, par.height())
        self.raise_()

    def open_panel(self) -> None:
        self.place()
        self.setVisible(True)
        self.raise_()
        # The close button, not the panel: it makes Esc live immediately and
        # puts the keyboard one Tab away from the first thing worth reading.
        self.close_btn.setFocus(Qt.OtherFocusReason)

    def close_panel(self) -> None:
        if not self.is_open():
            return
        self.setVisible(False)
        self._scroll.verticalScrollBar().setValue(0)
        self.closed.emit()

    def toggle(self) -> None:
        self.close_panel() if self.is_open() else self.open_panel()

    def is_open(self) -> bool:
        return not self.isHidden()

    # -- geometry --------------------------------------------------------------
    # Both hints are deliberately NOT the height of the content. The body
    # scrolls, so the panel only ever needs to be as tall as the window lets
    # it be — and a hint that asked for the whole 1400px of text would set a
    # minimum no 830px window could satisfy.
    def sizeHint(self) -> QSize:
        return QSize(self.WIDTH, 560)

    def minimumSizeHint(self) -> QSize:
        return QSize(self.MIN_W, 240)
