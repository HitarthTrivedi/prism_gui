"""Setup / Preferences dialog — the GUI's equivalent of the CLI's onboarding
wizard and /config, /agents, /profile, /key, /chrome commands, all in one
place since a GUI doesn't need them as separate steps."""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QLabel,
    QComboBox, QPushButton, QCheckBox, QGroupBox, QMessageBox, QScrollArea,
    QWidget, QDialogButtonBox,
)

import core_bridge as CB

SKIP = "— skip this category —"


class SetupDialog(QDialog):
    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Prism Setup")
        self.setMinimumWidth(560)
        self.cfg = dict(cfg)
        self._combos: dict[str, QComboBox] = {}
        self._premium_boxes: dict[str, QCheckBox] = {}

        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        form_root = QVBoxLayout(inner)

        # ── Groq API key ──────────────────────────────────────────────
        key_box = QGroupBox("Groq API key")
        key_form = QFormLayout(key_box)
        key_form.addRow(QLabel(
            "Free at console.groq.com → API Keys → Create API Key (starts with gsk_)"))
        self.key_edit = QLineEdit(self.cfg.get("api_key", ""))
        self.key_edit.setEchoMode(QLineEdit.Password)
        key_form.addRow("API key:", self.key_edit)
        form_root.addWidget(key_box)

        # ── Profile ───────────────────────────────────────────────────
        prof_box = QGroupBox("What do you do?")
        prof_form = QFormLayout(prof_box)
        self.profile_edit = QLineEdit(self.cfg.get("profile", ""))
        self.profile_edit.setPlaceholderText("e.g. indie game dev, startup marketer…")
        prof_form.addRow("Profile:", self.profile_edit)
        form_root.addWidget(prof_box)

        # ── Agents per category ──────────────────────────────────────
        agents_box = QGroupBox("Your specialists (one tool per category)")
        agents_form = QFormLayout(agents_box)
        current_agents = self.cfg.get("agents", {}) or {}
        for cat, meta in CB.agents.CATEGORIES.items():
            combo = QComboBox()
            combo.addItems(list(meta["agents"]) + [SKIP])
            default = current_agents.get(cat)
            if default in meta["agents"]:
                combo.setCurrentText(default)
            else:
                combo.setCurrentText(SKIP)
            combo.currentIndexChanged.connect(self._rebuild_premium)
            self._combos[cat] = combo
            agents_form.addRow(f"{meta['emoji']} {meta['label']}", combo)
        form_root.addWidget(agents_box)

        # ── Premium plans ─────────────────────────────────────────────
        self.premium_box = QGroupBox("Premium plans (routes the bulk of the work here)")
        self.premium_layout = QVBoxLayout(self.premium_box)
        form_root.addWidget(self.premium_box)
        self._rebuild_premium()

        # ── Chrome version ────────────────────────────────────────────
        chrome_box = QGroupBox("Chrome version")
        chrome_row = QHBoxLayout(chrome_box)
        self.chrome_edit = QLineEdit(self.cfg.get("chrome_version", ""))
        self.chrome_edit.setPlaceholderText("blank = auto-detect")
        chrome_row.addWidget(self.chrome_edit)
        detect_btn = QPushButton("Detect")
        detect_btn.clicked.connect(self._detect_chrome)
        chrome_row.addWidget(detect_btn)
        form_root.addWidget(chrome_box)

        login_btn = QPushButton("Open login tabs for your chosen tools")
        login_btn.clicked.connect(self._open_login_tabs)
        form_root.addWidget(login_btn)

        scroll.setWidget(inner)
        outer.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

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
            self.premium_layout.addWidget(QLabel("Pick at least one specialist above."))
            return
        for n in names:
            cb = QCheckBox(n)
            cb.setChecked(n in existing_premium)
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
            return
        agents = self._current_agents()
        if not agents:
            QMessageBox.warning(self, "Agents", "Pick at least one specialist.")
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
