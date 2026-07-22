"""Setup — the GUI's equivalent of the CLI's onboarding wizard plus /config,
/agents, /profile, /key and /chrome, all in one scrolling page since a GUI
doesn't need them as separate steps.

The rail links to individual settings, so the dialog takes a `focus` argument:
clicking "API key" opens this scrolled to the key section with the field
already focused and the section briefly marked, instead of dumping the whole
wizard on you and leaving you to hunt for the one row you came for."""
from __future__ import annotations
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QLabel,
    QComboBox, QPushButton, QCheckBox, QMessageBox, QScrollArea,
    QWidget, QFrame,
)

import core_bridge as CB
import theme
from widgets import icons
from widgets.agents_panel import STAGE_COPY
from widgets.controls import heading, icon_label, kicker

SKIP = "— skip this category —"

# rail command -> the section it should land on (None = top of the page)
FOCUS_SECTIONS = {"key": "key", "profile": "profile", "agents": "agents",
                  "chrome": "chrome", "config": None}


class Section(QFrame):
    """One settings block: tracked kicker, optional explainer, then content.
    Sections are separated by whitespace and a hairline, not by boxes — this
    is one page you scroll, not six nested frames."""

    def __init__(self, title: str, blurb: str = "", parent=None):
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(9)

        self._kicker = kicker(title)
        # In its own row with a stretch so flash() tints the words, not the
        # full width of the dialog.
        kick_row = QHBoxLayout()
        kick_row.setContentsMargins(0, 0, 0, 0)
        kick_row.addWidget(self._kicker)
        kick_row.addStretch(1)
        box.addLayout(kick_row)
        if blurb:
            note = QLabel(blurb)
            note.setObjectName("meta")
            note.setWordWrap(True)
            box.addWidget(note)

        self.content = QVBoxLayout()
        self.content.setContentsMargins(0, 0, 0, 0)
        self.content.setSpacing(9)
        box.addLayout(self.content)

    def flash(self):
        """Mark the section you were sent to, then let it settle. Landing
        mid-page with a focused field is otherwise ambiguous — this says
        'here'."""
        self._kicker.setStyleSheet(
            f"background: {theme.ACCENT_RAMP[100]}; color: {theme.ACCENT_RAMP[800]};"
            f"padding: 3px 7px;")
        QTimer.singleShot(1400, lambda: self._kicker.setStyleSheet(""))


def rule() -> QFrame:
    line = QFrame()
    line.setObjectName("hr")
    line.setFixedHeight(1)
    return line


