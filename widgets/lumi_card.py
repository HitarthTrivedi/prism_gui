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
from typing import Optional

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush, QColor, QCursor, QFont, QIcon, QLinearGradient, QPainter,
    QPainterPath, QPen, QPixmap,
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
            painter.drawPixmap(mx, my, scaled)
        else:
            fallback = QPixmap(paths.resource("assets", "lumi", "lumi_character.png"))
            if not fallback.isNull():
                scaled = fallback.scaled(mw, mh, Qt.KeepAspectRatio, Qt.SmoothTransformation)
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
class LumiLauncherPill(QWidget):
    """The floating dark pill launcher with Lumi's avatar badge at the bottom-right."""

    toggle_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(50)
        self.setMinimumWidth(320)
        self.setMaximumWidth(390)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        pill = QFrame()
        pill.setObjectName("lumiPillFrame")
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

        # Circular Avatar Badge with Green Online Dot
        avatar_wrap = QWidget()
        avatar_wrap.setFixedSize(40, 40)
        a_layout = QVBoxLayout(avatar_wrap)
        a_layout.setContentsMargins(0, 0, 0, 0)

        avatar_btn = QLabel(avatar_wrap)
        av_pix = QPixmap(paths.resource("assets", "lumi", "lumi_avatar.png"))
        if not av_pix.isNull():
            avatar_btn.setPixmap(av_pix.scaled(38, 38, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        avatar_btn.setFixedSize(38, 38)
        avatar_btn.setStyleSheet(
            "border: 2px solid #2dd4bf; border-radius: 19px; background: #0f172a;"
        )

        # Online status dot at top-right
        dot = QLabel(avatar_wrap)
        dot.setFixedSize(10, 10)
        dot.move(28, 2)
        dot.setStyleSheet(
            "background: #22c55e; border: 1.5px solid #18181b; border-radius: 5px;"
        )
        p_box.addWidget(avatar_wrap)

        layout.addWidget(pill)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.toggle_requested.emit()
        super().mouseReleaseEvent(event)


# ── FULL FLOATING OVERLAY COORDINATOR ─────────────────────────────────────────
class LumiOverlay(QWidget):
    """Coordinates the floating launcher and popup card over any host window."""

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
        if hasattr(support_panel, "command_requested"):
            support_panel.command_requested.connect(self.command_requested.emit)

        self._card.hide()
        self.reposition()

    def is_open(self) -> bool:
        return self._card.isVisible()

    def open(self):
        self.reposition()
        self._card.show()
        self._card.raise_()
        self._launcher.raise_()

    def close(self):
        self._card.hide()

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
        cy = ly - gap - ch
        if cy < edge:
            cy = max(edge, area.height() - edge - ch)
        self._card.move(cx, cy)
