"""Off-thread workers for Leads & Outreach.

Per-addon workers, like addons/step/workers.py — the shared workers.py holds
only what more than one add-on needs. Each subclasses the shared
`workers._Worker` (which anchors a running QThread against GC, so a dialog can
close mid-run without a native crash), and imports the prospector engine lazily
inside run() so importing this module never drags the engine onto the UI thread.
"""
from __future__ import annotations

from PySide6.QtCore import Signal

from workers import _Worker


def _seen_index(sessions_dir: str, include_earlier: bool):
    """Everyone an earlier session already pulled, as a SeenIndex — or None when
    the user asked to include earlier people (or there is nowhere to look).
    Built inside run(): reading the session index is disk I/O."""
    if include_earlier or not sessions_dir:
        return None
    from addons.leads import sessions
    from prospector.identity import SeenIndex
    keys = sessions.seen_keys(sessions_dir)
    return SeenIndex(keys) if keys else None


def outside_filters(filtered, top: int = 3) -> tuple:
    """(total, "380 location, 32 job title") from a source run's
    stats["filtered"] — how many people the filters turned away, and the `top`
    reasons, most first, in the words of prospector.filters.REASONS. Shared by
    the no-one-left message here and the workbench's run summary."""
    from prospector.filters import REASONS
    counts = {k: int(v) for k, v in (filtered or {}).items()
              if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0}
    top = sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0])))[:top]
    words = ", ".join(f"{n} {REASONS.get(k, str(k).replace('_', ' '))}" for k, n in top)
    return sum(counts.values()), words


def _nobody_left(skipped: int, filtered) -> str:
    """Why a search ended with nobody, naming what the owner can change: the
    filters that turned people away, the Net-new switch, or the search width."""
    total, words = outside_filters(filtered)
    already = (f" {skipped} more were already pulled in an earlier session — turn "
               "off “Net new only” to include them." if skipped else "")
    if total:
        return (f"Nobody who came back matched your filters — {total} were outside "
                f"them ({words}). Loosen a filter or widen the search.{already}")
    if skipped:
        return (f"Everyone this search found ({skipped}) was already pulled in an "
                "earlier session. Widen the filters, or turn off “Net new only”.")
    return "No people came back — widen the filters, or check your Exa balance."


def _filter_new(leads: list, skip):
    """(kept, skipped, duplicates): drop repeats within the run (first wins),
    then anyone `skip` already knows. Local on purpose — the workers only need
    prospector.identity, not an engine helper."""
    from prospector.identity import dedupe
    kept, dropped = dedupe(leads)
    if skip is None:
        return kept, 0, len(dropped)
    fresh = [lead for lead in kept if lead not in skip]
    return fresh, len(kept) - len(fresh), len(dropped)


