"""Lumi Help Center & Floating Assistant.

Recreates the Lumi Help Center card popup and floating launcher, featuring:
  • Sprite-animated Lumi axolotl (8-frame spritesheet with waving and idle loops)
  • Welcome View with mint-gradient banner, wavy cloud, pill search bar, and 3 action cards
  • Conversational Chat View with rich markdown rendering, action chips, and back navigation
  • Persistent floating dark pill launcher with circular Lumi avatar and online status dot
"""
from __future__ import annotations

import math
import os
import random
from typing import Optional

from PySide6.QtCore import (
    QEasingCurve, QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer,
    QVariantAnimation, Signal,
)
from PySide6.QtGui import (
    QBrush, QColor, QCursor, QFont, QIcon, QLinearGradient, QPainter,
    QPainterPath, QPen, QPixmap, QTransform,
)
from PySide6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QSizePolicy, QStackedLayout, QVBoxLayout, QWidget,
)

import i18n
import paths
import theme
from widgets import controls as C
from widgets import icons
from widgets.markdown import render_markdown


# ── SPRITE ANIMATION FOR LUMI ────────────────────────────────────────────────
class LumiSpriteWidget(QWidget):
    """Animated Lumi axolotl using the 8-frame spritesheet.

    Row 0 (frames 0-3): Idle swaying, blinking, happy sparkling.
    Row 1 (frames 4-7): Waving hand animation.
    """

    def __init__(self, mode: str = "waving", size: QSize = QSize(160, 160), parent=None):
        super().__init__(parent)
        self.setFixedSize(size)
        self.setAttribute(Qt.WA_Hover, True)
        self.setCursor(Qt.PointingHandCursor)

        self._frames: list[QPixmap] = []
        self._mode = mode
        self._current_seq_idx = 0
        self._load_spritesheet()

        # Animation sequence index lists
        self._waving_seq = [4, 5, 6, 7, 6, 5, 4, 5, 6, 7]
        self._idle_seq = [0, 1, 2, 3, 2, 1]

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._next_frame)
        self._timer.start(160)

    def _load_spritesheet(self):
        sheet_path = paths.resource("assets", "lumi", "lumi_spritesheet.png")
        if not os.path.exists(sheet_path):
            return

        sheet = QPixmap(sheet_path)
        if sheet.isNull():
            return

        fw = sheet.width() // 4
        fh = sheet.height() // 2
        for r in range(2):
            for c in range(4):
                frame = sheet.copy(c * fw, r * fh, fw, fh)
                self._frames.append(frame)

    def _next_frame(self):
        seq = self._waving_seq if self._mode == "waving" else self._idle_seq
        if not seq:
            return
        self._current_seq_idx = (self._current_seq_idx + 1) % len(seq)
        self.update()

    def set_mode(self, mode: str):
        if self._mode != mode:
            self._mode = mode
            self._current_seq_idx = 0
            self._timer.setInterval(160 if mode == "waving" else 220)
            self.update()

    def enterEvent(self, event):
        self.set_mode("waving")
        super().enterEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        if not self._frames:
            # Fallback to static character if spritesheet is missing
            fallback = QPixmap(paths.resource("assets", "lumi", "lumi_character.png"))
            if not fallback.isNull():
                scaled = fallback.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                x = (self.width() - scaled.width()) // 2
                y = (self.height() - scaled.height()) // 2
                painter.drawPixmap(x, y, scaled)
            return

        seq = self._waving_seq if self._mode == "waving" else self._idle_seq
        frame_idx = seq[self._current_seq_idx % len(seq)]
        frame = self._frames[frame_idx]

        scaled = frame.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        x = (self.width() - scaled.width()) // 2
        y = self.height() - scaled.height()
        painter.drawPixmap(x, y, scaled)


