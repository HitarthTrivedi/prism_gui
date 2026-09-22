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
from prospector.filters import MAX_FACET_VALUES, SearchSpec
from addons.leads import saved_searches
from addons.leads.filter_panel import (
    HELP_KEYS as _FILTER_HELP_KEYS, FilterPanel, reveal_in_scroll, static_suggest,
)
from addons.leads.workers import (LeadsEmailWorker, LeadsExportWorker,
                                  LeadsQualifyWorker, LeadsSendWorker,
                                  LeadsSessionLoadWorker, LeadsVerifyWorker,
                                  ProspectorWorker, SourceWorker, outside_filters)
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


# The Apollo half of the source switch, in two states. Apollo's own API Keys
# page says its search and match endpoints "aren't included in your Free plan
# and won't be accessible even with a master key" — so the tooltip says it
# before a run spends a thread finding out. Functions, not constants: the
# translation must be looked up when the tooltip is set, not at import.
# What the "?" walkthrough calls the search's own parts (addons/leads/help.py).
# Kept as a set so a key meant for the filters or the cockpit is not answered
# here by accident.
_HELP_KEYS = frozenset({
    "source_switch", "mode_switch", "run_target", "run_qualify", "run_verify",
    "offer", "net_new", "btn_find", "btn_prepare", "keys_box", "notice",
})


def _apollo_tip() -> str:
    return i18n.t("Searching Apollo needs a PAID Apollo plan — the free plan "
                  "has no API access. Exa needs only its own key.")


def _apollo_blocked_text() -> str:
    """What the disabled switch says when Apollo refused without words of its
    own — normally it carries Apollo's actual 403 message instead."""
    return i18n.t("Apollo's API refused this key. Its people search is not in "
                  "the free Apollo plan; Exa is doing the finding.")


def _default_spec() -> SearchSpec:
    """A fresh search: the default job titles and industries, anywhere."""
    return SearchSpec.from_dict({
        "job_titles": {"include": _DEFAULT_ROLES.split("\n")},
        "industries": {"include": _DEFAULT_INDUSTRIES.split("\n")},
    })


# Decision-maker levels broad enough to reach a real person at almost any
# company, whatever it makes — unlike _DEFAULT_ROLES, which names one
# specific vertical (digital-transformation / automation heads).
#
# Two, not five: _queries() asks Exa once per (role, company) PAIR, so
# every extra seniority word here multiplies every batch's real query
# count, not adds to it — five names meant 250 real searches for one
# 50-company batch, not the ~50 a customer would reasonably expect from
# "50 companies". "Owner" reaches a small manufacturer; "Director" reaches
# a larger one (this sheet has both, "Acme Tooling" beside "Sun
# Pharmaceutical Industries Limited") — two terms, not the whole ladder.
_COMPANY_SEARCH_SENIORITY = ("owner", "director")


def _company_search_spec(spec: SearchSpec) -> SearchSpec:
    """The base a company-only-sheet search asks with, unless the owner has
    customised Find people's job titles or seniority themselves.

    _default_spec()'s titles are ONE vertical: "Head of Digital
    Transformation", "Automation Head". A company sheet can be any industry
    at all, and asking Exa for exactly those titles at, say, a small
    Vadodara pharma-machinery manufacturer finds nobody — not because
    there is nobody there, but because that specific title is not a role a
    company that size has (proved live, 22-09-2026: the same companies,
    called through the real pipeline with just Owner/Director instead,
    returned real people with real LinkedIn profiles in seconds). Owner /
    Director reaches a real decision-maker almost anywhere, and the sheet
    already named the industry by naming the companies — asking Exa for it
    again on top would only narrow a search that is already as scoped as
    it can be.

    22-09-2026: originally gated on the WHOLE spec being byte-for-byte
    _default_spec() — any other field differing (a saved search touched
    earlier the same session, a restored run, anything) silently kept the
    stale automation-vertical titles with no sign anything had gone
    wrong. Gated on the one thing that actually matters instead: are the
    job titles still exactly the ones this sheet-search path must not use.
    Any OTHER seniority/job-title choice the owner made is respected.
    Industries is cleared regardless — with real companies named, it has
    no effect on the query Exa is sent (filters._queries' company branch
    never reads it) and only exists here as unused bookkeeping."""
    stale_titles = list(_DEFAULT_ROLES.split("\n"))
    out = spec.copy()
    out.industries.include = []
    if not out.job_titles.include or out.job_titles.include == stale_titles:
        out.job_titles.include = []
        if not out.seniority.include and not out.functions.include:
            out.seniority.include = list(_COMPANY_SEARCH_SENIORITY)
    return out


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


