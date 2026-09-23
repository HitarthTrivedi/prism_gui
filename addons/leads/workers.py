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


def _nobody_left(skipped: int, filtered, source: str = "exa",
                 query_errors: int = 0, queries_used: int = 0) -> str:
    """Why a search ended with nobody, naming what the owner can change: the
    filters that turned people away, the Net-new switch, or the search width.
    The last line names the database that was asked, because "check your
    balance" is only actionable when it says whose.

    22-Sep-2026: that last line used to be the ONLY answer for a genuine
    zero-match search AND for a search where every call to the database
    itself failed (a bad or expired key, an empty balance, the service
    down) — prospector.source's own _exa_people distinguishes the two
    (`None` = the call failed, `[]` = it answered with nothing) and counts
    both in `stats`, but nothing downstream READ query_errors, so "check
    your balance" was a guess dressed as the only message, every time,
    whether the account was fine or not. Reported live three times the
    same evening on a sheet with well-known companies that should have
    been easy to find someone for — exactly the shape this was blind to."""
    total, words = outside_filters(filtered)
    # The switch by the name Search settings shows it under.
    switch = "“Only find people no earlier search found” in Search settings"
    already = (f" {skipped} more were already pulled in an earlier search — they "
               f"are on the People page already; turn off {switch} to fetch them "
               "again." if skipped else "")
    if total:
        return (f"Nobody who came back matched your filters — {total} were outside "
                f"them ({words}). Loosen a filter or widen the search.{already}")
    if skipped:
        return (f"Everyone this search found ({skipped}) was already pulled in an "
                f"earlier search — they are on the People page already. Widen the "
                f"filters, or turn off {switch}.")
    db = "Apollo" if source == "apollo" else "Exa"
    if queries_used and query_errors >= queries_used:
        # Not a guess: every single call to the database failed outright —
        # this is what a bad/expired key or an empty balance looks like,
        # told apart from a real zero-match search.
        return (f"Every one of the {queries_used} searches to {db} failed — "
                f"this points at your {db} API key or balance, not the "
                f"filters. Check it under Keys & claims before trying again.")
    note = (f" ({query_errors} of {queries_used} searches to {db} failed — "
            f"worth checking your {db} key or balance too)"
            if query_errors else "")
    if source == "apollo":
        return f"No people came back from Apollo — widen the filters, or check your Apollo plan.{note}"
    return f"No people came back — widen the filters, or check your Exa balance.{note}"


def _plan_refusal(exc, apollo) -> str:
    """Apollo's 403 — a FREE plan (its search and match endpoints are not in
    one, and a master key does not help) or a key scoped to other endpoints —
    told apart from every other ApolloError by the message apollo itself writes
    for it. Matched on the halves around the endpoint it names, so the wording
    can be improved there without this going blind. "" = a different refusal."""
    text = str(exc)
    head, _sep, tail = apollo.SCOPED_KEY.partition("{path}")
    return text if head and text.startswith(head) and text.endswith(tail) else ""


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
    live count instead of a frozen dialog. `limit=0` reads the sheet and ranks
    it and stops there: no Groq, no drafts — the cheap "load the sheet" half of
    the two Prepare buttons.

    A sheet is NEVER cut against earlier sessions. The owner picked this file,
    row by row; the commonest sheet there is now is one Prism itself exported
    from the run before, and a seen-index would hand that back empty. "Net new
    only" is about a SEARCH not re-finding people, and says so on the rail.
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
                skip=None, stats={},
                on_progress=lambda i, n, l: self.progress.emit(
                    f"Qualifying {i} of {n}: {l.display()}"))
            if not res.dossiers:
                # limit=0 — the sheet is on screen, nothing was spent on it.
                self.done.emit(res, [])
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


