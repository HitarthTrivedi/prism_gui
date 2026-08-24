"""Help & support — the answer book on the left, the conversation on the right.

────────────────────────────────────────────────────────────────────────────
Three tiers, in this order, and the order is the whole design
────────────────────────────────────────────────────────────────────────────
    1. the written answers   (`support_kb.py` — instant, free, always right)
    2. the assistant         (their own Groq key, answering from that same
                              written material — never from its imagination)
    3. our team              (an email that already contains everything we
                              would otherwise have to ask for)

Tiers 2 and 3 stay shut until tier 1 has actually been tried. That is the
pattern every government service site uses, and it is used here for the same
unglamorous reason: most support questions have a written answer that is
faster than any conversation, and a "Contact us" button sitting next to it
gets pressed anyway — not because the answer was bad, but because a button
marked contact-us reads as the shortest path even when it is the longest one.

────────────────────────────────────────────────────────────────────────────
Why the gate is not a wall
────────────────────────────────────────────────────────────────────────────
A gate that traps someone is worse than no gate. Somebody whose problem is
genuinely not in the book must not be made to read six irrelevant answers to
earn the right to speak to a human. So it opens on the FIRST honest miss:
they read an answer and pressed "No, still stuck", or they typed a question
there was no answer for. One of either is enough.

────────────────────────────────────────────────────────────────────────────
Two columns, because a menu is not a conversation
────────────────────────────────────────────────────────────────────────────
The first version put everything in the thread: ten topic chips floating over
an empty screen, and a question box exiled to the bottom of it. Nothing about
the shape said "there are seventy-one answers in here", and the only way to
find out what a topic contained was to open it and lose your place.

So the screen is now split, and the split is the fix:

  · LEFT — the book. Search across every written answer, then the ten topics
    with the number of answers in each and the line that says what is on that
    shelf. It never scrolls away, so browsing costs nothing and going back
    costs nothing. This is where the topics live now; they are no longer
    posted into the thread.
  · RIGHT — the conversation. It opens on the questions the rest of the book
    points back at most, as pressable rows rather than behind a chip, and it
    keeps the three rules the first redesign earned:

      · **A menu is retired the moment the conversation moves past it.** The
        pick is already echoed as the customer's own bubble, so nothing is
        lost — and live buttons left in the scrollback are how a conversation
        forks. (The did-this-help row collapses itself for the same reason.)
      · **Questions stay full-width rows**, because they are whole sentences
        and a truncated question cannot be chosen.
      · **Prism's messages carry its mark.** Two voices in one column need
        telling apart faster than reading them.

This is a SCREEN, not a dialog — it keeps its conversation for the life of
the window, so following an answer's button to Settings and coming back
lands on the same thread. Start over is the one control that forgets.
"""
from __future__ import annotations

from collections import Counter

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

import app_meta
import i18n
import support_kb as KB
import theme
from widgets import controls as C
from widgets import icons

# How the assistant is told to behave. Written as instructions to a support
# agent rather than as a specification, because that is what produces the
# tone — and the refusal rule is first for the same reason it is first in a
# real induction: a made-up menu item costs the customer more time than an
# admitted "I don't know" ever does.
_SYSTEM = """\
You are the support assistant inside Prism, a desktop app used by small
manufacturers, fabricators, contractors and agencies in India. You are
talking to the owner or a member of their staff. They run a business; they
are not technical, and they did not choose any of the technology involved.

THE RULES, IN ORDER OF IMPORTANCE

1. Answer ONLY from the Prism reference material below. If the answer is not
   in it, say plainly that you do not have that one and tell them to press
   "Contact the team" at the bottom of this screen. Never guess at a menu,
   a button or a setting that is not named in the material. A confident wrong
   answer costs them more than no answer.
2. Never repeat, word for word, an answer they have already been shown. They
   have read it and it did not help. Take it as read and go further.
3. Plain English only. Never write: prompt, pipeline, LLM, model, token,
   endpoint, selector, driver, JSON, HTTP, or any error code.
4. Be short. Two or three sentences of explanation, then numbered steps if
   there is something to do. Never more than six steps.
5. Write the steps as instructions to a person, starting with a verb —
   "Open Settings and…", not "The setting is located in…".
6. Never blame them and never tell them to reinstall or reset anything as a
   first move.
7. If it sounds like a bug, or like something only we can fix, say so
   honestly and point at "Contact the team". That is a good answer, not a
   failure.
"""


# ── what the book actually contains ────────────────────────────────────────
# Read off support_kb rather than typed out here, so a question added there
# shows up here without anybody remembering to update a count.
_TOPIC_OF: dict[str, KB.Topic] = {
    q.qid: topic for topic in KB.TOPICS for q in topic.questions}
ANSWER_COUNT = len(KB.all_questions())
TOPIC_COUNT = len(KB.TOPICS)


def _most_pointed_at(limit: int) -> tuple[KB.Question, ...]:
    """The questions the rest of the book points back at, most first.

    The screen has to open on SOMETHING — ten topic names over an empty field
    told the customer nothing — and the one thing it must not do is invent a
    popularity figure it does not have. Nothing in Prism counts how often an
    answer is read.

    What the book does carry is `related`: every answer names the ones worth
    reading next, and those pointers were written one at a time by whoever
    wrote the answers. A question that eleven other answers hand you to is,
    by the book's own reckoning, the one people keep needing. Ties break on
    the order the file lists them in, so this is stable between runs.
    """
    pull: Counter[str] = Counter()
    for question in KB.all_questions():
        for other in question.related:
            pull[other] += 1
    order = {q.qid: i for i, q in enumerate(KB.all_questions())}
    ranked = sorted(pull, key=lambda qid: (-pull[qid], order.get(qid, 9999)))
    picked = [KB.question(qid) for qid in ranked[:limit]]
    return tuple(q for q in picked if q is not None)


