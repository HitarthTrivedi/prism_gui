"""
Leads & Outreach — the workbench widget
────────────────────────────────────────
The whole working surface as one embeddable QWidget, so it can be the full
in-window screen (addons/leads/panel.py) instead of living inside a modal. It
carries the search setup (foldable), the dense tabbed cockpit
(addons/leads/cockpit.py) and every action — prepare, verify, save, export,
send — with the heavy work off the UI thread (addons/leads/workers.py).

Who a list is for is set as lead FILTERS, Apollo / Sales Navigator style
(addons/leads/filter_panel.py): every facet includes and excludes, and an
exclusion is enforced on every person who comes back, not pasted into a query.
A set of filters can be saved and used again (addons/leads/saved_searches.py).

It PREPARES; a person presses Send, and only the value claims from the seller's
own file are ever made (prospector/reach.py). Sending goes one-per-person from
the owner's own account, through the same engine mailer the Email add-on uses.
"""
from __future__ import annotations

import csv
import datetime
import os
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout,
    QWidget,
)

import core_bridge as CB
import i18n
import theme
from widgets import controls as C
from prospector.filters import SearchSpec
from addons.leads import saved_searches
from addons.leads.filter_panel import FilterPanel, static_suggest
from addons.leads.workers import (LeadsExportWorker, LeadsQualifyWorker,
                                  LeadsSendWorker, LeadsSessionLoadWorker,
                                  LeadsVerifyWorker, ProspectorWorker,
                                  SourceWorker, outside_filters)
from addons.leads.cockpit import LeadsWorkspace

try:
    from prospector.run_poc import DEFAULT_OFFER
except Exception:                                       # noqa: BLE001
    DEFAULT_OFFER = "what your company sells"

# Pre-filled filters so a first "Find people" run is one click. Editable: each
# line becomes one include chip (job titles, industries).
_DEFAULT_INDUSTRIES = (
    "Automobile\nAuto Components\nTyre\nSteel Manufacturing\nDie Casting\n"
    "Aerospace & MRO\nDefense\nElectrical & Electronics\n"
    "Warehousing & Logistics\nMining")
_DEFAULT_ROLES = (
    "Head of Digital Transformation / Industry 4.0 / IIoT\n"
    "Automation Head / Smart Manufacturing\n"
    "Manufacturing Excellence / Operations / Production Head\n"
    "Business Excellence & Continuous Improvement\n"
    "Plant Head / Head of Manufacturing\n"
    "Supply Chain / Warehouse / Materials Head")


def _default_spec() -> SearchSpec:
    """A fresh search: the default job titles and industries, anywhere."""
    return SearchSpec.from_dict({
        "job_titles": {"include": _DEFAULT_ROLES.split("\n")},
        "industries": {"include": _DEFAULT_INDUSTRIES.split("\n")},
    })


def _suggest(facet: str, text: str) -> list:
    """The filter panel's typeahead. Places come from prospector.places (every
    country, region, state and city it knows) ahead of the starter list, which
    stays the fallback when that lookup is missing or fails; every other facet
    offers its starter list."""
    base = static_suggest(facet, text)
    if facet not in ("locations", "company_hq"):
        return base
    try:
        from prospector import places                  # lazy: a big table
        found = list(places.suggest(text, limit=8) or [])
    except Exception:                                   # noqa: BLE001
        return base
    # Beside the places lookup, the starter list only adds names a WORD of
    # which starts with the text — "ger" is Germany, not Nigeria.
    fold = " ".join((text or "").split()).casefold()
    base = [s for s in base if f" {fold}" in f" {s.casefold()}"]
    out, seen = [], set()
    for value in found + base:
        if isinstance(value, str) and value.strip() and value.casefold() not in seen:
            seen.add(value.casefold())
            out.append(value)
    return out


def _when(iso: str) -> str:
    """A session timestamp as a person reads it: "11 Sep, 14:02"."""
    try:
        return datetime.datetime.fromisoformat(iso).strftime("%d %b, %H:%M")
    except (TypeError, ValueError):
        return iso or ""


def _kick(text: str) -> QLabel:
    """A rail section heading — the same voice as the cockpit's REFINE RESULTS."""
    lab = QLabel(text.upper())
    lab.setStyleSheet(
        f"color:{theme.NEUTRAL[600]};font-family:'{theme.FONT_HEADING}';"
        f"font-size:11px;letter-spacing:1px;font-weight:600;background:transparent;")
    return lab


def _field(text: str) -> QLabel:
    """A field label above an input in the rail."""
    lab = QLabel(text)
    lab.setStyleSheet(f"color:{theme.NEUTRAL[700]};font-size:12px;font-weight:600;"
                      f"background:transparent;")
    return lab


def _setting(text: str, spin: QSpinBox) -> QWidget:
    """One run setting as a row — its name, and a compact spin box on the right —
    the way the refine rail's "Minimum fit" reads, so a narrow rail never has to
    split two spin boxes into slivers."""
    row = QWidget()
    h = QHBoxLayout(row)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(theme.SPACE_2)
    lab = QLabel(text)
    lab.setStyleSheet(f"color:{theme.NEUTRAL[800]};font-size:13px;font-weight:500;"
                      f"background:transparent;")
    h.addWidget(lab, 1)
    spin.setFixedWidth(104)
    h.addWidget(spin)
    return row


class _Line(QLabel):
    """A status / summary line that takes no vertical space until it has
    something to say — so an empty run leaves no grey band above the cockpit."""

    def __init__(self, level: str = "SUPPORT", on_change=None, ink: str = "",
                 weight: int = 0):
        super().__init__("")
        family, px, css_weight, default_ink = theme.TYPE.get(level, theme.T_BODY)
        self.setStyleSheet(
            f"font-family:'{family}';font-size:{px}px;"
            f"font-weight:{weight or css_weight};color:{ink or default_ink};"
            f"background:transparent;border:none;")
        self.setWordWrap(True)
        self.setVisible(False)
        self._on_change = on_change

    def setText(self, text: str):
        super().setText(text or "")
        self.setVisible(bool((text or "").strip()))
        if self._on_change is not None:
            self._on_change()


