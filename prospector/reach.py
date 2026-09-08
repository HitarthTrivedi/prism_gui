"""
Prism Sales Automation — reach: the qualified dossier becomes a real email
──────────────────────────────────────────────────────────────────────────
The last stage of the spine (source → verify → enrich → qualify → **reach**).
Everything upstream produced a `Dossier`: a verdict, the six cited dimensions,
and — the part that matters here — an `opener` already grounded in the
prospect's real, dated why-now signal. This module turns that into a full
email a person can read and send.

Two rules, inherited straight from the Email add-ons and the product's spine:

  · **It stops before it sends.** `draft_batch()` only prepares; `send()` is a
    separate call, refuses unless a sending account is configured, and is never
    reached by the demo. "Prism prepares; a person presses Send" (06-addons §6.1).
  · **No invention.** The draft prompt is handed ONLY the dossier's real signals
    and its already-grounded opener, and is forbidden to state any fact not in
    them. Where there is no signal, the email opens on fit — it never makes up an
    event. Same anti-hallucination bar the qualifier holds.

Sending reuses the engine's own SMTP sender (`core_bridge.mailer.send_bulk`) —
the GUI/CLI have used it for the email blast for months; we do not reimplement
mail. We only feed it a per-lead subject/body instead of one blast for all.
"""
from __future__ import annotations

import csv
import os
import re
import time
from dataclasses import dataclass

from .models import HOT, WARM, Dossier, Signal


# ── the prepared message ──────────────────────────────────────────────────────

@dataclass
class Draft:
    """One ready-to-read email for one qualified lead. Kept next to the dossier
    it came from so a reviewer can see the argument (why this person) beside the
    message (what we'd say)."""
    dossier: Dossier
    subject: str = ""
    body: str = ""
    status: str = "draft"          # draft / sent / failed / skipped
    error: str = ""                # set when a send attempt fails
    note: str = ""                 # set when we couldn't draft (no key, bad reply)

    @property
    def recipient(self) -> dict:
        lead = self.dossier.lead
        return {"email": lead.email, "name": lead.name}


# ── who is worth reaching ─────────────────────────────────────────────────────

# Local parts that address a mailbox nobody reads as a person — role/shared
# accounts. Cold outreach to these bounces or annoys, and never converts.
_ROLE = {"info", "sales", "hr", "admin", "contact", "support", "marketing",
         "careers", "career", "office", "enquiry", "enquiries", "mail", "team",
         "hello", "help", "reception", "accounts", "noreply", "no-reply",
         "donotreply", "webmaster", "postmaster", "jobs"}
# Email-check verdicts that must NOT auto-send: a dead address, or one the
# verifier could not confirm. Catch-all/unknown go to review, not the send set.
_UNSENDABLE = {"invalid", "no-mx", "no-domain", "catch-all", "unknown"}


def _drop(lead, reason: str) -> None:
    if reason not in (lead.drops or []):
        lead.drops.append(reason)


def reachable(dossiers: list[Dossier]) -> list[Dossier]:
    """The AUTO-SEND set: hot/warm leads with a real, personal, sendable address.
    Everything else is left OUT and tagged with a drop reason on the lead, so it
    shows as a visible outcome rather than silently getting mailed — a dead,
    catch-all, or role address burns the sender's OWN domain reputation."""
    out = []
    for d in dossiers:
        if d.verdict not in (HOT, WARM):
            continue
        email = (d.lead.email or "").strip().lower()
        if not email or "@" not in email:
            continue
        if email.split("@", 1)[0] in _ROLE:
            _drop(d.lead, "role_account")
            continue
        if (d.lead.extra or {}).get("email_check") in _UNSENDABLE:
            _drop(d.lead, "email_unsendable")
            continue
        out.append(d)
    return out


# ── the draft prompt (grounded, no invention) ─────────────────────────────────

def _signals_block(signals: list[Signal]) -> str:
    if not signals:
        return ("NONE. Open on the person's role and industry fit. Do NOT invent "
                "an event, a number, or a recent announcement.")
    out = []
    for i, s in enumerate(signals, 1):
        cite = " ".join(x for x in (s.source, s.published) if x)
        out.append(f"[S{i}] {s.title} ({cite})\n     {s.snippet}")
    return "\n".join(out)


