"""Progressive onboarding: one concept, one real target, one card beside it.

WHAT CHANGED AND WHY. The first version dimmed the whole window to a 51%
black wash and cut a hole in it. The owner's complaint about it is worth
quoting because every decision below answers a clause of it:

    "The onboarding tooltip is too generic and blocks too much of the
     interface... minimal obstruction, one concept at a time, highlight the
     actual target, allow skip, allow restart, remember completed steps. Use
     progressive onboarding. Do not darken the entire screen unnecessarily."

So:

  minimal obstruction   Nothing is dimmed. The screen stays at full strength
                        and the current target gets a painted spotlight — an
                        accent ring with a soft halo breathing around it. A
                        wash is only drawn when a step has no target to point
                        at, because then there is nothing else holding the
                        card down.
  one concept at a time Six steps became five, each one sentence long. Three
                        of the old six pointed at the whole of `home_panel`,
                        which at 1440x900 is most of the window — "highlight
                        the actual target" and "cut a hole around 70% of the
                        screen" are not the same instruction.
  the actual target     Every step names a specific widget, with fallbacks, so
                        a step points at the New task button rather than at
                        the rail that contains it.
  allow skip            Skip is on every step and Escape works throughout.
  allow restart         `restart()` clears progress and begins again; Settings
                        and the rail already emit `tour_requested`.
  remember steps        Each step is written to the config as it is passed, so
                        an interrupted tour resumes where it stopped and a
                        finished one does not re-run.

The spotlight is painted, never a QGraphicsEffect. An effect-driven overlay is
painted through a separate pipeline that renders as *nothing* on software
rasterisers, VMs and remote desktop — for a drop shadow that costs a shadow,
but for something drawn at full-window size over the app it would cost the
entire tour, silently, on exactly the machines least likely to report it.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

import i18n
import theme
from widgets import controls as C

# (id, [candidate attribute paths on MainWindow], title, body).
#
# The paths are tried in order and the first one that resolves to a visible
# widget wins, so a step points at the smallest real thing available and falls
# back to its container rather than disappearing. They are resolved lazily for
# the same reason: a build where an add-on is hidden must skip that step, not
# crash the tour.
#
# `_gated` is the rail's dict of licensed add-on rows, so `sidebar._gated
# [inquiry][0]` is the Email automation row itself — one row, about 34px tall,
# instead of the 240px-wide rail it sits in.
STEPS = [
    ("new_task",
     ["sidebar.new_task_btn", "sidebar"],
     "Start a job here",
     "Describe what you want in your own words. Prism works out the steps."),
    ("addons",
     ["sidebar._gated[inquiry][0]", "sidebar._gated[boq][0]", "sidebar"],
     "Jobs you do every day",
     "Email automation, BOQ and Gerber are ready-made — attach your files "
     "and go, no plan needed."),
    ("home",
     ["home_panel", "sidebar._nav[home]"],
     "Home is the report",
     "Where things stand: what is running now, what finished, and what is "
     "waiting on you."),
    ("history",
     ["sidebar._nav[runs]", "sidebar"],
     "Nothing is lost",
     "Every finished job stays in History, with the links its tools "
     "produced."),
    ("settings",
     ["sidebar._nav[config]", "sidebar"],
     "Everything else is in Settings",
     "Your licence, your specialists and your profile — always one click "
     "away."),
]

_CONFIG_KEY = "tour"


# ── remembering where somebody got to ───────────────────────────────────────
def _load() -> dict:
    """The saved tour state, or an empty one. Never raises: a tour is a
    nicety, and a corrupt config file must not stop the app opening."""
    try:
        import core_bridge as CB
        return dict((CB.config.load() or {}).get(_CONFIG_KEY) or {})
    except Exception:                                   # noqa: BLE001
        return {}


def _store(state: dict) -> None:
    try:
        import core_bridge as CB
        cfg = CB.config.load() or {}
        cfg[_CONFIG_KEY] = state
        CB.config.save(cfg)
    except Exception:                                   # noqa: BLE001
        pass


def seen_steps() -> set:
    """Which step ids this person has already been shown."""
    return set(_load().get("seen") or [])


def mark_seen(step_id: str) -> None:
    state = _load()
    seen = list(state.get("seen") or [])
    if step_id not in seen:
        seen.append(step_id)
    state["seen"] = seen
    if len(set(seen)) >= len(STEPS):
        state["complete"] = True
    _store(state)


def is_complete() -> bool:
    """True once every step has been passed. main_window can ask this before
    offering the tour on first run, so it is offered once and not again."""
    state = _load()
    return bool(state.get("complete")) or seen_steps() >= {s[0] for s in STEPS}


def reset_progress() -> None:
    _store({"seen": [], "complete": False})


class TourOverlay(QWidget):
    """A transparent sheet over the window that spotlights one widget at a
    time and explains it in a card beside it."""

    finished = Signal()

    # How far outside the target the ring and its halo reach.
    _PAD = 6
    _HALO = 3
    # The tallest band the spotlight will draw, and the share of the window
    # above which a target counts as "a region" rather than "a control".
    #
    # This is the mechanical half of "highlight the actual target". Some steps
    # genuinely mean a region — Home is a screen, not a button — but ringing a
    # 900px-tall panel outlines most of the window and says nothing, which is
    # what "too generic" meant. A region is drawn as the band across its top
    # instead: still the real widget, still where the reader should look, and
    # still leaving the rest of the interface untouched.
    _BAND = 190
    _REGION_SHARE = 0.40

    def __init__(self, host, parent=None):
        super().__init__(parent or host)
        self._host = host
        self._step = 0
        self._target: QWidget | None = None
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(i18n.t("Prism tour"))

        # A repaint timer, not an animation object and certainly not a
        # QGraphicsEffect — the worst case on a bad renderer is that the halo
        # holds still, rather than that the whole overlay vanishes.
        self._phase = 0.0
        self._pulse = QTimer(self)
        self._pulse.setInterval(70)
        self._pulse.timeout.connect(self._tick)

        self._card = C.Card()
        self._card.setParent(self)
        self._card.setFixedWidth(292)
        col = self._card.body((theme.CARD_PAD, theme.SPACE_4,
                               theme.CARD_PAD, theme.SPACE_4), 0)

        self._kicker = C.kicker("", muted=True)
        col.addWidget(self._kicker)
        col.addSpacing(theme.SPACE_2)
        self._title = C.heading("", level=5)
        self._title.setWordWrap(True)
        col.addWidget(self._title)
        col.addSpacing(theme.SPACE_1 + 2)
        self._body = C.label("", level="SUPPORT", wrap=True)
        col.addWidget(self._body)
        col.addSpacing(theme.SPACE_4)

        dots = QHBoxLayout()
        dots.setContentsMargins(0, 0, 0, 0)
        dots.setSpacing(theme.SPACE_1)
        for _ in STEPS:
            dot = QLabel()
            dot.setFixedSize(18, 3)
            dot.setAttribute(Qt.WA_StyledBackground, True)
            dots.addWidget(dot)
        self._dots = [dots.itemAt(i).widget() for i in range(dots.count())]
        dots.addStretch(1)
        col.addLayout(dots)
        col.addSpacing(theme.SPACE_4)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(theme.SPACE_2)
        # Skip is a real button on every step, at the opposite end of the row
        # from Next. A tour nobody can leave is an interruption, not an offer.
        self._skip = C.button(i18n.t("Skip"), "tertiary", small=True,
                              on_click=self.stop)
        self._skip.setToolTip(i18n.t("Close the tour. You can restart it any "
                                     "time from Settings."))
        actions.addWidget(self._skip)
        actions.addStretch(1)
        self._back = C.button(i18n.t("Back"), "secondary", small=True,
                              on_click=self.previous)
        actions.addWidget(self._back)
        self._next = C.button(i18n.t("Next"), "primary",
                              on_click=self.advance)
        actions.addWidget(self._next)
        col.addLayout(actions)

        host.installEventFilter(self)

    # ── control ───────────────────────────────────────────────────────────
    def start(self):
        """Show the tour, resuming at the first step this person has not seen.

        A finished tour restarts from the top rather than refusing: by the time
        somebody asks for it a second time they have asked on purpose, and
        opening an empty tour would be the wrong answer to a deliberate click.
        """
        seen = seen_steps()
        first = next((i for i, step in enumerate(STEPS)
                      if step[0] not in seen), 0)
        self._begin(first)

    def restart(self):
        """Forget the saved progress and run the whole tour again."""
        reset_progress()
        self._begin(0)

    def _begin(self, index: int):
        self._step = max(0, min(index, len(STEPS) - 1))
        self.setGeometry(self._host.rect())
        self.show()
        self.raise_()
        self.setFocus()
        self._pulse.start()
        self._apply()

    def advance(self):
        mark_seen(STEPS[self._step][0])
        if self._step + 1 >= len(STEPS):
            self.stop()
            return
        self._step += 1
        self._apply()

    def previous(self):
        if self._step > 0:
            self._step -= 1
            self._apply()

    def stop(self):
        # The step on screen counts as seen even when Skip ends the tour:
        # somebody who read step two and left has read step two, and showing
        # it to them again next time is the behaviour they just declined.
        mark_seen(STEPS[self._step][0])
        self._pulse.stop()
        self.hide()
        self.finished.emit()

    # ── layout ────────────────────────────────────────────────────────────
    def _resolve(self, path: str) -> QWidget | None:
        """Walk an attribute path, with `name[key]` for dicts and lists.

        `sidebar._gated[inquiry][0]` is the Email automation row: the rail
        keeps its licensed add-ons in a dict of tuples, and pointing at the
        row rather than at the rail is the whole difference between
        highlighting a control and highlighting a quarter of the window.
        """
        node = self._host
        for part in path.split("."):
            name, _, rest = part.partition("[")
            if name:
                node = getattr(node, name, None)
            for key in [k for k in rest.split("[") if k]:
                key = key.rstrip("]")
                try:
                    node = node[int(key)] if key.lstrip("-").isdigit() \
                        else node[key]
                except (TypeError, KeyError, IndexError, AttributeError):
                    return None
            if node is None:
                return None
        return node if isinstance(node, QWidget) and node.isVisible() else None

    def _first_target(self, paths) -> QWidget | None:
        for path in paths:
            found = self._resolve(path)
            if found is not None:
                return found
        return None

    def _tick(self):
        self._phase = (self._phase + 0.045) % 1.0
        self.update()

    def _apply(self):
        _id, paths, title, body = STEPS[self._step]
        self._target = self._first_target(paths)
        self._kicker.setText(i18n.t("STEP {n} OF {total}").format(
            n=self._step + 1, total=len(STEPS)))
        self._title.setText(i18n.t(title))
        self._body.setText(i18n.t(body))
        self._back.setVisible(self._step > 0)
        self._next.setText(i18n.t("Finish") if self._step + 1 >= len(STEPS)
                           else i18n.t("Next"))
        seen = seen_steps()
        for i, dot in enumerate(self._dots):
            if i == self._step:
                colour = theme.ACCENT
            elif STEPS[i][0] in seen:
                colour = theme.ACCENT_RAMP[300]
            else:
                colour = theme.NEUTRAL[300]
            dot.setStyleSheet(f"background: {colour};"
                              f" border-radius: {theme.R_MICRO // 2}px;")
        # What a screen reader reads out, because the visual half of a step is
        # a ring around something else entirely.
        self.setAccessibleDescription(
            f"{i18n.t(title)}. {i18n.t(body)}")
        self._place_card()
        self.update()

    def _hole(self) -> QRect | None:
        if self._target is None:
            return None
        top_left = self._target.mapTo(self._host, QPoint(0, 0))
        rect = QRect(top_left, self._target.size()).adjusted(
            -self._PAD, -self._PAD, self._PAD, self._PAD)
        page = max(1, self.width() * self.height())
        if rect.width() * rect.height() > page * self._REGION_SHARE:
            rect.setHeight(min(rect.height(), self._BAND))
        return rect

    def _place_card(self):
        """Beside the spotlight, on whichever side has room, never over it.

        Each candidate is tested against the highlight rather than picked by a
        rule about which half of the screen the target is in — the rail's
        add-on rows and Home's run strip want opposite answers, and a card that
        covers the thing it is describing is the one failure this cannot have.
        """
        # The card has a fixed width and a wrapping body, so sizeHint alone
        # under-measures it: a three-line explanation was being drawn into the
        # space a two-line one left behind, on top of its own title. Ask the
        # layout what height this width actually needs.
        self._card.adjustSize()
        layout = self._card.layout()
        if layout is not None and layout.hasHeightForWidth():
            needed = layout.heightForWidth(self._card.width())
            if needed > 0:
                self._card.setFixedHeight(needed)
        size = self._card.size()
        gap, margin = theme.SPACE_4, theme.SPACE_6
        hole = self._hole()
        if hole is None:
            self._card.move(
                int((self.width() - size.width()) / 2),
                int((self.height() - size.height()) / 2))
            return

        def clamp(x, y):
            x = max(margin, min(int(x), self.width() - size.width() - margin))
            y = max(margin, min(int(y), self.height() - size.height() - margin))
            return QRect(x, y, size.width(), size.height())

        near_y = hole.top()
        candidates = [
            clamp(hole.right() + gap, near_y),          # to its right
            clamp(hole.left() - gap - size.width(), near_y),
            clamp(hole.left(), hole.bottom() + gap),    # under it
            clamp(hole.left(), hole.top() - gap - size.height()),
        ]
        halo = hole.adjusted(-self._HALO * 4, -self._HALO * 4,
                             self._HALO * 4, self._HALO * 4)
        for rect in candidates:
            if not rect.intersects(halo):
                self._card.move(rect.topLeft())
                return
        # Nothing clears the target — put the card in the far corner from it
        # rather than on top of it.
        far_x = margin if hole.center().x() > self.width() // 2 \
            else self.width() - size.width() - margin
        far_y = margin if hole.center().y() > self.height() // 2 \
            else self.height() - size.height() - margin
        self._card.move(int(far_x), int(far_y))

    # ── paint ─────────────────────────────────────────────────────────────
    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        hole = self._hole()

        if hole is None:
            # No target to anchor the card, so the card needs ground of its
            # own. This is the ONLY case that dims anything, and it is the
            # case the owner's complaint was not about.
            painter.fillRect(self.rect(), QColor(15, 20, 26, 96))
        else:
            self._paint_spotlight(painter, hole)
        self._paint_card_shadow(painter)

    def _paint_spotlight(self, painter: QPainter, hole: QRect):
        """An accent ring with three fading rings breathing outside it.

        This replaces the dark wash entirely. A ring alone is easy to miss on
        a busy screen; a ring with a halo that moves is not, and it costs the
        rest of the interface nothing — everything around it stays at full
        strength and full legibility, which is the whole point.
        """
        grow = self._phase
        radius = theme.R_CONTROL + 2
        for step in range(self._HALO, 0, -1):
            spread = int(step * 5 + grow * 5)
            alpha = max(0.0, 0.26 * (1 - (step - 1) / self._HALO)
                        * (1 - grow * 0.45))
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(theme.c(theme.ACCENT, alpha), 3))
            painter.drawRoundedRect(
                QRectF(hole.adjusted(-spread, -spread, spread, spread)),
                radius + spread, radius + spread)
        painter.setPen(QPen(theme.c(theme.ACCENT), 2.5))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(QRectF(hole), radius, radius)

    def _paint_card_shadow(self, painter: QPainter):
        """A painted lift under the card.

        Nothing is dimmed any more, so the card is a white panel sitting on
        whatever happened to be underneath it. It needs to read as floating,
        and the ordinary way to do that — QGraphicsDropShadowEffect — is the
        one thing this file must not use.
        """
        rect = self._card.geometry()
        if rect.isEmpty():
            return
        painter.setPen(Qt.NoPen)
        for step in range(6, 0, -1):
            painter.setBrush(theme.c(theme.SHADOW_INK, 0.030))
            painter.drawRoundedRect(
                QRectF(rect.adjusted(-step, -step + 2, step, step + 3)),
                theme.R_CARD + step, theme.R_CARD + step)

    # ── events ────────────────────────────────────────────────────────────
    def eventFilter(self, obj, event):
        if obj is self._host and event.type() == QEvent.Resize and self.isVisible():
            self.setGeometry(self._host.rect())
            self._place_card()
        return False

    def hideEvent(self, event):
        # A repaint timer behind a hidden overlay is a wakeup nobody sees.
        self._pulse.stop()
        super().hideEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.stop()
        elif event.key() in (Qt.Key_Right, Qt.Key_Return, Qt.Key_Enter):
            self.advance()
        elif event.key() == Qt.Key_Left:
            self.previous()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        """Clicking the open area steps forward; clicking the highlight does
        nothing, so a tour step cannot fire the button it is pointing at."""
        hole = self._hole()
        if hole is not None and hole.contains(event.pos()):
            return
        if not self._card.geometry().contains(event.pos()):
            self.advance()