class SetupDialog(QDialog):
    def __init__(self, cfg: dict, parent=None, focus: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Prism Setup")
        # Sized up front: a QScrollArea reports its viewport's sizeHint, so
        # without this the dialog opens as a slot barely one form row tall.
        self.resize(720, 680)
        self.setMinimumSize(560, 460)
        self.cfg = dict(cfg)
        self._combos: dict[str, QComboBox] = {}
        self._premium_boxes: dict[str, QCheckBox] = {}
        self._sections: dict[str, Section] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._header())

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        inner = QWidget()
        page = QVBoxLayout(inner)
        page.setContentsMargins(24, 20, 24, 24)
        page.setSpacing(20)

        for index, (key, section) in enumerate((
            ("key", self._key_section()),
            ("profile", self._profile_section()),
            ("agents", self._agents_section()),
            ("premium", self._premium_section()),
            ("chrome", self._chrome_section()),
        )):
            if index:
                page.addWidget(rule())
            self._sections[key] = section
            page.addWidget(section)
        page.addStretch(1)

        self.scroll.setWidget(inner)
        outer.addWidget(self.scroll, stretch=1)
        outer.addWidget(self._footer())

        self._rebuild_premium()
        if focus:
            # Deferred: scrolling to a widget that hasn't been laid out yet
            # lands nowhere.
            QTimer.singleShot(0, lambda: self._focus_section(focus))

    # ── chrome ────────────────────────────────────────────────────────────
    def _header(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("setupHeader")
        bar.setStyleSheet(f"QFrame#setupHeader {{ background: {theme.SURFACE};"
                          f"border-bottom: 1px solid {theme.DIVIDER}; }}")
        row = QHBoxLayout(bar)
        row.setContentsMargins(24, 16, 24, 16)
        row.setSpacing(11)
        glyph = QLabel()
        glyph.setPixmap(icons.pixmap("sliders", 20, theme.ACCENT))
        glyph.setAlignment(Qt.AlignTop)
        row.addWidget(glyph)
        title = QVBoxLayout()
        title.setSpacing(1)
        title.addWidget(heading("Setup"))
        sub = QLabel("Your key, your profile, and which tool handles each kind "
                     "of step. Shared with the Prism CLI.")
        sub.setObjectName("meta")
        sub.setWordWrap(True)
        title.addWidget(sub)
        row.addLayout(title, stretch=1)
        return bar

    def _footer(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("setupFooter")
        # Scoped: unscoped, this surface fill lands on the Save button too and
        # flattens it back to a plain box.
        bar.setStyleSheet(f"QFrame#setupFooter {{ background: {theme.SURFACE};"
                          f"border-top: 1px solid {theme.DIVIDER}; }}")
        row = QHBoxLayout(bar)
        row.setContentsMargins(24, 13, 24, 13)
        row.setSpacing(9)

        login_btn = QPushButton(" Open login tabs")
        login_btn.setObjectName("smallBtn")
        login_btn.setCursor(Qt.PointingHandCursor)
        login_btn.setToolTip("Opens each chosen tool in Chrome so you can sign in")
        icons.button_icon(login_btn, "lock", 14, theme.TEXT)
        login_btn.clicked.connect(self._open_login_tabs)
        row.addWidget(login_btn)
        row.addStretch(1)

        cancel = QPushButton("Cancel")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)

        save = QPushButton(" Save")
        save.setObjectName("primaryBtn")
        save.setCursor(Qt.PointingHandCursor)
        save.setDefault(True)
        icons.button_icon(save, "check", 15, theme.BG)
        save.clicked.connect(self._save)
        row.addWidget(save)
        return bar

    # ── sections ──────────────────────────────────────────────────────────
    def _key_section(self) -> Section:
        s = Section("Groq API key",
                    "Free at console.groq.com → API Keys → Create API Key. "
                    "It starts with gsk_.")
        self.key_edit = QLineEdit(self.cfg.get("api_key", ""))
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("gsk_…")
        s.content.addWidget(self.key_edit)
        return s

    def _profile_section(self) -> Section:
        s = Section("What do you do?",
                    "One line. Prism uses it to pitch every prompt at the right "
                    "audience.")
        self.profile_edit = QLineEdit(self.cfg.get("profile", ""))
        self.profile_edit.setPlaceholderText("e.g. indie game dev, startup marketer…")
        s.content.addWidget(self.profile_edit)
        return s

    def _agents_section(self) -> Section:
        s = Section("Your specialists",
                    "One tool per kind of step. These are the names you'll see "
                    "on the plan — skip any you don't want Prism to use.")
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(9)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        current_agents = self.cfg.get("agents", {}) or {}
        # Pipeline order, not dict order — these rows should read in the same
        # sequence the plan lists them in.
        for cat in [c for c in CB.agents.PIPELINE_ORDER if c in CB.agents.CATEGORIES]:
            meta = CB.agents.CATEGORIES[cat]
            combo = QComboBox()
            combo.addItems(list(meta["agents"]) + [SKIP])
            default = current_agents.get(cat)
            combo.setCurrentText(default if default in meta["agents"] else SKIP)
            combo.currentIndexChanged.connect(self._rebuild_premium)
            combo.setToolTip(meta.get("desc", ""))
            self._combos[cat] = combo
            # The plan calls this step "Build the slides"; setup should name
            # the same thing the same way, with the same icon.
            icon_name, title, _ = STAGE_COPY.get(cat, ("grid", meta["label"], ""))
            form.addRow(icon_label(icon_name, title), combo)
        s.content.addLayout(form)
        return s

    def _premium_section(self) -> Section:
        s = Section("Premium plans",
                    "Tick the tools you pay for — Prism routes the bulk of the "
                    "work to those.")
        self.premium_layout = QVBoxLayout()
        self.premium_layout.setContentsMargins(0, 0, 0, 0)
        self.premium_layout.setSpacing(6)
        s.content.addLayout(self.premium_layout)
        return s

    def _chrome_section(self) -> Section:
        s = Section("Chrome version",
                    "Leave blank to auto-detect. Only pin this if automation "
                    "keeps failing to attach.")
        row = QHBoxLayout()
        row.setSpacing(9)
        self.chrome_edit = QLineEdit(self.cfg.get("chrome_version", ""))
        self.chrome_edit.setPlaceholderText("blank = auto-detect")
        row.addWidget(self.chrome_edit, stretch=1)
        detect_btn = QPushButton("Detect")
        detect_btn.setCursor(Qt.PointingHandCursor)
        detect_btn.clicked.connect(self._detect_chrome)
        row.addWidget(detect_btn)
        s.content.addLayout(row)
        return s

    # ── focus ─────────────────────────────────────────────────────────────
    def _focus_section(self, key: str):
        section = self._sections.get(FOCUS_SECTIONS.get(key, key) or "")
        if section is None:
            return
        self.scroll.ensureWidgetVisible(section, 0, 60)
        section.flash()
        field = {"key": getattr(self, "key_edit", None),
                 "profile": getattr(self, "profile_edit", None),
                 "chrome": getattr(self, "chrome_edit", None)}.get(key)
        if field is not None:
            field.setFocus()
        elif key == "agents" and self._combos:
            next(iter(self._combos.values())).setFocus()

    # ── data ──────────────────────────────────────────────────────────────
    def _current_agents(self) -> dict:
        out = {}
        for cat, combo in self._combos.items():
            v = combo.currentText()
            if v != SKIP:
                out[cat] = v
        return out

    def _rebuild_premium(self):
        while self.premium_layout.count():
            item = self.premium_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._premium_boxes = {}
        names = sorted(set(self._current_agents().values()))
        existing_premium = set(self.cfg.get("premium") or [])
        if not names:
            empty = QLabel("Pick at least one specialist above.")
            empty.setObjectName("meta")
            self.premium_layout.addWidget(empty)
            return
        for n in names:
            cb = QCheckBox(n)
            cb.setChecked(n in existing_premium)
            cb.setCursor(Qt.PointingHandCursor)
            self._premium_boxes[n] = cb
            self.premium_layout.addWidget(cb)

    def _detect_chrome(self):
        try:
            automation = CB.get_automation()
            v = automation.detect_chrome_version()
        except Exception as e:
            QMessageBox.warning(self, "Chrome detection", f"Couldn't detect Chrome: {e}")
            return
        self.chrome_edit.setText(str(v) if v else "")

    def _open_login_tabs(self):
        agents = self._current_agents()
        if not agents:
            QMessageBox.information(self, "Login tabs", "Pick at least one specialist first.")
            return
        try:
            automation = CB.get_automation()
        except Exception as e:
            QMessageBox.warning(self, "Login tabs", f"Automation deps not available: {e}")
            return
        urls, seen = [], set()
        for name in agents.values():
            if name not in seen:
                urls.append(CB.agents.AGENT_REGISTRY[name]["url"])
                seen.add(name)
        automation.open_login_tabs(urls)
        QMessageBox.information(self, "Login tabs",
                                f"Opened {len(urls)} tab(s) in Chrome — sign in, then close this dialog.")

    def _save(self):
        key = self.key_edit.text().strip()
        if key and not (key.startswith("gsk_") and len(key) > 20):
            QMessageBox.warning(self, "API key", "That doesn't look like a Groq key (should start with 'gsk_').")
            self._focus_section("key")
            return
        agents = self._current_agents()
        if not agents:
            QMessageBox.warning(self, "Specialists", "Pick at least one specialist.")
            self._focus_section("agents")
            return
        self.cfg["api_key"] = key
        self.cfg["profile"] = self.profile_edit.text().strip()
        self.cfg["agents"] = agents
        self.cfg["premium"] = [n for n, cb in self._premium_boxes.items() if cb.isChecked()]
        v = CB.automation_available()[0] and CB.get_automation().parse_chrome_version(self.chrome_edit.text())
        self.cfg["chrome_version"] = str(v) if v else ""
        self.cfg["onboarded"] = True
        CB.config.save(self.cfg)
        self.accept()