class LeadsEmailWorker(_Worker):
    """Find the SELECTED leads' e-mail addresses, off the UI thread — the
    cockpit's "Find e-mails".

    A Find-people run deliberately brings back no addresses (finding people is
    free; finding their addresses costs a lookup and a credit each), so this is
    where that money is spent, on the people the owner ticked — or on the rows
    of a sheet they exported and brought back.

    Two stages, in the order that costs least:
      1) `enrich` — ONE Exa lookup per unique company for its real domain, then
         the working-pattern address. Blank addresses only; a sheet that came
         in with real ones keeps them.
      2) `verify.find_and_verify` per lead — the free verifier waterfall first,
         and a paid finder (Tomba, Apollo, Hunter) only where its key is set and
         only when the free pass could not confirm the address.
    NEITHER stage is capped by the rail's Verify setting. That number is a
    budget for a RUN, which verifies whatever its top slice happens to be —
    this action is the owner naming people, row by row, and the workbench asks
    before a batch past ten. Capping stage 2 and not stage 1 was worse than
    either: it wrote a guessed address for everyone and confirmed the first
    twenty-five, so the rest reached the exported sheet as unchecked guesses
    that read like findings."""
    progress = Signal(int, int, object)     # i, total, lead
    done = Signal(int, int)                 # addresses found, of them verified
    failed = Signal(str)

    def __init__(self, leads: list, cfg: dict):
        super().__init__()
        self.leads, self.cfg = list(leads or []), cfg

    def run(self):
        try:
            from prospector import enrich, signals, verify
            keys = verify.collect_keys(self.cfg)
            # Apollo's people/match is not in a free Apollo plan either, and the
            # workbench has already learnt that from a refused run — so don't
            # spend a lead's turn on a finder that answers 403.
            if self.cfg.get("apollo_api_blocked"):
                keys.pop("apollo_api_key", None)
            blank = [l for l in self.leads if not (l.email or "").strip()]
            if blank:
                self.progress.emit(0, len(self.leads), blank[0])
                enrich.enrich(blank, signals.exa_key(self.cfg))
            for i, lead in enumerate(self.leads, 1):
                self.progress.emit(i, len(self.leads), lead)
                lead.extra = lead.extra or {}
                verify.find_and_verify(lead, keys)
            # "Found" is people who had NO address and have one now — the thing
            # this action was pressed for. Confirming one they already had is
            # counted as a verification, not as a find.
            found = sum(1 for l in blank if (l.email or "").strip())
            ok = sum(1 for l in self.leads
                     if (l.extra or {}).get("email_check") == "valid")
            self.done.emit(found, ok)
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


