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
                 exclude_domains: list = None):
        super().__init__()
        self.path, self.offer, self.cfg = path, offer, cfg
        self.sheet, self.limit, self.focus = sheet, limit, focus
        self.verify_limit = verify_limit
        self.sender, self.claims = sender, claims or []
        self.exclude_domains = exclude_domains or []

    def run(self):
        try:
            from prospector import engine, reach, signals, verify
            provider = signals.make_provider(self.cfg, self.focus,
                                             exclude_domains=self.exclude_domains)
            res = engine.run(
                self.path, self.offer, self.cfg, sheet_name=self.sheet,
                limit=self.limit, focus=self.focus, provider=provider,
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


class SourceWorker(_Worker):
    """The full from-scratch pipeline off the UI thread: build a list from the
    ICP (Exa people-search), enrich it with real-domain e-mails, then qualify
    and draft. Emits the SAME (RunResult, drafts) as ProspectorWorker, so the
    dialog treats the sheet path and the ICP path identically."""
    progress = Signal(str)
    done = Signal(object, list)             # RunResult, list[reach.Draft]
    failed = Signal(str)

    def __init__(self, industries: list, roles: list, offer: str, cfg: dict, *,
                 location: str = "India", target: int = 300, limit: int = 25,
                 verify_limit: int = 25, focus: str = "", sender: str = "",
                 claims: list = None, exclude_domains: list = None,
                 leads_only: bool = False):
        super().__init__()
        self.industries, self.roles = industries, roles
        self.offer, self.cfg = offer, cfg
        self.location, self.target, self.limit = location, target, limit
        self.verify_limit = verify_limit
        self.focus, self.sender = focus, sender
        self.claims = claims or []
        self.exclude_domains = exclude_domains or []
        self.leads_only = leads_only

    def run(self):
        try:
            from prospector import source, enrich, engine, reach, signals, verify
            key = signals.exa_key(self.cfg)
            if not key:
                self.failed.emit("Building a list from your ICP needs an Exa API "
                                 "key — add it in the Why-now field and try again.")
                return
            self.progress.emit("Sourcing people across your industries…")
            leads = source.source(
                self.industries, self.roles, key, location=self.location,
                target=self.target,
                on_progress=lambda qi, n, ind, got: self.progress.emit(
                    f"Sourcing {ind} — {got} found ({qi}/{n} searches)"))
            if not leads:
                self.failed.emit("No people came back — widen the industries or "
                                 "roles, or check your Exa balance.")
                return
            self.progress.emit(f"Found {len(leads)} people. Finding real e-mail domains…")
            enrich.enrich(leads, key)
            if self.leads_only:
                # The cheap deliverable: a ranked, enriched leads sheet with NO
                # Groq at all (qualify + draft skipped) — so a rate-limited or
                # exhausted Groq key never blocks the list the user actually wants.
                from prospector import triage
                ranked = triage.rank(leads, self.offer, self.roles)
                res = engine.RunResult(dossiers=[], total_in_sheet=len(ranked),
                                       signal_source="", all_leads=ranked)
                self.done.emit(res, [])
                return
            provider = signals.make_provider(self.cfg, self.focus,
                                             exclude_domains=self.exclude_domains)
            res = engine.run_leads(
                leads, self.offer, self.cfg, limit=self.limit, focus=self.focus,
                provider=provider, roles=self.roles,
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