class LeadsWorkbench(QWidget):
    """The full Leads & Outreach surface as one widget — setup, cockpit and all
    the actions. Host it in a panel (full-window) or a dialog; it behaves the
    same, and needs only a cfg dict."""

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg or {}
        self._mode = "sheet"
        self._path = ""
        self._claims_path = ""
        self._drafts = []
        self._draft_by = {}
        self._res = None
        self._worker = None
        self._send_worker = None
        self._export_worker = None
        self._verify_worker = None
        self._qualify_worker = None
        self._announce_export = False
        self._opened_autosave = False
        # How many background jobs (prepare / verify / send / export) are running.
        # A count, not a flag: an export finishing must not re-enable Send while a
        # send started from the bulk bar is still going — two sends would mail the
        # same prospect twice.
        self._jobs = 0
        # The session on screen. Every finished run becomes one (sessions.py);
        # "" until then. _next_* hold the inputs of the run in flight.
        self._session_id = ""
        self._session_mode = "sheet"
        self._run_params: dict = {}
        self._next_mode, self._next_params = "sheet", {}
        self._load_worker = None
        self._restoring = ""
        # The saved search on the rail ("Use search" or "Save search"), and its
        # filters as saved: a finished run is recorded on it only while the
        # filters still say what it saved.
        self._active_search_id = ""
        self._active_search_filters = None

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(theme.SPACE_5, theme.SPACE_4,
                                      theme.SPACE_5, theme.SPACE_5)
        self._root.setSpacing(theme.SPACE_3)
        self._build_actions()
        self._build_inputs()
        self._build_results()
        self._set_mode("icp")

    # ── batch actions (placed by the host) ────────────────────────────────────
    def _build_actions(self):
        """Export sheets and Send all act on the whole run, so they belong in the
        host's chrome — the page header, or a dialog footer — not in this layout.
        They are built here (their handlers and enabled state live here) and the
        host places them via action_buttons()."""
        self._export_btn = C.button(i18n.t("Export sheets"), "secondary",
                                    icon_name="file", on_click=self._export)
        self._export_btn.setEnabled(False)
        self._send_btn = C.button(i18n.t("Send all"), "primary",
                                  icon_name="mail", on_click=self._on_send)
        self._send_btn.setEnabled(False)

    def action_buttons(self) -> list:
        return [self._export_btn, self._send_btn]

    # ── the search, mounted at the top of the cockpit's left rail ─────────────
    def _build_inputs(self):
        """The list-building search, laid out for the Leads rail — a narrow,
        scrolling column — instead of a full-width form stacked over the results,
        which is what crushed every control on a short window."""
        self._setup_panel = QWidget()
        col = QVBoxLayout(self._setup_panel)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_3)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(theme.SPACE_2)
        head.addWidget(_kick(i18n.t("Build a list")), 1)
        self._setup_toggle = C.button(i18n.t("New search"), "secondary",
                                      small=True, on_click=self._toggle_setup)
        self._setup_toggle.setVisible(False)          # nothing to fold to yet
        head.addWidget(self._setup_toggle)
        col.addLayout(head)
        self._setup_summary = C.label("", level="SUPPORT", wrap=True)
        col.addWidget(self._setup_summary)
        self._setup_summary.setVisible(False)

        # Everything below folds away once a list is on screen.
        self._setup_details = QWidget()
        body = QVBoxLayout(self._setup_details)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(theme.SPACE_3)

        # Two ways in — a segmented switch that shows which one is on: find
        # people with the lead filters (Exa people-search → checked against
        # every filter → real-domain e-mails → qualify → draft), or a sheet
        # you already have.
        seg = QFrame()
        seg.setObjectName("modeSeg")
        seg.setAttribute(Qt.WA_StyledBackground, True)
        seg.setStyleSheet(
            f"QFrame#modeSeg{{background:{theme.WELL};border:1px solid {theme.HAIRLINE};"
            f"border-radius:{theme.R_CONTROL}px;}}"
            f"QFrame#modeSeg QPushButton{{background:transparent;border:none;"
            f"color:{theme.NEUTRAL[600]};padding:5px 8px;min-height:22px;"
            f"font-size:13px;font-weight:600;border-radius:{theme.R_CHIP}px;}}"
            f"QFrame#modeSeg QPushButton:checked{{background:{theme.CARD};"
            f"color:{theme.TEXT};}}"
            f"QFrame#modeSeg QPushButton:disabled{{color:{theme.NEUTRAL[400]};}}")
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(3, 3, 3, 3)
        sl.setSpacing(2)
        self._mode_icp = QPushButton(i18n.t("Find people"))
        self._mode_sheet = QPushButton(i18n.t("Import a sheet"))
        for b, mode in ((self._mode_icp, "icp"), (self._mode_sheet, "sheet")):
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, m=mode: self._set_mode(m))
            sl.addWidget(b, 1)
        body.addWidget(seg)

        # -- sheet mode --------------------------------------------------------
        self._sheet_box = QWidget()
        sb = QVBoxLayout(self._sheet_box)
        sb.setContentsMargins(0, 0, 0, 0)
        sb.setSpacing(theme.SPACE_1)
        self._pick = C.button(i18n.t("Choose a sheet…"), "secondary",
                              icon_name="paperclip", on_click=self._choose_file)
        sb.addWidget(self._pick)
        self._file_lbl = C.label(i18n.t("An Excel or CSV export of your leads"),
                                 level="META", wrap=True)
        sb.addWidget(self._file_lbl)
        body.addWidget(self._sheet_box)

        # -- find people: the lead filters --------------------------------------
        self._icp_box = QWidget()
        ib = QVBoxLayout(self._icp_box)
        ib.setContentsMargins(0, theme.SPACE_1, 0, 0)
        ib.setSpacing(0)
        self._filters = FilterPanel(suggest=_suggest)
        self._filters.set_spec(_default_spec())
        self._filters.changed.connect(self._refresh_prepare)
        self._filters.saveRequested.connect(self._save_search)
        ib.addWidget(self._filters)
        body.addWidget(self._icp_box)

        # -- run settings (both modes) -----------------------------------------
        body.addSpacing(theme.SPACE_2)
        body.addWidget(_kick(i18n.t("Run settings")))
        rows = QVBoxLayout()
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(theme.SPACE_2)
        self._target = QSpinBox()
        self._target.setRange(20, 2000)
        self._target.setValue(300)
        self._target.setToolTip(i18n.t(
            "How many people to find before qualifying. Everyone outside your "
            "filters is left out and does not count."))
        self._target_row = _setting(i18n.t("Source up to"), self._target)
        rows.addWidget(self._target_row)
        self._limit = QSpinBox()
        self._limit.setRange(1, 500)
        self._limit.setValue(25)
        self._limit.setToolTip(i18n.t("How many leads to qualify this run."))
        rows.addWidget(_setting(i18n.t("Qualify"), self._limit))
        self._verify_limit = QSpinBox()
        self._verify_limit.setRange(0, 200)
        self._verify_limit.setValue(25)
        self._verify_limit.setToolTip(i18n.t(
            "How many hot/warm addresses to check with Hunter. Its free tier is "
            "~50 credits a month, so keep this modest — 0 skips verification."))
        rows.addWidget(_setting(i18n.t("Verify (Hunter)"), self._verify_limit))
        body.addLayout(rows)

        offer = QVBoxLayout()
        offer.setContentsMargins(0, theme.SPACE_1, 0, 0)
        offer.setSpacing(theme.SPACE_1)
        offer.addWidget(_field(i18n.t("What you sell")))
        self._offer = QPlainTextEdit()
        self._offer.setPlainText(DEFAULT_OFFER)
        self._offer.setFixedHeight(72)
        self._offer.setToolTip(i18n.t("Every lead is qualified against this."))
        offer.addWidget(self._offer)
        body.addLayout(offer)

        # Net new only: anyone an earlier session already pulled is skipped,
        # unless this is turned off to re-work an old list on purpose.
        net = QVBoxLayout()
        net.setContentsMargins(0, 0, 0, 0)
        net.setSpacing(0)
        self._skip_seen = QCheckBox(i18n.t("Net new only"))
        self._skip_seen.setChecked(True)
        self._skip_seen.setStyleSheet(
            f"QCheckBox{{border:none;background:transparent;color:{theme.NEUTRAL[800]};"
            f"font-size:13px;font-weight:600;}}")
        self._skip_seen.setToolTip(i18n.t(
            "People are matched by e-mail, LinkedIn link, or name and company. "
            "A search keeps looking until it has the number you asked for in "
            "new people."))
        net.addWidget(self._skip_seen)
        self._skip_meta = C.label(i18n.t("Skip anyone pulled in an earlier session"),
                                  level="META", wrap=True)
        # Under the checkbox's text, not its box: the indicator and its gap.
        self._skip_meta.setContentsMargins(26, 0, 0, 0)
        net.addWidget(self._skip_meta)
        body.addLayout(net)

        body.addSpacing(theme.SPACE_1)
        self._prepare = C.button(i18n.t("Prepare outreach"), "primary",
                                 icon_name="play", on_click=self._on_prepare)
        body.addWidget(self._prepare)
        self._leads_only = C.button(
            i18n.t("Leads sheet only (no Groq)"), "tertiary", icon_name="file",
            on_click=lambda: self._on_prepare(leads_only=True))
        self._leads_only.setToolTip(i18n.t(
            "Source and enrich a leads sheet only — no qualification, no emails, "
            "no Groq. Uses Exa alone, so a rate-limited Groq key can't block it."))
        body.addWidget(self._leads_only)

        # Keys & claims are set once — folded away unless the Exa key is missing.
        # "&&": a lone & in a button label is eaten as a keyboard mnemonic.
        self._keys_toggle = C.button(i18n.t("Keys & claims").replace("&", "&&"), "link",
                                     icon_name="key", on_click=self._toggle_keys)
        body.addWidget(self._keys_toggle)
        self._keys_box = QWidget()
        kb = QVBoxLayout(self._keys_box)
        kb.setContentsMargins(0, 0, 0, 0)
        kb.setSpacing(theme.SPACE_1)
        kb.addWidget(_field(i18n.t("Exa API key · finds people and why-now signals")))
        self._exa = QLineEdit()
        self._exa.setText(self.cfg.get("exa_api_key") or "")
        self._exa.setEchoMode(QLineEdit.PasswordEchoOnEdit)   # never on screen at rest
        self._exa.setPlaceholderText(i18n.t("Needed to find people — saved once"))
        kb.addWidget(self._exa)
        kb.addSpacing(theme.SPACE_2)
        self._claims = C.button(i18n.t("Approved claims file…"), "secondary",
                                icon_name="file", on_click=self._choose_claims)
        kb.addWidget(self._claims)
        self._claims_lbl = C.label(
            i18n.t("Optional — with none, the emails make no numeric claim."),
            level="META", wrap=True)
        kb.addWidget(self._claims_lbl)
        kb.addWidget(C.label(i18n.t(
            "Verifier keys (Reoon, ZeroBounce, Hunter…) come from Settings > "
            "Agents — free tiers first, so most checks cost nothing."),
            level="META", wrap=True))
        body.addWidget(self._keys_box)
        self._keys_box.setVisible(not (self.cfg.get("exa_api_key") or "").strip())

        col.addWidget(self._setup_details)

    def _set_mode(self, mode: str):
        self._mode = mode
        self._mode_sheet.setChecked(mode == "sheet")
        self._mode_icp.setChecked(mode == "icp")
        self._sheet_box.setVisible(mode == "sheet")
        self._icp_box.setVisible(mode == "icp")
        self._target_row.setVisible(mode == "icp")   # a sheet brings its own people
        self._leads_only.setVisible(mode == "icp")   # search-only cheap deliverable
        self._refresh_prepare()

    # ── fold the setup away once a list is on screen ─────────────────────────
    def _toggle_setup(self):
        self._fold_setup(not self._setup_details.isVisible())

    def _fold_setup(self, open_: bool):
        """Open the setup, or fold it to a one-line summary so the dense cockpit
        fills the window. The toggle shows only once there's a run to return to."""
        self._setup_details.setVisible(open_)
        self._setup_toggle.setVisible(True)
        self._setup_toggle.setText(i18n.t("Done") if open_
                                   else i18n.t("New search"))
        self._setup_summary.setText("" if open_ else self._setup_line())
        self._setup_summary.setVisible(not open_)

    def _toggle_keys(self):
        self._keys_box.setVisible(self._keys_box.isHidden())

    def _sync_notice(self):
        notice, summary = getattr(self, "_notice", None), getattr(self, "_summary", None)
        if notice is not None and summary is not None:
            notice.setVisible(not (self._status.isHidden() and summary.isHidden()))

    def _setup_line(self) -> str:
        """The current setup in a few words, for the folded header."""
        if self._mode == "icp":
            return i18n.t("Find people · {filters} · qualify {q}").format(
                filters=self._filters.spec().summary(), q=self._limit.value())
        name = os.path.basename(self._path) if self._path else i18n.t("No sheet chosen")
        return i18n.t("{name} · qualify {q} · verify {v}").format(
            name=name, q=self._limit.value(), v=self._verify_limit.value())

    def _refresh_prepare(self):
        if self._mode == "icp":
            # A search needs someone to look for — a title, a function or a
            # seniority; every other filter is optional.
            ok = self._filters.spec().is_searchable()
        else:
            ok = bool(self._path)
        self._prepare.setEnabled(ok)
        self._leads_only.setEnabled(ok and self._mode == "icp")

    # ── the tabbed cockpit ────────────────────────────────────────────────────
    def _build_results(self):
        # One slim notice line over the workspace: live progress on the left
        # ("Qualifying 3 of 25…"), the run summary on the right (hot/warm/cold,
        # drafted, why-now coverage). Takes no space until it has something.
        self._notice = QFrame()
        self._notice.setObjectName("leadsNotice")
        self._notice.setAttribute(Qt.WA_StyledBackground, True)
        self._notice.setStyleSheet(
            f"QFrame#leadsNotice{{background:{theme.CARD};border:1px solid "
            f"{theme.HAIRLINE};border-radius:{theme.R_CONTROL}px;}}")
        nl = QHBoxLayout(self._notice)
        nl.setContentsMargins(theme.SPACE_4, theme.SPACE_2, theme.SPACE_4, theme.SPACE_2)
        nl.setSpacing(theme.SPACE_4)
        self._status = _Line("SUPPORT", on_change=self._sync_notice,
                             ink=theme.TEXT, weight=600)
        self._summary = _Line("SUPPORT", on_change=self._sync_notice)
        self._summary.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        nl.addWidget(self._status, 1)
        nl.addWidget(self._summary, 1)
        self._notice.setVisible(False)
        self._root.addWidget(self._notice)
        # The workspace: Leads · Lists · Saved searches · Sequences · Analytics.
        # The search is mounted in the Leads tab's left rail (above the refine
        # filters), so it scrolls with the rail instead of stacking above the
        # results and crushing them on a short window.
        self._cockpit = LeadsWorkspace(leads_folder=self._autosave_dir(),
                                       sessions_folder=self._sessions_dir(),
                                       searches_folder=self._searches_dir())
        self._cockpit.openSessionRequested.connect(self.open_session)
        self._cockpit.useSavedSearchRequested.connect(self.use_saved_search)
        self._cockpit.deleteSavedSearchRequested.connect(self._delete_saved_search)
        self._cockpit.verifyRequested.connect(self._verify_selected)
        self._cockpit.saveListRequested.connect(self._save_list)
        self._cockpit.exportRequested.connect(self._export_selected)
        self._cockpit.sequenceRequested.connect(self._add_to_sequence)
        self._cockpit.qualifyRequested.connect(self._qualify_selected)
        self._cockpit.set_search_panel(self._setup_panel)
        frame = QFrame()
        frame.setObjectName("leadsFrame")
        frame.setAttribute(Qt.WA_StyledBackground, True)
        frame.setStyleSheet(f"QFrame#leadsFrame{{background:{theme.CARD};"
                            f"border:1px solid {theme.HAIRLINE};}}")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(1, 1, 1, 1)
        fl.setSpacing(0)
        fl.addWidget(self._cockpit)
        self._root.addWidget(frame, stretch=1)

    def refresh_lists(self) -> None:
        """Re-scan the saved-lists folder — the panel calls this when the screen
        is shown again, so a list saved elsewhere appears."""
        if getattr(self, "_cockpit", None) is not None:
            self._cockpit.refresh_lists()

    # ── file pickers ─────────────────────────────────────────────────────────
    def _choose_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.t("Choose a leads sheet"), "",
            "Leads (*.xlsx *.xlsm *.csv)")
        if not path:
            return
        self._path = path
        self._file_lbl.setText(os.path.basename(path))
        self._refresh_prepare()

    def _choose_claims(self):
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.t("Approved value claims — one per line"), "",
            "Text (*.txt *.md);;All files (*.*)")
        if not path:
            return
        self._claims_path = path
        self._claims_lbl.setText(os.path.basename(path))

    # ── prepare ──────────────────────────────────────────────────────────────
    def _on_prepare(self, leads_only: bool = False):
        if self._jobs:
            return
        from prospector import reach
        # Persist the Exa key once, to config, so every run after picks it up.
        # Read the config FRESH and change only that key: self.cfg can predate an
        # account or key saved elsewhere, and saving it whole would wipe them.
        exa = self._exa.text().strip()
        if exa != (self.cfg.get("exa_api_key") or ""):
            try:
                fresh = CB.config.load()
                fresh["exa_api_key"] = exa
                CB.config.save(fresh)
            except Exception:                               # noqa: BLE001
                pass
        self.cfg["exa_api_key"] = exa
        claims = reach.load_claims(self._claims_path)
        offer = self._offer.toPlainText().strip() or DEFAULT_OFFER
        include_earlier = not self._skip_seen.isChecked()
        spec = self._filters.spec()
        if self._mode == "icp" and not spec.is_searchable():
            return
        if self._mode != "icp" and not self._path:
            return
        legacy = spec.legacy_params()
        # What this run was asked — saved with its session (no keys, no cfg).
        # The filters travel as their dict; the legacy industries / roles /
        # location beside them keep a session label and an older build reading.
        self._next_mode = (("icp_leads_only" if leads_only else "icp")
                           if self._mode == "icp" else "sheet")
        self._next_params = {
            "mode": self._next_mode, "sheet_path": self._path,
            **legacy, "filters": spec.to_dict(),
            "target": self._target.value(), "offer": offer,
            "limit": self._limit.value(), "verify_limit": self._verify_limit.value(),
            "claims_path": self._claims_path, "include_earlier": include_earlier,
        }
        if self._mode == "icp":
            self._set_running(True)
            self._status.setText(i18n.t("Finding people (no Groq)…")
                                 if leads_only else i18n.t("Finding people…"))
            self._worker = SourceWorker(
                legacy["industries"], legacy["roles"], offer, self.cfg,
                location=legacy["location"],
                target=self._target.value(), limit=self._limit.value(),
                verify_limit=self._verify_limit.value(),
                sender=self._sender(), claims=claims,
                exclude_domains=self._seller_domains(), leads_only=leads_only,
                sessions_dir=self._sessions_dir(), include_earlier=include_earlier,
                spec=spec.to_dict())
        else:
            self._set_running(True)
            self._status.setText(i18n.t("Reading the sheet…"))
            self._worker = ProspectorWorker(
                self._path, offer, self.cfg, limit=self._limit.value(),
                verify_limit=self._verify_limit.value(),
                sender=self._sender(), claims=claims,
                exclude_domains=self._seller_domains(),
                sessions_dir=self._sessions_dir(), include_earlier=include_earlier)
        self._worker.progress.connect(self._status.setText)
        self._worker.done.connect(self._on_prepared)
        self._worker.failed.connect(self._on_failed)
        self._job_started()
        self._worker.start()

    def _seller_domains(self) -> list:
        """The seller's own site(s), pulled from the offer text and the claims
        file, so the why-now search never cites the seller's own pages."""
        text = self._offer.toPlainText()
        if self._claims_path:
            try:
                with open(self._claims_path, encoding="utf-8") as f:
                    text += " " + f.read()
            except Exception:                               # noqa: BLE001
                pass
        return sorted(set(re.findall(
            r"\b([a-z0-9][a-z0-9-]*\.(?:com|in|io|ai|co|net|org))\b",
            text.lower())))

    def _on_prepared(self, res, drafts):
        idle = self._job_done()
        # A finished run is a new session: kept on disk, reopenable, and the
        # people it pulled are skipped by the next run.
        try:
            from addons.leads import sessions
            self._session_id = sessions.new_id()
        except Exception:                                   # noqa: BLE001
            self._session_id = ""
        self._session_mode = self._next_mode
        self._run_params = dict(self._next_params)
        self._show_result(res, drafts)
        if idle:
            self._set_running(False)
        self._save_session()
        self._record_search_run(res)
        # The sheets ARE the deliverable — write them automatically to a known
        # folder the moment a run finishes (leads-only included, which needed no
        # Groq at all), so a run always produces a file instead of hiding it
        # behind a button the user must find.
        if res.dossiers or getattr(res, "all_leads", None):
            self._start_export(self._autosave_dir(), announce=False)

    def _show_result(self, res, drafts):
        """Put a run on screen — shared by a finished run and an opened session
        (which must NOT re-export or re-save)."""
        self._res = res
        self._drafts = list(drafts or [])
        self._draft_by = {id(d.dossier): d for d in self._drafts}
        leads_only = not res.dossiers and bool(getattr(res, "all_leads", None))
        if leads_only:
            # There ARE leads — just none qualified — so don't say "No leads yet".
            self._cockpit.set_empty_text(
                i18n.t("{n} leads sourced — not qualified").format(
                    n=len(res.all_leads)),
                i18n.t("Their sheet is saved — open it under Lists. To qualify and "
                       "draft, press New search, then Prepare outreach."))
        else:
            self._cockpit.set_empty_text()
        self._cockpit.set_dossiers(res.dossiers, self._drafts,
                                   getattr(res, "all_leads", None))
        # The setup has done its job — fold it so the dense cockpit fills the
        # screen. "New search" brings it back.
        self._fold_setup(False)
        skipped = getattr(res, "skipped_seen", 0) or 0
        if leads_only:
            text = i18n.t("Sourced {n} new leads · enriched · sheet saved "
                          "(no Groq used).").format(n=len(res.all_leads))
            if skipped:
                text += "   ·   " + i18n.t("{n} already pulled, skipped").format(n=skipped)
            outside = self._outside_bit(res)
            if outside:
                text += "   ·   " + outside
            self._summary.setText(text)
        else:
            self._summary.setText(self._run_summary(res, self._drafts))
            self._status.setText(i18n.t(
                "{n} ready to send — every lead below shows its outcome."
            ).format(n=len(self._pending(self._drafts))))
        self._export_btn.setEnabled(bool(res.dossiers or getattr(res, "all_leads", None)))
        self._send_btn.setEnabled(bool(self._pending(self._drafts)))

    def _on_failed(self, msg):
        if self._job_done():
            self._set_running(False)
        self._save_session()                # a failed send can leave drafts half-sent
        self._status.setText("")
        QMessageBox.warning(self, i18n.t("Leads & Outreach"),
                            i18n.t("Something went wrong:\n\n{msg}").format(msg=msg))

    # ── bulk-bar actions on the checked leads ─────────────────────────────────
    def _verify_selected(self, dossiers):
        """Re-verify the checked leads' e-mails with the FREE verifier waterfall
        (no paid finder), off-thread, then re-render with the fresh statuses."""
        if not dossiers or self._jobs:
            return
        from prospector import verify
        if not verify.collect_keys(self.cfg):
            QMessageBox.information(
                self, i18n.t("Verify e-mails"),
                i18n.t("Add a verifier key in Settings > Agents (Reoon, "
                       "Verifalia, ZeroBounce, AbstractAPI or Kickbox) and "
                       "Prism can confirm addresses for free."))
            return
        self._set_running(True)
        self._status.setText(i18n.t("Verifying {n} selected…").format(n=len(dossiers)))
        self._verify_worker = LeadsVerifyWorker(dossiers, self.cfg)
        self._verify_worker.progress.connect(lambda i, n, l: self._status.setText(
            i18n.t("Verifying {i} of {n}: {who}").format(i=i, n=n, who=l.display())))
        self._verify_worker.done.connect(self._on_verified)
        self._verify_worker.failed.connect(self._on_failed)
        self._job_started()
        self._verify_worker.start()

    def _on_verified(self):
        if self._job_done():
            self._set_running(False)
        if self._res is not None:
            self._cockpit.set_dossiers(self._res.dossiers, self._drafts,
                                           getattr(self._res, "all_leads", None))
        self._save_session()                # verify changed each lead's e-mail status
        self._status.setText(i18n.t("Verification done — statuses updated."))

    def _qualify_selected(self, dossiers):
        """Qualify & draft the checked people the run sourced but never
        qualified — a leads-sheet-only run's whole list, or everyone past a full
        run's Qualify count — right here, instead of re-importing a sheet."""
        if not dossiers or self._jobs or self._res is None:
            return
        from addons.leads.cockpit import RETRYABLE
        # Never qualified, or a pass that failed (no key, a Groq error) — a lead
        # already qualified is left as it is.
        leads = [d.lead for d in dossiers if getattr(d, "status", "") in RETRYABLE]
        if not leads:
            self._status.setText(i18n.t("Those leads are already qualified."))
            return
        # Without a Groq key every lead would come back "no model" after its
        # why-now search was already paid for — say so before spending anything.
        if not (self.cfg.get("api_key") or "").strip():
            self._status.setText(i18n.t(
                "Qualifying needs your Groq key — add it in Settings, then try again."))
            return
        if not self._confirm_qualify(len(leads)):
            return
        from prospector import reach
        offer = self._offer.toPlainText().strip() or DEFAULT_OFFER
        # Score with the roles the run itself ranked by: a sheet run used none.
        roles = ([] if self._session_mode == "sheet"
                 else SearchSpec.from_params(self._run_params).role_terms())
        self._set_running(True)
        self._status.setText(i18n.t("Qualifying {n} selected…").format(n=len(leads)))
        self._qualify_worker = LeadsQualifyWorker(
            leads, offer, self.cfg, roles=roles,
            verify_limit=self._verify_limit.value(), sender=self._sender(),
            claims=reach.load_claims(self._claims_path),
            exclude_domains=self._seller_domains())
        self._qualify_worker.progress.connect(self._status.setText)
        self._qualify_worker.done.connect(self._on_qualified)
        self._qualify_worker.failed.connect(self._on_failed)
        self._job_started()
        self._qualify_worker.start()

    def _confirm_qualify(self, n: int) -> bool:
        """Each lead costs a why-now search and a Groq call, and a free Groq key
        paces them — so a batch past ten asks first. Tests patch this."""
        if n <= 10:
            return True
        answer = QMessageBox.question(
            self, i18n.t("Qualify & draft"),
            i18n.t("Qualify and draft {n} leads now? Prism researches each one and "
                   "makes a Groq call per lead, so on a free Groq key this can "
                   "take several minutes.").format(n=n))
        return answer == QMessageBox.StandardButton.Yes

    def _on_qualified(self, res, drafts):
        """Fold the newly qualified people into the run on screen: their rows
        turn into real outcomes, their drafts join Send, and the session is
        saved with them.

        Only a pass that WORKED counts. A lead that came back "no model" or
        "qualify error" (no Groq key, a rate limit) is not stored as qualified —
        it keeps a row the button can retry — and a retry that works replaces
        the lead's earlier failed dossier, so nobody is listed twice."""
        from prospector.models import OK
        idle = self._job_done()
        came_back = list(res.dossiers or [])
        good = [d for d in came_back if getattr(d, "status", OK) == OK]
        failed = [d for d in came_back if getattr(d, "status", OK) != OK]
        good_ids = {id(d) for d in good}
        new_drafts = [dr for dr in (drafts or []) if id(dr.dossier) in good_ids]
        if self._res is not None:
            redone = {id(d.lead) for d in good}
            replaced = {id(d) for d in (self._res.dossiers or []) if id(d.lead) in redone}
            self._res.dossiers = [d for d in (self._res.dossiers or [])
                                  if id(d) not in replaced] + good
            kept = [dr for dr in self._drafts if id(dr.dossier) not in replaced]
            # A sheet-only run that now holds qualified leads is a full run.
            if good and self._session_mode == "icp_leads_only":
                self._session_mode = "icp"
                self._run_params = dict(self._run_params, mode="icp")
            self._show_result(self._res, kept + new_drafts)
            self._save_session()
        if idle:
            self._set_running(False)
        text = i18n.t("Qualified {n} — {d} drafted, {r} ready to send.").format(
            n=len(good), d=len(new_drafts), r=len(self._pending(self._drafts)))
        if failed:
            why = (failed[0].note or "").strip() or i18n.t("the qualify pass failed")
            text += "  " + i18n.t(
                "{n} couldn't be qualified ({why}) — tick them and try again.").format(
                    n=len(failed), why=why.rstrip("."))
        self._status.setText(text)

    def _save_list(self, dossiers):
        """Write the checked leads to a named CSV in the Prism Leads folder — a
        reusable list, saved where every run's sheets already land."""
        if not dossiers:
            return
        name, ok = QInputDialog.getText(
            self, i18n.t("Save to list"), i18n.t("Name this list:"),
            text=i18n.t("My shortlist"))
        if not ok or not name.strip():
            return
        safe = re.sub(r"[^\w .-]+", "", name.strip()) or "list"
        path = os.path.join(self._autosave_dir(), f"{safe}.csv")
        try:
            n = self._write_leads_csv(dossiers, path)
        except OSError as e:
            QMessageBox.warning(self, i18n.t("Save to list"), i18n.t(
                "Couldn't write {path}: {err}. If it is open in Excel, close it "
                "and try again.").format(path=path, err=e))
            return
        self._cockpit.refresh_lists()      # show it on the Lists tab at once
        QMessageBox.information(
            self, i18n.t("Save to list"),
            i18n.t("Saved {n} lead(s) to:\n{path}").format(n=n, path=path))

    def _export_selected(self, dossiers):
        """The cockpit's Export — the checked leads to a CSV wherever the user
        chooses. (The 'Export sheets' action still writes the full deliverable.)"""
        if not dossiers:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, i18n.t("Export selected leads"),
            os.path.join(self._autosave_dir(), "selected leads.csv"),
            "CSV (*.csv)")
        if not path:
            return
        try:
            n = self._write_leads_csv(dossiers, path)
        except OSError as e:
            QMessageBox.warning(self, i18n.t("Export"), i18n.t(
                "Couldn't write {path}: {err}. If it is open in Excel, close it "
                "and try again.").format(path=path, err=e))
            return
        QMessageBox.information(
            self, i18n.t("Export"),
            i18n.t("Exported {n} lead(s) to:\n{path}").format(n=n, path=path))

    def _write_leads_csv(self, dossiers, path) -> int:
        from addons.leads.cockpit import status_of
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["name", "company", "title", "email", "fit", "status",
                        "verdict"])
            for d in dossiers:
                lead = d.lead
                w.writerow([lead.name, lead.company, lead.title, lead.email,
                            f"{getattr(lead, 'fit_score', 0) or 0:g}",
                            status_of(d, self._draft_by.get(id(d))), d.verdict])
        return len(dossiers)

    def _add_to_sequence(self, dossiers):
        """Enrol the checked leads. For now this sends the first touch (the
        reviewed draft) now; automatic follow-ups arrive with the Phase-2
        stop-on-reply engine. Only leads that were drafted can be enrolled."""
        if not dossiers or self._jobs:
            return
        drafts = [self._draft_by[id(d)] for d in dossiers if id(d) in self._draft_by]
        if not drafts:
            QMessageBox.information(
                self, i18n.t("Add to sequence"),
                i18n.t("None of the selected leads has a drafted email yet — "
                       "qualify and draft them first (they must be hot/warm)."))
            return
        # Never resend: the suppression floor would mark a mailed lead 'skipped'
        # and it would stop reading as Mailed.
        drafts = self._pending(drafts)
        if not drafts:
            QMessageBox.information(self, i18n.t("Add to sequence"),
                                    i18n.t("Those leads were already mailed."))
            return
        if not CB.mailer.is_configured(self.cfg):
            self._need_account()
            return
        addr = (self.cfg.get("email") or {}).get("address", "")
        confirm = QMessageBox.question(
            self, i18n.t("Add to sequence"),
            i18n.t("Send the first touch to {n} selected lead(s) now, from "
                   "{addr}?\n\nAutomatic follow-ups arrive with the sequence "
                   "engine — for now this sends touch 1.").format(
                       n=len(drafts), addr=addr))
        if confirm == QMessageBox.StandardButton.Yes:
            self._run_send(drafts)

    def _run_summary(self, res, drafts) -> str:
        dos = res.dossiers
        c = lambda p: sum(1 for d in dos if p(d))
        bits = [i18n.t("Sourced {n}").format(n=res.total_in_sheet),
                i18n.t("qualified {n}").format(n=len(dos)),
                i18n.t("{h} hot / {w} warm / {c} cold").format(
                    h=c(lambda d: d.verdict == "hot"),
                    w=c(lambda d: d.verdict == "warm"),
                    c=c(lambda d: d.verdict == "cold")),
                i18n.t("{n} drafted").format(n=len(drafts))]
        skipped = getattr(res, "skipped_seen", 0) or 0
        if skipped:
            bits.append(i18n.t("{n} already pulled, skipped").format(n=skipped))
        outside = self._outside_bit(res)
        if outside:
            bits.append(outside)
        no_email = c(lambda d: d.status == "ok" and not (d.lead.email or "").strip())
        if no_email:
            bits.append(i18n.t("{n} no-email").format(n=no_email))
        errs = c(lambda d: d.status != "ok")
        if errs:
            bits.append(i18n.t("{n} qualify-errors").format(n=errs))
        cov = i18n.t("why-now {a}/{b}").format(
            a=c(lambda d: d.signal_status == "found"), b=len(dos))
        sig_err = c(lambda d: d.signal_status == "source_error")
        if sig_err:
            cov += i18n.t(" ({n} source-errors)").format(n=sig_err)
        bits.append(cov)
        return "   ·   ".join(bits)

    @staticmethod
    def _outside_bit(res) -> str:
        """"412 outside your filters (location)" — the people a search turned
        away, and the top reason — or "" when the filters left nobody out."""
        total, why = outside_filters(getattr(res, "filtered_out", None), top=1)
        if not total:
            return ""
        return i18n.t("{n} outside your filters ({why})").format(
            n=total, why=why.split(" ", 1)[-1])

    # ── send ─────────────────────────────────────────────────────────────────
    def _need_account(self):
        QMessageBox.information(
            self, i18n.t("Set up your sending account"),
            i18n.t("No sending account is set up yet. Open the Email screen "
                   "> Change account, add your address and app password, "
                   "then come back and send."))

    def _on_send(self):
        """'Send all' — every drafted lead not already mailed."""
        pending = self._pending(self._drafts)
        if not pending or self._jobs:
            return
        if not CB.mailer.is_configured(self.cfg):
            self._need_account()
            return
        addr = (self.cfg.get("email") or {}).get("address", "")
        confirm = QMessageBox.question(
            self, i18n.t("Send outreach"),
            i18n.t("Send {n} personalised email(s) — one to each lead — from "
                   "{addr}?\n\nEach person gets their own message, from your "
                   "own account.").format(n=len(pending), addr=addr))
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._run_send(pending)

    def _run_send(self, drafts):
        """Shared sender for 'Send all' and 'Add to sequence' (selected)."""
        self._set_running(True, sending=True)
        self._status.setText(i18n.t("Sending…"))
        self._send_worker = LeadsSendWorker(drafts, self.cfg)
        self._send_worker.progress.connect(self._on_send_progress)
        self._send_worker.done.connect(self._on_sent)
        self._send_worker.failed.connect(self._on_failed)
        self._job_started()
        self._send_worker.start()

    def _on_send_progress(self, i, total, _draft):
        self._status.setText(i18n.t("Sent {i} of {total}…").format(
            i=i, total=total))
        self._save_session()                # a crash mid-send keeps who was mailed

    def _on_sent(self, sent, failed):
        if self._job_done():
            self._set_running(False)
        if getattr(self, "_res", None) is not None:
            self._cockpit.set_dossiers(self._res.dossiers, self._drafts,
                                           getattr(self._res, "all_leads", None))
        self._save_session()
        self._status.setText(i18n.t("Sent {s}, failed {f}.").format(
            s=len(sent), f=len(failed)))
        QMessageBox.information(
            self, i18n.t("Leads & Outreach"),
            i18n.t("Sent {s} email(s). {f} failed.").format(
                s=len(sent), f=len(failed)))

    # ── shared ───────────────────────────────────────────────────────────────
    def _autosave_dir(self) -> str:
        """Where a run's sheets land without asking — a predictable folder the
        user can always find, created on first use."""
        d = os.path.join(os.path.expanduser("~"), "Documents", "Prism Leads")
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:                                   # noqa: BLE001
            d = os.path.expanduser("~")
        return d

    def _export(self):
        """The 'Export sheets' action — choose where, and confirm loudly."""
        if self._jobs:
            return
        if not self._res or not (self._res.dossiers
                                 or getattr(self._res, "all_leads", None)):
            QMessageBox.information(self, i18n.t("Leads & Outreach"),
                                    i18n.t("Prepare a list first."))
            return
        folder = QFileDialog.getExistingDirectory(
            self, i18n.t("Choose a folder for the sheets"))
        if not folder:
            return
        self._start_export(folder, announce=True)

    def _start_export(self, folder: str, announce: bool):
        """Write the two xlsx (live MX check per row → worker thread) plus the
        drafts CSV. `announce=False` is the automatic save after a run — quiet,
        opens the folder once; `announce=True` is the button — confirms loudly."""
        if not self._res or not (self._res.dossiers
                                 or getattr(self._res, "all_leads", None)):
            return
        self._announce_export = announce
        # The drafts CSV is quick — write it inline; the xlsx go to the worker.
        from prospector import reach
        try:
            reach.write_outreach(self._drafts, os.path.join(folder, "outreach.csv"))
        except Exception:                                   # noqa: BLE001
            pass
        self._set_running(True)
        self._status.setText(i18n.t("Verifying e-mails and writing the sheets…"))
        self._export_worker = LeadsExportWorker(
            self._res.all_leads, self._res.dossiers, folder)
        self._export_worker.progress.connect(self._status.setText)
        self._export_worker.done.connect(self._on_exported)
        self._export_worker.failed.connect(self._on_failed)
        self._job_started()
        self._export_worker.start()

    def _on_exported(self, paths):
        if self._job_done():
            self._set_running(False)
        self.refresh_lists()                # the new sheets belong on Lists now
        folder = os.path.dirname(paths[0]) if paths else ""
        self._status.setText(
            i18n.t("Leads sheet + hot list saved to {f}").format(f=folder)
            if folder else i18n.t("Sheets written."))
        if folder and (self._announce_export or not self._opened_autosave):
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
            self._opened_autosave = True
        if self._announce_export:
            QMessageBox.information(
                self, i18n.t("Leads & Outreach"),
                i18n.t("Wrote the leads sheet and the hot list (xlsx), plus "
                       "outreach.csv, to that folder."))

    def _sender(self) -> str:
        try:
            import identity
            return identity.describe() or ""
        except Exception:                                   # noqa: BLE001
            return ""

    def _set_running(self, running: bool, sending: bool = False):
        for w in (self._pick, self._offer, self._claims, self._limit,
                  self._verify_limit, self._prepare, self._leads_only,
                  self._send_btn, self._export_btn, self._mode_sheet,
                  self._mode_icp, self._filters, self._target, self._exa,
                  self._skip_seen):
            w.setEnabled(not running)
        # The cockpit's bulk bar starts sends and verifies too. Disabling the bar
        # itself holds its buttons off even when _refresh_bulk re-arms them.
        cockpit = getattr(self, "_cockpit", None)
        if cockpit is not None:
            cockpit.leads._bulk.setEnabled(not running)
        if not running:
            self._refresh_prepare()
            self._send_btn.setEnabled(bool(self._pending(self._drafts)))
            self._export_btn.setEnabled(self._res is not None
                                        and bool(getattr(self._res, "dossiers", None)
                                                 or getattr(self._res, "all_leads", None)))

    # ── background jobs ───────────────────────────────────────────────────────
    def _job_started(self):
        self._jobs += 1

    def _job_done(self) -> bool:
        """One background job finished; True when none are left running."""
        self._jobs = max(0, self._jobs - 1)
        return self._jobs == 0

    @staticmethod
    def _pending(drafts) -> list:
        """Drafts not yet mailed — what Send may still send."""
        return [d for d in (drafts or []) if getattr(d, "status", "") != "sent"]

    # ── sessions: every run is kept, and no run repeats people ────────────────
    def _sessions_dir(self) -> str:
        """This member's Leads sessions: under their workspace folder, beside
        their run history (shared-drive aware, readable by a manager), falling
        back to ~/.prism when no workspace resolves. Tests patch this method."""
        try:
            import identity
            import workspace
            return workspace.member_dir(identity.current()["mid"], self.cfg,
                                        "leads", "sessions")
        except Exception:                                   # noqa: BLE001
            import paths
            return paths.user_dir("leads", "sessions")

    def _save_session(self):
        """Write (or rewrite) the session on screen. Never raises into the UI —
        a failed save is said on the status line."""
        if self._res is None or not self._session_id:
            return
        try:
            from addons.leads import sessions
            sessions.save(
                self._sessions_dir(), self._session_id, mode=self._session_mode,
                params=self._run_params, all_leads=list(self._res.all_leads or []),
                dossiers=list(self._res.dossiers or []), drafts=list(self._drafts),
                total_in_sheet=self._res.total_in_sheet,
                signal_source=getattr(self._res, "signal_source", "") or "",
                skipped_seen=getattr(self._res, "skipped_seen", 0) or 0)
        except Exception as e:                              # noqa: BLE001
            self._status.setText(str(e) or i18n.t("Couldn't save this session."))
            return
        refresh = getattr(self._cockpit, "refresh_sessions", None)
        if refresh is not None:
            refresh(self._session_id)

    def restore_latest(self):
        """Bring back the latest session when the screen first opens — read off
        the UI thread, and dropped if the user has already started something."""
        self._load_session("")

    def open_session(self, session_id: str):
        """Open a session picked on the Sessions tab."""
        if self._jobs:
            self._status.setText(i18n.t(
                "Wait for the current job to finish, then open the session."))
            return
        self._load_session(session_id)

    def _load_session(self, session_id: str):
        self._restoring = session_id or "latest"
        self._load_worker = LeadsSessionLoadWorker(self._sessions_dir(), session_id)
        self._load_worker.done.connect(self._on_session_loaded)
        self._load_worker.failed.connect(self._on_session_load_failed)
        self._load_worker.start()

    def _on_session_loaded(self, loaded):
        explicit = self._restoring not in ("", "latest")
        self._restoring = ""
        if loaded is None:
            return
        # Never clobber live work: a run in flight, or (for the automatic
        # restore) a run the user already finished while this was loading.
        if self._jobs or (not explicit and self._res is not None):
            return
        self._apply_session(loaded)

    def _on_session_load_failed(self, msg):
        explicit = self._restoring not in ("", "latest")
        self._restoring = ""
        if explicit:
            QMessageBox.warning(self, i18n.t("Open session"), msg)
        else:
            self._status.setText(i18n.t(
                "Couldn't restore the last session: {err}").format(err=msg))

    def _apply_session(self, loaded: dict):
        """Put a saved session back exactly as it was — no re-export, no re-save."""
        from prospector import engine
        head = loaded.get("header") or {}
        params = loaded.get("params") or {}
        res = engine.RunResult(
            dossiers=list(loaded.get("dossiers") or []),
            total_in_sheet=int(loaded.get("total_in_sheet") or 0),
            signal_source=loaded.get("signal_source") or "",
            all_leads=list(loaded.get("all_leads") or []))
        res.skipped_seen = int(loaded.get("skipped_seen") or 0)
        self._session_id = head.get("id", "")
        self._session_mode = params.get("mode") or head.get("mode") or "sheet"
        self._run_params = dict(params)
        self._restore_inputs(params)
        self._show_result(res, loaded.get("drafts") or [])
        self._status.setText(i18n.t("Opened the session from {when}.").format(
            when=_when(head.get("created_at", ""))))
        refresh = getattr(self._cockpit, "refresh_sessions", None)
        if refresh is not None:
            refresh(self._session_id)

    def _restore_inputs(self, params: dict):
        """Put an opened session's search back in the rail, so "New search"
        starts from what that run asked. A session saved before filters comes
        back as the filters it meant: "Global except india" is Location,
        excluding India."""
        mode = params.get("mode") or "sheet"
        self._set_mode("sheet" if mode == "sheet" else "icp")
        if params.get("sheet_path"):
            self._path = params["sheet_path"]
            self._file_lbl.setText(os.path.basename(self._path))
        if (isinstance(params.get("filters"), dict)
                or any(params.get(k) for k in ("industries", "roles", "location"))):
            self._filters.set_spec(SearchSpec.from_params(params))
        for spin, key in ((self._target, "target"), (self._limit, "limit"),
                          (self._verify_limit, "verify_limit")):
            try:
                spin.setValue(int(params[key]))
            except (KeyError, TypeError, ValueError):
                pass
        if params.get("offer"):
            self._offer.setPlainText(str(params["offer"]))
        if params.get("claims_path"):
            self._claims_path = params["claims_path"]
            self._claims_lbl.setText(os.path.basename(self._claims_path))
        self._skip_seen.setChecked(not params.get("include_earlier", False))
        self._refresh_prepare()

    # ── saved searches: filters kept to run again ─────────────────────────────
    def _searches_dir(self) -> str:
        """This member's saved searches, beside their Leads sessions (see
        _sessions_dir). Tests patch this method."""
        try:
            import identity
            import workspace
            return workspace.member_dir(identity.current()["mid"], self.cfg,
                                        "leads", "searches")
        except Exception:                                   # noqa: BLE001
            import paths
            return paths.user_dir("leads", "searches")

    def _ask_search_name(self, suggested: str = ""):
        """(name, ok) from the owner. A seam, so a test never opens a dialog."""
        return QInputDialog.getText(self, i18n.t("Save search"),
                                    i18n.t("Name this search:"), text=suggested)

    def _confirm_delete(self, name: str) -> bool:
        """True when the owner confirms. A seam, so a test never opens a box."""
        return QMessageBox.question(
            self, i18n.t("Delete saved search"),
            i18n.t("Delete the saved search “{name}”? Sessions its runs saved "
                   "are kept.").format(name=name)) == QMessageBox.StandardButton.Yes

    def _run_settings(self) -> dict:
        return {"target": self._target.value(), "limit": self._limit.value(),
                "verify_limit": self._verify_limit.value(),
                "include_earlier": not self._skip_seen.isChecked(),
                "offer": self._offer.toPlainText().strip()}

    def _save_search(self):
        """The filter panel's Save search: name it, keep the filters and the run
        settings. Saving under the name of the search that is on the rail
        updates that search instead of refusing the name as taken."""
        folder = self._searches_dir()
        active = saved_searches.get(folder, self._active_search_id) \
            if self._active_search_id else None
        name, ok = self._ask_search_name(active["name"] if active else "")
        if not ok or not (name or "").strip():
            return
        spec = self._filters.spec()
        same = active is not None and " ".join(name.split()).casefold() \
            == active["name"].casefold()
        try:
            record = saved_searches.save(folder, name, spec.to_dict(),
                                         settings=self._run_settings(),
                                         search_id=active["id"] if same else None)
        except saved_searches.SavedSearchError as e:
            self._status.setText(str(e))
            return
        self._active_search_id = record["id"]
        self._active_search_filters = record["filters"]
        self._status.setText(i18n.t("Saved “{name}”.").format(name=record["name"]))
        self._cockpit.refresh_searches()

    def use_saved_search(self, search_id: str):
        """"Use search" on the Saved searches tab: its filters and settings go
        back in the rail, ready for Prepare outreach — never run on their own."""
        if self._jobs:
            self._status.setText(i18n.t(
                "Wait for the current job to finish, then use the search."))
            return
        record = saved_searches.get(self._searches_dir(), search_id)
        if record is None:
            self._status.setText(i18n.t("That saved search is no longer there."))
            self._cockpit.refresh_searches()
            return
        self._filters.set_spec(record["filters"])
        settings = record.get("settings") or {}
        for spin, key in ((self._target, "target"), (self._limit, "limit"),
                          (self._verify_limit, "verify_limit")):
            if isinstance(settings.get(key), int):
                spin.setValue(settings[key])
        if (settings.get("offer") or "").strip():
            self._offer.setPlainText(settings["offer"])
        if isinstance(settings.get("include_earlier"), bool):
            self._skip_seen.setChecked(not settings["include_earlier"])
        self._set_mode("icp")
        if self._setup_details.isHidden():      # folded over a run: open it
            self._fold_setup(True)
        self._cockpit._select(0)
        self._active_search_id = record["id"]
        self._active_search_filters = record["filters"]
        self._status.setText(i18n.t(
            "Loaded “{name}” — press Prepare outreach to run it.").format(
                name=record["name"]))

    def _delete_saved_search(self, search_id: str):
        folder = self._searches_dir()
        record = saved_searches.get(folder, search_id)
        if record is None:
            self._cockpit.refresh_searches()
            return
        if not self._confirm_delete(record["name"]):
            return
        try:
            saved_searches.delete(folder, search_id)
        except saved_searches.SavedSearchError as e:
            self._status.setText(str(e))
            return
        if search_id == self._active_search_id:
            self._active_search_id, self._active_search_filters = "", None
        self._status.setText(i18n.t("Deleted “{name}”.").format(name=record["name"]))
        self._cockpit.refresh_searches()

    def _record_search_run(self, res):
        """A finished Find-people run of the saved search on the rail counts as
        one of its runs — but only while the filters are still the ones saved;
        a search edited after Use is a different search."""
        if (not self._active_search_id or self._session_mode == "sheet"
                or self._run_params.get("filters") != self._active_search_filters):
            return
        try:
            saved_searches.mark_run(
                self._searches_dir(), self._active_search_id, self._session_id,
                new_people=len(getattr(res, "all_leads", None) or []))
        except saved_searches.SavedSearchError as e:
            self._status.setText(str(e))
            return
        self._cockpit.refresh_searches()