def _matching(query: str) -> list[KB.Question]:
    """Every written answer this typed text could be about, best first.

    Deliberately NOT `KB.search`. That one is a decision — it returns nothing
    rather than a weak guess, because an empty result is what opens the route
    to a person. This is a browse filter on a list the customer can already
    see, so the honest behaviour is the opposite: narrow as they type, match
    on any part of any word, and let them judge. Both are wired up: this one
    filters the column, and pressing Ask still goes through `KB.search`.
    """
    words = [w for w in query.lower().split() if w]
    if not words:
        return []
    named, mentioned = [], []
    for question in KB.all_questions():
        topic = _TOPIC_OF.get(question.qid)
        heading = " ".join((question.text, " ".join(question.keywords),
                            topic.label if topic else "")).lower()
        body = " ".join((question.answer.what, " ".join(question.answer.steps),
                         question.answer.note)).lower()
        if all(word in heading for word in words):
            named.append(question)
        elif all(word in heading + " " + body for word in words):
            mentioned.append(question)
    return named + mentioned


def _chip(label: str, icon_name: str = "", tip: str = "") -> QPushButton:
    """One compact pressable — a small conversational move inside the thread.

    The capsule object name rather than a hand-rolled stylesheet: `#chipBtn`
    is the secondary variant in capsule form and already carries hover,
    pressed, focus and disabled states from style.qss.
    """
    btn = C.button(f" {label}" if icon_name else label, "secondary",
                   small=True)
    btn.setObjectName("chipBtn")
    if icon_name:
        icons.button_icon(btn, icon_name, 14, theme.ACCENT)
    if tip:
        btn.setToolTip(tip)
    return btn


# ── little shared pieces ───────────────────────────────────────────────────
def _wrap(widget: QWidget, mine: bool, glyph: str = "",
          full: bool = False) -> QWidget:
    """Put one message on its side of the transcript.

    Stretch rather than a fixed maximum width, so a bubble is ~75% of
    whatever the column happens to be. `glyph` puts Prism's mark beside its
    own messages — two voices in one column need telling apart at a glance.

    `full` is for the menus rather than the messages. A said thing is easier
    to read short, which is what the 75% is for; a list of questions to
    choose between is not a said thing, and holding it to 75% left a dead
    strip down the right of the screen and wrapped questions that would have
    fitted on one line.

    Minimum vertical policy, or a message can be squeezed shorter than its
    own text: these rows stack inside a scroll area that is routinely
    shorter than its content, so "short of room" is the normal case.
    """
    row = QWidget()
    row.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
    box = QHBoxLayout(row)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(theme.SPACE_2)
    if mine:
        box.addStretch(1)
        box.addWidget(widget, stretch=3)
    else:
        if glyph:
            mark = QLabel()
            mark.setPixmap(icons.pixmap(glyph, 18, theme.ACCENT))
            mark.setAlignment(Qt.AlignTop)
            mark.setFixedWidth(20)
            mark.setStyleSheet("background: transparent; padding-top: 10px;")
            box.addWidget(mark)
        box.addWidget(widget, stretch=3)
        if not full:
            box.addStretch(1)
    return row


def _bubble(text: str, mine: bool = False) -> QWidget:
    frame = QFrame()
    frame.setObjectName("supportMine" if mine else "supportBot")
    # Scoped by object name: unscoped, this fill lands on every child too and
    # flattens the buttons inside an answer card back into plain boxes.
    frame.setStyleSheet(
        f"QFrame#{frame.objectName()} {{"
        f"background: {theme.ACCENT_RAMP[100] if mine else theme.CARD};"
        f"border: 1px solid {theme.ACCENT_RAMP[300] if mine else theme.HAIRLINE};"
        f"border-radius: {theme.R_CARD}px; }}")
    box = QVBoxLayout(frame)
    box.setContentsMargins(theme.SPACE_4 - 1, theme.SPACE_3,
                           theme.SPACE_4 - 1, theme.SPACE_3)
    body = C.label(text, level="BODY", wrap=True)
    body.setTextInteractionFlags(Qt.TextSelectableByMouse)
    box.addWidget(body)
    return _wrap(frame, mine, glyph="" if mine else "prism")