def _setting(text: str, control: QWidget) -> QWidget:
    """One run setting as a row — its name, and a compact control on the right —
    the way the refine rail's "Minimum fit" reads, so a narrow rail never has to
    split two spin boxes into slivers. The label is kept on the row (`.name`)
    because a setting can be renamed by what it now costs: "Source up to"
    becomes "Reveal up to" when the source charges per person."""
    row = QWidget()
    h = QHBoxLayout(row)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(theme.SPACE_2)
    lab = QLabel(text)
    lab.setStyleSheet(f"color:{theme.NEUTRAL[800]};font-size:13px;font-weight:500;"
                      f"background:transparent;")
    h.addWidget(lab, 1)
    if isinstance(control, QSpinBox):
        control.setFixedWidth(104)
    h.addWidget(control)
    row.name = lab
    return row


def _segment(name: str) -> QFrame:
    """A segmented switch — a well with the chosen half lifted onto a card,
    its QHBoxLayout ready for the buttons. Scoped by object name on purpose:
    unscoped, the global style.qss would make each half a 34px-tall button and
    the pair would dwarf the rail it sits in."""
    seg = QFrame()
    seg.setObjectName(name)
    seg.setAttribute(Qt.WA_StyledBackground, True)
    seg.setStyleSheet(
        f"QFrame#{name}{{background:{theme.WELL};border:1px solid {theme.HAIRLINE};"
        f"border-radius:{theme.R_CONTROL}px;}}"
        f"QFrame#{name} QPushButton{{background:transparent;border:none;"
        f"color:{theme.NEUTRAL[600]};padding:5px 8px;min-height:22px;"
        f"font-size:13px;font-weight:600;border-radius:{theme.R_CHIP}px;}}"
        f"QFrame#{name} QPushButton:checked{{background:{theme.CARD};"
        f"color:{theme.TEXT};}}"
        f"QFrame#{name} QPushButton:disabled{{color:{theme.NEUTRAL[400]};}}")
    lay = QHBoxLayout(seg)
    lay.setContentsMargins(3, 3, 3, 3)
    lay.setSpacing(2)
    return seg


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
        self._source = "exa"                # _build_inputs picks by the keys set
        self._path = ""
        self._claims_path = ""
        self._drafts = []
        self._draft_by = {}
        self._res = None
        self._worker = None
        self._send_worker = None
        self._export_worker = None
        self._verify_worker = None
        self._email_worker = None
        self._qualify_worker = None
        # Apollo's own words when its API refused this plan or key scope, and
        # the key it refused (held in memory only — the config keeps a flag,
        # never a key). Empty = Apollo is on offer.
        self._apollo_blocked = ""
        self._blocked_key = ""
        self._announce_export = False
        self._opened_autosave = False
        # A chosen sheet with no name column is read as COMPANIES instead
        # (see _on_prepare) -- one filtered search per "Load the sheet"
        # press, up to prospector.filters._MAX_VALUES names at a time. This
        # is how far into that list the last press got to; a new file choice
        # resets it (_choose_file).
        self._sheet_company_offset = 0
        self._sheet_batch_note = ""
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
                                  on_click=self._on_send)
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
        seg = self._mode_seg = _segment("modeSeg")
        sl = seg.layout()
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

        # -- find people: where to search, then the lead filters -----------------
        self._icp_box = QWidget()
        ib = QVBoxLayout(self._icp_box)
        ib.setContentsMargins(0, theme.SPACE_1, 0, 0)
        ib.setSpacing(0)
        # The same filters, asked of two databases: Exa's web search (an Exa
        # call per industry) or Apollo's own people index (free to search,
        # about a credit per person revealed). Exa is the default and the
        # fallback: Apollo's search endpoints are not in its FREE plan, so an
        # owner who has only pasted a key would meet a 403, not a list.
        src = _segment("sourceSeg")
        self._src_apollo = QPushButton(i18n.t("Apollo"))
        self._src_exa = QPushButton(i18n.t("Exa"))
        for b, name in ((self._src_apollo, "apollo"), (self._src_exa, "exa")):
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, s=name: self._set_source(s))
            src.layout().addWidget(b, 1)
        # The rows are kept, not just their controls: the walkthrough points at
        # a whole setting — its name and its control — the way it is read.
        self._source_row = _setting(i18n.t("Search with"), src)
        ib.addWidget(self._source_row)
        ib.addSpacing(theme.SPACE_2)
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
        # Its name and tooltip belong to the source — _set_source writes both.
        self._target_row = _setting(i18n.t("Source up to"), self._target)
        rows.addWidget(self._target_row)
        self._limit = QSpinBox()
        self._limit.setRange(1, 500)
        self._limit.setValue(25)
        self._limit.setToolTip(i18n.t("How many leads to qualify this run."))
        self._qualify_row = _setting(i18n.t("Qualify"), self._limit)
        rows.addWidget(self._qualify_row)
        self._verify_limit = QSpinBox()
        self._verify_limit.setRange(0, 200)
        self._verify_limit.setValue(25)
        self._verify_limit.setToolTip(i18n.t(
            "How many hot/warm addresses to check with Hunter. Its free tier is "
            "~50 credits a month, so keep this modest — 0 skips verification."))
        self._verify_row = _setting(i18n.t("Verify (Hunter)"), self._verify_limit)
        rows.addWidget(self._verify_row)
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
        # Two runs, cheapest first. The primary finds the PEOPLE and stops:
        # no e-mail lookups, no Groq — so it costs only its searches, and
        # "Find e-mails" spends on the rows the owner picks afterwards. The
        # secondary is the whole pipeline, for when they want it in one press.
        # (This primary replaced "Leads sheet only (no Groq)", which did the
        # same thing minus the saving.)
        # Both wired through a lambda: clicked(bool) would otherwise hand its
        # "checked" False to the first argument and turn the cheap run into
        # the expensive one.
        self._prepare = C.button(
            i18n.t("Find people"), "primary", icon_name="play",
            on_click=lambda: self._on_prepare(leads_only=True, emails="later"))
        self._prepare.setToolTip(i18n.t(
            "Find the people who match your filters and list them. No e-mail "
            "lookups and no Groq — tick rows and press “Find e-mails” when you "
            "want addresses."))
        body.addWidget(self._prepare)
        self._prepare_all = C.button(
            i18n.t("Find and prepare"), "secondary", icon_name="mail",
            on_click=lambda: self._on_prepare(leads_only=False, emails="now"))
        self._prepare_all.setToolTip(i18n.t(
            "The whole pipeline in one run: find the people, look up their "
            "e-mails, qualify the top ones with Groq and draft a message each."))
        body.addWidget(self._prepare_all)

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
        C.add_password_visibility(self._exa)
        kb.addWidget(self._exa)
        kb.addSpacing(theme.SPACE_1)
        kb.addWidget(_field(i18n.t("Apollo API key · searches Apollo's own database")))
        self._apollo = QLineEdit()
        self._apollo.setText(self.cfg.get("apollo_api_key") or "")
        self._apollo.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        self._apollo.setPlaceholderText(i18n.t(
            "Search Apollo's database and reveal verified emails — saved once"))
        C.add_password_visibility(self._apollo)
        kb.addWidget(self._apollo)
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
        # A different Apollo key is a different Apollo plan, so typing one lifts
        # a block this key earned.
        self._apollo.textEdited.connect(self._on_apollo_key_typed)
        # Either key is enough to run a search, so either folds the box away.
        self._keys_box.setVisible(not (self._key("exa_api_key")
                                       or self._key("apollo_api_key")))
        # Exa is the default even where an Apollo key is set: Apollo's people
        # search is not in its FREE plan (its API Keys page says so outright),
        # so offering it first sends most owners into a 403. A run that already
        # hit that wall is remembered, and Apollo is not offered at all.
        if self.cfg.get("apollo_api_blocked"):
            self._blocked_key = self._key("apollo_api_key")
            self._apollo_blocked = _apollo_blocked_text()
        self._set_source("exa")

        col.addWidget(self._setup_details)

    def _key(self, name: str) -> str:
        return (self.cfg.get(name) or "").strip()

    # How many people a run may fetch, per source: Exa pages a web search and
    # nothing is charged per person, Apollo charges about a credit for each one
    # it reveals — so the same spin box is a budget under one and a ceiling
    # under the other, and has to say which.
    _TARGET_LABEL = {"apollo": "Reveal up to", "exa": "Source up to"}
    _TARGET_TIP = {
        "apollo": "Searching Apollo is free; revealing a person's name and "
                  "e-mail costs about one Apollo credit each — and a run "
                  "stops at this many, even when your filters leave it short.",
        "exa": "How many people to find before qualifying. Everyone outside "
               "your filters is left out and does not count.",
    }

    def _set_source(self, source: str):
        """Which database a Find-people run asks. Either can be picked with or
        without its key — Prepare says which one is missing rather than a dead
        button leaving the owner to guess. Apollo, once its API has refused
        this plan, cannot be picked at all: not by a click, and not by a
        session that was run on it before the refusal."""
        self._source = "apollo" if source == "apollo" else "exa"
        if self._source == "apollo" and self._apollo_blocked:
            self._source = "exa"
        self._src_apollo.setChecked(self._source == "apollo")
        self._src_exa.setChecked(self._source == "exa")
        self._sync_apollo()
        self._target_row.name.setText(i18n.t(self._TARGET_LABEL[self._source]))
        tip = i18n.t(self._TARGET_TIP[self._source])
        self._target_row.setToolTip(tip)
        self._target.setToolTip(tip)

    def _source_name(self) -> str:
        return i18n.t("Apollo") if self._source == "apollo" else i18n.t("Exa")

    def _sync_apollo(self):
        """The Apollo half of the switch: on offer with a tooltip saying what
        it needs, or off with Apollo's own refusal on it. Called wherever the
        switch is (re)armed — _set_running re-enables every control, and would
        otherwise hand back a button that only leads to another 403."""
        self._src_apollo.setToolTip(self._apollo_blocked or _apollo_tip())
        if self._apollo_blocked:
            self._src_apollo.setEnabled(False)

    def _on_apollo_key_typed(self, text: str):
        """A new Apollo key is a new Apollo plan, so it lifts the block the old
        key earned — the config forgets too, and the switch comes back."""
        if not self._apollo_blocked:
            return
        if (text or "").strip() and (text or "").strip() != self._blocked_key:
            self._apollo_blocked = self._blocked_key = ""
            self._save_cfg("apollo_api_blocked", False)
            self._src_apollo.setEnabled(not self._jobs)
            self._sync_apollo()

    def _on_source_blocked(self, why: str):
        """Apollo turned the run down on its PLAN or the key's scope. One
        refusal is enough: the rail goes back to Exa, the Apollo half is
        switched off carrying Apollo's own words, and the config remembers — a
        flag, never the key — so the next launch does not offer the same wall."""
        if self._job_done():
            self._set_running(False)
        self._apollo_blocked = why or _apollo_blocked_text()
        self._blocked_key = self._key("apollo_api_key")
        self._src_apollo.setEnabled(False)
        self._set_source("exa")
        self._save_cfg("apollo_api_blocked", True)
        self._status.setText(i18n.t(
            "Apollo refused this key — its people search needs a paid Apollo "
            "plan. Switched to Exa; hover Apollo for what it said."))

    def _set_mode(self, mode: str):
        self._mode = mode
        self._mode_sheet.setChecked(mode == "sheet")
        self._mode_icp.setChecked(mode == "icp")
        self._sheet_box.setVisible(mode == "sheet")
        self._icp_box.setVisible(mode == "icp")
        self._target_row.setVisible(mode == "icp")   # a sheet brings its own people
        # "Net new only" is about a SEARCH not re-finding people. A sheet is
        # never cut against it (the file is the owner's own choice, row by row),
        # so the switch would be a lie sitting there in sheet mode.
        for w in (self._skip_seen, self._skip_meta):
            w.setVisible(mode == "icp")
        # The same two runs either way — list people cheaply, or spend on them —
        # but a sheet is not "found", it is loaded, and an owner who just picked
        # a file should not be told Prism is off to find people.
        if mode == "sheet":
            self._prepare.setText(i18n.t("Load the sheet"))
            self._prepare_all.setText(i18n.t("Load and prepare"))
        else:
            self._prepare.setText(i18n.t("Find people"))
            self._prepare_all.setText(i18n.t("Find and prepare"))
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
            # Which database the run asked matters as much as the filters —
            # the same filters cost nothing on Exa and credits on Apollo.
            return i18n.t("{source} · {filters} · qualify {q}").format(
                source=self._source_name(),
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
        self._prepare_all.setEnabled(ok)

    # ── the guided walkthrough points at these ────────────────────────────────
    def help_targets(self) -> dict:
        """The search's parts the "?" tour can ring, by the key it asks for:
        the widgets already in the rail, never a copy of them. A part that is
        not on screen right now — the source switch while a sheet is being
        imported, the notice line before a run has said anything — is left out,
        and the tour skips that step. The lead filters answer for themselves
        (FilterPanel.help_targets), and so does the cockpit."""
        out = {
            "source_switch": self._source_row,
            "mode_switch": self._mode_seg,
            "run_target": self._target_row,
            "run_qualify": self._qualify_row,
            "run_verify": self._verify_row,
            "offer": self._offer,
            "net_new": self._skip_seen,
            "btn_find": self._prepare,
            "btn_prepare": self._prepare_all,
            # Folded away once a key is set, so point at what opens it instead.
            "keys_box": (self._keys_box if not self._keys_box.isHidden()
                         else self._keys_toggle),
            "notice": self._notice,
        }
        return {k: w for k, w in out.items() if w is not None and w.isVisibleTo(self)}

    def help_reveal(self, key: str) -> None:
        """Make one part reachable: the Leads tab, the rail unfolded, the setup
        unfolded, the keys box open, the rail scrolled to it. It starts no run,
        changes no filter and writes no config — an owner who walks the tour
        comes back to exactly the search they had.

        The lead filters' keys are answered here too, for the unfolding only.
        They sit in this search, in the cockpit's rail, and the filter panel
        can neither see that rail nor bring it back: with Hide filters on, every
        facet step was skipped and the walk opened on the run line."""
        if key not in _HELP_KEYS and key not in _FILTER_HELP_KEYS:
            return
        self._cockpit.help_reveal("tab_leads")      # the rail is in the Leads tab
        if key == "notice":
            return                                  # over the tabs, not in the rail
        self._cockpit.leads.set_filters_shown(True)  # Hide filters folds it away
        if self._setup_details.isHidden():
            self._fold_setup(True)                  # it was folded to one line
        if key == "keys_box" and self._keys_box.isHidden():
            self._keys_box.setVisible(True)         # what "Keys & claims" opens
        widget = self.help_targets().get(key)
        if widget is not None:
            reveal_in_scroll(widget)

    def help_snapshot(self) -> dict:
        """The two folds a reveal opens: the setup and the keys box."""
        return {"setup_hidden": self._setup_details.isHidden(),
                "keys_hidden": self._keys_box.isHidden()}

    def help_restore(self, snap: dict) -> None:
        if not isinstance(snap, dict):
            return
        if snap.get("setup_hidden") != self._setup_details.isHidden():
            self._fold_setup(not snap.get("setup_hidden"))
        if snap.get("keys_hidden") != self._keys_box.isHidden():
            self._keys_box.setVisible(not snap.get("keys_hidden"))

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
        self._cockpit.emailsRequested.connect(self._find_emails)
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
        self._sheet_company_offset = 0
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
    def _on_prepare(self, leads_only: bool = True, emails: str = "later"):
        """Start a run. The defaults are the primary button's: find the people,
        leave the e-mails and Groq for the actions on the rows that come back.
        "Find and prepare" passes leads_only=False, emails="now"."""
        if self._jobs:
            return
        from prospector import reach
        # Persist the search keys once, to config, so every run after picks them
        # up. Read the config FRESH and change only those keys: self.cfg can
        # predate an account or key saved elsewhere, and saving it whole would
        # wipe them.
        self._save_search_key("exa_api_key", self._exa.text().strip())
        self._save_search_key("apollo_api_key", self._apollo.text().strip())
        if self._mode == "icp":
            missing = self._missing_key()
            if missing:
                self._keys_box.setVisible(True)
                self._status.setText(missing)
                return
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
            **legacy, "filters": spec.to_dict(), "source": self._source,
            "target": self._target.value(), "offer": offer,
            "limit": self._limit.value(), "verify_limit": self._verify_limit.value(),
            "claims_path": self._claims_path, "include_earlier": include_earlier,
        }
        # A sheet with no contact signal (has_contact_signal() False -- no
        # name, email or LinkedIn column) is a list of COMPANIES, not
        # people -- a research export, not a contacts sheet. load() reads
        # zero people out of it (nothing identifies a person on any row),
        # which used to be the whole story: the sheet loaded, found
        # nobody, and looked exactly like the button had done nothing (see
        # the 22-Sep-2026 report). Now that sheet becomes the search: its
        # companies go into the SAME "Current company" filter Find people
        # already has, MAX_FACET_VALUES at a time (that cap is a real
        # product limit -- unbounded companies is unbounded Exa queries --
        # not something to route around), one press per batch. A sheet
        # with Company + Email columns and no separate Name column (real,
        # if thin, contacts -- Apollo's own "Import contacts" accepts
        # exactly this) has a contact signal and goes through load()
        # normally instead -- has_contact_signal is deliberately broader
        # than "has a Name column" for this reason.
        from prospector import sheet as _sheet
        sheet_companies = False
        if self._mode != "icp" and self._path:
            try:
                sheet_companies = not _sheet.has_contact_signal(self._path)
            except Exception:                                   # noqa: BLE001
                pass    # unreadable -- fall through to the normal sheet
                        # path below, which will read it again and fail
                        # the same way _on_failed already handles
        if self._mode == "icp" or sheet_companies:
            missing = self._missing_key()
            if missing:
                self._keys_box.setVisible(True)
                self._status.setText(missing)
                return
        self._sheet_batch_note = ""
        if self._mode == "icp":
            self._set_running(True)
            self._status.setText(i18n.t("Finding people (no e-mails, no Groq)…")
                                 if leads_only else i18n.t("Finding people…"))
            self._worker = SourceWorker(
                legacy["industries"], legacy["roles"], offer, self.cfg,
                location=legacy["location"],
                target=self._target.value(), limit=self._limit.value(),
                verify_limit=self._verify_limit.value(),
                sender=self._sender(), claims=claims,
                exclude_domains=self._seller_domains(), leads_only=leads_only,
                sessions_dir=self._sessions_dir(), include_earlier=include_earlier,
                spec=spec.to_dict(), source=self._source, emails=emails)
            self._worker.blocked.connect(self._on_source_blocked)
        elif sheet_companies:
            companies = _sheet.load_companies(self._path)
            start = self._sheet_company_offset
            batch = companies[start:start + MAX_FACET_VALUES]
            if not batch:
                self._status.setText(i18n.t(
                    "Every company in this sheet has already been searched. "
                    "Choose a different sheet to search more."))
                return
            # Never touch the visible ICP filters, and never search this
            # sheet's companies against the automation-vertical defaults —
            # see _company_search_spec.
            batch_spec = _company_search_spec(spec)
            batch_spec.companies.include = list(batch)
            self._sheet_company_offset = start + len(batch)
            if self._sheet_company_offset < len(companies):
                self._sheet_batch_note = i18n.t(
                    "Searched {done} of {total} companies from the sheet — "
                    "press Load the sheet again for the rest."
                ).format(done=self._sheet_company_offset, total=len(companies))
            self._set_running(True)
            self._status.setText(i18n.t(
                "This sheet has no name column — finding people at its "
                "{n} companies instead…").format(n=len(batch)))
            self._worker = SourceWorker(
                [], [], offer, self.cfg,
                target=self._target.value(), limit=self._limit.value(),
                verify_limit=self._verify_limit.value(),
                sender=self._sender(), claims=claims,
                exclude_domains=self._seller_domains(), leads_only=leads_only,
                sessions_dir=self._sessions_dir(), include_earlier=include_earlier,
                spec=batch_spec.to_dict(), source=self._source, emails=emails)
            self._worker.blocked.connect(self._on_source_blocked)
        else:
            self._set_running(True)
            self._status.setText(i18n.t("Reading the sheet…"))
            # limit=0 for the primary: read the sheet, rank it, list it —
            # nothing spent. A sheet is never cut against earlier sessions
            # (workers.ProspectorWorker says why), so the export of the run
            # before comes back whole.
            self._worker = ProspectorWorker(
                self._path, offer, self.cfg,
                limit=0 if leads_only else self._limit.value(),
                verify_limit=self._verify_limit.value(),
                sender=self._sender(), claims=claims,
                exclude_domains=self._seller_domains())
        self._worker.progress.connect(self._status.setText)
        self._worker.done.connect(self._on_prepared)
        self._worker.failed.connect(self._on_failed)
        self._job_started()
        self._worker.start()

    def _save_search_key(self, name: str, value: str):
        """Keep one search key in the config, and in this window's cfg."""
        if value != (self.cfg.get(name) or ""):
            self._save_cfg(name, value)
        self.cfg[name] = value

    def _save_cfg(self, name: str, value):
        """Write ONE setting to the config, and to this window's cfg. Only that
        one: the fresh config can hold an account or a key saved elsewhere since
        this screen opened, and saving self.cfg whole would write them back as
        they were when it opened."""
        try:
            fresh = CB.config.load()
            fresh[name] = value
            CB.config.save(fresh)
        except Exception:                                   # noqa: BLE001
            pass
        self.cfg[name] = value

    def _missing_key(self) -> str:
        """Why this search cannot start, naming the key the chosen source
        needs — said before a worker spends a thread finding out."""
        if self._source == "apollo" and not self._key("apollo_api_key"):
            return i18n.t("Searching Apollo needs an Apollo API key — add it "
                          "under Keys & claims, or search with Exa instead.")
        if self._source == "exa" and not self._key("exa_api_key"):
            return i18n.t("Searching with Exa needs an Exa API key — add it "
                          "under Keys & claims, or search with Apollo instead.")
        return ""

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
        if self._sheet_batch_note:
            # More companies from this sheet are still unsearched — said
            # after _show_result's own summary, not instead of it.
            text = self._summary.text()
            self._summary.setText(
                (text + "   ·   " if text else "") + self._sheet_batch_note)
            self._sheet_batch_note = ""
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
                i18n.t("Their sheet is saved — open it under Lists. Tick rows to "
                       "find their e-mails, or to qualify and draft."))
        elif (self._mode == "sheet" and self._path and not res.dossiers
              and not getattr(res, "all_leads", None)):
            # A totally empty result from a sheet import is ambiguous: an
            # empty file and a real file with no contact signal both come
            # back with nothing, and the default "No leads yet" tells the
            # owner to do what they just did. Say which one actually
            # happened — this is mostly a defensive fallback now (a normal
            # "Load the sheet" press on a company-only sheet runs the
            # search in _on_prepare instead of reaching this with nothing),
            # reached by an old saved session from before that existed, or
            # has_contact_signal itself failing to read the file here too.
            from prospector import sheet as _sheet
            try:
                has_contact = _sheet.has_contact_signal(self._path)
            except Exception:                               # noqa: BLE001
                has_contact = True    # unsure beats a wrong claim
            if has_contact:
                self._cockpit.set_empty_text()
            else:
                self._cockpit.set_empty_text(
                    i18n.t("This sheet has no name, e-mail or LinkedIn "
                           "column Prism recognises"),
                    i18n.t("Prism looks for a column that identifies a "
                           "person — Name, Email or LinkedIn — and skips "
                           "any row without one; every row in this sheet "
                           "was skipped. If it only lists companies, "
                           "press Load the sheet again to search for "
                           "people at them."))
        else:
            self._cockpit.set_empty_text()
        self._cockpit.set_dossiers(res.dossiers, self._drafts,
                                   getattr(res, "all_leads", None))
        # The setup has done its job — fold it so the dense cockpit fills the
        # screen. "New search" brings it back.
        self._fold_setup(False)
        skipped = getattr(res, "skipped_seen", 0) or 0
        if leads_only:
            # What it found and what it did NOT spend — the whole point of the
            # cheap run, said where the owner reads the result. A list that HAS
            # addresses (an older run, or a sheet that came with them) must not
            # claim nothing was looked up.
            blank = not any((l.email or "").strip() for l in res.all_leads)
            text = (i18n.t("Found {n} people · sheet saved · no e-mail lookups, "
                           "no Groq.") if blank else
                    i18n.t("Found {n} people · sheet saved · no Groq used.")
                    ).format(n=len(res.all_leads))
            if skipped:
                text += "   ·   " + i18n.t("{n} already pulled, skipped").format(n=skipped)
            outside = self._outside_bit(res)
            if outside:
                text += "   ·   " + outside
            apollo = self._apollo_bit(res)
            if apollo:
                text += "   ·   " + apollo
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
        # Same deal as Find e-mails: the sheet already on disk is the
        # deliverable, so a status a verify pass just confirmed belongs in it
        # too, not only on screen.
        if self._res is not None and (self._res.dossiers
                                      or getattr(self._res, "all_leads", None)):
            self._start_export(self._autosave_dir(), announce=False)

    def _find_emails(self, dossiers):
        """"Find e-mails" — get the checked people an address and check it.

        A Find-people run brings back nobody's address on purpose: finding
        people costs only the searches, finding their addresses costs a lookup
        per company and a credit a head. So this is where that is spent, on the
        rows the owner picked (or on a sheet they exported and brought back)."""
        if not dossiers or self._jobs:
            return
        from addons.leads.cockpit import needs_email
        # A confirmed address has nothing left to find; asking again only
        # spends credits on an answer we already have.
        leads = [d.lead for d in dossiers if needs_email(d)]
        if not leads:
            self._status.setText(i18n.t(
                "Those leads already have a verified address."))
            return
        if not self._confirm_emails(len(leads)):
            return
        self._set_running(True)
        self._status.setText(i18n.t("Finding e-mails for {n} selected…").format(
            n=len(leads)))
        # No verify_limit: the rail's Verify is a budget for a RUN, which picks
        # its own top slice. These rows were ticked by hand, so every one of
        # them is checked — a guessed address nobody confirmed is worse in the
        # sheet than no address at all.
        self._email_worker = LeadsEmailWorker(leads, self.cfg)
        self._email_worker.progress.connect(lambda i, n, l: self._status.setText(
            i18n.t("Finding e-mail domains…") if not i else
            i18n.t("Checking {i} of {n}: {who}").format(i=i, n=n, who=l.display())))
        self._email_worker.done.connect(self._on_emails_found)
        self._email_worker.failed.connect(self._on_failed)
        self._job_started()
        self._email_worker.start()

    def _confirm_emails(self, n: int) -> bool:
        """Each lead costs an Exa domain lookup and, where the free verifiers
        can't confirm it, a finder credit — and every ticked row is checked,
        nothing is sampled — so a batch past ten asks first, and names whose
        credits. This question is the only cap on the spend. Tests patch this."""
        if n <= 10:
            return True
        who = i18n.t("verifier credits")
        if self._key("apollo_api_key") and not self.cfg.get("apollo_api_blocked"):
            who = i18n.t("verifier credits, and Apollo credits where Apollo is "
                         "the finder")
        answer = QMessageBox.question(
            self, i18n.t("Find e-mails"),
            i18n.t("Find and check e-mails for {n} leads? Prism looks up each "
                   "company's real domain, then confirms every one of the {n} "
                   "addresses — free verifiers first, then {who}.").format(
                       n=n, who=who))
        return answer == QMessageBox.StandardButton.Yes

    def _on_emails_found(self, found: int, verified: int):
        """Fold the addresses in: the rows re-render with their new Status
        (Verified / Guessed / Catch-all / No email) and the session keeps them,
        so the next thing the owner does starts from what this cost."""
        idle = self._job_done()
        if self._res is not None:
            self._cockpit.set_dossiers(self._res.dossiers, self._drafts,
                                       getattr(self._res, "all_leads", None))
        self._save_session()                # the addresses are the run's value now
        if idle:
            self._set_running(False)
        self._status.setText(i18n.t(
            "Found {n} new address(es) — {v} verified.").format(
                n=found, v=verified))
        # The sheet already sitting in the autosave folder is the deliverable —
        # rewrite it with the addresses this run just found, the same way a
        # finished run writes it the first time, so the owner never has to
        # press Export sheets just to see what Find e-mails cost.
        if self._res is not None and (self._res.dossiers
                                      or getattr(self._res, "all_leads", None)):
            self._start_export(self._autosave_dir(), announce=False)

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
        apollo = self._apollo_bit(res)
        if apollo:
            bits.append(apollo)
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
    def _apollo_bit(res) -> str:
        """"Apollo: 240 found · 25 revealed (about 25 credits)" — what the run
        cost, in the only unit Apollo bills in. Searching is free; a revealed
        person is a credit, so the owner can read the bill off the summary
        instead of the Apollo dashboard. "" for a run that was not Apollo's."""
        stats = getattr(res, "apollo_stats", None)
        if not isinstance(stats, dict):
            return ""
        found = int(stats.get("searched") or 0)
        revealed = int(stats.get("revealed") or 0)
        if not (found or revealed):
            return ""
        return i18n.t("Apollo: {n} found · {m} revealed (about {m} credits)").format(
            n=found, m=revealed)

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
            i18n.t("No sending account is set up yet. Open the Email spamming "
                   "screen > Change account, add your address and app "
                   "password, then come back and send."))

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
                  self._verify_limit, self._prepare, self._prepare_all,
                  self._send_btn, self._export_btn, self._mode_sheet,
                  self._mode_icp, self._filters, self._target, self._exa,
                  self._apollo, self._src_apollo, self._src_exa,
                  self._skip_seen):
            w.setEnabled(not running)
        # …except a source Apollo has already refused: re-enabling it here would
        # hand the owner a button that only leads to the same 403.
        if self._apollo_blocked:
            self._src_apollo.setEnabled(False)
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
        # Always the source that run asked — a session saved before Prism could
        # ask Apollo carries none, and can only have been an Exa run. Leaving
        # the rail on its own default (Apollo, whenever that key is set) would
        # re-point a search the owner reopened to repeat at a database that
        # bills per person.
        self._set_source(params["source"]
                         if params.get("source") in ("apollo", "exa") else "exa")
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
        back in the rail, ready for Find people — never run on their own."""
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
            "Loaded “{name}” — press Find people to run it.").format(
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