def load_claims(path: str | None) -> list[str]:
    """The seller's own approved selling points — the ONLY value statements the
    drafter is allowed to make. One claim per line; blank lines and #-comments
    ignored. A missing or empty file means no claims, and the drafter then makes
    no numeric or performance promise at all. This mirrors the email add-on's
    bargaining-limits file exactly: with no file, it offers nothing."""
    if not path:
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [ln.strip() for ln in f
                    if ln.strip() and not ln.lstrip().startswith("#")]
    except Exception:                        # noqa: BLE001 — a missing file just means "no claims"
        return []


def _claims_block(claims: list[str]) -> str:
    if claims:
        return "\n".join(f"- {c}" for c in claims)
    return ("NONE PROVIDED. Make NO numeric, percentage, or performance claim at "
            "all — describe in plain words what the seller does, and ask for a call.")


def build_prompt(dossier: Dossier, offer: str, sender: str = "",
                 claims: list[str] | None = None) -> str:
    lead = dossier.lead
    first = (lead.name or "there").split()[0]
    sign = sender.strip() or "the team"
    opener = dossier.opener or ""
    grounded = (f"\nA GROUNDED FIRST LINE, already drafted from the reason above "
                f"(reuse or improve it — keep it factual):\n{opener}\n"
                if opener else "")
    return f"""You write ONE short B2B outreach email. Reply with NOTHING but the email.

WHAT THE SELLER SELLS (a plain description — NOT a licence to invent results):
{offer}

WHO YOU ARE WRITING TO:
{lead.name or "(no name)"} — {lead.title or "unknown role"} at {lead.company or "their company"} ({lead.industry or "industry unknown"})

THE REAL, DATED REASON TO REACH OUT NOW (cite ONLY this — invent nothing else):
{_signals_block(dossier.signals)}
{grounded}
VALUE CLAIMS YOU MAY MAKE (the ONLY selling points allowed — use these, add none of your own):
{_claims_block(claims or [])}

Write the email in EXACTLY this format and nothing else:
SUBJECT: <one specific line, max ~60 chars, about THEIR real situation — no clickbait, no "Re:">
BODY:
<Address them as "{first}". 3 to 5 short sentences: open on their real reason above, connect it in one line to what the seller does, add at most ONE value point taken ONLY from VALUE CLAIMS (skip it entirely if the list is NONE), then a soft ask for a short call. Plain text, no markdown, no bullet points, no placeholders. Sign off as "{sign}".>

HARD RULES:
- Every fact must come from THE REASON above, the person's details, or VALUE CLAIMS. Invent nothing.
- FORBIDDEN unless it appears verbatim in VALUE CLAIMS or THE REASON: any number, any percentage, "up to X%", "Nx", statistics, client names, dates, product names. When in doubt, leave it out and just ask for a call.
- If THE REASON is NONE, open on their role/industry — never pretend there was an announcement.
- Sound like a person wrote it. No "Dear Sir/Madam", no "I hope this email finds you well"."""


# ── the independent number check (don't trust one pass) ───────────────────────

# Percentages and multipliers — "15%", "up to 20 percent", "3x" — almost never
# belong in a cold email unless they came from an approved claim or the signal
# itself. This is the Gerber lesson applied to prose: the prompt guard is
# primary, but a second, mechanical check catches the plausible number that
# slips through with confidence, so a human is warned before it is ever sent.
# `%` takes no trailing \b (it is a non-word char — a boundary after it needs a
# following word char, which "15% " has not, so `%\b` would silently never
# match); `percent`/`x` keep the \b so "24x7" or a word are not mistaken for a
# multiplier.
_CLAIMY_NUMBER = re.compile(r"(?:up to\s*)?\d+(?:\.\d+)?\s*(?:%|(?:percent|x)\b)", re.I)


def _signals_text(signals: list[Signal]) -> str:
    return " ".join(f"{s.title} {s.snippet}" for s in signals)


def _unverified_numbers(body: str, allowed: str) -> list[str]:
    """Claim-shaped numbers in the body whose figure isn't found anywhere in the
    allowed source text (signals + approved claims + the offer). Returns the
    offending fragments, de-duplicated in order — the evidence for the warning."""
    low = (allowed or "").lower()
    hits = []
    for m in _CLAIMY_NUMBER.finditer(body or ""):
        frag = m.group(0).strip()
        num = re.search(r"\d+(?:\.\d+)?", frag)
        if num and num.group(0) not in low:
            hits.append(frag)
    return list(dict.fromkeys(hits))


