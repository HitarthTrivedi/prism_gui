"""The visual vocabulary of the WhatsApp workspace — time formatting, avatar
colours, and the two row painters (conversations and contacts).

Rows are PAINTED, not built from a widget per row. The first version put a
QFrame of labels inside every QListWidgetItem and sized the item from a
throwaway copy of the widget; the real one then disagreed by a few pixels and
clipped its own second line. A delegate owns its own geometry, elides text to
the width it actually has, and costs nothing per row — which is what an inbox
that may hold a few thousand conversations needs.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

import i18n
import theme
from addons.whatsapp import readstate

CONVO_ROW_H = 72
CONTACT_ROW_H = 60

# Muted, distinct hues that all clear white-on-fill contrast. Chosen by hashing
# the NAME, so a person is the same colour in the inbox, the thread header and
# the contacts list — and across restarts, which `hash()` would not give us.
_HUES = ("#0f766e", "#4f46e5", "#b45309", "#be123c", "#0369a1", "#6d28d9",
         "#15803d", "#9a3412", "#0e7490", "#7e22ce")


def avatar_colour(name: str, opted_out: bool = False) -> str:
    if opted_out:
        return theme.NEUTRAL[500]
    total = sum(ord(ch) for ch in (name or "?"))
    return _HUES[total % len(_HUES)]


# ── time ─────────────────────────────────────────────────────────────────────

def parse_ts(stamp: str) -> datetime | None:
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return None


def clock(stamp: str) -> str:
    """8:41 AM — the time inside a bubble."""
    dt = parse_ts(stamp)
    if dt is None:
        return ""
    return dt.strftime("%I:%M %p").lstrip("0")


def short_time(stamp: str) -> str:
    """The time on a conversation row: a clock today, then Yesterday, then the
    weekday for the past week, then a date — the ladder every messenger uses,
    because each rung answers 'how long ago' at the precision that matters."""
    dt = parse_ts(stamp)
    if dt is None:
        return ""
    today = datetime.now().astimezone().date()
    gap = (today - dt.date()).days
    if gap <= 0:
        return clock(stamp)
    if gap == 1:
        return i18n.t("Yesterday")
    if gap < 7:
        return dt.strftime("%a")
    return "%d %s" % (dt.day, dt.strftime("%b"))


def day_label(dt: datetime) -> str:
    today = datetime.now().astimezone().date()
    gap = (today - dt.date()).days
    if gap <= 0:
        return i18n.t("Today")
    if gap == 1:
        return i18n.t("Yesterday")
    if gap < 7:
        return dt.strftime("%A")
    return "%s, %d %s" % (dt.strftime("%a"), dt.day, dt.strftime("%b %Y" if gap > 300 else "%b"))


def window_left(messages: list) -> timedelta | None:
    """How long WhatsApp will still let a plain reply through.

    Meta only delivers a free-form message inside 24 hours of the customer's
    last message to you; after that only an approved template goes. None means
    they have never written, so there is no window at all.
    """
    last_in = None
    for m in messages:
        if m.get("direction") == "in":
            dt = parse_ts(m.get("created_at", ""))
            if dt is not None and (last_in is None or dt > last_in):
                last_in = dt
    if last_in is None:
        return None
    return timedelta(hours=24) - (datetime.now().astimezone() - last_in)


def human_delta(delta: timedelta) -> str:
    secs = max(0, int(delta.total_seconds()))
    hours, rem = divmod(secs, 3600)
    minutes = rem // 60
    if hours:
        return "%dh %dm" % (hours, minutes)
    return "%dm" % max(1, minutes)


# ── row painters ─────────────────────────────────────────────────────────────

def _font(px: float, weight: int = 400, heading: bool = False) -> QFont:
    f = QFont(theme.FONT_HEADING if heading else theme.FONT_BODY)
    f.setPixelSize(int(px))
    f.setWeight(QFont.Weight(weight))
    return f


def _draw_avatar(p: QPainter, cx: float, cy: float, size: int, name: str,
                 fill: str) -> None:
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(fill))
    p.drawEllipse(QRectF(cx - size / 2, cy - size / 2, size, size))
    p.setPen(QColor("#ffffff"))
    p.setFont(_font(size * 0.42, 700, heading=True))
    initial = ((name or "?").strip()[:1] or "?").upper()
    p.drawText(QRectF(cx - size / 2, cy - size / 2, size, size), Qt.AlignCenter,
               initial)


def _plate(p: QPainter, option, rect: QRectF) -> None:
    """The selected / hovered row background — a soft rounded tint, not the
    platform's blue bar."""
    if option.state & QStyle.State_Selected:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 20))
        p.drawRoundedRect(rect, theme.R_CONTROL, theme.R_CONTROL)
    elif option.state & QStyle.State_MouseOver:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 9))
        p.drawRoundedRect(rect, theme.R_CONTROL, theme.R_CONTROL)