class _Choice(QFrame):
    """One pressable row: a question in the thread, or a line in the browse
    column. Full width and left-aligned, because these are whole sentences —
    a row of chips would truncate them.

    A QFrame carrying real QLabels rather than a QPushButton with a newline
    in its text, and that is not a style preference. A push button's minimum
    height ignores embedded newlines entirely, so Qt is free to squash it to
    one line once the conversation grows taller than the viewport. Labels
    report a minimum height that includes their second line, so there is
    nothing for the layout to take.

    `flat` is the browse-column skin — no box of its own, because ten boxed
    rows inside one card reads as a list of cards rather than as a list. It
    keeps the hover tint and gains a current state, since that column has to
    show which shelf the thread is currently on.
    """

    clicked = Signal()

    # Everything between the frame's outer edge and the text column. BORDER is
    # the hairline the stylesheet draws: it is outside the contents rect, so
    # leaving it out overstated the text width by 2px — enough, at exactly the
    # wrong window width, to cost a blurb its last word.
    PAD, PAD_Y, GAP, ICON, BORDER, SLACK = 13, 10, 10, 16, 1, 2

    def __init__(self, label: str, icon_name: str = "chevron-right",
                 blurb: str = "", muted: bool = False, trail: str = "",
                 flat: bool = False, level: str = "BODY", parent=None):
        super().__init__(parent)
        self._flat = flat
        if flat:
            # Tighter, because these are index entries in a narrow column and
            # ten of them have to be readable at once — the whole point of the
            # column is that you can see the shape of the book without
            # scrolling it.
            self.PAD, self.PAD_Y = 9, 6
        self._current = False
        self.setObjectName("supportNavRow" if flat else "supportChoice")
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        # Reachable, and visibly so. A row you can only get to with a mouse is
        # not a control, and the focus ring is what the keyboard user reads as
        # "this is the one Enter will open".
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(label)
        # Height-for-width, declared. A word-wrapped QLabel knows how tall it
        # needs to be only once it knows how wide it is, and a layout will not
        # ask unless the size policy says to.
        policy = QSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Minimum)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self._skin()

        row = QHBoxLayout(self)
        row.setContentsMargins(self.PAD, self.PAD_Y, self.PAD, self.PAD_Y)
        row.setSpacing(self.GAP)
        glyph = QLabel()
        glyph.setPixmap(icons.pixmap(
            icon_name, self.ICON,
            theme.NEUTRAL[500] if muted else theme.ACCENT))
        glyph.setAlignment(Qt.AlignTop)
        glyph.setFixedWidth(self.ICON)
        glyph.setStyleSheet("background: transparent;")
        row.addWidget(glyph)

        self._stack = stack = QVBoxLayout()
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(1)
        stack.addWidget(C.label(
            label, level=level, wrap=True,
            colour=theme.NEUTRAL[500] if muted else ""))
        if blurb:
            stack.addWidget(C.label(blurb, role="meta", wrap=True))
        row.addLayout(stack, stretch=1)

        # The count on a topic row. Real — it is how many answers are on that
        # shelf — and it is the thing that makes the column browsable rather
        # than a list of names.
        self._trail = 0
        if trail:
            tag = C.label(trail, role="meta")
            tag.setAlignment(Qt.AlignTop | Qt.AlignRight)
            self._trail = tag.sizeHint().width() + self.GAP
            row.addWidget(tag, alignment=Qt.AlignTop)

    # ── skin ──────────────────────────────────────────────────────────────
    def _skin(self):
        name = self.objectName()
        if self._flat:
            fill = theme.ACCENT_RAMP[100] if self._current else "transparent"
            edge = theme.ACCENT_RAMP[300] if self._current else "transparent"
            hover = theme.ACCENT_RAMP[100] if self._current else theme.WELL
            self.setStyleSheet(
                f"QFrame#{name} {{ background: {fill};"
                f"border: 1px solid {edge};"
                f"border-radius: {theme.R_CONTROL}px; }}"
                f"QFrame#{name}:hover {{ background: {hover};"
                f"border-color: {theme.ACCENT_RAMP[300]}; }}"
                f"QFrame#{name}:focus {{ border-color: {theme.ACCENT}; }}")
            return
        self.setStyleSheet(
            f"QFrame#{name} {{ background: {theme.CARD};"
            f"border: 1px solid {theme.HAIRLINE};"
            f"border-radius: {theme.R_CONTROL}px; }}"
            f"QFrame#{name}:hover {{ border-color: {theme.ACCENT};"
            f"background: {theme.ACCENT_RAMP[100]}; }}"
            f"QFrame#{name}:focus {{ border-color: {theme.ACCENT};"
            f"background: {theme.ACCENT_RAMP[100]}; }}")

    def set_current(self, current: bool):
        if current == self._current:
            return
        self._current = current
        self._skin()

    # ── geometry ──────────────────────────────────────────────────────────
    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        """How tall this row needs to be at that width.

        Asked of the TEXT COLUMN, not of the whole row: a QHBoxLayout answers
        heightForWidth by passing the full width to each child rather than
        the share each will receive.

        SLACK, and not `max(…, sizeHint().height())`, which is what this used
        to take. A word-wrapped QLabel's sizeHint is not its height at any
        particular width — it is Qt's guess at a pleasant wrap, and for a
        sentence of forty characters that guess is two lines. Taking the max
        therefore added a phantom line to every long question and left twenty
        rows on this screen each carrying an inch of nothing. Two pixels
        covers the real problem it was hiding: a single-line label's
        bare-metrics height clips the descender on a "g".
        """
        inner = max(1, width - (2 * self.PAD) - (2 * self.BORDER)
                    - self.ICON - self.GAP - self._trail)
        return (self._stack.heightForWidth(inner) + self.SLACK
                + (2 * self.PAD_Y) + (2 * self.BORDER))

    def resizeEvent(self, event):
        """Pin the height to what this width actually needs. A size POLICY
        was not enough: inside a scroll area Qt handed these rows 43px
        against a minimumSizeHint of 68 and overlapped the two lines. A hard
        setMinimumHeight is the one constraint a layout will not negotiate
        away, and the correct value is only knowable once the width is."""
        super().resizeEvent(event)
        self.setMinimumHeight(self.heightForWidth(self.width()))

    # ── input ─────────────────────────────────────────────────────────────
    def mouseReleaseEvent(self, event):
        # Only a press and release both inside it counts, so dragging away to
        # change your mind works the way it does on every other control.
        if (event.button() == Qt.LeftButton
                and self.rect().contains(event.position().toPoint())):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit()
            return
        super().keyPressEvent(event)


class _Steps(QFrame):
    """The numbered things to try. Same shape as the one in the problem
    dialog, because a customer should not have to learn two layouts for the
    same idea."""

    def __init__(self, steps: tuple[str, ...], parent=None):
        super().__init__(parent)
        self.setObjectName("supportSteps")
        self.setStyleSheet(
            f"QFrame#supportSteps {{ background: {theme.ACCENT_RAMP[100]};"
            f"border: 1px solid {theme.ACCENT_RAMP[200]};"
            f"border-radius: {theme.R_CONTROL}px; }}")
        box = QVBoxLayout(self)
        box.setContentsMargins(theme.SPACE_4, theme.SPACE_3,
                               theme.SPACE_4, theme.SPACE_3)
        box.setSpacing(theme.SPACE_2)
        box.addWidget(C.kicker(i18n.t("Try this")))
        for index, step in enumerate(steps, 1):
            row = QHBoxLayout()
            row.setSpacing(theme.SPACE_3 - 2)
            number = C.label(str(index), level="BODY",
                             colour=theme.ACCENT_RAMP[700], weight=700)
            number.setFixedWidth(16)
            number.setAlignment(Qt.AlignTop | Qt.AlignRight)
            row.addWidget(number)
            body = C.label(step, level="BODY", wrap=True)
            body.setTextInteractionFlags(Qt.TextSelectableByMouse)
            row.addWidget(body, stretch=1)
            box.addLayout(row)