def _make_draft(dossier: Dossier, subject: str, body: str, offer: str,
                claims: list[str], note: str = "") -> Draft:
    """Every path out of drafting funnels through here so the number check runs
    on model output AND on the fallback alike — one place, no path skips it."""
    allowed = " ".join([_signals_text(dossier.signals), " ".join(claims or []), offer])
    flags = _unverified_numbers(body, allowed)
    if flags:
        warn = ("⚠ unverified figure(s): " + ", ".join(flags) +
                " — not in your claims or the signal; remove it or add it to the claims file.")
        note = f"{note} · {warn}" if note else warn
    return Draft(dossier=dossier, subject=subject.strip(), body=body.strip(), note=note)


# ── drafting one, and a batch ─────────────────────────────────────────────────

def _fallback(dossier: Dossier, offer: str, sender: str, claims: list[str],
              note: str) -> Draft:
    """When there is no model to call (no key) or its reply won't parse, still
    hand back something honest: the dossier's own grounded opener as the body,
    a plain subject, and a note saying so. Degrade, never fail — the reviewer
    can edit it, and it references only real material."""
    lead = dossier.lead
    first = (lead.name or "there").split()[0]
    sign = sender.strip() or "the team"
    subject = (f"{lead.company} — a quick idea" if lead.company else "A quick idea")
    opener = dossier.opener.strip() if dossier.opener else ""
    lines = [f"Hi {first},", ""]
    lines.append(opener or f"I work with teams in {lead.industry or 'your industry'} and thought this might be relevant.")
    lines += ["", "Would a short call next week be worth it?", "", sign]
    return _make_draft(dossier, subject, "\n".join(lines), offer, claims, note)


def draft_for(dossier: Dossier, offer: str, cfg: dict, sender: str = "",
              claims: list[str] | None = None) -> Draft:
    """Dossier → a subject+body grounded in its real signals and the seller's
    approved claims, via Prism's own Groq router and the engine's SUBJECT/BODY
    parser. Falls back to the opener if the key is missing or the reply won't
    parse. A claim-shaped number the sources don't support is flagged, not
    trusted."""
    claims = claims or []
    api_key = cfg.get("api_key", "")
    if not api_key:
        return _fallback(dossier, offer, sender, claims,
                         "No Groq key — used the grounded opener instead of a fresh draft.")
    import core_bridge as CB                 # lazy: wires the engine + submodule
    prompt = build_prompt(dossier, offer, sender, claims)
    try:
        raw = CB.router.groq_chat(api_key, cfg.get("model", ""), prompt,
                                  temperature=0.4, json_mode=False, retries=3)
    except Exception as e:                   # noqa: BLE001 — one bad draft can't sink the batch
        return _fallback(dossier, offer, sender, claims,
                         f"Draft model unreachable ({e}); used the grounded opener.")
    parsed = CB.mailer.parse_draft(raw)      # same SUBJECT:/BODY: contract the blast uses
    if not parsed:
        return _fallback(dossier, offer, sender, claims,
                         "Draft reply didn't parse; used the grounded opener.")
    subject, body = parsed
    return _make_draft(dossier, subject, body, offer, claims)


def draft_batch(dossiers: list[Dossier], offer: str, cfg: dict, sender: str = "",
                claims: list[str] | None = None, on_progress=None) -> list[Draft]:
    """Draft every reachable lead. Progress is reported per lead because at a
    real hot-list's size a person is watching this run, and one model call each
    is slow enough to want a live count."""
    targets = reachable(dossiers)
    drafts = []
    for i, d in enumerate(targets, 1):
        if on_progress:
            on_progress(i, len(targets), d.lead)
        drafts.append(draft_for(d, offer, cfg, sender, claims))
        if i < len(targets):
            time.sleep(0.4)      # pace the drafting calls — free Groq keys rate-limit on bursts
    return drafts


# ── the durable record (the thin "store") ─────────────────────────────────────

_FIELDS = ["status", "verdict", "score", "company", "name", "title", "email",
           "subject", "body", "why_now", "note"]


