"""Setup — the GUI's equivalent of the CLI's onboarding wizard plus /config,
/agents, /profile, /key and /chrome, all in one page since a GUI doesn't need
them as separate steps.

This is the first surface a paying customer meets, so it is the one that had
the most to gain from the shared modal chrome: eight sections used to run down
a single undifferentiated column separated by hairlines, which reads as one
very long form and gives a first-time user no idea how much of it is left. The
sections are cards now, and an index down the left says how many there are and
lets any one of them be reached in a click.

The rail links to individual settings, so the dialog takes a `focus` argument:
clicking "API key" opens this scrolled to the key section with the field
already focused and the section briefly marked, instead of dumping the whole
wizard on you and leaving you to hunt for the one row you came for. The index
drives exactly the same code path — a nav entry IS a `focus`."""
from __future__ import annotations
import os
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit,
    QLabel, QComboBox, QPushButton, QCheckBox, QMessageBox, QScrollArea,
    QWidget, QFrame, QApplication, QFileDialog,
)

import app_meta
import core_bridge as CB
import i18n
import identity
import licensing
import roles as R
import workspace as W
import theme
from dialogs.base import PrismDialog
from widgets import controls as C
from widgets import icons
from widgets.agents_panel import STAGE_COPY
from widgets.controls import heading, icon_label, kicker, meta

SKIP = "— skip this category —"

# rail command -> the section it should land on (None = top of the page)
FOCUS_SECTIONS = {"key": "key", "profile": "profile", "agents": "agents",
                  "chrome": "chrome", "licence": "licence",
                  "language": "language", "team": "team", "config": None}

# (section key, the words on the index, the glyph). The order here is the order
# down the page and the order down the index — they are the same list, so the
# two cannot drift apart.
SECTION_INDEX = [
    ("licence", "Licence", "key"),
    ("team", "Your role", "user"),
    ("language", "Language", "globe"),
    ("key", "API key", "lock"),
    ("profile", "What you do", "user"),
    ("agents", "Specialists", "grid"),
    ("premium", "Premium plans", "chart"),
    ("chrome", "Chrome", "globe"),
]


class Section(C.Card):
    """One settings block, as a card: tracked kicker, optional explainer, then
    content.

    These used to be bare frames separated by hairlines, on the theory that
    Setup is one page you scroll rather than six nested boxes. That was right
    about the nesting and wrong about the result: eight blocks of left-aligned
    form rows with nothing but whitespace between them reads as one form eight
    screens long, and a first-time user cannot see where a section starts, how
    long it is, or how much of it is still to come. A card answers all three
    without adding a level of nesting — it IS the level of nesting the
    hairlines were standing in for.
    """

    def __init__(self, title: str, blurb: str = "", parent=None):
        super().__init__(parent=parent)
        box = self.body((theme.CARD_PAD, theme.CARD_PAD,
                         theme.CARD_PAD, theme.CARD_PAD), theme.SPACE_3)

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
        self.content.setSpacing(theme.SPACE_3)
        box.addLayout(self.content)

    def flash(self):
        """Mark the section you were sent to, then let it settle. Landing
        mid-page with a focused field is otherwise ambiguous — this says
        'here'."""
        self._kicker.setStyleSheet(
            f"background: {theme.ACCENT_RAMP[100]}; color: {theme.ACCENT_RAMP[800]};"
            f"padding: 3px 7px; border-radius: {theme.R_CHIP}px;")
        QTimer.singleShot(1400, lambda: self._kicker.setStyleSheet(""))


def rule() -> QFrame:
    line = QFrame()
    line.setObjectName("hr")
    line.setFixedHeight(1)
    return line