class _AnswerCard(QFrame):
    """One answer, and the only question that matters afterwards: did it
    work? The did-this-help row is not telemetry. It is the gate: "still
    stuck" is what opens the assistant and the contact sheet, so the
    customer is never asked to rate us — they are asked the one thing that
    decides what happens next."""

    def __init__(self, question: KB.Question, locked: bool, on_verdict,
                 on_action, parent=None):
        super().__init__(parent)
        self.setObjectName("supportBot")
        self.setStyleSheet(
            f"QFrame#supportBot {{ background: {theme.CARD};"
            f"border: 1px solid {theme.HAIRLINE};"
            f"border-radius: {theme.R_CARD}px; }}")
        answer = question.answer
        box = QVBoxLayout(self)
        box.setContentsMargins(theme.SPACE_4 - 1, theme.SPACE_3 + 1,
                               theme.SPACE_4 - 1, theme.SPACE_3 + 1)
        box.setSpacing(theme.SPACE_3 - 1)

        topic = _TOPIC_OF.get(question.qid)
        if topic:
            box.addWidget(C.kicker(topic.label))

        if locked:
            tag = C.label(i18n.t("This part isn't in your licence — here's "
                                 "what it does anyway."), role="tagWarn",
                          wrap=True)
            box.addWidget(tag, alignment=Qt.AlignLeft)

        what = C.label(answer.what, level="BODY", wrap=True)
        what.setTextInteractionFlags(Qt.TextSelectableByMouse)
        box.addWidget(what)

        if answer.steps:
            box.addWidget(_Steps(answer.steps))

        if answer.note:
            box.addWidget(C.label(answer.note, role="meta", wrap=True))

        if answer.action:
            go = C.button(i18n.t(answer.action_label or "Take me there"),
                          "secondary", "arrow-right", small=True)
            go.clicked.connect(
                lambda _=False, key=answer.action: on_action(key))
            box.addWidget(go, alignment=Qt.AlignLeft)

        box.addWidget(C.hairline())

        self._verdict = QWidget()
        row = QHBoxLayout(self._verdict)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE_2)
        row.addWidget(C.label(i18n.t("Did that sort it?"), level="SUPPORT"))
        row.addStretch(1)
        for label, solved in ((i18n.t("Yes, thanks"), True),
                              (i18n.t("No, still stuck"), False)):
            btn = C.button(label, "secondary", small=True)
            btn.clicked.connect(
                lambda _=False, s=solved: self._answer(s, question.qid,
                                                       on_verdict))
            row.addWidget(btn)
        box.addWidget(self._verdict)

    def _answer(self, solved: bool, qid: str, on_verdict):
        """Replace the buttons with what was chosen — live buttons left in
        the scrollback are how the conversation forks."""
        layout = self._verdict.layout()
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        layout.addWidget(C.label(
            i18n.t("You said: that sorted it") if solved
            else i18n.t("You said: still stuck"), role="meta"))
        layout.addStretch(1)
        on_verdict(qid, solved)