# ── ACTION CARD WIDGET ───────────────────────────────────────────────────────
class _QuickCard(QFrame):
    """One of the 3 cards below the input bar (Ask assistant / Book meeting / Contact)."""

    clicked = Signal()

    def __init__(self, title: str, subtitle: str, icon_name: str, parent=None):
        super().__init__(parent)
        self.setObjectName("lumiQuickCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(124)
        self.setStyleSheet(
            "QFrame#lumiQuickCard {"
            "  background: #ffffff;"
            "  border: 1px solid #e2e8f0;"
            "  border-radius: 18px;"
            "}"
            "QFrame#lumiQuickCard:hover {"
            "  background: #f0fdfa;"
            "  border-color: #2dd4bf;"
            "}"
        )

        box = QVBoxLayout(self)
        box.setContentsMargins(12, 12, 12, 12)
        box.setSpacing(5)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(icons.pixmap(icon_name, 28, "#0d9488", stroke=2.0))
        icon_lbl.setStyleSheet("background: transparent; border: none; padding: 0;")
        box.addWidget(icon_lbl, alignment=Qt.AlignLeft)

        t_lbl = QLabel(title)
        t_lbl.setStyleSheet(
            "font-size: 13px; font-weight: 700; color: #0f172a; background: transparent; border: none; padding: 0;"
        )
        t_lbl.setWordWrap(True)
        box.addWidget(t_lbl)

        s_lbl = QLabel(subtitle)
        s_lbl.setStyleSheet(
            "font-size: 11.5px; color: #64748b; font-weight: 500; line-height: 125%; background: transparent; border: none; padding: 0;"
        )
        s_lbl.setWordWrap(True)
        box.addWidget(s_lbl)
        box.addStretch(1)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


# ── WELCOME VIEW HEADER WITH WAVES, MASCOT, AND CLOUD SHELF ───────────────────
class LumiWelcomeHeader(QWidget):
    """Header with flowing waves, sparkles, animated Lumi mascot, and fluffy cloud shelf."""

    minimize_requested = Signal()
    close_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(225)
        self.setAttribute(Qt.WA_Hover, True)
        self.setCursor(Qt.ArrowCursor)

        self._frames: list[QPixmap] = []
        self._mode = "waving"
        self._current_seq_idx = 0
        self._load_spritesheet()

        self._waving_seq = [4, 5, 6, 7, 6, 5, 4, 5, 6, 7]
        self._idle_seq = [0, 1, 2, 3, 2, 1]

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._next_frame)
        self._timer.start(160)

        # Child layouts for window controls and header text
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(24, 16, 24, 0)
        vbox.setSpacing(4)

        # Top Bar
        top_bar = QHBoxLayout()
        top_bar.addStretch(1)

        min_btn = QPushButton("—")
        min_btn.setFixedSize(26, 26)
        min_btn.setCursor(Qt.PointingHandCursor)
        min_btn.setToolTip(i18n.t("Minimize"))
        min_btn.setStyleSheet(
            "QPushButton {"
            "  border: none; background: transparent; font-size: 16px; font-weight: 700; color: #1e293b;"
            "}"
            "QPushButton:hover { background: rgba(0,0,0,0.06); border-radius: 6px; }"
        )
        min_btn.clicked.connect(self.minimize_requested.emit)
        top_bar.addWidget(min_btn)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(26, 26)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setToolTip(i18n.t("Close"))
        close_btn.setStyleSheet(
            "QPushButton {"
            "  border: none; background: transparent; font-size: 15px; font-weight: 700; color: #1e293b;"
            "}"
            "QPushButton:hover { background: rgba(0,0,0,0.06); border-radius: 6px; }"
        )
        close_btn.clicked.connect(self.close_requested.emit)
        top_bar.addWidget(close_btn)
        vbox.addLayout(top_bar)

        # Header Text
        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 6, 0, 0)

        text_col = QVBoxLayout()
        text_col.setSpacing(6)
        text_col.addStretch(1)

        title = QLabel(i18n.t("Hi, I’m Lumi"))
        title.setStyleSheet(
            f"font-family: '{theme.FONT_HEADING}'; font-size: 30px; font-weight: 800; color: #0f172a; background: transparent; border: none; padding: 0;"
        )
        text_col.addWidget(title)

        sub = QLabel(i18n.t("I can answer questions, find docs, and\nconnect you to support."))
        sub.setStyleSheet(
            "font-size: 13.5px; color: #334155; font-weight: 500; line-height: 135%; background: transparent; border: none; padding: 0;"
        )
        sub.setWordWrap(True)
        text_col.addWidget(sub)
        text_col.addStretch(1)

        content_row.addLayout(text_col, stretch=5)
        content_row.addSpacing(210)  # Space reserved for animated mascot on the right
        vbox.addLayout(content_row)

    def _load_spritesheet(self):
        sheet_path = paths.resource("assets", "lumi", "lumi_spritesheet.png")
        if not os.path.exists(sheet_path):
            return
        sheet = QPixmap(sheet_path)
        if sheet.isNull():
            return
        fw = sheet.width() // 4
        fh = sheet.height() // 2
        for r in range(2):
            for c in range(4):
                frame = sheet.copy(c * fw, r * fh, fw, fh)
                self._frames.append(frame)

    def _next_frame(self):
        seq = self._waving_seq if self._mode == "waving" else self._idle_seq
        if not seq:
            return
        self._current_seq_idx = (self._current_seq_idx + 1) % len(seq)
        self.update()

    def set_mode(self, mode: str):
        if self._mode != mode:
            self._mode = mode
            self._current_seq_idx = 0
            self._timer.setInterval(160 if mode == "waving" else 220)
            self.update()

    def enterEvent(self, event):
        self.set_mode("waving")
        super().enterEvent(event)

    def _draw_star(self, painter: QPainter, cx: float, cy: float, r_outer: float, r_inner: float, color: QColor):
        path = QPainterPath()
        for i in range(8):
            angle = i * math.pi / 4.0
            r = r_outer if i % 2 == 0 else r_inner
            px = cx + r * math.cos(angle)
            py = cy + r * math.sin(angle)
            if i == 0:
                path.moveTo(px, py)
            else:
                path.lineTo(px, py)
        path.closeSubpath()
        painter.fillPath(path, color)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        w = float(self.width())
        h = float(self.height())

        # 1. Base gradient
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(220, 252, 231, 230))
        grad.setColorAt(0.35, QColor(204, 251, 241, 180))
        grad.setColorAt(0.8, QColor(230, 255, 250, 240))
        grad.setColorAt(1.0, QColor(240, 253, 250, 255))
        painter.fillRect(self.rect(), grad)

        # 2. Organic flowing waves on top-left (matching reference)
        wave1 = QPainterPath()
        wave1.moveTo(0, 0)
        wave1.lineTo(w * 0.42, 0)
        wave1.cubicTo(w * 0.46, h * 0.16, w * 0.34, h * 0.42, w * 0.18, h * 0.38)
        wave1.cubicTo(w * 0.06, h * 0.34, 0, h * 0.42, 0, h * 0.46)
        wave1.closeSubpath()
        painter.fillPath(wave1, QColor(167, 243, 208, 85))

        wave2 = QPainterPath()
        wave2.moveTo(0, h * 0.22)
        wave2.cubicTo(w * 0.16, h * 0.14, w * 0.32, h * 0.30, w * 0.38, h * 0.48)
        wave2.cubicTo(w * 0.28, h * 0.62, w * 0.12, h * 0.66, 0, h * 0.58)
        wave2.closeSubpath()
        painter.fillPath(wave2, QColor(153, 246, 228, 70))

        # 3. Draw Sparkles
        sparkle_color = QColor(45, 212, 191, 230)
        # Left sparkles
        self._draw_star(painter, w * 0.45, h * 0.58, 9.5, 3.2, sparkle_color)
        self._draw_star(painter, w * 0.48, h * 0.70, 6.5, 2.2, sparkle_color)
        dash_pen = QPen(sparkle_color, 2.5, Qt.SolidLine, Qt.RoundCap)
        painter.setPen(dash_pen)
        painter.drawLine(QPointF(w * 0.45, h * 0.45), QPointF(w * 0.465, h * 0.425))
        painter.drawLine(QPointF(w * 0.43, h * 0.48), QPointF(w * 0.44, h * 0.50))
        # Right sparkles
        self._draw_star(painter, w * 0.93, h * 0.65, 7.5, 2.5, sparkle_color)
        painter.drawLine(QPointF(w * 0.89, h * 0.59), QPointF(w * 0.905, h * 0.57))
        painter.drawLine(QPointF(w * 0.92, h * 0.54), QPointF(w * 0.93, h * 0.56))

        # 4. Animated Lumi Mascot - perfectly scaled to fill right side
        mw = int(w * 0.54)
        mh = mw
        mx = int(w * 0.45)
        my = int(h * 0.05)

        if self._frames:
            seq = self._waving_seq if self._mode == "waving" else self._idle_seq
            frame_idx = seq[self._current_seq_idx % len(seq)]
            frame = self._frames[frame_idx]
            scaled = frame.scaled(mw, mh, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            if self._mode == "diving":
                painter.save()
                painter.translate(mx + scaled.width() / 2, my + scaled.height() / 2)
                painter.rotate(-16.0)
                painter.drawPixmap(-scaled.width() // 2, -scaled.height() // 2 + 12, scaled)
                painter.restore()
            else:
                painter.drawPixmap(mx, my, scaled)
        else:
            fallback = QPixmap(paths.resource("assets", "lumi", "lumi_character.png"))
            if not fallback.isNull():
                scaled = fallback.scaled(mw, mh, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                if self._mode == "diving":
                    painter.save()
                    painter.translate(mx + scaled.width() / 2, my + scaled.height() / 2)
                    painter.rotate(-16.0)
                    painter.drawPixmap(-scaled.width() // 2, -scaled.height() // 2 + 12, scaled)
                    painter.restore()
                else:
                    painter.drawPixmap(mx, my, scaled)

        # 5. Fluffy White Cloud Shelf under Lumi
        cloud = QPainterPath()
        cloud.moveTo(w * 0.32, h)
        cloud.cubicTo(w * 0.38, h * 0.90, w * 0.46, h * 0.74, w * 0.59, h * 0.74)
        cloud.cubicTo(w * 0.70, h * 0.69, w * 0.82, h * 0.73, w * 0.90, h * 0.82)
        cloud.cubicTo(w * 0.95, h * 0.87, w, h * 0.89, w, h)
        cloud.lineTo(w, h + 30)
        cloud.lineTo(w * 0.32, h + 30)
        cloud.closeSubpath()
        painter.fillPath(cloud, QColor(255, 255, 255, 255))


# ── LUMI CARD (POPUP WINDOW) ─────────────────────────────────────────────────
class LumiCard(QFrame):
    """The modern Lumi Help Center card popup matching the design references."""

    minimize_requested = Signal()
    close_requested = Signal()
    expand_toggled = Signal(bool)
    command_requested = Signal(str)
    typing_occurred = Signal()

    def __init__(self, support_panel: QWidget, parent=None):
        super().__init__(parent)
        self._support_panel = support_panel
        self.setObjectName("lumiMainCard")
        self.setFixedSize(465, 520)
        self._is_expanded = False
        self._exp_btns: list[QPushButton] = []

        self.setStyleSheet(
            "QFrame#lumiMainCard {"
            "  background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #dcfce7, stop:0.35 #e6fffa, stop:0.7 #f0fdfa, stop:1.0 #e6fffa);"
            "  border: 3px solid #5eead4;"
            "  border-radius: 36px;"
            "}"
        )

        # Soft mint drop shadow
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(36)
        shadow.setColor(QColor(45, 212, 191, 75))
        shadow.setOffset(0, 10)
        self.setGraphicsEffect(shadow)

        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)

        # View 0: Welcome / Landing View
        self._welcome_view = self._build_welcome_view()
        self._stack.addWidget(self._welcome_view)

        # View 1: Conversation View
        self._chat_view = self._build_chat_view()
        self._stack.addWidget(self._chat_view)

    def toggle_expand(self):
        self._is_expanded = not getattr(self, "_is_expanded", False)
        if self._is_expanded:
            parent = self.parentWidget()
            pw = parent.width() if parent else 1200
            ph = parent.height() if parent else 800
            target_w = max(680, min(860, int(pw * 0.75)))
            target_h = max(620, min(840, int(ph * 0.88)))
            self.setFixedSize(target_w, target_h)
            for b in self._exp_btns:
                icons.button_icon(b, "minimize", 14, "#475569")
                b.setToolTip(i18n.t("Restore size"))
        else:
            self.setFixedSize(465, 520)
            for b in self._exp_btns:
                icons.button_icon(b, "maximize", 14, "#475569")
                b.setToolTip(i18n.t("Expand"))

        self.expand_toggled.emit(self._is_expanded)
        if hasattr(self._support_panel, "_sync_thread_height"):
            self._support_panel._sync_thread_height()

    def _build_welcome_view(self) -> QWidget:
        root = QWidget()
        box = QVBoxLayout(root)
        box.setContentsMargins(0, 0, 0, 16)
        box.setSpacing(12)

        # Header with flowing waves, animated mascot, and fluffy cloud shelf
        self._welcome_header = LumiWelcomeHeader(root)
        self._mascot = self._welcome_header
        self._welcome_header.minimize_requested.connect(self.minimize_requested.emit)
        self._welcome_header.close_requested.connect(self.close_requested.emit)
        box.addWidget(self._welcome_header)

        # Middle: Pill search bar
        search_wrap = QWidget()
        search_layout = QHBoxLayout(search_wrap)
        search_layout.setContentsMargins(18, 0, 18, 0)

        pill = QFrame()
        pill.setObjectName("lumiSearchPill")
        pill.setFixedHeight(52)
        pill.setStyleSheet(
            "QFrame#lumiSearchPill {"
            "  background: #ffffff;"
            "  border: 1px solid #cbd5e1;"
            "  border-radius: 26px;"
            "}"
            "QFrame#lumiSearchPill:focus-within {"
            "  border-color: #2dd4bf;"
            "}"
        )
        p_row = QHBoxLayout(pill)
        p_row.setContentsMargins(18, 2, 6, 2)
        p_row.setSpacing(10)

        self._input = QLineEdit()
        self._input.setPlaceholderText(i18n.t("Ask me anything about Prism..."))
        self._input.setStyleSheet(
            "QLineEdit { border: none; background: transparent; font-size: 13.5px; color: #0f172a; }"
        )
        self._input.returnPressed.connect(self._on_search_submitted)
        self._input.textChanged.connect(lambda _: self.typing_occurred.emit())
        p_row.addWidget(self._input, stretch=1)

        send_btn = QPushButton()
        send_btn.setFixedSize(38, 38)
        send_btn.setCursor(Qt.PointingHandCursor)
        send_btn.setToolTip(i18n.t("Send"))
        send_btn.setIcon(icons.icon("send-plane", 18, "#0d9488"))
        send_btn.setIconSize(QSize(18, 18))
        send_btn.setStyleSheet(
            "QPushButton {"
            "  background: #99f6e4;"
            "  border: none;"
            "  border-radius: 19px;"
            "}"
            "QPushButton:hover {"
            "  background: #5eead4;"
            "}"
        )
        send_btn.clicked.connect(self._on_search_submitted)
        p_row.addWidget(send_btn)

        search_layout.addWidget(pill)
        box.addWidget(search_wrap)

        # Bottom: 3 Quick Action Cards
        cards_wrap = QWidget()
        cards_layout = QHBoxLayout(cards_wrap)
        cards_layout.setContentsMargins(16, 0, 16, 0)
        cards_layout.setSpacing(8)

        card1 = _QuickCard(i18n.t("Ask assistant"), i18n.t("Get help and find docs"), "chat-dots")
        card1.clicked.connect(self._open_assistant_chat)
        cards_layout.addWidget(card1)

        card2 = _QuickCard(i18n.t("Book a meeting"), i18n.t("Talk to the team"), "calendar-dots")
        card2.clicked.connect(self._open_book_meeting)
        cards_layout.addWidget(card2)

        card3 = _QuickCard(i18n.t("Contact support"), i18n.t("Get help from our team"), "headphones-mic")
        card3.clicked.connect(self._open_contact_sheet)
        cards_layout.addWidget(card3)

        box.addWidget(cards_wrap)
        box.addStretch(1)

        return root

    def _build_chat_view(self) -> QWidget:
        root = QWidget()
        box = QVBoxLayout(root)
        box.setContentsMargins(14, 12, 14, 12)
        box.setSpacing(10)

        # Chat header: Back button | Avatar | Title | Min/Close
        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        back_btn = QPushButton()
        back_btn.setFixedSize(30, 30)
        back_btn.setCursor(Qt.PointingHandCursor)
        back_btn.setToolTip(i18n.t("Back to Lumi Home"))
        icons.button_icon(back_btn, "chevron-left", 14, "#334155")
        back_btn.setStyleSheet(
            "QPushButton {"
            "  border: 1px solid #cbd5e1;"
            "  background: #f8fafc;"
            "  border-radius: 15px;"
            "  min-width: 30px; max-width: 30px;"
            "  min-height: 30px; max-height: 30px;"
            "  padding: 0;"
            "}"
            "QPushButton:hover {"
            "  background: #f1f5f9;"
            "  border-color: #94a3b8;"
            "}"
        )
        back_btn.clicked.connect(self._show_welcome)
        top_row.addWidget(back_btn, alignment=Qt.AlignVCenter)

        avatar_lbl = QLabel()
        av_pix = QPixmap(paths.resource("assets", "lumi", "lumi_avatar.png"))
        if not av_pix.isNull():
            avatar_lbl.setPixmap(av_pix.scaled(30, 30, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        avatar_lbl.setFixedSize(30, 30)
        top_row.addWidget(avatar_lbl, alignment=Qt.AlignVCenter)

        info_col = QVBoxLayout()
        info_col.setSpacing(1)
        c_title = QLabel("Lumi")
        c_title.setStyleSheet("font-size: 14px; font-weight: 700; color: #0f172a;")
        info_col.addWidget(c_title)
        c_status = QLabel("● " + i18n.t("Online · Prism Assistant"))
        c_status.setStyleSheet("font-size: 11px; font-weight: 600; color: #10b981;")
        info_col.addWidget(c_status)
        top_row.addLayout(info_col, stretch=1)

        min_btn = QPushButton()
        min_btn.setFixedSize(28, 28)
        min_btn.setCursor(Qt.PointingHandCursor)
        min_btn.setToolTip(i18n.t("Minimize"))
        icons.button_icon(min_btn, "minus", 14, "#475569")
        min_btn.setStyleSheet(
            "QPushButton { border: none; background: transparent; padding: 0; }"
            "QPushButton:hover { background: rgba(0,0,0,0.07); border-radius: 6px; }"
        )
        min_btn.clicked.connect(self.minimize_requested.emit)
        top_row.addWidget(min_btn, alignment=Qt.AlignVCenter)

        exp_btn = QPushButton()
        exp_btn.setFixedSize(28, 28)
        exp_btn.setCursor(Qt.PointingHandCursor)
        exp_btn.setToolTip(i18n.t("Expand"))
        icons.button_icon(exp_btn, "maximize", 14, "#475569")
        exp_btn.setStyleSheet(
            "QPushButton { border: none; background: transparent; padding: 0; }"
            "QPushButton:hover { background: rgba(0,0,0,0.07); border-radius: 6px; }"
        )
        exp_btn.clicked.connect(self.toggle_expand)
        self._exp_btns.append(exp_btn)
        top_row.addWidget(exp_btn, alignment=Qt.AlignVCenter)

        close_btn = QPushButton()
        close_btn.setFixedSize(28, 28)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setToolTip(i18n.t("Close"))
        icons.button_icon(close_btn, "x", 14, "#475569")
        close_btn.setStyleSheet(
            "QPushButton { border: none; background: transparent; padding: 0; }"
            "QPushButton:hover { background: rgba(0,0,0,0.07); border-radius: 6px; }"
        )
        close_btn.clicked.connect(self.close_requested.emit)
        top_row.addWidget(close_btn, alignment=Qt.AlignVCenter)

        box.addLayout(top_row)

        # Embedded SupportPanel inside the card
        if hasattr(self._support_panel, "set_compact"):
            self._support_panel.set_compact(True)
        box.addWidget(self._support_panel, stretch=1)

        return root

    def _show_welcome(self):
        self._stack.setCurrentIndex(0)
        self._mascot.set_mode("waving")

    def _show_chat(self):
        self._stack.setCurrentIndex(1)

    def _on_search_submitted(self):
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self._show_chat()
        # Feed question directly to SupportPanel
        if hasattr(self._support_panel, "_entry"):
            self._support_panel._entry.setText(text)
            self._support_panel._on_typed()

    def _open_assistant_chat(self):
        self._show_chat()
        if hasattr(self._support_panel, "_start_ai"):
            self._support_panel._start_ai()

    def _open_book_meeting(self):
        if hasattr(self._support_panel, "_book_meeting"):
            self._support_panel._book_meeting()

    def _open_contact_sheet(self):
        if hasattr(self._support_panel, "_open_contact"):
            self._support_panel._open_contact()


# ── FLOATING LAUNCHER PILL ───────────────────────────────────────────────────
# ── PARTICLE FX: RIPPLES, WATER DROPS & CONFETTI ───────────────────────────
class _ConfettiParticle:
    """Festive confetti ribbon/square particle for celebrations (3.2)."""
    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y
        self.vx = random.uniform(-3.5, 3.5)
        self.vy = random.uniform(-6.5, -3.0)  # initial upward burst
        self.rot = random.uniform(0, 360)
        self.vrot = random.uniform(-14.0, 14.0)
        self.w = random.uniform(4.0, 7.0)
        self.h = random.uniform(5.0, 9.0)
        self.alpha = 255.0
        colors = [
            QColor(45, 212, 191),   # mint
            QColor(245, 158, 11),   # gold
            QColor(236, 72, 153),   # rose/pink
            QColor(139, 92, 246),   # violet
            QColor(56, 189, 248),   # sky blue
            QColor(34, 197, 94),    # lime
        ]
        self.color = random.choice(colors)

    def update(self) -> bool:
        self.x += self.vx
        self.y += self.vy
        self.vy += 0.28
        self.vx *= 0.98
        self.rot += self.vrot
        self.alpha = max(0.0, self.alpha - 5.5)
        return self.alpha > 0 and self.y < 120


class _Ripple:
    """Expanding aquatic ripple ring."""
    def __init__(self, x: float, y: float, max_r: float = 38.0, color: Optional[QColor] = None):
        self.x = x
        self.y = y
        self.radius = 6.0
        self.max_r = max_r
        self.alpha = 220.0
        self.color = color or QColor(45, 212, 191)

    def update(self) -> bool:
        self.radius += 2.2
        self.alpha = max(0.0, self.alpha - 14.0)
        return self.radius < self.max_r and self.alpha > 0


class _WaterDrop:
    """Tiny splash water droplet particle with physics arc."""
    def __init__(self, x: float, y: float, vx: float, vy: float):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.alpha = 240.0
        self.r = random.uniform(2.0, 3.5)

    def update(self) -> bool:
        self.x += self.vx
        self.y += self.vy
        self.vy += 0.45  # gravity
        self.alpha = max(0.0, self.alpha - 12.0)
        return self.alpha > 0 and self.y < 120


# ── FLOATING LAUNCHER PILL WITH ANIMATED MASCOT LOCOMOTION ───────────────────
class LumiLauncherPill(QWidget):
    """The floating dark pill launcher with Lumi's avatar badge and walking mascot companion."""

    toggle_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(124)
        self.setMinimumWidth(340)
        self.setMaximumWidth(400)
        self.setAttribute(Qt.WA_Hover, True)

        self._frames: list[QPixmap] = []
        self._load_spritesheet()

        # Locomotion & State
        # States: "idle", "walking", "sitting", "waving", "shaking", "leaping", "working", "celebrating", "typing"
        self._state = "walking"
        self._mascot_x = 70.0
        self._target_x = 220.0
        self._facing_left = False
        self._walk_step = 0
        self._state_timer = 0
        self._shake_phase = 0
        self._leap_progress = 0.0
        self._card_is_open = False

        # Specialized modes (3.2 Celebration, 3.3 Worker Running, 3.5 Typing Sync)
        self._celebrate_timer = 0
        self._worker_run_ticks = 0
        self._typing_timer = 0
        self._typing_bob = 0.0

        # Visual FX
        self._ripples: list[_Ripple] = []
        self._droplets: list[_WaterDrop] = []
        self._confetti: list[_ConfettiParticle] = []

        self._idle_seq = [0, 1, 2, 3, 2, 1]
        self._waving_seq = [4, 5, 6, 7, 6, 5]

        # Top 74px: transparent stage where Lumi perches & walks comfortably
        # Bottom 50px: dark pill frame
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 74, 0, 0)
        layout.setSpacing(0)

        pill = QFrame(self)
        pill.setObjectName("lumiPillFrame")
        pill.setFixedHeight(50)
        pill.setStyleSheet(
            "QFrame#lumiPillFrame {"
            "  background: #18181b;"
            "  border: 1px solid rgba(255, 255, 255, 0.16);"
            "  border-radius: 25px;"
            "}"
            "QFrame#lumiPillFrame:hover {"
            "  background: #27272a;"
            "  border-color: #2dd4bf;"
            "}"
        )

        p_box = QHBoxLayout(pill)
        p_box.setContentsMargins(16, 5, 6, 5)
        p_box.setSpacing(10)

        text_lbl = QLabel(i18n.t("Need help? Lumi can answer questions, find docs, and connect you to support."))
        text_lbl.setStyleSheet(
            "font-size: 11.5px; font-weight: 500; color: #f1f5f9; line-height: 130%; background: transparent;"
        )
        text_lbl.setWordWrap(True)
        p_box.addWidget(text_lbl, stretch=1)

        # Avatar badge at right
        avatar_wrap = QWidget()
        avatar_wrap.setFixedSize(40, 40)
        a_layout = QVBoxLayout(avatar_wrap)
        a_layout.setContentsMargins(0, 0, 0, 0)

        self._avatar_btn = QLabel(avatar_wrap)
        av_pix = QPixmap(paths.resource("assets", "lumi", "lumi_avatar.png"))
        if not av_pix.isNull():
            self._avatar_btn.setPixmap(av_pix.scaled(38, 38, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self._avatar_btn.setFixedSize(38, 38)
        self._avatar_btn.setStyleSheet(
            "border: 2px solid #2dd4bf; border-radius: 19px; background: #0f172a;"
        )

        dot = QLabel(avatar_wrap)
        dot.setFixedSize(10, 10)
        dot.move(28, 2)
        dot.setStyleSheet(
            "background: #22c55e; border: 1.5px solid #18181b; border-radius: 5px;"
        )
        p_box.addWidget(avatar_wrap)

        layout.addWidget(pill)

        # Make entire pill and contents reliably clickable
        pill.mouseReleaseEvent = lambda e: self._on_clicked(e)
        text_lbl.mouseReleaseEvent = lambda e: self._on_clicked(e)
        avatar_wrap.mouseReleaseEvent = lambda e: self._on_clicked(e)

        # Tick timer for locomotion cycle and particle physics
        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._on_tick)
        self._tick_timer.start(50)

    def _load_spritesheet(self):
        sheet_path = paths.resource("assets", "lumi", "lumi_spritesheet.png")
        if not os.path.exists(sheet_path):
            return
        sheet = QPixmap(sheet_path)
        if sheet.isNull():
            return
        fw = sheet.width() // 4
        fh = sheet.height() // 2
        for r in range(2):
            for c in range(4):
                self._frames.append(sheet.copy(c * fw, r * fh, fw, fh))

    def _on_clicked(self, event):
        if event.button() == Qt.LeftButton:
            self.toggle_requested.emit()

    def trigger_celebration(self, duration_ms: int = 3500):
        """3.2 Celebration & Confetti burst (explicit achievements, quotes, completed tasks)."""
        self._state = "celebrating"
        self._celebrate_timer = int(duration_ms / 50)
        mx = self._mascot_x + 27
        my = 74.0 - 20
        for _ in range(36):
            self._confetti.append(_ConfettiParticle(mx, my))
        self.update()

    def on_user_typing(self):
        """3.5 Typing Sync — reacts to user typing keystrokes."""
        if self._card_is_open or self._state in ("leaping", "shaking", "celebrating"):
            return
        self._typing_timer = 24  # ~1.2 seconds of focused attention
        self._typing_bob = 3.8
        self._state = "typing"
        self.update()

    def trigger_dive_and_splash(self):
        """Called when card closes: creates splash and mascot emerges on top of the pill."""
        self._card_is_open = False
        self._state = "shaking"
        self._shake_phase = 18
        self._mascot_x = max(50.0, float(self.width() - 95))
        self._facing_left = True

        # Spawn ripples at the avatar location
        ax = float(self.width() - 36)
        ay = 74.0 + 25.0
        self._ripples.append(_Ripple(ax, ay, max_r=42.0))
        self._ripples.append(_Ripple(ax, ay, max_r=26.0))

        # Spawn water droplets
        for _ in range(8):
            vx = random.uniform(-2.5, 2.5)
            vy = random.uniform(-5.5, -2.0)
            self._droplets.append(_WaterDrop(ax, ay - 10, vx, vy))

        self.update()

    def trigger_leap_and_pop(self):
        """Called when card opens: mascot leaps upward into the card."""
        self._state = "leaping"
        self._leap_progress = 0.0

        mx = self._mascot_x + 27
        my = 74.0
        self._ripples.append(_Ripple(mx, my, max_r=36.0))

        anim = QVariantAnimation(self)
        anim.setDuration(280)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutQuad)

        def _step(val):
            self._leap_progress = float(val)
            self.update()

        def _done():
            self._card_is_open = True
            self._state = "idle"
            self.update()

        anim.valueChanged.connect(_step)
        anim.finished.connect(_done)
        anim.start()

    def _on_tick(self):
        # 1. Update particles
        self._ripples = [r for r in self._ripples if r.update()]
        self._droplets = [d for d in self._droplets if d.update()]
        self._confetti = [c for c in self._confetti if c.update()]

        # Decay typing bounce
        if self._typing_bob > 0:
            self._typing_bob = max(0.0, self._typing_bob - 0.7)

        # 2. Check worker activity across Prism
        # Only persistent background workers (> 2.0s) enter working runner mode.
        # Transient sub-second workers (licensing, Gerber/STEP check, plan route setup)
        # do NOT trigger working mode and NEVER trigger celebratory confetti!
        is_working = False
        try:
            import workers
            is_working = bool(workers._running)
        except Exception:
            pass

        if is_working:
            self._worker_run_ticks += 1
            if self._worker_run_ticks >= 40 and self._state not in ("leaping", "shaking", "celebrating"):
                self._state = "working"
        else:
            self._worker_run_ticks = 0
            if self._state == "working":
                self._state = "idle"
                self._state_timer = 0

        if self._card_is_open:
            if self._ripples or self._droplets or self._confetti:
                self.update()
            return

        self._state_timer += 1

        # 3. State machine handling
        if self._state == "celebrating":
            self._celebrate_timer -= 1
            self._walk_step += 1
            if self._celebrate_timer <= 0:
                self._state = "idle"
                self._state_timer = 0
            self.update()
            return

        if self._state == "typing":
            self._typing_timer -= 1
            if self._typing_timer <= 0:
                self._state = "idle"
                self._state_timer = 0
            self.update()
            return

        if self._state == "working":
            # Running briskly back and forth with determination during long operations
            self._walk_step += 1
            speed = 2.0
            min_x = 30.0
            max_x = max(50.0, float(self.width() - 110))

            if self._facing_left:
                self._mascot_x -= speed
                if self._mascot_x <= min_x:
                    self._mascot_x = min_x
                    self._facing_left = False
            else:
                self._mascot_x += speed
                if self._mascot_x >= max_x:
                    self._mascot_x = max_x
                    self._facing_left = True

            # Effort droplets
            if self._walk_step % 18 == 0:
                ax = self._mascot_x + (34 if self._facing_left else 12)
                self._droplets.append(_WaterDrop(ax, 38.0, random.uniform(-0.8, 0.8), -1.8))

            self.update()
            return

        if self._state == "shaking":
            self._shake_phase -= 1
            if self._shake_phase <= 0:
                self._state = "sitting"
                self._state_timer = 0
            self.update()
            return

        if self._state == "leaping":
            return

        if self._state == "waving":
            self._walk_step += 1
            self.update()
            return

        if self._state == "idle":
            self._walk_step += 1
            if self._state_timer > 60:  # ~3 seconds
                if random.random() < 0.35:
                    self._state = "sitting"
                    self._state_timer = 0
                else:
                    self._state = "walking"
                    min_x = 30.0
                    max_x = max(60.0, float(self.width() - 110))
                    t = random.uniform(min_x, max_x)
                    if abs(t - self._mascot_x) < 45.0:
                        t = max_x if self._mascot_x < (min_x + max_x) / 2 else min_x
                    self._target_x = t
                    self._facing_left = (self._target_x < self._mascot_x)
                    self._state_timer = 0
            self.update()
            return

        if self._state == "sitting":
            self._walk_step += 1
            if self._state_timer > 75:  # ~3.5 seconds
                self._state = "walking"
                min_x = 30.0
                max_x = max(60.0, float(self.width() - 110))
                t = random.uniform(min_x, max_x)
                if abs(t - self._mascot_x) < 45.0:
                    t = max_x if self._mascot_x < (min_x + max_x) / 2 else min_x
                self._target_x = t
                self._facing_left = (self._target_x < self._mascot_x)
                self._state_timer = 0
            self.update()
            return

        if self._state == "walking":
            self._walk_step += 1
            dist = self._target_x - self._mascot_x
            if abs(dist) < 2.0 or self._state_timer > 180:
                self._mascot_x = self._target_x
                self._state = "idle"
                self._state_timer = 0
            else:
                speed = 1.05  # Smooth, gentle waddle speed
                step = speed if dist > 0 else -speed
                self._mascot_x += step
                self._facing_left = (step < 0)
            self.update()

    def enterEvent(self, event):
        if not self._card_is_open and self._state not in ("leaping", "shaking", "celebrating"):
            self._prev_state = self._state
            self._state = "waving"
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._card_is_open and self._state == "waving":
            self._state = getattr(self, "_prev_state", "idle")
            self._state_timer = 0
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.toggle_requested.emit()
        super().mouseReleaseEvent(event)

    def _draw_star(self, painter: QPainter, cx: float, cy: float, r_outer: float, r_inner: float, color: QColor):
        path = QPainterPath()
        for i in range(8):
            angle = i * math.pi / 4.0
            r = r_outer if i % 2 == 0 else r_inner
            px = cx + r * math.cos(angle)
            py = cy + r * math.sin(angle)
            if i == 0:
                path.moveTo(px, py)
            else:
                path.lineTo(px, py)
        path.closeSubpath()
        painter.fillPath(path, color)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        # 1. Paint Ripples
        for r in self._ripples:
            col = QColor(r.color.red(), r.color.green(), r.color.blue(), int(r.alpha))
            pen = QPen(col, 2.0)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QPointF(r.x, r.y), r.radius, r.radius * 0.45)

        # 2. Paint Water Droplets
        for d in self._droplets:
            col = QColor(45, 212, 191, int(d.alpha))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(col))
            painter.drawEllipse(QPointF(d.x, d.y), d.r, d.r)

        # 3. Paint Confetti (3.2 Celebration)
        for c in self._confetti:
            painter.save()
            painter.translate(c.x, c.y)
            painter.rotate(c.rot)
            col = QColor(c.color.red(), c.color.green(), c.color.blue(), int(c.alpha))
            painter.fillRect(QRectF(-c.w / 2, -c.h / 2, c.w, c.h), col)
            painter.restore()

        # 4. Paint Mascot (hidden while card is open, active otherwise)
        if self._card_is_open and self._state != "leaping":
            return

        if not self._frames:
            return

        # Baseline ground alignment offsets for frames 0..7 based on measured asset alpha bboxes
        # [0, 6, 0, -1, 32, 30, 31, 30] * (72 / 384)
        FRAME_BASELINE_OFFSETS = [0.0, 1.1, 0.0, -0.2, 5.8, 5.6, 5.8, 5.6]

        # Scaled up for prominent, expressive display (was 36x44 -> now 54x72)
        mw, mh = 54, 72
        bob_y = 0.0
        tilt = 0.0
        scale_x = 1.0
        scale_y = 1.0
        y_base = 74.0 - mh + 3.0  # Feet planted comfortably on the dark pill top rim

        if self._state == "walking":
            # Natural, grounded waddle (penguin / cute mascot locomotion)
            # Distance-coupled phase ensures completely steady progress without jumping
            waddle_phase = self._mascot_x * 0.13
            tilt = math.sin(waddle_phase) * 3.2
            bob_y = -abs(math.sin(waddle_phase)) * 1.3
            squash = math.sin(waddle_phase * 2.0) * 0.035
            scale_x = 1.0 + squash
            scale_y = 1.0 - squash
            # Natural blinking (Frame 2 shares the exact foot baseline with Frame 0)
            is_blink = (self._walk_step % 65) in (0, 1, 2)
            idx = 2 if is_blink else 0

        elif self._state == "idle":
            # Gentle breathing
            breath = math.sin(self._state_timer * 0.07)
            bob_y = breath * 0.6
            scale_y = 1.0 + breath * 0.015
            is_blink = (self._state_timer % 70) in (0, 1, 2)
            idx = 2 if is_blink else 0

        elif self._state == "sitting":
            idx = 0
            y_base += 6.0  # Relaxed sitting with legs resting over pill rim
            breath = math.sin(self._state_timer * 0.05)
            bob_y = breath * 0.5
            is_blink = (self._state_timer % 80) in (0, 1, 2)
            if is_blink:
                idx = 2

        elif self._state == "working":
            # 3.3 Running worker progress
            run_phase = self._mascot_x * 0.22
            tilt = -9.0 if self._facing_left else 9.0
            bob_y = -abs(math.sin(run_phase)) * 2.2
            squash = math.sin(run_phase * 2.0) * 0.04
            scale_x = 1.0 + squash
            scale_y = 1.0 - squash
            idx = 0

        elif self._state == "celebrating":
            # 3.2 Celebration dance & sparkles
            seq = [4, 5, 6, 7]
            idx = seq[(self._walk_step // 2) % len(seq)]
            bob_y = -abs(math.sin(self._walk_step * 0.45)) * 9.0
            tilt = math.sin(self._walk_step * 0.45) * 11.0
            # Sparkle stars
            self._draw_star(painter, self._mascot_x + mw + 4, y_base - 10, 5.5, 2.0, QColor(245, 158, 11, 230))
            self._draw_star(painter, self._mascot_x - 8, y_base - 4, 4.5, 1.8, QColor(45, 212, 191, 230))

        elif self._state == "waving":
            seq = self._waving_seq
            idx = seq[(self._walk_step // 3) % len(seq)]
            tilt = math.sin(self._walk_step * 0.25) * 2.5

        elif self._state == "typing":
            # 3.5 Typing sync nod
            idx = 1
            bob_y = -self._typing_bob
            tilt = 0.0

        elif self._state == "shaking":
            idx = 2 if (self._shake_phase % 2 == 0) else 3
            bob_y = (self._shake_phase % 2) * 1.5
            tilt = 6.0 if (self._shake_phase % 2 == 0) else -6.0

        elif self._state == "leaping":
            p = self._leap_progress
            h_leap = 50.0
            bob_y = -4.0 * h_leap * p * (1.0 - p)
            tilt = -14.0 if self._facing_left else 14.0
            idx = 4
        else:
            seq = self._idle_seq
            idx = seq[(self._walk_step // 4) % len(seq)]

        pix = self._frames[idx]
        baseline_adj = FRAME_BASELINE_OFFSETS[idx] if idx < len(FRAME_BASELINE_OFFSETS) else 0.0
        target_x = self._mascot_x
        target_y = y_base + bob_y + baseline_adj

        painter.save()
        painter.translate(target_x + mw / 2, target_y + mh / 2)
        if tilt != 0.0:
            painter.rotate(tilt)
        if self._facing_left:
            painter.scale(-scale_x, scale_y)
        else:
            painter.scale(scale_x, scale_y)

        scaled = pix.scaled(mw, mh, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        painter.drawPixmap(-scaled.width() // 2, -scaled.height() // 2, scaled)
        painter.restore()


# ── FULL FLOATING OVERLAY COORDINATOR WITH DIVE & POP TRANSITIONS ────────────
class LumiOverlay(QWidget):
    """Coordinates the floating launcher and popup card with smooth Dive & Pop locomotion."""

    command_requested = Signal(str)

    def __init__(self, host: QWidget, support_panel: QWidget):
        super().__init__(host)
        self._host = host
        self._support_panel = support_panel
        self.setFixedSize(1, 1)

        self._launcher = LumiLauncherPill(host)
        self._launcher.toggle_requested.connect(self.toggle)

        self._card = LumiCard(support_panel, host)
        self._card.minimize_requested.connect(self.close)
        self._card.close_requested.connect(self.close)
        self._card.expand_toggled.connect(lambda _: self.reposition())
        self._card.command_requested.connect(self.command_requested.emit)
        self._card.typing_occurred.connect(self._launcher.on_user_typing)
        if hasattr(support_panel, "command_requested"):
            support_panel.command_requested.connect(self.command_requested.emit)

        self._card_anim: Optional[QVariantAnimation] = None
        self._is_closing = False

        self._card.hide()
        self.reposition()

        # Follow host resizing and typing automatically
        self._host.installEventFilter(self)

    def eventFilter(self, watched, event):
        if watched == self._host:
            if event.type() == QEvent.Resize:
                self.reposition()
            elif event.type() == QEvent.KeyPress:
                self._launcher.on_user_typing()
        return super().eventFilter(watched, event)

    def celebrate(self, duration_ms: int = 3500):
        """3.2 Celebration: triggers confetti burst and happy dance."""
        self._launcher.trigger_celebration(duration_ms)
        if hasattr(self._card, "_welcome_header") and hasattr(self._card._welcome_header, "set_mode"):
            self._card._welcome_header.set_mode("waving")

    def is_open(self) -> bool:
        return self._card.isVisible() and not self._is_closing

    def open(self):
        if self._card_anim and self._card_anim.state() == QVariantAnimation.Running:
            self._card_anim.stop()

        self._is_closing = False
        self.reposition()

        use_effects = (os.environ.get("PRISM_EFFECTS", "1") != "0"
                       and os.environ.get("QT_QPA_PLATFORM") != "offscreen")

        if not use_effects:
            self._card.show()
            self._card.raise_()
            self._launcher.raise_()
            self._launcher._card_is_open = True
            return

        # 1. Trigger mascot leap & pop effect from the pill
        self._launcher.trigger_leap_and_pop()

        # 2. Smoothly slide & spring the card up
        cx = self._card.x()
        target_y = self._card.y()
        start_y = target_y + 40

        self._card.move(cx, start_y)
        self._card.show()
        self._card.raise_()
        self._launcher.raise_()

        anim = QVariantAnimation(self)
        anim.setDuration(280)
        anim.setStartValue(start_y)
        anim.setEndValue(target_y)
        anim.setEasingCurve(QEasingCurve.OutCubic)

        def _step(val):
            self._card.move(cx, int(val))

        def _done():
            self._card.move(cx, target_y)
            if hasattr(self._card, "_welcome_header") and hasattr(self._card._welcome_header, "set_mode"):
                self._card._welcome_header.set_mode("waving")

        anim.valueChanged.connect(_step)
        anim.finished.connect(_done)
        self._card_anim = anim
        anim.start()

    def close(self):
        if self._card_anim and self._card_anim.state() == QVariantAnimation.Running:
            self._card_anim.stop()

        use_effects = (os.environ.get("PRISM_EFFECTS", "1") != "0"
                       and os.environ.get("QT_QPA_PLATFORM") != "offscreen")

        if not use_effects or not self._card.isVisible():
            self._is_closing = False
            self._card.hide()
            self._launcher.trigger_dive_and_splash()
            return

        self._is_closing = True

        # Header mascot dives forward
        if hasattr(self._card, "_welcome_header") and hasattr(self._card._welcome_header, "set_mode"):
            self._card._welcome_header.set_mode("diving")

        cx = self._card.x()
        start_y = self._card.y()
        end_y = self._launcher.y() - 10

        anim = QVariantAnimation(self)
        anim.setDuration(230)
        anim.setStartValue(start_y)
        anim.setEndValue(end_y)
        anim.setEasingCurve(QEasingCurve.InCubic)

        def _step(val):
            self._card.move(cx, int(val))

        def _done():
            self._card.hide()
            self._is_closing = False
            self.reposition()
            # Splash & mascot emerges on top of the launcher pill
            self._launcher.trigger_dive_and_splash()

        anim.valueChanged.connect(_step)
        anim.finished.connect(_done)
        self._card_anim = anim
        anim.start()

    def toggle(self):
        if self.is_open():
            self.close()
        else:
            self.open()

    def reposition(self):
        area = self._host.rect()
        edge = 24
        gap = 12

        lw = self._launcher.width()
        lh = self._launcher.height()
        lx = max(edge, area.width() - edge - lw)
        ly = max(edge, area.height() - edge - lh)
        self._launcher.move(lx, ly)

        cw = self._card.width()
        ch = self._card.height()
        cx = max(edge, area.width() - edge - cw)
        # Gap measured from top of the dark pill frame (y = ly + 74)
        pill_top = ly + 74
        cy = pill_top - gap - ch
        if cy < edge:
            cy = max(edge, area.height() - edge - ch)
        self._card.move(cx, cy)