class ConversationDelegate(QStyledItemDelegate):
    """One inbox row: avatar · name / time · last message / unread dot.

    Reads the row dict from Qt.UserRole and asks readstate whether it is
    unread, so the list needs no per-row bookkeeping of its own."""

    def sizeHint(self, option, index):
        return QSize(0, CONVO_ROW_H)

    def paint(self, p: QPainter, option, index):
        row = index.data(Qt.UserRole) or {}
        unread = readstate.is_unread(row)
        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(option.rect).adjusted(6, 2, -6, -2)
        _plate(p, option, r)

        who = row.get("contact_name") or row.get("contact_phone") or i18n.t("Unknown")
        cy = r.center().y()
        _draw_avatar(p, r.left() + 10 + 22, cy, 44, who,
                     avatar_colour(who, bool(row.get("opt_out"))))

        left = r.left() + 10 + 44 + 12
        right = r.right() - 10

        # time (top right) — green and heavier when there is something new
        stamp = short_time(row.get("last_active_at", ""))
        tfont = _font(11.5, 600 if unread else 400)
        p.setFont(tfont)
        p.setPen(QColor(theme.OK_INK if unread else theme.NEUTRAL[600]))
        tw = QFontMetrics(tfont).horizontalAdvance(stamp)
        top = r.top() + 13
        p.drawText(QRectF(right - tw, top, tw, 18), Qt.AlignRight | Qt.AlignVCenter, stamp)

        # name (top left), leaving room for the time
        nfont = _font(14.5, 700 if unread else 600)
        p.setFont(nfont)
        p.setPen(QColor(theme.TEXT))
        name_w = right - left - tw - 10
        name = QFontMetrics(nfont).elidedText(who, Qt.ElideRight, int(max(20, name_w)))
        p.drawText(QRectF(left, top, name_w, 18), Qt.AlignLeft | Qt.AlignVCenter, name)

        # last message (bottom), leaving room for the unread dot
        text = (row.get("last_text") or "").strip().replace("\n", " ")
        if not text:
            text = i18n.t("No messages yet")
        elif row.get("last_direction") == "out":
            text = i18n.t("You: ") + text
        pfont = _font(13, 600 if unread else 400)
        p.setFont(pfont)
        p.setPen(QColor(theme.TEXT if unread else theme.NEUTRAL[600]))
        reserve = 22 if unread else 0
        prev_w = right - left - reserve
        prev = QFontMetrics(pfont).elidedText(text, Qt.ElideRight, int(max(20, prev_w)))
        line2 = r.top() + 37
        p.drawText(QRectF(left, line2, prev_w, 18), Qt.AlignLeft | Qt.AlignVCenter, prev)

        if unread:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.OK))
            p.drawEllipse(QRectF(right - 11, line2 + 4, 11, 11))
        p.restore()


class ContactDelegate(QStyledItemDelegate):
    """One contact row: avatar · name / phone · company · tag pills."""

    def sizeHint(self, option, index):
        return QSize(0, CONTACT_ROW_H)

    def paint(self, p: QPainter, option, index):
        row = index.data(Qt.UserRole) or {}
        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(option.rect).adjusted(6, 2, -6, -2)
        _plate(p, option, r)

        who = row.get("name") or row.get("phone") or i18n.t("Unknown")
        cy = r.center().y()
        opted_out = bool(row.get("opt_out"))
        _draw_avatar(p, r.left() + 10 + 19, cy, 38, who, avatar_colour(who, opted_out))

        left = r.left() + 10 + 38 + 12
        right = r.right() - 10

        # pills, right-aligned, painted first so the text knows how much room is left
        pills = []
        if opted_out:
            pills.append((i18n.t("Opted out"), QColor(theme.WARN_INK), QColor(202, 138, 4, 36)))
        tags = [t for t in (row.get("tags") or []) if isinstance(t, str) and t]
        for t in tags[:2]:
            pills.append((t, QColor(theme.NEUTRAL[800]), QColor(0, 0, 0, 16)))
        if len(tags) > 2:
            pills.append(("+%d" % (len(tags) - 2), QColor(theme.NEUTRAL[700]), QColor(0, 0, 0, 10)))
        pfont = _font(11.5, 600)
        fm = QFontMetrics(pfont)
        x = right
        for text, ink, bg in reversed(pills):
            w = fm.horizontalAdvance(text) + 16
            x -= w
            box = QRectF(x, cy - 10, w, 20)
            p.setPen(Qt.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(box, 10, 10)
            p.setPen(ink)
            p.setFont(pfont)
            p.drawText(box, Qt.AlignCenter, text)
            x -= 6
        avail = max(40, x - left - 4)

        nfont = _font(14.5, 600)
        p.setFont(nfont)
        p.setPen(QColor(theme.TEXT))
        p.drawText(QRectF(left, r.top() + 9, avail, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(nfont).elidedText(who, Qt.ElideRight, int(avail)))

        sub = " · ".join(s for s in (row.get("phone") or "", row.get("company") or "") if s)
        sfont = _font(12.5, 400)
        p.setFont(sfont)
        p.setPen(QColor(theme.NEUTRAL[600]))
        p.drawText(QRectF(left, r.top() + 30, avail, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(sfont).elidedText(sub, Qt.ElideRight, int(avail)))
        p.restore()
