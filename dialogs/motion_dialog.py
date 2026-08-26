"""
Prism Desktop Motion Graphics Studio Dialog
────────────────────────────────────────────
Visual workspace for previewing, inspecting, editing, and rendering
programmatic Motion Graphics projects with real-time feedback.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import core_bridge as CB
from dialogs.base import PrismDialog
from workers import MotionWorker


PRESET_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "SaaS Product UI & Feature Demo": {
        "project": { "width": 1080, "height": 1920, "fps": 30, "duration": 6.0, "background": "#090D16" },
        "camera": {
            "tracks": [
                { "time": 0.0, "zoom": 1.0, "position": [540, 960] },
                { "time": 1.4, "duration": 1.2, "easing": "easeInOutCubic", "position": [540, 920], "zoom": 1.35 },
                { "time": 4.5, "duration": 1.0, "easing": "easeOutExpo", "position": [540, 960], "zoom": 1.0 }
            ]
        },
        "scenes": [
            {
                "nodes": [
                    { "type": "text", "content": "Intelligent Automation", "position": [540, 420], "font_size": 52, "font_weight": 800, "fill": "#F8FAFC" },
                    {
                        "type": "domain_ui_mockup",
                        "position": [540, 920],
                        "width": 900,
                        "height": 520,
                        "title": "Prism Studio · Live Engine",
                        "url": "engine.alphakore.in",
                        "elements": [
                            { "type": "card", "x": 40, "y": 30, "w": 380, "h": 160, "title": "Engine Health: 99.98%" },
                            { "type": "card", "x": 460, "y": 30, "w": 380, "h": 160, "title": "Active Jobs: 1,420" },
                            { "type": "button", "x": 260, "y": 230, "w": 360, "h": 60, "label": "Trigger Pipeline", "color": "#38BDF8" }
                        ],
                        "cursor_actions": [{ "time": 1.5, "duration": 1.0, "from": [-300, -100], "to": [0, 90], "click": True }]
                    },
                    {
                        "type": "group", "position": [540, 1420],
                        "animation": { "enter": { "type": "pop_in", "time": 2.8, "duration": 0.6, "easing": "back.out" } },
                        "children": [
                            { "type": "shape_rect", "width": 780, "height": 130, "radius": 20, "fill": "rgba(30, 41, 59, 0.88)", "stroke": "rgba(56, 189, 248, 0.3)", "stroke_width": 2 },
                            { "type": "text", "content": "Real-Time Hardware Render in 1080p", "position": [0, 0], "font_size": 32, "font_weight": 700, "fill": "#38BDF8" }
                        ]
                    }
                ]
            }
        ]
    },
    "Growth Chart & Financial KPI": {
        "project": { "width": 1080, "height": 1920, "fps": 30, "duration": 6.0, "background": "#0B111E" },
        "camera": {
            "tracks": [
                { "time": 0.0, "zoom": 1.0, "position": [540, 960] },
                { "time": 1.5, "duration": 1.5, "easing": "easeInOutCubic", "position": [540, 920], "zoom": 1.25 },
                { "time": 4.5, "duration": 1.2, "easing": "easeOutExpo", "position": [540, 960], "zoom": 1.0 }
            ]
        },
        "scenes": [
            {
                "nodes": [
                    { "type": "text", "content": "Quarterly Revenue Surge", "position": [540, 420], "font_size": 48, "font_weight": 800, "fill": "#FFFFFF" },
                    { "type": "domain_chart", "chart_type": "metric", "position": [540, 680], "value_prefix": "₹", "value_suffix": " Cr", "data": [{ "label": "Annual Gross Run-Rate (+142%)", "value": 88000, "color": "#10B981" }], "start_time": 0.6, "duration": 1.8 },
                    { "type": "domain_chart", "chart_type": "bar", "position": [540, 1140], "width": 840, "height": 420, "value_prefix": "₹", "value_suffix": "k", "start_time": 1.8, "duration": 1.4, "data": [{ "label": "Q1 24", "value": 240, "color": "#38BDF8" }, { "label": "Q2 24", "value": 390, "color": "#38BDF8" }, { "label": "Q3 24", "value": 580, "color": "#38BDF8" }, { "label": "Q4 24", "value": 880, "color": "#10B981" }] }
                ]
            }
        ]
    },
    "System Architecture & Flow": {
        "project": { "width": 1080, "height": 1920, "fps": 30, "duration": 6.0, "background": "#0A0E17" },
        "camera": {
            "tracks": [
                { "time": 0.0, "zoom": 1.0, "position": [540, 960] },
                { "time": 1.5, "duration": 1.4, "easing": "easeInOutCubic", "position": [540, 980], "zoom": 1.3 },
                { "time": 4.5, "duration": 1.2, "easing": "easeOutExpo", "position": [540, 960], "zoom": 1.0 }
            ]
        },
        "scenes": [
            {
                "nodes": [
                    { "type": "text", "content": "Distributed Pipeline", "position": [540, 420], "font_size": 48, "font_weight": 800, "fill": "#FFFFFF" },
                    {
                        "type": "domain_diagram",
                        "position": [540, 980],
                        "nodes": [
                            { "id": "client", "label": "Client UI", "x": -280, "y": -160, "w": 180, "h": 70, "color": "#1E293B", "stroke": "#38BDF8" },
                            { "id": "gateway", "label": "API Gateway", "x": 0, "y": -160, "w": 200, "h": 70, "color": "#1E293B", "stroke": "#818CF8" },
                            { "id": "orchestrator", "label": "AI Orchestrator", "x": 280, "y": -160, "w": 200, "h": 70, "color": "#1E293B", "stroke": "#C084FC" },
                            { "id": "engine", "label": "Motion Runtime", "x": 140, "y": 140, "w": 220, "h": 75, "color": "#1E293B", "stroke": "#34D399" },
                            { "id": "ffmpeg", "label": "FFmpeg Muxer", "x": -140, "y": 140, "w": 200, "h": 75, "color": "#1E293B", "stroke": "#FB7185" }
                        ],
                        "edges": [
                            { "from": "client", "to": "gateway", "glow_color": "#38BDF8", "speed": 1.2 },
                            { "from": "gateway", "to": "orchestrator", "glow_color": "#818CF8", "speed": 1.5 },
                            { "from": "orchestrator", "to": "engine", "glow_color": "#C084FC", "speed": 1.0 },
                            { "from": "engine", "to": "ffmpeg", "glow_color": "#34D399", "speed": 1.4 },
                            { "from": "ffmpeg", "to": "client", "glow_color": "#FB7185", "speed": 1.1 }
                        ]
                    }
                ]
            }
        ]
    }
}


class MotionDialog(PrismDialog):
    def __init__(self, cfg: dict, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.cfg = cfg
        self.worker: Optional[MotionWorker] = None
        self.last_output_path: Optional[str] = None

        self.setWindowTitle("Prism Motion Graphics Studio")
        self.setMinimumSize(920, 680)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Header
        header_row = QHBoxLayout()
        title = QLabel("Motion Graphics Studio")
        title.setFont(QFont("Inter", 18, QFont.Bold))
        title.setStyleSheet("color: #F8FAFC;")
        header_row.addWidget(title)
        header_row.addStretch()

        self.preset_combo = QComboBox()
        self.preset_combo.setStyleSheet("""
            QComboBox {
                background: #1E293B;
                color: #F8FAFC;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 6px 14px;
                font-weight: 600;
            }
        """)
        for name in PRESET_TEMPLATES.keys():
            self.preset_combo.addItem(name)
        self.preset_combo.currentTextChanged.connect(self._on_preset_changed)
        header_row.addWidget(self.preset_combo)
        layout.addLayout(header_row)

        # Editor Frame
        self.editor = QTextEdit()
        self.editor.setFont(QFont("JetBrains Mono, monospace", 12))
        self.editor.setStyleSheet("""
            QTextEdit {
                background: #090D16;
                color: #38BDF8;
                border: 1px solid #1E293B;
                border-radius: 12px;
                padding: 14px;
            }
        """)
        layout.addWidget(self.editor, 1)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar { background: #1E293B; border-radius: 4px; }
            QProgressBar::chunk { background: #38BDF8; border-radius: 4px; }
        """)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        # Status Label
        self.status_label = QLabel("Ready to render 1080x1920 broadcast video.")
        self.status_label.setStyleSheet("color: #94A3B8; font-size: 13px;")
        layout.addWidget(self.status_label)

        # Footer Actions
        footer = QHBoxLayout()
        self.play_btn = QPushButton("Open Video")
        self.play_btn.setStyleSheet("background: #334155; color: white; padding: 10px 18px; border-radius: 8px; font-weight: 600;")
        self.play_btn.clicked.connect(self._play_output)
        self.play_btn.hide()
        footer.addWidget(self.play_btn)

        self.reveal_btn = QPushButton("Show in Files")
        self.reveal_btn.setStyleSheet("background: #334155; color: white; padding: 10px 18px; border-radius: 8px; font-weight: 600;")
        self.reveal_btn.clicked.connect(self._reveal_output)
        self.reveal_btn.hide()
        footer.addWidget(self.reveal_btn)

        footer.addStretch()

        self.render_btn = QPushButton("Export Broadcast MP4")
        self.render_btn.setStyleSheet("""
            QPushButton {
                background: #38BDF8;
                color: #090D16;
                padding: 12px 24px;
                border-radius: 8px;
                font-weight: 700;
                font-size: 14px;
            }
            QPushButton:hover { background: #7DD3FC; }
            QPushButton:disabled { background: #475569; color: #94A3B8; }
        """)
        self.render_btn.clicked.connect(self._start_render)
        footer.addWidget(self.render_btn)
        layout.addLayout(footer)

        self._on_preset_changed(self.preset_combo.currentText())

    def _on_preset_changed(self, name: str):
        preset = PRESET_TEMPLATES.get(name, {})
        self.editor.setPlainText(json.dumps(preset, indent=2))

    def _start_render(self):
        text = self.editor.toPlainText()
        try:
            from core.motion.schema import validate_motion_spec
            spec = validate_motion_spec(text)
        except Exception as e:
            QMessageBox.warning(self, "Invalid Specification", f"JSON validation failed:\n{e}")
            return

        out_dir = os.path.expanduser("~/Desktop/Prism Artifacts")
        os.makedirs(out_dir, exist_ok=True)
        stamp = int(time.time())
        out_path = os.path.join(out_dir, f"motion_{stamp}.mp4")

        self.render_btn.setEnabled(False)
        self.progress_bar.show()
        self.progress_bar.setValue(0)
        self.play_btn.hide()
        self.reveal_btn.hide()
        self.status_label.setText("Rendering frames deterministically to FFmpeg…")

        self.worker = MotionWorker(spec, out_path)
        self.worker.progress.connect(self._on_progress)
        self.worker.done.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_progress(self, current: int, total: int):
        pct = int((current / max(1, total)) * 100)
        self.progress_bar.setValue(pct)
        self.status_label.setText(f"Rendering frame {current}/{total} ({pct}%)…")

    def _on_done(self, out_path: str):
        self.last_output_path = out_path
        self.render_btn.setEnabled(True)
        self.progress_bar.hide()
        self.status_label.setText(f"Complete: {out_path}")
        self.play_btn.show()
        self.reveal_btn.show()

    def _on_failed(self, error: str):
        self.render_btn.setEnabled(True)
        self.progress_bar.hide()
        self.status_label.setText(f"Render failed: {error}")
        QMessageBox.critical(self, "Render Failed", error)

    def _play_output(self):
        if self.last_output_path and os.path.exists(self.last_output_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_output_path))

    def _reveal_output(self):
        if self.last_output_path and os.path.exists(self.last_output_path):
            folder = os.path.dirname(self.last_output_path)
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