def _why_now(dossier: Dossier) -> str:
    """The one dated trigger this email leans on, kept in the record so the sheet
    itself shows why each person was contacted."""
    s = dossier.signals[0] if dossier.signals else None
    return f"{s.title} ({s.source} {s.published})".strip() if s else ""


def write_outreach(drafts: list[Draft], path: str) -> str:
    """Write the whole batch to a CSV the owner can open in Excel, edit, and
    keep — theirs whatever happens to Prism, exactly like the inquiry register
    and the email blast's recipients CSV. This is the outreach store's first,
    thinnest form: one row per prepared message, status carried alongside."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_FIELDS)
        w.writeheader()
        for d in drafts:
            lead = d.dossier.lead
            w.writerow({
                "status": d.status, "verdict": d.dossier.verdict,
                "score": d.dossier.score, "company": lead.company,
                "name": lead.name, "title": lead.title, "email": lead.email,
                "subject": d.subject, "body": d.body,
                "why_now": _why_now(d.dossier), "note": d.note or d.error,
            })
    return path


# ── suppression: never contact the same person twice; honour opt-outs ─────────

def _suppression_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".prism", "outreach_suppressed.txt")


def load_suppression() -> set:
    """Addresses we must not (re-)contact: previously emailed, hard-bounced, or
    opted out. A plain text file the owner can also edit by hand — the send
    checks it before every message."""
    try:
        with open(_suppression_path(), encoding="utf-8") as f:
            return {ln.strip().lower() for ln in f
                    if ln.strip() and not ln.startswith("#")}
    except Exception:                                       # noqa: BLE001
        return set()


def _suppress(emails) -> None:
    new = {e.strip().lower() for e in emails if e and e.strip()} - load_suppression()
    if not new:
        return
    try:
        path = _suppression_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            for e in sorted(new):
                f.write(e + "\n")
    except Exception:                                       # noqa: BLE001
        pass


def _with_optout(body: str) -> str:
    """A plain-text opt-out on every message — the honest, deliverability-
    protecting floor. (A one-click List-Unsubscribe HEADER is the next,
    mailer-level add; this footer works today with no engine change.)"""
    if "reply stop" in (body or "").lower():
        return body
    return (body or "") + ("\n\n—\nNot the right person, or prefer not to hear "
                           "from us? Reply STOP and we'll remove you.")


def _is_bounce(err: str) -> bool:
    e = (err or "").lower()
    return any(x in e for x in ("550", "551", "553", "no such user",
                                "does not exist", "user unknown",
                                "mailbox unavailable", "recipient rejected"))


# ── sending — separate, gated, human-pressed ──────────────────────────────────

def send(drafts: list[Draft], cfg: dict, on_progress=None, should_stop=None):
    """Send the prepared drafts through the owner's own account. Deliberately a
    SECOND call, never folded into drafting: this is the step that costs money
    and goodwill, so it must be pressed on purpose.

    The send FLOOR: it skips anyone already on the suppression list, appends a
    plain-text opt-out to every message, and records each sent OR hard-bounced
    address to suppression so a re-run never re-contacts them — the reputation
    guardrails a real sending domain needs. Refuses outright with no account
    configured. Returns (sent, failed)."""
    import core_bridge as CB
    if not CB.mailer.is_configured(cfg):
        raise RuntimeError("No sending account is set up yet "
                           "(Email → Set up the sending account).")
    suppressed = load_suppression()
    sent, failed = [], []
    total = len(drafts)
    for i, d in enumerate(drafts, 1):
        if should_stop and should_stop():
            break
        email = (d.recipient["email"] or "").strip().lower()
        if not email:
            d.status = "skipped"
            continue
        if email in suppressed:
            d.status = "skipped"
            d.note = "on the suppression list (already contacted or opted out)"
            if on_progress:
                on_progress(i, total, d)
            continue
        s, f = CB.mailer.send_bulk(cfg, [d.recipient], d.subject,
                                   _with_optout(d.body), files=[])
        if s:
            d.status = "sent"
            sent.append(d.recipient["email"])
            _suppress([email])                     # don't re-contact on a re-run
        else:
            d.status, d.error = "failed", (f[0][1] if f else "unknown error")
            failed.append((d.recipient["email"], d.error))
            if _is_bounce(d.error):
                _suppress([email])                 # a hard bounce → never retry
        if on_progress:
            on_progress(i, total, d)
    return sent, failed