# ════════════════════════════════════════════════════════════════════════════
class SupportPanel(QWidget):
    """The Help & support screen. `command_requested` carries a sidebar
    command key so an answer's button can take them to the setting instead
    of describing where it lives — the same wiring the guide uses.

    Holds `cfg` because the assistant runs on the customer's own planning
    key; the window re-hands it on every visit so a key saved thirty seconds
    ago — which is exactly when somebody opens the help screen — is seen.
    """

    command_requested = Signal(str)

    # The browse column. Fixed, because it is an index: a column that grows
    # with the window would put the topic names on one line at 1920 and three
    # at 1280, and the list would stop being scannable at either end.
    NAV_W = 352
    # How many of the most-pointed-at questions the thread opens on. Seven
    # fills the conversation column at 1440x900 without the last one landing
    # half-cut on the fold, which reads as a rendering fault rather than as
    # "there is more below".
    STARTERS = 7

    def __init__(self, cfg: dict | None = None, parent=None):
        super().__init__(parent)
        self.cfg = cfg or {}
        self._stage = "triage"
        self._seen: list[str] = []          # answers actually shown
        self._unsolved: list[str] = []      # ones that did not help
        self._log: list[tuple[str, str]] = []   # ("you"/"prism", text)
        self._live: list[QWidget] = []      # menus still pressable
        self._nav_rows: dict[str, _Choice] = {}
        self._worker = None
        self._thinking: QWidget | None = None
        self._thinking_timer: QTimer | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._restart = C.button(i18n.t("Start over"), "secondary", small=True,
                                 on_click=self._start_over)
        self._restart.setToolTip(i18n.t(
            "Clear this conversation and begin again"))
        self._head = C.PageHeader(
            i18n.t("Help & support"),
            i18n.t("{n} written answers, in plain English. Most things are "
                   "sorted by one of them.").format(n=ANSWER_COUNT),
            [self._restart])
        root.addWidget(self._head)

        body = QHBoxLayout()
        body.setContentsMargins(theme.PAGE_PAD, theme.PAGE_PAD,
                                theme.PAGE_PAD, theme.PAGE_PAD)
        body.setSpacing(theme.CARD_GAP)
        body.addWidget(self._browse_column())
        body.addWidget(self._talk_column(), stretch=1)
        root.addLayout(body, stretch=1)

        self._fill_nav()
        self._greet()

    # ── the book: search, then the shelves ────────────────────────────────
    def _browse_column(self) -> QWidget:
        """Search over every written answer, then the ten topics with the
        number of answers on each. Fixed to the left of the conversation and
        never retired, so nothing has to be re-opened to be looked at twice.
        """
        holder = QWidget()
        holder.setFixedWidth(self.NAV_W)
        col = QVBoxLayout(holder)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_3)

        self._search = C.SearchField(i18n.t("Search the written answers"))
        self._search.changed.connect(self._fill_nav)
        col.addWidget(self._search)

        card = C.Card()
        inner = card.body((theme.SPACE_3, theme.SPACE_3,
                           theme.SPACE_3, theme.SPACE_3), theme.SPACE_2)
        head = QHBoxLayout()
        head.setContentsMargins(theme.SPACE_1, 0, theme.SPACE_1, 0)
        head.setSpacing(theme.SPACE_2)
        self._nav_kicker = C.kicker(i18n.t("Browse by topic"))
        head.addWidget(self._nav_kicker, stretch=1)
        self._nav_count = C.meta(
            i18n.t("{n} answers").format(n=ANSWER_COUNT))
        head.addWidget(self._nav_count)
        inner.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        listing = QWidget()
        listing.setStyleSheet("background: transparent;")
        listing.setMinimumSize(1, 1)
        self._nav_box = QVBoxLayout(listing)
        self._nav_box.setContentsMargins(0, 0, theme.SPACE_1, 0)
        self._nav_box.setSpacing(2)
        scroll.setWidget(listing)
        inner.addWidget(scroll, stretch=1)
        col.addWidget(card, stretch=1)
        return holder

    def _fill_nav(self, query: str = ""):
        """Redraw the column: the ten topics, or what a search matched."""
        while self._nav_box.count():
            item = self._nav_box.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
                item.widget().deleteLater()
        self._nav_rows = {}
        query = (query or "").strip()

        if not query:
            self._nav_kicker.setText(i18n.t("Browse by topic").upper())
            self._nav_count.setText(
                i18n.t("{n} answers").format(n=ANSWER_COUNT))
            for topic in KB.TOPICS:
                row = _Choice(topic.label, topic.icon, topic.blurb,
                              trail=str(len(topic.questions)), flat=True,
                              level="CARD_TITLE")
                row.clicked.connect(
                    lambda _=False, k=topic.key: self._pick_topic(k))
                self._nav_box.addWidget(row)
                self._nav_rows[topic.key] = row
            self._nav_box.addStretch(1)
            return

        hits = _matching(query)
        self._nav_kicker.setText(i18n.t("Matches").upper())
        self._nav_count.setText(i18n.t("{n} of {total}").format(
            n=len(hits), total=ANSWER_COUNT))
        if not hits:
            # Genuinely empty, so it centres in the height it has rather than
            # leaving a hole under a one-line apology.
            blank = C.EmptyState(
                "search", i18n.t("Nothing here matches that"),
                i18n.t("Try fewer words. Or ask it in your own words on the "
                       "right — if we have no written answer, the assistant "
                       "and our team open up straight away."))
            self._nav_box.addWidget(blank, stretch=1)
            return
        for question in hits:
            topic = _TOPIC_OF.get(question.qid)
            row = _Choice(question.text, topic.icon if topic else "help",
                          blurb=topic.label if topic else "", flat=True)
            row.clicked.connect(
                lambda _=False, qid=question.qid: self._show_answer(qid))
            self._nav_box.addWidget(row)
        self._nav_box.addStretch(1)

    def _pick_topic(self, key: str):
        for topic_key, row in self._nav_rows.items():
            row.set_current(topic_key == key)
        self._show_topic(key)

    # ── the conversation ──────────────────────────────────────────────────
    def _talk_column(self) -> QWidget:
        holder = QWidget()
        col = QVBoxLayout(holder)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        # A transcript is word-wrapped labels all the way down, and a wrapped
        # label's MINIMUM size is tall-and-narrow — its height when wrapped
        # at its widest single word. QVBoxLayout sums those minimums with no
        # width in hand, so the scroll area was handed a floor hundreds of
        # pixels past the real content. An explicit tiny minimum takes that
        # floor away; the area then sizes the column by height-for-width, the
        # same calculation that places the bubbles.
        inner.setMinimumSize(1, 1)
        self._thread_box = QVBoxLayout(inner)
        self._thread_box.setContentsMargins(0, 0, theme.SPACE_3, theme.SPACE_4)
        self._thread_box.setSpacing(theme.SPACE_3)
        self._thread_box.addStretch(1)
        scroll.setWidget(inner)
        self._scroll = scroll
        # A new message's layout settles over several passes — a word-wrapped
        # label reports its true height only once it knows its width — and
        # each pass grows the scroll range a little more. A single deferred
        # jump lands one pass short, with the newest message just below the
        # fold. So while a message is settling (_follow, armed by _say) the
        # bar rides the range's growth; afterwards it is the reader's.
        self._follow = False
        scroll.verticalScrollBar().rangeChanged.connect(
            lambda _lo, hi: self._follow
            and self._scroll.verticalScrollBar().setValue(hi))
        col.addWidget(scroll, stretch=1)

        col.addWidget(self._composer())
        col.addWidget(self._escalation())
        return holder

    # ── chrome ────────────────────────────────────────────────────────────
    def _composer(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("supportComposer")
        bar.setStyleSheet(
            f"QFrame#supportComposer {{"
            f"border-top: 1px solid {theme.HAIRLINE}; }}")
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, theme.SPACE_3, 0, theme.SPACE_3)
        row.setSpacing(theme.SPACE_2 + 1)
        self._entry = QLineEdit()
        self._entry.setPlaceholderText(
            i18n.t("Or type your question in your own words…"))
        self._entry.setMinimumHeight(38)
        self._entry.setAccessibleName(i18n.t("Your question"))
        self._entry.returnPressed.connect(self._on_typed)
        row.addWidget(self._entry, stretch=1)
        self._send = C.button(i18n.t("Ask"), "primary",
                              on_click=self._on_typed)
        self._send.setMinimumHeight(38)
        row.addWidget(self._send)
        return bar

    def _escalation(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("supportFoot")
        bar.setStyleSheet(
            f"QFrame#supportFoot {{"
            f"border-top: 1px solid {theme.HAIRLINE}; }}")
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, theme.SPACE_3 - 1, 0, 0)
        row.setSpacing(theme.SPACE_2 + 1)
        self._foot_note = C.label("", role="meta", wrap=True)
        row.addWidget(self._foot_note, stretch=1)

        self._ai_btn = C.button(i18n.t(" Ask the assistant"), "secondary",
                                small=True, on_click=self._start_ai)
        row.addWidget(self._ai_btn)

        self._contact_btn = C.button(i18n.t(" Contact the team"), "secondary",
                                     small=True, on_click=self._open_contact)
        row.addWidget(self._contact_btn)

        self._refresh_escalation()
        return bar

    def _refresh_escalation(self):
        """Both routes out, locked or open, with the reason written down.

        A disabled button with no explanation is indistinguishable from a
        broken one, so the padlock always comes with the sentence that says
        what opens it.
        """
        open_now = bool(self._unsolved)
        for btn, icon_name in ((self._ai_btn, "bulb"),
                               (self._contact_btn, "mail")):
            enabled = open_now and not (btn is self._ai_btn
                                        and self._stage == "ai")
            btn.setEnabled(enabled)
            icons.button_icon(btn, icon_name if open_now else "lock", 14,
                              theme.TEXT if enabled else theme.NEUTRAL[400])
        if self._stage == "ai":
            self._foot_note.setText(i18n.t(
                "You're talking to the assistant. It answers from Prism's own "
                "help, and says so when it doesn't know."))
            self._ai_btn.setToolTip("")
            self._contact_btn.setToolTip("")
        elif open_now:
            self._foot_note.setText(i18n.t(
                "Still stuck? The assistant knows Prism's help in full, or "
                "send it to a person."))
            self._ai_btn.setToolTip("")
            self._contact_btn.setToolTip("")
        else:
            self._foot_note.setText(i18n.t(
                "Have a look through the questions first — these open as soon "
                "as one doesn't sort it."))
            tip = i18n.t("Read an answer and press “No, still stuck”, "
                         "or type a question we have no answer for, and this "
                         "opens.")
            self._ai_btn.setToolTip(tip)
            self._contact_btn.setToolTip(tip)

    # ── the transcript ────────────────────────────────────────────────────
    def _say(self, widget: QWidget, scroll: bool = True):
        self._thread_box.insertWidget(self._thread_box.count() - 1, widget)
        if not scroll:
            return
        self._follow = True
        bar = self._scroll.verticalScrollBar()
        QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))
        QTimer.singleShot(250, self._stop_following)

    def _stop_following(self):
        self._follow = False

    def _bot(self, text: str):
        self._log.append(("prism", text))
        self._say(_bubble(text, mine=False))

    def _me(self, text: str):
        self._log.append(("you", text))
        self._say(_bubble(text, mine=True))

    def _retire_menus(self):
        """Take every still-pressable menu out of the thread.

        Called the moment the conversation moves past them. The customer's
        pick is already echoed as their own bubble, so nothing readable is
        lost — what goes is the wall of buttons that made the first version
        read as a form that kept growing, and the stale-click fork risk that
        comes with it. The browse column is not a menu in this sense: it is
        an index, it never posted anything into the thread, and it stays.
        """
        for group in self._live:
            self._thread_box.removeWidget(group)
            group.setParent(None)
            group.deleteLater()
        self._live = []

    def _options(self, buttons: list, scroll: bool = True, header: str = "",
                 note: str = ""):
        holder = QWidget()
        holder.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(theme.SPACE_2 - 2)
        if header:
            box.addWidget(C.kicker(header))
            if note:
                box.addWidget(C.label(note, role="meta", wrap=True))
            box.addSpacing(2)
        for btn in buttons:
            # A chip keeps its own width; a question row is a sentence and
            # takes the column.
            if isinstance(btn, QPushButton):
                box.addWidget(btn, alignment=Qt.AlignLeft)
            else:
                box.addWidget(btn)
        row = _wrap(holder, mine=False, full=True)
        self._live.append(row)
        self._say(row, scroll=scroll)
        return holder

    # ── tier 1: the written answers ───────────────────────────────────────
    def _greet(self):
        # scroll=False on both: the opening state reads from the TOP.
        self._log.append(("prism", i18n.t(
            "Hello. I can answer most questions about Prism straight away.")))
        self._say(_bubble(i18n.t(
            "Hello. I can answer most questions about Prism straight away."
            "\n\nPick one of these, browse the topics on the left, or type "
            "your question at the bottom in your own words."), mine=False),
            scroll=False)
        self._show_starters(scroll=False)
        self._entry.setFocus()

    def _show_starters(self, scroll: bool = True):
        """Open on real questions rather than on a row of topic names.

        These are not a guess at what is popular — see `_most_pointed_at`.
        They are the answers the rest of the written material keeps handing
        people to, which is the closest thing the book has to a well-worn
        page, and every one of them is one press from being read.
        """
        rows = []
        for question in _most_pointed_at(self.STARTERS):
            topic = _TOPIC_OF.get(question.qid)
            row = _Choice(question.text, "chevron-right",
                          blurb=topic.label if topic else "")
            row.clicked.connect(
                lambda _=False, qid=question.qid: self._show_answer(qid))
            rows.append(row)
        self._options(rows, scroll=scroll, header=i18n.t("Common questions"),
                      note=i18n.t("The ones the rest of the help points back "
                                  "at most often."))

    def _show_topic(self, key: str):
        topic = KB.topic(key)
        if not topic:
            return
        self._retire_menus()
        self._me(topic.label)
        self._bot(i18n.t("Which of these is it?"))
        buttons = []
        for question in topic.questions:
            btn = _Choice(question.text, "chevron-right")
            btn.clicked.connect(
                lambda _=False, q=question.qid: self._show_answer(q))
            buttons.append(btn)
        back = _chip(i18n.t("Back to the common questions"), "chevron-left")
        back.clicked.connect(lambda: self._back_to_start())
        self._options(buttons)
        self._options([back])

    def _back_to_start(self):
        self._retire_menus()
        self._show_starters()

    def _show_answer(self, qid: str):
        question = KB.question(qid)
        if not question:
            return
        self._retire_menus()
        self._me(question.text)
        if qid not in self._seen:
            self._seen.append(qid)
        self._log.append(("prism", KB.as_text(question)))

        locked = False
        if question.answer.feature:
            try:
                import licensing
                locked = not licensing.has(question.answer.feature)
            except Exception:               # noqa: BLE001
                locked = False              # never let a licence read hide help
        card = _AnswerCard(question, locked, self._verdict,
                           self._take_action)
        self._say(_wrap(card, mine=False, glyph="prism"))

    def _take_action(self, key: str):
        """An answer's button. Emits the sidebar command; the screen keeps
        its thread, so they can come back to the rest of the answer."""
        self.command_requested.emit(key)

    def _verdict(self, qid: str, solved: bool):
        if solved:
            self._bot(i18n.t("Good — glad that was all it was."))
            again = _chip(i18n.t("Ask about something else"), "help")
            again.clicked.connect(lambda: self._back_to_start())
            self._options([again])
            return

        if qid not in self._unsolved:
            self._unsolved.append(qid)
        self._refresh_escalation()

        nearby = [q for q in KB.related_to(qid) if q.qid not in self._seen]
        if nearby:
            self._bot(i18n.t("Sorry about that. These are close to it — one "
                             "of them may be the real problem:"))
            buttons = []
            for question in nearby:
                btn = _Choice(question.text, "chevron-right")
                btn.clicked.connect(
                    lambda _=False, q=question.qid: self._show_answer(q))
                buttons.append(btn)
            self._options(buttons)
        else:
            self._bot(i18n.t("Sorry about that."))

        self._bot(i18n.t(
            "The two buttons at the bottom are open now. The assistant can "
            "talk it through with you, or you can send it straight to our "
            "team with everything we'd need already filled in."))

    # ── typing a question ─────────────────────────────────────────────────
    def _on_typed(self):
        text = self._entry.text().strip()
        if not text:
            return
        self._entry.clear()
        self._retire_menus()
        self._me(text)
        if self._stage == "ai":
            self._ask_ai(text)
            return

        hits = [q for q in KB.search(text) if q.qid not in self._seen]
        if hits:
            self._bot(i18n.t("Here's the closest I have:"))
            buttons = []
            for question in hits:
                btn = _Choice(question.text, "chevron-right")
                btn.clicked.connect(
                    lambda _=False, q=question.qid: self._show_answer(q))
                buttons.append(btn)
            none = _Choice(i18n.t("None of these is what I meant"), "x",
                           muted=True)
            none.clicked.connect(lambda t=text: self._no_answer(t))
            buttons.append(none)
            self._options(buttons)
        else:
            self._no_answer(text)

    def _no_answer(self, text: str):
        """No written answer for this one — which opens the gate immediately.

        This is the case the gate exists to let through. Making somebody read
        unrelated answers because the book happens not to cover their problem
        would be exactly the behaviour that gives these systems their
        reputation.
        """
        self._retire_menus()
        marker = f"typed:{text[:60]}"
        if marker not in self._unsolved:
            self._unsolved.append(marker)
        self._refresh_escalation()
        self._bot(i18n.t(
            "I don't have a written answer for that one — so I've opened both "
            "buttons at the bottom. The assistant can work through it with "
            "you, or send it to our team and a person will pick it up."))

    # ── tier 2: the assistant ─────────────────────────────────────────────
    def _start_ai(self):
        if not self.cfg.get("api_key"):
            self._bot(i18n.t(
                "The assistant needs the free key Prism uses to work out your "
                "tasks, and there isn't one saved on this computer yet. You "
                "can still contact our team with the button beside this "
                "one."))
            go = _chip(i18n.t("Add the key in Settings"), "key")
            go.clicked.connect(lambda: self.command_requested.emit("key"))
            self._options([go])
            return
        self._stage = "ai"
        self._entry.setPlaceholderText(
            i18n.t("Tell the assistant what's happening…"))
        self._head.set_subtitle(i18n.t(
            "The assistant answers from Prism's own help. If it doesn't know, "
            "it will say so — then use Contact the team."))
        self._refresh_escalation()
        self._bot(i18n.t(
            "Right — I'm the assistant. Tell me what's happening in your own "
            "words, including anything you've already tried, and I'll work "
            "through it with you."))
        self._entry.setFocus()

    def _ask_ai(self, text: str):
        if self._worker is not None:
            return                      # one question at a time
        self._start_thinking()
        self._entry.setEnabled(False)
        self._send.setEnabled(False)

        from workers import SupportWorker
        self._worker = SupportWorker(self.cfg, self._prompt(text), self)
        self._worker.done.connect(self._ai_answered)
        self._worker.failed.connect(self._ai_failed)
        self._worker.start()

    def _prompt(self, text: str) -> str:
        seen = tuple(self._seen)
        talk = "\n".join(
            f"{'CUSTOMER' if who == 'you' else 'PRISM'}: {said}"
            for who, said in self._log[-14:])
        return (
            f"{_SYSTEM}\n\n"
            f"─── PRISM REFERENCE MATERIAL ───\n"
            f"{KB.as_context(text, seen)}\n\n"
            f"─── THIS CUSTOMER'S SITUATION ───\n"
            f"{self._facts()}\n\n"
            f"─── THE CONVERSATION SO FAR ───\n{talk}\n\n"
            f"─── ANSWER THIS ───\n{text}\n\n"
            f"Reply as the support assistant, following the rules above.")

    def _facts(self) -> str:
        """What we know about this machine without asking them anything.

        Half of a support conversation is normally spent establishing these
        four facts. The assistant starts with them.
        """
        bits = [f"Prism version: {app_meta.VERSION}",
                f"Planning key saved: "
                f"{'yes' if self.cfg.get('api_key') else 'NO — not set up yet'}"]
        try:
            import sys
            bits.append(f"Computer: {sys.platform}")
        except Exception:                   # noqa: BLE001
            pass
        try:
            import licensing
            state = licensing.state()
            bits.append(f"Licence: {state.status}"
                        + (f", covers {', '.join(sorted(state.features))}"
                           if getattr(state, "features", None) else ""))
        except Exception:                   # noqa: BLE001
            pass
        if self._seen:
            titles = [KB.question(q).text for q in self._seen
                      if KB.question(q)]
            bits.append("Already read (do not repeat these): "
                        + "; ".join(titles))
        return "\n".join(bits)

    def _start_thinking(self):
        """An animated "Thinking" bubble while the assistant works.

        The dots are appended to the already-translated base, so the
        animation costs one catalogue entry rather than four.
        """
        frame = QFrame()
        frame.setObjectName("supportBot")
        frame.setStyleSheet(
            f"QFrame#supportBot {{ background: {theme.CARD};"
            f"border: 1px solid {theme.HAIRLINE};"
            f"border-radius: {theme.R_CARD}px; }}")
        box = QVBoxLayout(frame)
        box.setContentsMargins(theme.SPACE_4 - 1, theme.SPACE_3,
                               theme.SPACE_4 - 1, theme.SPACE_3)
        label = C.label("", level="BODY", colour=theme.NEUTRAL[600])
        box.addWidget(label)
        base = i18n.t("Thinking")
        ticks = {"count": 0}

        def tick():
            label.setText(base + " ·" * (ticks["count"] % 4))
            ticks["count"] += 1
        tick()
        self._thinking = _wrap(frame, mine=False, glyph="prism")
        self._thinking_timer = QTimer(self)
        self._thinking_timer.timeout.connect(tick)
        self._thinking_timer.start(350)
        self._say(self._thinking)

    def _ai_answered(self, reply: str):
        self._clear_thinking()
        self._bot(reply or i18n.t(
            "I didn't get an answer back that time. Try asking again, or use "
            "Contact the team."))

    def _ai_failed(self, error: str):
        self._clear_thinking()
        # friendly.py already knows how to say every one of these — reusing it
        # means the assistant's failures read exactly like the app's do.
        import friendly
        problem = friendly.explain(error, "support")
        # Title included. Without it the message opens mid-sentence — the
        # headline is the half that says what kind of problem this is, and
        # the steps below make no sense arriving without it.
        text = f"{problem.title}\n\n{problem.what}"
        if problem.steps:
            text += "\n\n" + "\n".join(f"{i}. {s}"
                                       for i, s in enumerate(problem.steps, 1))
        self._bot(text)

    def _clear_thinking(self):
        self._entry.setEnabled(True)
        self._send.setEnabled(True)
        self._entry.setFocus()
        if self._thinking_timer is not None:
            self._thinking_timer.stop()
            self._thinking_timer = None
        if self._thinking is not None:
            self._thread_box.removeWidget(self._thinking)
            self._thinking.setParent(None)
            self._thinking.deleteLater()
            self._thinking = None
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None

    # ── tier 3: a person ──────────────────────────────────────────────────
    def _open_contact(self):
        from dialogs.contact_dialog import ContactDialog
        sheet = ContactDialog(self._transcript(), self.window())
        sheet.exec()
        if sheet.sent:
            self._bot(i18n.t(
                "Sent to our team. We read every one of these and normally "
                "reply the same working day."))

    def _transcript(self) -> str:
        lines = [f"{'Me' if who == 'you' else 'Prism'}: {said}"
                 for who, said in self._log]
        return "\n\n".join(lines)

    # ── starting again ────────────────────────────────────────────────────
    def _start_over(self):
        """Forget the conversation and greet afresh — the one control that
        does. Refused while the assistant is mid-answer, because a reply
        arriving into a cleared thread would answer a question nobody can
        see any more."""
        if self._worker is not None:
            return
        while self._thread_box.count() > 1:      # keep the trailing stretch
            item = self._thread_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._live = []
        self._seen = []
        self._unsolved = []
        self._log = []
        self._stage = "triage"
        self._thinking = None
        self._entry.setEnabled(True)
        self._send.setEnabled(True)
        self._entry.clear()
        self._entry.setPlaceholderText(
            i18n.t("Or type your question in your own words…"))
        self._head.set_subtitle(i18n.t(
            "{n} written answers, in plain English. Most things are sorted "
            "by one of them.").format(n=ANSWER_COUNT))
        self._search.clear()                     # also redraws the column
        self._fill_nav()
        self._refresh_escalation()
        self._greet()

    # ── shutting down ─────────────────────────────────────────────────────
    def shutdown(self):
        """Wind up the assistant's thread before the window goes.

        A running QThread destroyed with its owner takes the whole process
        with it — the customer would see Prism vanish while asking for help,
        which is a memorably bad way to end a support session. Called from
        the main window's own closeEvent, beside its other workers.
        """
        worker = self._worker
        if worker is None:
            return
        try:
            if worker.isRunning() and not worker.wait(3000):
                worker.terminate()
                worker.wait(1000)
        except RuntimeError:
            pass                            # already deleted; nothing to wait