class ProspectorWorker(_Worker):
    """Qualify a sheet of leads and draft an email for each, off the UI thread.

    Groq is called once per lead to qualify and once per reachable lead to
    draft — minutes for a real list — so like the other engine workers this
    cannot run inline. `progress` carries a line per lead so the window has a
    live count instead of a frozen dialog.
    """
    progress = Signal(str)
    done = Signal(object, list)      # RunResult, list[reach.Draft]
    failed = Signal(str)

    def __init__(self, path: str, offer: str, cfg: dict, *, sheet: str = None,
                 limit: int = 25, verify_limit: int = 25, focus: str = "",
                 sender: str = "", claims: list = None,
                 exclude_domains: list = None, sessions_dir: str = "",
                 include_earlier: bool = False):
        super().__init__()
        self.path, self.offer, self.cfg = path, offer, cfg
        self.sheet, self.limit, self.focus = sheet, limit, focus
        self.verify_limit = verify_limit
        self.sender, self.claims = sender, claims or []
        self.exclude_domains = exclude_domains or []
        self.sessions_dir, self.include_earlier = sessions_dir, include_earlier

    def run(self):
        try:
            from prospector import engine, reach, signals, verify
            skip = _seen_index(self.sessions_dir, self.include_earlier)
            provider = signals.make_provider(self.cfg, self.focus,
                                             exclude_domains=self.exclude_domains)
            res = engine.run(
                self.path, self.offer, self.cfg, sheet_name=self.sheet,
                limit=self.limit, focus=self.focus, provider=provider,
                skip=skip, stats={},
                on_progress=lambda i, n, l: self.progress.emit(
                    f"Qualifying {i} of {n}: {l.display()}"))
            if not res.all_leads and getattr(res, "skipped_seen", 0):
                self.failed.emit(
                    f"All {res.skipped_seen} people in this sheet were already "
                    "worked in an earlier session. Turn off “Net new only” to go "
                    "through them again.")
                return
            vkeys = verify.collect_keys(self.cfg)
            if vkeys and self.verify_limit:
                self.progress.emit("Verifying the hot/warm emails…")
                verify.verify_reachable(
                    res.dossiers, vkeys, limit=self.verify_limit,
                    on_progress=lambda i, n, l: self.progress.emit(
                        f"Verifying {i} of {n}: {l.display()}"))
            drafts = reach.draft_batch(
                res.dossiers, self.offer, self.cfg, sender=self.sender,
                claims=self.claims,
                on_progress=lambda i, n, l: self.progress.emit(
                    f"Writing {i} of {n}: {l.display()}"))
            self.done.emit(res, drafts)
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class LeadsSendWorker(_Worker):
    """Send the prepared outreach — one personalised message per lead — off the
    UI thread. SMTP blocks per message and a hot-list can be dozens of sends;
    `stop()` lets a person pull out part-way, and the reach layer refuses
    outright if no sending account is configured."""
    progress = Signal(int, int, object)     # i, total, reach.Draft
    done = Signal(list, list)               # sent emails, [(email, error), …]
    failed = Signal(str)

    def __init__(self, drafts: list, cfg: dict):
        super().__init__()
        self.drafts, self.cfg = drafts, cfg
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            from prospector import reach
            sent, failed = reach.send(
                self.drafts, self.cfg,
                on_progress=lambda i, n, d: self.progress.emit(i, n, d),
                should_stop=lambda: self._stop)
            self.done.emit(sent, failed)
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class LeadsExportWorker(_Worker):
    """Write the two deliverable spreadsheets off the UI thread — the leads
    sheet does a live MX lookup per unique domain, which blocks, so it can no
    more run inline than a blast can."""
    progress = Signal(str)
    done = Signal(list)                     # [leads_path, hotlist_path]
    failed = Signal(str)

    def __init__(self, all_leads: list, dossiers: list, out_dir: str):
        super().__init__()
        self.all_leads, self.dossiers, self.out_dir = all_leads, dossiers, out_dir

    def run(self):
        try:
            import os
            from prospector import exports
            self.progress.emit("Verifying e-mails and writing the leads sheet…")
            leads_path = exports.leads_xlsx(
                self.all_leads, os.path.join(self.out_dir, "Prism leads.xlsx"))
            self.progress.emit("Writing the hot list…")
            hot_path = exports.hotlist_xlsx(
                self.dossiers, os.path.join(self.out_dir, "Prism hot list.xlsx"))
            self.done.emit([leads_path, hot_path])
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class LeadsVerifyWorker(_Worker):
    """Re-verify the SELECTED leads' e-mails with the free-first verifier
    waterfall (verifiers only — never a paid finder), off the UI thread. Each
    live SMTP probe blocks, so a checked batch cannot run inline. Mutates
    lead.extra['email_check'] in place; the dialog re-renders when done."""
    progress = Signal(int, int, object)     # i, total, lead
    done = Signal()
    failed = Signal(str)

    def __init__(self, dossiers: list, cfg: dict):
        super().__init__()
        self.dossiers, self.cfg = dossiers, cfg

    def run(self):
        try:
            from prospector import verify
            keys = verify.collect_keys(self.cfg)
            targets = [d for d in self.dossiers if (d.lead.email or "").strip()]
            for i, d in enumerate(targets, 1):
                self.progress.emit(i, len(targets), d.lead)
                status = verify.verify_email(d.lead.email, keys)
                if status:
                    d.lead.extra = d.lead.extra or {}
                    d.lead.extra["email_check"] = status
            self.done.emit()
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class LeadsQualifyWorker(_Worker):
    """Qualify and draft the leads the user ticked, off the UI thread — the
    cockpit's "Qualify & draft". A leads-sheet-only run, or everyone past a full
    run's Qualify count, leaves people sourced but never qualified; this spends
    the same expensive pass a run spends on its top slice (why-now signal, Groq
    dossier, the free verifier on hot/warm, the draft) on exactly those people,
    so nobody has to re-import a sheet to reach them. They already belong to the
    session on screen, so none is skipped as "already pulled"."""
    progress = Signal(str)
    done = Signal(object, list)             # RunResult for those leads, drafts
    failed = Signal(str)

    def __init__(self, leads: list, offer: str, cfg: dict, *, roles: list = None,
                 verify_limit: int = 25, focus: str = "", sender: str = "",
                 claims: list = None, exclude_domains: list = None):
        super().__init__()
        self.leads, self.offer, self.cfg = list(leads or []), offer, cfg
        self.roles, self.verify_limit, self.focus = roles or [], verify_limit, focus
        self.sender, self.claims = sender, claims or []
        self.exclude_domains = exclude_domains or []

    def run(self):
        try:
            from prospector import engine, reach, signals, verify
            provider = signals.make_provider(self.cfg, self.focus,
                                             exclude_domains=self.exclude_domains)
            res = engine.run_leads(
                self.leads, self.offer, self.cfg, limit=len(self.leads),
                focus=self.focus, provider=provider, roles=self.roles,
                on_progress=lambda i, n, l: self.progress.emit(
                    f"Qualifying {i} of {n}: {l.display()}"))
            vkeys = verify.collect_keys(self.cfg)
            if vkeys and self.verify_limit:
                self.progress.emit("Verifying the hot/warm emails…")
                verify.verify_reachable(
                    res.dossiers, vkeys, limit=self.verify_limit,
                    on_progress=lambda i, n, l: self.progress.emit(
                        f"Verifying {i} of {n}: {l.display()}"))
            drafts = reach.draft_batch(
                res.dossiers, self.offer, self.cfg, sender=self.sender,
                claims=self.claims,
                on_progress=lambda i, n, l: self.progress.emit(
                    f"Writing {i} of {n}: {l.display()}"))
            self.done.emit(res, drafts)
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class LeadsSessionLoadWorker(_Worker):
    """Read a saved Leads session off the UI thread — the latest one when the
    screen first opens, or the one picked on the Sessions tab. A 2,000-lead run
    is megabytes of JSON; parsing it inline would freeze the window. Emits the
    loaded session dict (see addons/leads/sessions.load), or None when there is
    no session yet."""
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, folder: str, session_id: str = ""):
        super().__init__()
        self.folder, self.session_id = folder, session_id

    def run(self):
        try:
            from addons.leads import sessions
            sid = self.session_id
            if not sid:
                head = sessions.latest(self.folder)
                if head is None:
                    self.done.emit(None)
                    return
                sid = head["id"]
            self.done.emit(sessions.load(self.folder, sid))
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class SourceWorker(_Worker):
    """The full from-scratch pipeline off the UI thread: find people who match
    the lead FILTERS (Exa people-search, every person checked against the
    filters before they take a slot), enrich them with real-domain e-mails,
    then qualify and draft. Emits the SAME (RunResult, drafts) as
    ProspectorWorker, so the dialog treats the sheet path and the search path
    identically.

    `spec` is the filter panel's SearchSpec dict. The industries / roles /
    location arguments are derived from it by the caller; with a spec they
    only matter to an engine that predates filters."""
    progress = Signal(str)
    done = Signal(object, list)             # RunResult, list[reach.Draft]
    failed = Signal(str)

    def __init__(self, industries: list, roles: list, offer: str, cfg: dict, *,
                 location: str = "India", target: int = 300, limit: int = 25,
                 verify_limit: int = 25, focus: str = "", sender: str = "",
                 claims: list = None, exclude_domains: list = None,
                 leads_only: bool = False, sessions_dir: str = "",
                 include_earlier: bool = False, spec: dict | None = None):
        super().__init__()
        self.spec = spec
        self.industries, self.roles = industries, roles
        self.offer, self.cfg = offer, cfg
        self.location, self.target, self.limit = location, target, limit
        self.verify_limit = verify_limit
        self.focus, self.sender = focus, sender
        self.claims = claims or []
        self.exclude_domains = exclude_domains or []
        self.leads_only = leads_only
        self.sessions_dir, self.include_earlier = sessions_dir, include_earlier

    def run(self):
        try:
            from prospector import source, enrich, engine, reach, signals, verify
            from prospector.filters import SearchSpec
            key = signals.exa_key(self.cfg)
            if not key:
                self.failed.emit("Finding people needs an Exa API key — add it "
                                 "under Keys & claims and try again.")
                return
            spec = SearchSpec.from_dict(self.spec) if isinstance(self.spec, dict) else None
            # The roles triage and qualification read: the job titles, or the
            # seniority x function the filters ask for when there are none.
            roles = (spec.role_terms() if spec is not None else None) or self.roles
            skip = _seen_index(self.sessions_dir, self.include_earlier)
            stats: dict = {}
            self.progress.emit("Finding people who match your filters…"
                               if skip is None else
                               "Finding new people — skipping anyone already pulled…")
            # Only a spec'd run passes spec=, so an engine without filters still
            # takes the call.
            extra = {"spec": spec} if spec is not None else {}
            leads = source.source(
                self.industries, roles, key, location=self.location,
                target=self.target, skip=skip, stats=stats,
                on_progress=lambda qi, n, ind, got: self.progress.emit(
                    f"Sourcing {ind} — {got} found ({qi}/{n} searches)"), **extra)
            skipped, dups = stats.get("skipped_seen", 0), stats.get("duplicates", 0)
            filtered = dict(stats.get("filtered") or {})
            unverified = int(stats.get("company_unverified") or 0)
            if not leads:
                self.failed.emit(_nobody_left(skipped, filtered))
                return
            self.progress.emit(f"Found {len(leads)} new people. Finding real e-mail domains…")
            enrich.enrich(leads, key)
            # Someone first pulled from a SHEET is on file only by e-mail; now that
            # enrich has guessed addresses, look once more before spending Groq.
            leads, late_skipped, late_dups = _filter_new(leads, skip)
            skipped += late_skipped
            dups += late_dups
            if not leads:
                self.failed.emit(_nobody_left(skipped, filtered))
                return
            if self.leads_only:
                # The cheap deliverable: a ranked, enriched leads sheet with NO
                # Groq at all (qualify + draft skipped) — so a rate-limited or
                # exhausted Groq key never blocks the list the user actually wants.
                from prospector import triage
                ranked = triage.rank(leads, self.offer, roles)
                res = engine.RunResult(dossiers=[], total_in_sheet=len(ranked),
                                       signal_source="", all_leads=ranked)
                res.skipped_seen, res.duplicates = skipped, dups
                res.filtered_out, res.company_unverified = filtered, unverified
                self.done.emit(res, [])
                return
            provider = signals.make_provider(self.cfg, self.focus,
                                             exclude_domains=self.exclude_domains)
            res = engine.run_leads(
                leads, self.offer, self.cfg, limit=self.limit, focus=self.focus,
                provider=provider, roles=roles,
                on_progress=lambda i, n, l: self.progress.emit(
                    f"Qualifying {i} of {n}: {l.display()}"))
            res.skipped_seen = skipped
            res.duplicates = dups + (getattr(res, "duplicates", 0) or 0)
            res.filtered_out, res.company_unverified = filtered, unverified
            vkeys = verify.collect_keys(self.cfg)
            if vkeys and self.verify_limit:
                self.progress.emit("Verifying the hot/warm emails…")
                verify.verify_reachable(
                    res.dossiers, vkeys, limit=self.verify_limit,
                    on_progress=lambda i, n, l: self.progress.emit(
                        f"Verifying {i} of {n}: {l.display()}"))
            drafts = reach.draft_batch(
                res.dossiers, self.offer, self.cfg, sender=self.sender,
                claims=self.claims,
                on_progress=lambda i, n, l: self.progress.emit(
                    f"Writing {i} of {n}: {l.display()}"))
            self.done.emit(res, drafts)
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))