class LeadsPoolWorker(_Worker):
    """Everyone Prism holds, read off the UI thread: the saved contacts and
    every past run — what the People page filters instantly (addons/leads/
    pool.build joins them). Emits (contacts, runs), each run a (session_id,
    created_at, all_leads, dossiers, drafts, params) tuple — params being what
    the run was asked, which the pool reads to know what its search was
    steered by. A run that cannot be read is left out, not the whole page: one
    damaged file must not hide everyone else."""
    done = Signal(object, object)
    failed = Signal(str)

    def __init__(self, contacts_dir: str, sessions_dir: str):
        super().__init__()
        self.contacts_dir, self.sessions_dir = contacts_dir, sessions_dir

    def run(self):
        try:
            from addons.leads import contacts, sessions
            saved = contacts.list_contacts(self.contacts_dir) if self.contacts_dir else []
            runs = []
            for head in sessions.list_sessions(self.sessions_dir) if self.sessions_dir else ():
                try:
                    got = sessions.load(self.sessions_dir, head["id"])
                except sessions.SessionStoreError:
                    continue
                runs.append((head["id"], got["header"].get("created_at", ""),
                             got["all_leads"], got["dossiers"], got["drafts"],
                             got["params"]))
            self.done.emit(saved, runs)
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class SourceWorker(_Worker):
    """The full from-scratch pipeline off the UI thread: find people who match
    the lead FILTERS (every person checked against the filters before they take
    a slot), enrich them with real-domain e-mails, then qualify and draft.
    Emits the SAME (RunResult, drafts) as ProspectorWorker, so the dialog
    treats the sheet path and the search path identically.

    Two databases answer the same filters. `source="exa"` pages a web people
    search, free per person; `source="apollo"` asks Apollo's own index, free to
    search and about a credit for each person it reveals — so that path spends
    nothing on anyone the filters or an earlier session would drop, and the run
    carries its credit count back as `res.apollo_stats`.

    `emails="later"` finds the PEOPLE and stops: no domain lookups, no verifier,
    no finder — so a run costs only its searches, and the owner spends on
    addresses afterwards, for the rows they tick (or a sheet they export and
    bring back). `emails="now"` is the whole pipeline, as before.

    `spec` is the filter panel's SearchSpec dict. The industries / roles /
    location arguments are derived from it by the caller; with a spec they
    only matter to an engine that predates filters."""
    progress = Signal(str)
    done = Signal(object, list)             # RunResult, list[reach.Draft]
    failed = Signal(str)
    # Apollo refused the run on its PLAN or the key's scope (its own 403).
    # Separate from `failed` because the owner must not be able to spend
    # another run finding the same wall: the workbench switches back to Exa
    # and puts Apollo's reason on the switch it disables.
    blocked = Signal(str)

    def __init__(self, industries: list, roles: list, offer: str, cfg: dict, *,
                 location: str = "India", target: int = 300, limit: int = 25,
                 verify_limit: int = 25, focus: str = "", sender: str = "",
                 claims: list = None, exclude_domains: list = None,
                 leads_only: bool = False, sessions_dir: str = "",
                 include_earlier: bool = False, spec: dict | None = None,
                 source: str = "exa", emails: str = "now"):
        super().__init__()
        self.spec = spec
        self.source = "apollo" if source == "apollo" else "exa"
        self.emails = "later" if emails == "later" else "now"
        self.industries, self.roles = industries, roles
        self.offer, self.cfg = offer, cfg
        self.location, self.target, self.limit = location, target, limit
        self.verify_limit = verify_limit
        self.focus, self.sender = focus, sender
        self.claims = claims or []
        self.exclude_domains = exclude_domains or []
        self.leads_only = leads_only
        self.sessions_dir, self.include_earlier = sessions_dir, include_earlier

    def _apollo_progress(self, stage, done, total, found):
        """Apollo's two phases, said in what each costs: paging its index is
        free, so that line counts pages and people; revealing is billed, so
        that line counts credits against the target."""
        if stage == "reveal":
            self.progress.emit(
                f"Revealing {done} of {total or self.target} (Apollo credits)")
        else:
            self.progress.emit(f"Searching Apollo — page {done} · {found} found")

    def run(self):
        try:
            from prospector import enrich, engine, reach, signals, verify
            from prospector.filters import SearchSpec
            spec = SearchSpec.from_dict(self.spec) if isinstance(self.spec, dict) else None
            # The roles triage and qualification read: the job titles, or the
            # seniority x function the filters ask for when there are none.
            roles = (spec.role_terms() if spec is not None else None) or self.roles
            skip = _seen_index(self.sessions_dir, self.include_earlier)
            stats: dict = {}
            apollo_run = self.source == "apollo"
            exa_key = signals.exa_key(self.cfg)
            if apollo_run:
                # Lazy, like every engine import here: the Exa path must not
                # pay for a module it never calls.
                from prospector import apollo
                key = apollo.api_key(self.cfg)
                if not key:
                    self.failed.emit("Searching Apollo needs an Apollo API key — "
                                     "add it under Keys & claims and try again.")
                    return
                self.progress.emit("Searching Apollo for people who match your filters…"
                                   if skip is None else
                                   "Searching Apollo — skipping anyone already pulled…")
                # An ApolloError (a bad key, a plan that cannot search, a rate
                # limit that outlasted its retries) is already written for the
                # owner; run()'s own handler emits it as the failure. The one
                # it does NOT emit as a failure is the plan/scope refusal:
                # that wall is there for every later run too, so it goes out
                # as `blocked` and the rail stops offering Apollo.
                try:
                    leads = apollo.search_people(
                        spec if spec is not None else (self.spec or {}), key,
                        target=self.target, skip=skip, stats=stats,
                        on_progress=self._apollo_progress)
                except apollo.ApolloError as exc:
                    why = _plan_refusal(exc, apollo)
                    if not why:
                        raise
                    self.blocked.emit(why)
                    return
            else:
                # `as people_search`: self.source is the name of the database,
                # the module is the Exa people search itself.
                from prospector import source as people_search
                key = exa_key
                if not key:
                    self.failed.emit("Finding people needs an Exa API key — add it "
                                     "under Keys & claims and try again.")
                    return
                self.progress.emit("Finding people who match your filters…"
                                   if skip is None else
                                   "Finding new people — skipping anyone already pulled…")
                # Only a spec'd run passes spec=, so an engine without filters
                # still takes the call.
                extra = {"spec": spec} if spec is not None else {}
                leads = people_search.source(
                    self.industries, roles, key, location=self.location,
                    target=self.target, skip=skip, stats=stats,
                    on_progress=lambda qi, n, ind, got: self.progress.emit(
                        f"Sourcing {ind} — {got} found ({qi}/{n} searches)"), **extra)
            skipped, dups = stats.get("skipped_seen", 0), stats.get("duplicates", 0)
            filtered = dict(stats.get("filtered") or {})
            unverified = int(stats.get("company_unverified") or 0)
            if not leads:
                self.failed.emit(_nobody_left(
                    skipped, filtered, self.source,
                    query_errors=int(stats.get("query_errors") or 0),
                    queries_used=int(stats.get("queries_used") or 0)))
                return
            if self.emails == "later":
                # Finding PEOPLE is cheap — the searches are all it costs.
                # Finding their ADDRESSES is not: a domain lookup per company,
                # then a verifier or finder credit a head. So this run stops
                # here, and "Find e-mails" spends that on the rows the owner
                # ticks. (Apollo hands over the addresses it already revealed;
                # they are kept, nothing is guessed on top.)
                self.progress.emit(f"Found {len(leads)} new people — e-mails left "
                                   f"for later.")
            elif apollo_run:
                # Apollo hands over the address it holds; only the people it had
                # none for need a domain looked up and a pattern address guessed.
                need = [lead for lead in leads if not (lead.email or "").strip()]
                if need:
                    self.progress.emit(f"Found {len(leads)} new people. Finding "
                                       f"real e-mail domains for {len(need)}…")
                    enrich.enrich(need, exa_key)
                else:
                    self.progress.emit(f"Found {len(leads)} new people, every one "
                                       f"with an address.")
            else:
                self.progress.emit(f"Found {len(leads)} new people. Finding real e-mail domains…")
                enrich.enrich(leads, key)
            # Someone first pulled from a SHEET is on file only by e-mail; now that
            # enrich has guessed addresses, look once more before spending Groq.
            # (An e-mails-later run learns no new keys here — it only pays the
            # in-run dedupe, which is free.)
            leads, late_skipped, late_dups = _filter_new(leads, skip)
            skipped += late_skipped
            dups += late_dups
            if not leads:
                self.failed.emit(_nobody_left(skipped, filtered, self.source))
                return
            if self.leads_only:
                # The cheap deliverable: a ranked leads sheet with NO Groq at all
                # (qualify + draft skipped) — so a rate-limited or exhausted Groq
                # key never blocks the list the user actually wants. With
                # emails="later" it is cheaper still: the searches, and nothing else.
                from prospector import triage
                ranked = triage.rank(leads, self.offer, roles)
                res = engine.RunResult(dossiers=[], total_in_sheet=len(ranked),
                                       signal_source="", all_leads=ranked)
                res.skipped_seen, res.duplicates = skipped, dups
                res.filtered_out, res.company_unverified = filtered, unverified
                if apollo_run:
                    res.apollo_stats = stats    # what the run cost, in credits
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
            if apollo_run:
                res.apollo_stats = stats        # what the run cost, in credits
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
