"""Help & support — the written answers first, then the assistant, then us.

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
The transcript is a conversation, not a ledger
────────────────────────────────────────────────────────────────────────────
The first version posted every menu into the thread and left it there — ten
topic cards, then ten question rows, then ten more topic cards when somebody
went back — and the screen read as a form that kept growing rather than a
conversation that moved. Three rules fixed it, and they are worth keeping:

  · **Topics are chips**, one line of the screen, because their names are
    two words long. Questions stay full-width rows, because they are whole
    sentences and a truncated question cannot be chosen.
  · **A menu is retired the moment the conversation moves past it.** The
    pick is already echoed as the customer's own bubble, so nothing is lost
    — and live buttons left in the scrollback are how a conversation forks.
    (The did-this-help row collapses itself for the same reason.)
  · **Prism's messages carry its mark.** Two voices in one column need
    telling apart faster than reading them.

This is a SCREEN, not a dialog — it keeps its conversation for the life of
the window, so following an answer's button to Settings and coming back
lands on the same thread. Start over is the one control that forgets.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLayout, QLineEdit, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

import app_meta
import i18n
import support_kb as KB
import theme
from widgets import icons
from widgets.controls import kicker

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


# ── layout for the topic chips ─────────────────────────────────────────────
class _FlowLayout(QLayout):
    """Left-to-right, wrapping. Qt ships no flow layout; this is the classic
    example implementation, kept because ten topic chips must take three
    short rows at any width rather than one column of ten."""

    def __init__(self, parent=None, hspace: int = 8, vspace: int = 8):
        super().__init__(parent)
        self._items = []
        self._h, self._v = hspace, vspace
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(QRect(0, 0, width, 0), place=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect, place=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _arrange(self, rect, *, place: bool) -> int:
        x, y, row = rect.x(), rect.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > rect.right() + 1 and row:
                x = rect.x()
                y += row + self._v
                row = 0
            if place:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._h
            row = max(row, hint.height())
        return y + row - rect.y()


def _chip(label: str, icon_name: str = "", tip: str = "") -> QPushButton:
    """One compact pressable — a topic, or a small conversational move."""
    btn = QPushButton(f" {label}" if icon_name else label)
    btn.setObjectName("supportChip")
    btn.setCursor(Qt.PointingHandCursor)
    if icon_name:
        icons.button_icon(btn, icon_name, 14, theme.ACCENT)
    if tip:
        btn.setToolTip(tip)
    btn.setStyleSheet(
        f"QPushButton#supportChip {{ background: {theme.CARD};"
        f"border: 1px solid {theme.DIVIDER}; border-radius: 14px;"
        f"padding: 5px 12px; font-size: 13px;"
        f"color: {theme.NEUTRAL[800]}; }}"
        f"QPushButton#supportChip:hover {{ border-color: {theme.ACCENT};"
        f"background: {theme.ACCENT_RAMP[100]}; }}")
    return btn


# ── little shared pieces ───────────────────────────────────────────────────
def _wrap(widget: QWidget, mine: bool, glyph: str = "") -> QWidget:
    """Put one message on its side of the transcript.

    Stretch rather than a fixed maximum width, so a bubble is ~75% of
    whatever the column happens to be. `glyph` puts Prism's mark beside its
    own messages — two voices in one column need telling apart at a glance.

    Minimum vertical policy, or a message can be squeezed shorter than its
    own text: these rows stack inside a scroll area that is routinely
    shorter than its content, so "short of room" is the normal case.
    """
    row = QWidget()
    row.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
    box = QHBoxLayout(row)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(8)
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
        f"border: 1px solid {theme.DIVIDER if not mine else theme.ACCENT_RAMP[300]};"
        f"border-radius: {theme.R_CARD}px; }}")
    box = QVBoxLayout(frame)
    box.setContentsMargins(15, 12, 15, 12)
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    label.setStyleSheet(f"color: {theme.NEUTRAL[800]}; font-size: 13.5px;"
                        " background: transparent;")
    box.addWidget(label)
    return _wrap(frame, mine, glyph="" if mine else "prism")


class _Choice(QFrame):
    """One question they can press. Full width and left-aligned, because
    these are whole sentences — a row of chips would truncate them.

    A QFrame carrying real QLabels rather than a QPushButton with a newline
    in its text, and that is not a style preference. A push button's minimum
    height ignores embedded newlines entirely, so Qt is free to squash it to
    one line once the conversation grows taller than the viewport. Labels
    report a minimum height that includes their second line, so there is
    nothing for the layout to take.
    """

    clicked = Signal()

    # Everything between the frame's outer edge and the text column. BORDER is
    # the hairline the stylesheet draws: it is outside the contents rect, so
    # leaving it out overstated the text width by 2px — enough, at exactly the
    # wrong window width, to cost a blurb its last word.
    PAD, PAD_Y, GAP, ICON, BORDER = 13, 10, 10, 16, 1

    def __init__(self, label: str, icon_name: str = "chevron-right",
                 blurb: str = "", muted: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("supportChoice")
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        # Height-for-width, declared. A word-wrapped QLabel knows how tall it
        # needs to be only once it knows how wide it is, and a layout will not
        # ask unless the size policy says to.
        policy = QSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Minimum)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setStyleSheet(
            f"QFrame#supportChoice {{ background: {theme.CARD};"
            f"border: 1px solid {theme.DIVIDER};"
            f"border-radius: {theme.R_CONTROL}px; }}"
            f"QFrame#supportChoice:hover {{ border-color: {theme.ACCENT};"
            f"background: {theme.ACCENT_RAMP[100]}; }}")

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
        title = QLabel(label)
        title.setWordWrap(True)
        title.setStyleSheet(
            f"color: {theme.NEUTRAL[500] if muted else theme.NEUTRAL[800]};"
            f"font-size: 13.5px; background: transparent;")
        stack.addWidget(title)
        if blurb:
            sub = QLabel(blurb)
            sub.setObjectName("meta")
            sub.setWordWrap(True)
            sub.setStyleSheet("background: transparent;")
            stack.addWidget(sub)
        row.addLayout(stack, stretch=1)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        """How tall this row needs to be at that width.

        Asked of the TEXT COLUMN, not of the whole row: a QHBoxLayout answers
        heightForWidth by passing the full width to each child rather than
        the share each will receive. The max with the plain sizeHint covers
        single-line labels, whose bare-metrics heightForWidth comes up a
        couple of pixels short and clipped every descender.
        """
        inner = max(1, width - (2 * self.PAD) - (2 * self.BORDER)
                    - self.ICON - self.GAP)
        text = max(self._stack.heightForWidth(inner),
                   self._stack.sizeHint().height())
        return text + (2 * self.PAD_Y) + (2 * self.BORDER)

    def resizeEvent(self, event):
        """Pin the height to what this width actually needs. A size POLICY
        was not enough: inside a scroll area Qt handed these rows 43px
        against a minimumSizeHint of 68 and overlapped the two lines. A hard
        setMinimumHeight is the one constraint a layout will not negotiate
        away, and the correct value is only knowable once the width is."""
        super().resizeEvent(event)
        self.setMinimumHeight(self.heightForWidth(self.width()))

    def mouseReleaseEvent(self, event):
        # Only a press and release both inside it counts, so dragging away to
        # change your mind works the way it does on every other control.
        if (event.button() == Qt.LeftButton
                and self.rect().contains(event.position().toPoint())):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class _Steps(QFrame):
    """The numbered things to try. Same shape as the one in the problem
    dialog, because a customer should not have to learn two layouts for the
    same idea."""

    def __init__(self, steps: tuple[str, ...], parent=None):
        super().__init__(parent)
        self.setObjectName("supportSteps")
        self.setStyleSheet(
            f"QFrame#supportSteps {{ background: {theme.ACCENT_RAMP[100]};"
            f"border: 1px solid {theme.DIVIDER};"
            f"border-radius: {theme.R_CONTROL}px; }}")
        box = QVBoxLayout(self)
        box.setContentsMargins(16, 13, 16, 13)
        box.setSpacing(8)
        box.addWidget(kicker(i18n.t("Try this")))
        for index, step in enumerate(steps, 1):
            row = QHBoxLayout()
            row.setSpacing(10)
            number = QLabel(str(index))
            number.setFixedWidth(16)
            number.setAlignment(Qt.AlignTop | Qt.AlignRight)
            number.setStyleSheet(
                f"color: {theme.ACCENT_RAMP[700]}; font-weight: 700;"
                f"font-size: 13.5px; background: transparent;")
            row.addWidget(number)
            body = QLabel(step)
            body.setWordWrap(True)
            body.setTextInteractionFlags(Qt.TextSelectableByMouse)
            body.setStyleSheet(
                f"color: {theme.NEUTRAL[800]}; font-size: 13.5px;"
                " background: transparent;")
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
            f"border: 1px solid {theme.DIVIDER};"
            f"border-radius: {theme.R_CARD}px; }}")
        answer = question.answer
        box = QVBoxLayout(self)
        box.setContentsMargins(15, 13, 15, 13)
        box.setSpacing(11)

        if locked:
            tag = QLabel(i18n.t("This part isn't in your licence — here's "
                                "what it does anyway."))
            tag.setObjectName("tagWarn")
            tag.setWordWrap(True)
            box.addWidget(tag, alignment=Qt.AlignLeft)

        what = QLabel(answer.what)
        what.setWordWrap(True)
        what.setTextInteractionFlags(Qt.TextSelectableByMouse)
        what.setStyleSheet(f"color: {theme.NEUTRAL[800]}; font-size: 13.5px;"
                           " background: transparent;")
        box.addWidget(what)

        if answer.steps:
            box.addWidget(_Steps(answer.steps))

        if answer.note:
            note = QLabel(answer.note)
            note.setObjectName("meta")
            note.setWordWrap(True)
            note.setStyleSheet("background: transparent;")
            box.addWidget(note)

        if answer.action:
            go = QPushButton(i18n.t(answer.action_label or "Take me there"))
            go.setObjectName("smallBtn")
            go.setCursor(Qt.PointingHandCursor)
            go.clicked.connect(
                lambda _=False, key=answer.action: on_action(key))
            box.addWidget(go, alignment=Qt.AlignLeft)

        rule = QFrame()
        rule.setObjectName("hr")
        rule.setFixedHeight(1)
        box.addWidget(rule)

        self._verdict = QWidget()
        row = QHBoxLayout(self._verdict)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        ask = QLabel(i18n.t("Did that sort it?"))
        ask.setStyleSheet(f"color: {theme.NEUTRAL[700]}; font-size: 13px;"
                          " background: transparent;")
        row.addWidget(ask)
        row.addStretch(1)
        for label, solved in ((i18n.t("Yes, thanks"), True),
                              (i18n.t("No, still stuck"), False)):
            btn = QPushButton(label)
            btn.setObjectName("smallBtn")
            btn.setCursor(Qt.PointingHandCursor)
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
        said = QLabel(i18n.t("You said: that sorted it") if solved
                      else i18n.t("You said: still stuck"))
        said.setStyleSheet(f"color: {theme.NEUTRAL[500]}; font-size: 12px;"
                           " background: transparent;")
        layout.addWidget(said)
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

    # Narrower than the report screens' 1120: this is a conversation, and a
    # bubble stretched across a 27" monitor reads like a banner, not a reply.
    MAX_W = 880

    def __init__(self, cfg: dict | None = None, parent=None):
        super().__init__(parent)
        self.cfg = cfg or {}
        self._stage = "triage"
        self._seen: list[str] = []          # answers actually shown
        self._unsolved: list[str] = []      # ones that did not help
        self._log: list[tuple[str, str]] = []   # ("you"/"prism", text)
        self._live: list[QWidget] = []      # menus still pressable
        self._worker = None
        self._thinking: QWidget | None = None
        self._thinking_timer: QTimer | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(40, 32, 40, 20)
        holder = QWidget()
        holder.setMaximumWidth(self.MAX_W)
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        outer.addWidget(holder, stretch=1)
        outer.addStretch(0)

        head = QHBoxLayout()
        head.setSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel(i18n.t("Help & support"))
        title.setObjectName("h2")
        titles.addWidget(title)
        self._blurb = QLabel(i18n.t(
            "Start with the common questions — most things are answered in "
            "one. If yours isn't, the assistant and our team open up."))
        self._blurb.setWordWrap(True)
        self._blurb.setStyleSheet(
            f"font-size: 13px; color: {theme.NEUTRAL[600]};"
            " background: transparent;")
        titles.addWidget(self._blurb)
        head.addLayout(titles, stretch=1)
        self._restart = QPushButton(i18n.t("Start over"))
        self._restart.setObjectName("smallBtn")
        self._restart.setCursor(Qt.PointingHandCursor)
        self._restart.setToolTip(i18n.t(
            "Clear this conversation and begin again"))
        self._restart.clicked.connect(self._start_over)
        head.addWidget(self._restart, alignment=Qt.AlignTop)
        column.addLayout(head)
        column.addSpacing(14)

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
        self._thread_box.setContentsMargins(0, 4, 10, 14)
        self._thread_box.setSpacing(12)
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
        column.addWidget(scroll, stretch=1)

        column.addWidget(self._composer())
        column.addWidget(self._escalation())

        self._greet()

    # ── chrome ────────────────────────────────────────────────────────────
    def _composer(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("supportComposer")
        bar.setStyleSheet(
            f"QFrame#supportComposer {{"
            f"border-top: 1px solid {theme.DIVIDER}; }}")
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 13, 0, 13)
        row.setSpacing(9)
        self._entry = QLineEdit()
        self._entry.setPlaceholderText(
            i18n.t("Or type your question in your own words…"))
        self._entry.setMinimumHeight(38)
        self._entry.returnPressed.connect(self._on_typed)
        row.addWidget(self._entry, stretch=1)
        self._send = QPushButton(i18n.t("Ask"))
        self._send.setObjectName("primaryBtn")
        self._send.setCursor(Qt.PointingHandCursor)
        self._send.setMinimumHeight(38)
        self._send.clicked.connect(self._on_typed)
        row.addWidget(self._send)
        return bar

    def _escalation(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("supportFoot")
        bar.setStyleSheet(
            f"QFrame#supportFoot {{"
            f"border-top: 1px solid {theme.DIVIDER}; }}")
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 11, 0, 0)
        row.setSpacing(9)
        self._foot_note = QLabel()
        self._foot_note.setObjectName("meta")
        self._foot_note.setWordWrap(True)
        row.addWidget(self._foot_note, stretch=1)

        self._ai_btn = QPushButton(i18n.t(" Ask the assistant"))
        self._ai_btn.setObjectName("smallBtn")
        self._ai_btn.setCursor(Qt.PointingHandCursor)
        self._ai_btn.clicked.connect(self._start_ai)
        row.addWidget(self._ai_btn)

        self._contact_btn = QPushButton(i18n.t(" Contact the team"))
        self._contact_btn.setObjectName("smallBtn")
        self._contact_btn.setCursor(Qt.PointingHandCursor)
        self._contact_btn.clicked.connect(self._open_contact)
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
        comes with it.
        """
        for group in self._live:
            self._thread_box.removeWidget(group)
            group.setParent(None)
            group.deleteLater()
        self._live = []

    def _options(self, buttons: list, scroll: bool = True,
                 chips: bool = False):
        holder = QWidget()
        holder.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        if chips:
            box = _FlowLayout(holder)
        else:
            box = QVBoxLayout(holder)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(6)
        for btn in buttons:
            box.addWidget(btn)
        row = _wrap(holder, mine=False)
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
            "\n\nPick the topic that is closest, or type your question at "
            "the bottom in your own words."), mine=False), scroll=False)
        self._show_topics(scroll=False)
        self._entry.setFocus()

    def _show_topics(self, scroll: bool = True):
        chips = []
        for topic in KB.TOPICS:
            btn = _chip(topic.label, topic.icon, topic.blurb)
            btn.clicked.connect(
                lambda _=False, k=topic.key: self._show_topic(k))
            chips.append(btn)
        self._options(chips, scroll=scroll, chips=True)

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
        back = _chip(i18n.t("All the topics"), "chevron-left")
        back.clicked.connect(lambda: self._back_to_topics())
        self._options(buttons)
        self._options([back])

    def _back_to_topics(self):
        self._retire_menus()
        self._show_topics()

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
            again.clicked.connect(lambda: self._back_to_topics())
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
        self._blurb.setText(i18n.t(
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
            f"border: 1px solid {theme.DIVIDER};"
            f"border-radius: {theme.R_CARD}px; }}")
        box = QVBoxLayout(frame)
        box.setContentsMargins(15, 12, 15, 12)
        label = QLabel()
        label.setStyleSheet(f"color: {theme.NEUTRAL[600]}; font-size: 13.5px;"
                            " background: transparent;")
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
        self._blurb.setText(i18n.t(
            "Start with the common questions — most things are answered in "
            "one. If yours isn't, the assistant and our team open up."))
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