class SetupDialog(PrismDialog):
    def __init__(self, cfg: dict, parent=None, focus: str | None = None):
        super().__init__(
            i18n.t("Setup"),
            i18n.t("Your key, your profile, and which tool handles each kind "
                   "of step. Shared with the Prism CLI."),
            icon="sliders", parent=parent)
        self.setWindowTitle("Prism Setup")
        # Sized up front: a QScrollArea reports its viewport's sizeHint, so
        # without this the dialog opens as a slot barely one form row tall.
        # Wider than it was because the index now takes a column of its own —
        # the content column is unchanged in width.
        self.resize(880, 720)
        self.setMinimumSize(720, 520)
        self.cfg = dict(cfg)
        self._combos: dict[str, QComboBox] = {}
        self._premium_boxes: dict[str, QCheckBox] = {}
        self._sections: dict[str, Section] = {}
        self._nav_buttons: dict[str, QPushButton] = {}

        # The base class's body carries the page padding; this dialog puts an
        # index against the left edge, so it takes the padding back and hands
        # it to the two columns individually.
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(0)
        split = QHBoxLayout()
        split.setContentsMargins(0, 0, 0, 0)
        split.setSpacing(0)
        split.addWidget(self._index(), stretch=0)
        self.body.addLayout(split, stretch=1)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        inner = QWidget()
        page = QVBoxLayout(inner)
        page.setContentsMargins(theme.PAGE_PAD, theme.SPACE_5,
                                theme.PAGE_PAD, theme.SPACE_6)
        page.setSpacing(theme.CARD_GAP)

        builders = {
            # First on the page: it says who this copy belongs to and what it
            # can do, which frames every setting under it.
            "licence": self._licence_section,
            # Who this copy belongs to and what they may see. Directly under
            # the licence because the two are one idea: the company key says
            # the firm has paid, the designation key says which of its people
            # is sitting here.
            "team": self._team_section,
            # Then language, because it changes the words every section below
            # is written in — someone who opened Setup unable to read it needs
            # to reach this without scrolling past five English sections.
            "language": self._language_section,
            "key": self._key_section,
            "profile": self._profile_section,
            "agents": self._agents_section,
            "premium": self._premium_section,
            "chrome": self._chrome_section,
        }
        for key, _label, _icon in SECTION_INDEX:
            section = builders[key]()
            self._sections[key] = section
            page.addWidget(section)
        page.addStretch(1)

        self.scroll.setWidget(inner)
        split.addWidget(self.scroll, stretch=1)
        self._build_footer()

        self._rebuild_premium()
        self._set_tab_order()
        # Which card the reader is actually looking at, so the index is a
        # position indicator and not only a set of links.
        self.scroll.verticalScrollBar().valueChanged.connect(self._sync_index)
        QTimer.singleShot(0, self._sync_index)
        if focus:
            # Deferred: scrolling to a widget that hasn't been laid out yet
            # lands nowhere.
            QTimer.singleShot(0, lambda: self._focus_section(focus))

    # ── chrome ────────────────────────────────────────────────────────────
    def _index(self) -> QWidget:
        """The eight sections, down the left, as a reachable list.

        Setup already had the machinery for this — `_focus_section` scrolls to
        a section and flashes it, and the rail has been calling it for a while
        — it simply had no visible entry point, so the only way to reach the
        Chrome section was to scroll past seven others and recognise it.
        """
        rail = QFrame()
        rail.setObjectName("setupIndex")
        rail.setAttribute(Qt.WA_StyledBackground, True)
        rail.setFixedWidth(184)
        rail.setStyleSheet(
            f"#setupIndex {{ background: {theme.WELL};"
            f" border: none; border-right: 1px solid {theme.HAIRLINE}; }}")
        col = QVBoxLayout(rail)
        col.setContentsMargins(theme.SPACE_3, theme.SPACE_5,
                               theme.SPACE_3, theme.SPACE_3)
        col.setSpacing(2)
        col.addWidget(kicker(i18n.t("Sections"), muted=True))
        col.addSpacing(theme.SPACE_2)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        for key, label, icon_name in SECTION_INDEX:
            btn = QPushButton(f"  {i18n.t(label)}")
            btn.setObjectName("setupIndexBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(C.MIN_TARGET + 4)
            btn.setStyleSheet(
                f"#setupIndexBtn {{ text-align: left; border: none;"
                f" background: transparent; padding: 6px {theme.SPACE_2}px;"
                f" border-radius: {theme.R_CONTROL}px;"
                f" color: {theme.NEUTRAL[700]}; font-size: 13px; }}"
                f"#setupIndexBtn:hover {{ background: {theme.NEUTRAL[200]}; }}"
                f"#setupIndexBtn:checked {{ background: {theme.ACCENT_RAMP[100]};"
                f" color: {theme.ACCENT_RAMP[800]}; font-weight: 600; }}"
                f"#setupIndexBtn:focus {{ border: 2px solid {theme.ACCENT}; }}")
            icons.button_icon(btn, icon_name, 15, theme.NEUTRAL[600])
            btn.clicked.connect(lambda _=False, k=key: self._focus_section(k))
            self._nav_group.addButton(btn)
            self._nav_buttons[key] = btn
            col.addWidget(btn)
        col.addStretch(1)
        return rail

    def _sync_index(self):
        """Tick whichever card the viewport is currently showing most of."""
        if not self._sections:
            return
        top = self.scroll.verticalScrollBar().value()
        current = None
        for key, _label, _icon in SECTION_INDEX:
            section = self._sections.get(key)
            if section is None:
                continue
            if section.mapTo(self.scroll.widget(), section.rect().topLeft()).y() \
                    <= top + theme.SPACE_7:
                current = key
        btn = self._nav_buttons.get(current or SECTION_INDEX[0][0])
        if btn is not None and not btn.isChecked():
            btn.setChecked(True)

    def _build_footer(self):
        login_btn = self.button(
            i18n.t("Open login tabs"), "secondary", icon_name="lock",
            small=True,
            on_click=self._open_login_tabs,
            tooltip="Opens each chosen tool in Chrome so you can sign in")
        self.footer.add_utility(login_btn)

        # The one button that makes a support call short. Everything a
        # customer would otherwise have to describe from memory, in a file
        # they can attach to an email — with every credential redacted.
        diag_btn = self.button(
            i18n.t("Export diagnostics"), "secondary", icon_name="file",
            small=True,
            on_click=self._export_diagnostics,
            tooltip="Saves a text file describing this installation and what "
                    "Prism has been doing, so support can see what happened. "
                    "Your API key, passwords and licence key are removed "
                    "from it.")
        self.footer.add_utility(diag_btn)

        self.footer.add_secondary(
            self.button(i18n.t("Cancel"), "secondary", on_click=self.reject))
        self.footer.set_primary(
            self.button(i18n.t("Save"), "primary", icon_name="check",
                        on_click=self._save))

    def _set_tab_order(self):
        """The order somebody filling this in for the first time reads it.

        Qt's default is construction order, which here is eight helper methods
        deep and puts the workspace picker between the designation key and the
        language combo. Setup is the one dialog a customer may have to complete
        before they can do anything at all, so keyboard-only completion is not
        optional.
        """
        chain = [self.designation_edit, self.workspace_edit,
                 getattr(self, "member_name", None),
                 getattr(self, "member_role", None),
                 self.lang_combo, self.out_lang_combo,
                 self.key_edit, self.profile_edit]
        chain += list(self._combos.values())
        chain.append(self.chrome_edit)
        self.tab_chain(*chain)

    # ── sections ──────────────────────────────────────────────────────────
    def _licence_section(self) -> Section:
        """Who this copy belongs to, what it can do, and until when.

        Always shows the LICENCE end date, never the token's — a customer told
        "expires in 4 days" on day 3 of a 10-day trial will phone you, and be
        right to.
        """
        import time

        s = Section("Licence", "What this copy of Prism is licensed for.")
        state = licensing.state()

        if state.status == licensing.NONE:
            s.content.addWidget(icon_label(
                "lock", "Not activated on this computer yet."))
        else:
            when = (time.strftime("%d %B %Y", time.localtime(state.license_ends))
                    if state.license_ends else "—")
            word = "Ended" if not state.usable else (
                "Trial ends" if state.kind == "trial" else "Renews")
            rows = [
                ("Licensed to", state.customer or "—"),
                ("Plan", (state.plan or "—").title()
                 + (f" · {state.seats} seat{'s' if state.seats != 1 else ''}"
                    if state.seats else "")),
                (word, f"{when}"
                       + (f"  ({state.days_left} days left)"
                          if state.usable and state.days_left >= 0 else "")),
            ]
            form = QFormLayout()
            form.setContentsMargins(0, 0, 0, 0)
            form.setSpacing(6)
            for label, value in rows:
                value_label = QLabel(value)
                value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
                form.addRow(QLabel(label), value_label)
            s.content.addLayout(form)

            # Every add-on, ticked or padlocked. Showing the locked ones is
            # deliberate: this is the only place a customer can see what else
            # Prism does.
            from dialogs.license_dialog import FEATURE_NAMES, feature_label
            s.content.addWidget(kicker("Included", muted=True))
            for feature in ("core", "boq", "email", "reel", "bom"):
                if feature not in FEATURE_NAMES:
                    continue
                have = state.has(feature)
                # theme.OK, not theme.ACCENT. "You have this" is a success
                # state, and the accent rotates with the role — in a green
                # profile an accent tick and a neutral padlock were the same
                # colour family, so the one line telling a customer what they
                # have paid for stopped distinguishing bought from locked.
                row = icon_label("check" if have else "lock",
                                 feature_label(feature), 15,
                                 theme.OK if have else theme.NEUTRAL[400])
                if not have:
                    row.setStyleSheet(f"color: {theme.NEUTRAL[500]};")
                s.content.addWidget(row)

        note = meta(f"This computer: {licensing.device_fingerprint()}  ·  "
                    f"{app_meta.SUPPORT_EMAIL}")
        note.setTextInteractionFlags(Qt.TextSelectableByMouse)
        s.content.addWidget(note)

        row = QHBoxLayout()
        row.setSpacing(theme.SPACE_2)
        change = C.button(i18n.t(" Enter a licence key"), "secondary", "key",
                          small=True, on_click=self._change_licence)
        row.addWidget(change)
        row.addStretch(1)

        if state.status != licensing.NONE:
            # Destructive, and pushed to the far side of the row rather than
            # sitting shoulder to shoulder with "Enter a licence key". The two
            # buttons read almost identically at a glance and one of them ends
            # this machine's access to the product.
            release = C.button(i18n.t(" Deactivate this computer"), "destructive",
                               "trash", small=True, on_click=self._deactivate)
            release.setToolTip(
                "Frees this machine's seat so the licence can be used on "
                "another computer. You'll need the key again to come back.")
            row.addWidget(release)
        s.content.addLayout(row)
        return s

    def _change_licence(self):
        from dialogs.license_dialog import LicenseDialog
        if LicenseDialog(self, mode="change").exec() == QDialog.Accepted:
            QMessageBox.information(
                self, "Licence",
                "Activated. Reopen Setup to see the new details.")
            self._notify_parent()

    def _deactivate(self):
        if QMessageBox.question(
                self, "Deactivate this computer",
                "This frees the seat so the licence can be used elsewhere.\n\n"
                "Prism on THIS computer will stop until you enter the key "
                "again. Your settings and history stay put.",
                QMessageBox.Yes | QMessageBox.Cancel) != QMessageBox.Yes:
            return
        licensing.deactivate()
        self._notify_parent()
        QMessageBox.information(self, "Deactivated",
                                "This computer's seat has been released.")

    def _notify_parent(self):
        owner = self.parent()
        if owner is not None and hasattr(owner, "refresh_licence_ui"):
            owner.refresh_licence_ui()

    def _export_diagnostics(self):
        import diagnostics
        import time
        suggested = os.path.join(
            os.path.expanduser("~"),
            f"prism-diagnostics-{time.strftime('%Y%m%d-%H%M')}.txt")
        target, _ = QFileDialog.getSaveFileName(
            self, i18n.t("Save diagnostics"), suggested, "Text (*.txt)")
        if not target:
            return
        try:
            diagnostics.export(target)
        except Exception as e:                          # noqa: BLE001
            QMessageBox.warning(self, "Diagnostics", i18n.t(
                "Couldn't write the file: {error}").format(error=e))
            return
        QMessageBox.information(self, "Diagnostics", i18n.t(
            "Saved to {path}\n\nEmail it to support and they'll be able to "
            "see what happened. Your API key, passwords and licence key are "
            "not in it.").format(path=target))

    def _team_section(self) -> Section:
        """Who is using this copy, where the team's work lives, and — for a
        manager — who else is on the team.

        Deliberately shows a working member almost nothing to configure. Their
        role came from a signed key and is not theirs to change; the only
        thing this section owes them is a plain statement of what it means,
        including that their manager can read their history. Someone finding
        that out later, by surprise, is a much worse day than being told now.
        """
        s = Section("Your role",
                    "Which job this copy of Prism is set up for, and where "
                    "the team's work is kept.")
        me = identity.current()

        if me["role"]:
            role = R.get(me["role"])
            s.content.addWidget(icon_label(
                role.icon, f"{me['name'] or 'This copy'} — {role.label}"))
            note = meta(role.blurb)
            note.setWordWrap(True)
            s.content.addWidget(note)

            shared = W.is_shared(self.cfg)
            if me["admin"]:
                said = ("You can open any member's profile and history from "
                        "the History window.")
            elif shared:
                said = ("Your work is saved in the shared team workspace, so "
                        "your manager can see what you have run. Other "
                        "members cannot.")
            else:
                said = ("Your work stays in your own folder. Other members "
                        "cannot see it.")
            privacy = meta(said)
            privacy.setWordWrap(True)
            s.content.addWidget(privacy)
        else:
            s.content.addWidget(icon_label(
                "user", "Personal copy — no company role"))
            note = meta("If your company gave you a designation key, paste it "
                        "below to switch this copy to your job's setup.")
            note.setWordWrap(True)
            s.content.addWidget(note)

        # ── the designation key ───────────────────────────────────────────
        row = QHBoxLayout()
        row.setSpacing(9)
        self.designation_edit = QLineEdit()
        self.designation_edit.setPlaceholderText("PRSD1.… — paste your designation key")
        self.designation_edit.setToolTip(
            "The second key, one per person. It decides your role, your "
            "folder and this window's colour. It only works alongside your "
            "company licence key.")
        row.addWidget(self.designation_edit, stretch=1)
        apply_btn = QPushButton("Apply")
        apply_btn.setCursor(Qt.PointingHandCursor)
        apply_btn.clicked.connect(self._apply_designation)
        row.addWidget(apply_btn)
        if me["role"]:
            drop = QPushButton("Remove")
            drop.setCursor(Qt.PointingHandCursor)
            drop.setToolTip("Turn this back into a personal copy. Work "
                            "already saved in the workspace stays there.")
            drop.clicked.connect(self._clear_designation)
            row.addWidget(drop)
        s.content.addLayout(row)

        # ── where the workspace lives ─────────────────────────────────────
        s.content.addWidget(kicker("Team workspace", muted=True))
        where = meta(
            "Point this at a folder every member's computer can reach — a "
            "Google Drive, OneDrive or Dropbox folder, or a network share — "
            "and the manager can see the whole team's work. Leave it as it is "
            "to keep everything on this computer only.")
        where.setWordWrap(True)
        s.content.addWidget(where)

        root_row = QHBoxLayout()
        root_row.setSpacing(9)
        self.workspace_edit = QLineEdit(self.cfg.get("workspace_root", ""))
        self.workspace_edit.setPlaceholderText(W.default_root())
        root_row.addWidget(self.workspace_edit, stretch=1)
        browse = QPushButton("Choose…")
        browse.setCursor(Qt.PointingHandCursor)
        browse.clicked.connect(self._pick_workspace)
        root_row.addWidget(browse)
        s.content.addLayout(root_row)

        # ── the roster, for admins only ───────────────────────────────────
        if me["admin"]:
            s.content.addWidget(kicker("Team members", muted=True))
            roster = meta(
                "Everyone you have a designation key for. Tell us the names "
                "and jobs and we issue one key each — add them here so their "
                "work is labelled with a name instead of a folder id.")
            roster.setWordWrap(True)
            s.content.addWidget(roster)
            self.team_layout = QVBoxLayout()
            self.team_layout.setContentsMargins(0, 0, 0, 0)
            self.team_layout.setSpacing(5)
            s.content.addLayout(self.team_layout)
            self._rebuild_team()

            add_row = QHBoxLayout()
            add_row.setSpacing(9)
            self.member_name = QLineEdit()
            self.member_name.setPlaceholderText("Name, e.g. Ravi Patel")
            add_row.addWidget(self.member_name, stretch=1)
            self.member_role = QComboBox()
            for role in R.ordered():
                self.member_role.addItem(role.label, role.key)
            add_row.addWidget(self.member_role)
            add_member = QPushButton("Add")
            add_member.setCursor(Qt.PointingHandCursor)
            add_member.clicked.connect(self._add_member)
            add_row.addWidget(add_member)
            s.content.addLayout(add_row)
        return s

    def _rebuild_team(self):
        while self.team_layout.count():
            item = self.team_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        members = W.load_team(self.cfg)
        if not members:
            self.team_layout.addWidget(meta("Nobody added yet."))
            return
        for member in members:
            role = R.get(member["role"])
            self.team_layout.addWidget(icon_label(
                role.icon if role else "user",
                f"{member['name'] or member['mid']} — "
                f"{role.label if role else member['role']}"))

    def _add_member(self):
        name = self.member_name.text().strip()
        role = self.member_role.currentData()
        if not name:
            QMessageBox.information(self, "Team", "Enter the person's name.")
            return
        # The member id is derived the same way the minting tool derives it,
        # so the roster entry and the key we issue agree on the folder name
        # without anyone having to copy an id between the two.
        W.upsert_member(self.cfg, W.member_id(role, name), name, role)
        self.member_name.clear()
        self._rebuild_team()

    def _pick_workspace(self):
        chosen = QFileDialog.getExistingDirectory(
            self, i18n.t("Choose the team workspace folder"),
            self.workspace_edit.text().strip() or W.default_root())
        if chosen:
            self.workspace_edit.setText(chosen)

    def _apply_designation(self):
        key = self.designation_edit.text().strip()
        if not key:
            QMessageBox.information(
                self, "Designation key",
                "Paste the designation key we sent you for this person.")
            return
        try:
            me = identity.activate(key)
        except licensing.TokenError as e:
            QMessageBox.warning(self, "Designation key", str(e))
            return
        W.ensure_member(me["mid"], self.cfg)
        QMessageBox.information(
            self, "Designation key",
            f"This copy is now set up for {me['name'] or 'this member'} — "
            f"{R.label(me['role'])}.\n\nRestart Prism to pick up the role's "
            f"colours and default tools.")
        self._notify_parent()

    def _clear_designation(self):
        if QMessageBox.question(
                self, "Remove role",
                "Turn this back into a personal copy?\n\nWork already saved "
                "in the team workspace stays where it is.",
                QMessageBox.Yes | QMessageBox.Cancel) != QMessageBox.Yes:
            return
        identity.clear()
        QMessageBox.information(self, "Removed",
                                "Restart Prism to finish switching back.")
        self._notify_parent()

    def _language_section(self) -> Section:
        """Two languages, because they are two different wishes.

        The first is Prism's own words — buttons, labels, dialogs. The second
        is what the AI tools write back, and it defaults to "leave it alone"
        on purpose: an agency in Vadodara may well want the app in Gujarati
        and the deliverable it produces for a client in English. Inferring one
        from the other would quietly translate work that is about to be sent
        to somebody else.
        """
        s = Section("Language",
                    "Prism's own text, and — separately — what language you "
                    "want the AI tools to answer in.")

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(9)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.lang_combo = QComboBox()
        # Only languages that actually have a pack, so the picker can never
        # offer a choice that comes out entirely in English anyway.
        for code, name, native in i18n.available():
            done, total = i18n.coverage(code)
            # The endonym leads: someone who needs Prism in Gujarati is
            # exactly the person least helped by the word "Gujarati" in
            # English. A pack that is not finished says so rather than
            # letting the gaps look like a bug.
            label = native if native == name else f"{native} — {name}"
            if code != "en" and total and done < total:
                label += f"  ({done * 100 // total}%)"
            self.lang_combo.addItem(label, code)
        self._select_code(self.lang_combo, self.cfg.get("language") or i18n.DEFAULT)
        form.addRow(icon_label("globe", "Prism's language"), self.lang_combo)

        self.out_lang_combo = QComboBox()
        # Every language here, not just the ones with a pack: asking Claude to
        # reply in Tamil needs no translation of Prism's own buttons.
        self.out_lang_combo.addItem("Same as I asked in", "")
        for code, (name, native, _rtl) in i18n.LANGUAGES.items():
            if code == i18n.DEFAULT:
                continue
            self.out_lang_combo.addItem(f"{native} — {name}", code)
        self.out_lang_combo.insertItem(1, "English", "en")
        self._select_code(self.out_lang_combo, self.cfg.get("output_language") or "")
        self.out_lang_combo.setToolTip(
            "Adds one line to every prompt asking the tool to answer in this "
            "language. Email addresses, links, file names and code are left "
            "alone.")
        form.addRow(icon_label("pencil", "AI writes back in"), self.out_lang_combo)
        s.content.addLayout(form)

        self.lang_note = QLabel()
        self.lang_note.setObjectName("meta")
        self.lang_note.setWordWrap(True)
        s.content.addWidget(self.lang_note)
        self.lang_combo.currentIndexChanged.connect(self._refresh_lang_note)
        self._refresh_lang_note()

        add = QLabel(
            "Another language, or a wording you'd rather have? Copy any file "
            "from Prism's lang folder into ~/.prism/lang/ and edit the right-"
            "hand side — Prism picks it up on the next start.")
        add.setObjectName("meta")
        add.setWordWrap(True)
        s.content.addWidget(add)
        return s

    @staticmethod
    def _select_code(combo: QComboBox, code: str):
        """Select by data, not by label — the labels are translated."""
        index = combo.findData(code)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _refresh_lang_note(self):
        """A language change only reaches widgets built after it, and the
        window is already built. Rather than half-translate a live window,
        say plainly that it lands next time."""
        code = self.lang_combo.currentData()
        if code == (self.cfg.get("language") or i18n.DEFAULT):
            self.lang_note.setText("")
            return
        self.lang_note.setText(
            "Save, then restart Prism — the new language applies to the whole "
            "window from the next start.")

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
                    "on the steps — skip any you don't want Prism to use.")
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

        # WHICH of the customer's Chrome profiles to copy. Everything below
        # used to assume one called "Default", and Chrome does not have to
        # have one: a machine with eleven profiles and eight signed-in
        # accounts had no "Default" at all, so nothing was ever copied and
        # every run opened a blank, logged-out browser.
        self.profile_combo = QComboBox()
        self.profile_combo.setCursor(Qt.PointingHandCursor)
        self._fill_profile_combo()
        s.content.addWidget(QLabel("Which Chrome profile to copy your logins from"))
        s.content.addWidget(self.profile_combo)

        # Prism drives its own Chrome profile so that logins survive between
        # runs. That also means a login done in the everyday browser doesn't
        # reach it — hence this.
        self.profile_note = QLabel()
        self.profile_note.setObjectName("meta")
        self.profile_note.setWordWrap(True)
        self._refresh_profile_note()
        s.content.addWidget(self.profile_note)
        reseed_btn = QPushButton("Copy my Chrome logins again")
        reseed_btn.setCursor(Qt.PointingHandCursor)
        reseed_btn.setToolTip(
            "Re-copies cookies from your everyday Chrome into Prism's profile. "
            "Use it after signing in to a tool in your normal browser. Close "
            "Chrome first so its newest cookies are on disk.")
        reseed_btn.clicked.connect(self._reseed_profile)
        s.content.addWidget(reseed_btn)
        return s

    def _fill_profile_combo(self):
        """Every real Chrome profile, named the way the customer knows them.

        The account address is what identifies a profile to a person — "Work",
        "Profile 20" and "Personal" all look the same in a list until you can
        see which Google account is signed into each.
        """
        self.profile_combo.clear()
        ok, _err = CB.automation_available()
        if not ok:
            self.profile_combo.addItem("Chrome automation unavailable", "")
            self.profile_combo.setEnabled(False)
            return
        automation = CB.get_automation()
        try:
            profiles = automation.chrome_profiles()
        except Exception:
            profiles = []
        if not profiles:
            self.profile_combo.addItem("No Chrome profile found", "")
            self.profile_combo.setEnabled(False)
            return
        # Blank = "whichever Chrome used last", which is right for the many
        # people who only have one.
        self.profile_combo.addItem(
            f"Use the one Chrome opened last "
            f"({automation.describe_profile(profiles[0])})", "")
        for profile in profiles:
            self.profile_combo.addItem(
                automation.describe_profile(profile), profile["dir"])
        saved = str(self.cfg.get("chrome_profile") or "").strip()
        if saved:
            index = self.profile_combo.findData(saved)
            if index < 0:
                # Chosen once, then removed from Chrome. Say so rather than
                # silently falling back to somebody else's account.
                self.profile_combo.addItem(f"{saved} (not in Chrome any more)",
                                           saved)
                index = self.profile_combo.count() - 1
            self.profile_combo.setCurrentIndex(index)

    def _refresh_profile_note(self):
        ok, err = CB.automation_available()
        if not ok:
            self.profile_note.setText(
                "Prism keeps its own Chrome profile so tool logins persist "
                "between runs.")
            return
        automation = CB.get_automation()
        if automation.profile_is_seeded():
            self.profile_note.setText(
                f"Prism's browser profile: {automation.PROFILE_DIR} — logins "
                "you make in the window Prism opens are kept for next time.")
        else:
            self.profile_note.setText(
                "Prism hasn't copied your Chrome logins yet — it will on the "
                "first run.")

    def _reseed_profile(self):
        ok, err = CB.automation_available()
        if not ok:
            QMessageBox.warning(self, "Chrome", f"Automation isn't available: {err}")
            return
        automation = CB.get_automation()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            automation.seed_profile(force=True)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Chrome", f"Couldn't copy the profile: {e}")
            return
        QApplication.restoreOverrideCursor()
        self._refresh_profile_note()
        QMessageBox.information(
            self, "Chrome",
            "Copied your Chrome logins into Prism's profile.\n\nIf a tool "
            "still asks you to sign in, sign in inside the window Prism "
            "opens (Login tabs in the sidebar) — that sticks.")

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
        automation.open_login_tabs(urls, cfg=self.cfg)
        QMessageBox.information(
            self, "Login tabs",
            i18n.t("Opened {n} tab(s) in Chrome — sign in, then close this "
                   "dialog.").format(n=len(urls)))

    def _save(self):
        key = self.key_edit.text().strip()
        if not key:
            QMessageBox.warning(self, "API key", "Enter your Groq API key — Prism can't route anything without one.")
            self._focus_section("key")
            return
        if not (key.startswith("gsk_") and len(key) > 20):
            QMessageBox.warning(self, "API key", "That doesn't look like a Groq key (should start with 'gsk_').")
            self._focus_section("key")
            return
        agents = self._current_agents()
        if not agents:
            QMessageBox.warning(self, "Specialists", "Pick at least one specialist.")
            self._focus_section("agents")
            return
        self.cfg["workspace_root"] = self.workspace_edit.text().strip()
        self.cfg["language"] = self.lang_combo.currentData() or i18n.DEFAULT
        self.cfg["output_language"] = self.out_lang_combo.currentData() or ""
        self.cfg["api_key"] = key
        self.cfg["profile"] = self.profile_edit.text().strip()
        self.cfg["agents"] = agents
        self.cfg["premium"] = [n for n, cb in self._premium_boxes.items() if cb.isChecked()]
        v = CB.automation_available()[0] and CB.get_automation().parse_chrome_version(self.chrome_edit.text())
        self.cfg["chrome_version"] = str(v) if v else ""
        # Which real Chrome profile to copy logins from. "" means "whichever
        # Chrome used last", which is what almost everybody wants and what a
        # single-profile machine needs. seed_profile() notices when this
        # changes and re-copies, so choosing a different account here takes
        # effect on the next run.
        chosen = getattr(self, "profile_combo", None)
        if chosen is not None and chosen.isEnabled():
            self.cfg["chrome_profile"] = chosen.currentData() or ""
        self.cfg["onboarded"] = True
        CB.config.save(self.cfg)
        self.accept()
