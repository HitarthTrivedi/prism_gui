"""What the dashboard screens show, read from the same stores the rest of the
app writes.

The design's Home and Inquiry screens are full of numbers — inquiries logged,
quotes sent, win rate, recent activity. In the design those are invented
spring-manufacturer data. Here every one of them is derived from a real store:
run records under the member's runs folder, and the inquiry register CSV the
Inquiry Automation add-on maintains.

Nothing in here fabricates a figure. Where a store is missing or empty the
caller gets `None` or an empty list and is expected to show an empty state —
a dashboard that invents plausible numbers is worse than one that admits it has
nothing yet, because the first time a customer spots an invented number they
stop believing all of them.
"""
from __future__ import annotations
import json
import os
from datetime import date, datetime, timedelta

import core_bridge as CB
import identity
import workspace


# ── runs ─────────────────────────────────────────────────────────────────────
def _run_files(cfg: dict, mid: str = "") -> list[str]:
    """Newest-first paths of the member's saved run records."""
    who = mid or identity.viewing()["mid"]
    folder = workspace.runs_dir(who, cfg)
    if not os.path.isdir(folder):
        return []
    # Only run records. The same folder also holds artefacts a run produced —
    # reel scene specs, BOQ quantity CSVs — and those are not runs.
    names = sorted((n for n in os.listdir(folder)
                    if n.startswith("run_") and n.endswith(".json")),
                   reverse=True)
    return [os.path.join(folder, n) for n in names]


def _ago(stamp: float, now: float | None = None) -> str:
    """"2 hours ago" / "yesterday" / "1 week ago" — the design's phrasing."""
    now = now if now is not None else datetime.now().timestamp()
    seconds = max(0, int(now - stamp))
    minutes, hours = seconds // 60, seconds // 3600
    days = seconds // 86400
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes}m ago"
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    weeks = days // 7
    if weeks < 5:
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"
    return datetime.fromtimestamp(stamp).strftime("%d %b")


def recent_runs(cfg: dict, limit: int = 6) -> list[dict]:
    """The last few runs, shaped for a row: title, the tools it used, when,
    and whether it finished.

    Reads only as many files as it needs. History lists every run and can
    afford to walk the folder; Home wants three rows and is on the startup
    path, so a workspace with a thousand runs must not cost a thousand opens.
    """
    out = []
    for path in _run_files(cfg)[:limit]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                record = json.load(f) or {}
        except Exception:
            continue
        agents = record.get("agents") or {}
        # Ordered by stage as the run executed, de-duplicated — a task that
        # sent two stages to ChatGPT should say "ChatGPT", not "ChatGPT ·
        # ChatGPT".
        tools, seen = [], set()
        for tool in agents.values():
            name = (tool or "").strip()
            if name and name.lower() not in seen:
                seen.add(name.lower())
                tools.append(name)
        out.append({
            "title": (record.get("query") or "").strip() or "Untitled task",
            "tools": tools,
            "when": _ago(os.path.getmtime(path)),
            "ok": not record.get("error"),
            "path": path,
        })
    return out


def run_counts(cfg: dict, days: int = 7) -> tuple[int, int]:
    """(finished, failed) over the last `days`, for the Home stat cards."""
    cutoff = datetime.now().timestamp() - days * 86400
    done = failed = 0
    for path in _run_files(cfg):
        try:
            stamp = os.path.getmtime(path)
        except OSError:
            continue
        if stamp < cutoff:
            break                       # newest-first, so the rest are older
        try:
            with open(path, "r", encoding="utf-8") as f:
                record = json.load(f) or {}
        except Exception:
            continue
        if record.get("error"):
            failed += 1
        else:
            done += 1
    return done, failed


def runs_per_day(cfg: dict, days: int = 7) -> list[int]:
    """A run count per day, oldest first — the Home sparklines.

    Real counts, so a quiet week draws a flat line rather than the design's
    decorative staircase. That is the honest picture and it is also the useful
    one: a flat line is itself worth seeing.
    """
    today = date.today()
    buckets = {today - timedelta(days=n): 0 for n in range(days)}
    oldest = datetime.combine(min(buckets), datetime.min.time()).timestamp()
    for path in _run_files(cfg):
        try:
            stamp = os.path.getmtime(path)
        except OSError:
            continue
        if stamp < oldest:
            break
        day = datetime.fromtimestamp(stamp).date()
        if day in buckets:
            buckets[day] += 1
    return [buckets[today - timedelta(days=n)] for n in range(days - 1, -1, -1)]


# ── the inquiry register ─────────────────────────────────────────────────────
def register_rows(cfg: dict) -> list[dict]:
    """Every row of the inquiry register, or [] if the add-on isn't set up.

    Swallows failure on purpose: the register is a CSV on a shared drive that
    may be open in Excel, missing, or on a disconnected mount. None of those
    should stop Home from drawing — they just mean there is nothing to show.
    """
    try:
        from dialogs.inquiry_setup_dialog import settings_of
        folder = (settings_of(cfg) or {}).get("folder", "")
        if not folder:
            return []
        paths = CB.get_mailflow().Paths(folder)
        return CB.get_register().load(paths.register_csv)
    except Exception:
        return []


def inquiry_stats(cfg: dict, rows: list[dict] | None = None) -> dict | None:
    """The four figures the Inquiry screen leads with, and the two Home shows.

    Returns None when the add-on has never been set up, so the caller can show
    the "attach a mailbox to begin" state rather than a wall of zeroes — zero
    open inquiries and no register at all mean very different things.
    """
    rows = register_rows(cfg) if rows is None else rows
    if not rows:
        return None
    reg = CB.get_register()
    today = date.today()
    month = summary = None
    try:
        month = reg.summarise(rows, since=today.replace(day=1))
        summary = reg.summarise(rows, since=today - timedelta(days=90))
        week = reg.summarise(rows, since=today - timedelta(days=7))
        waiting = reg.awaiting_followup(rows)
    except Exception:
        return None
    open_now = sum(1 for r in rows
                   if (r.get("Status") or "").strip() in reg.OPEN_STATUSES)
    return {
        "open": open_now,
        "quoted_value": rupees(month.quoted_value, compact=True),
        "waiting": len(waiting),
        "win_rate": summary.conversion,
        "logged_week": week.received,
        "quoted_week": week.quoted,
    }


def inquiries_per_day(cfg: dict, rows: list[dict] | None = None,
                      days: int = 7) -> list[int]:
    """Inquiries received per day, oldest first — the Home sparkline.

    Off "Date received", so a row whose date will not parse is simply not
    counted rather than being bucketed to today; a mis-dated row inflating
    today's bar would be worse than a bar one short.
    """
    rows = register_rows(cfg) if rows is None else rows
    if not rows:
        return []
    reg = CB.get_register()
    today = date.today()
    buckets = {today - timedelta(days=n): 0 for n in range(days)}
    for row in rows:
        when = reg.parse_date(row.get("Date received", ""))
        if when in buckets:
            buckets[when] += 1
    return [buckets[today - timedelta(days=n)] for n in range(days - 1, -1, -1)]


def register_view(cfg: dict, rows: list[dict] | None = None) -> list[dict]:
    """The register, shaped for the design's table row."""
    rows = register_rows(cfg) if rows is None else rows
    reg = CB.get_register()
    out = []
    for row in rows:
        status = (row.get("Status") or "").strip()
        out.append({
            "num": row.get("Inquiry no", ""),
            "customer": row.get("Customer", ""),
            "item": row.get("Product asked", ""),
            "qty": row.get("Quantity", ""),
            "amount": rupees(row.get("Quotation value")),
            "status": status or reg.NEW,
            "tone": status_tone(status),
        })
    return out


def rupees(value, compact: bool = False) -> str:
    """A register amount as the reader expects to see it.

    The register stores plain digits on purpose — a currency symbol in the CSV
    turns the whole column into text for Excel (see register.money_str). So the
    symbol and the lakh grouping are put back here, at the point of display,
    using the same quoting.indian_currency() the quote documents already use.

    `compact` gives the dashboard form — ₹8.4L, ₹1.2Cr — because a headline
    figure is read at a glance and eleven digits is not a glance.
    """
    from decimal import Decimal
    try:
        amount = CB.get_register().money(value)
    except Exception:
        amount = Decimal(0)
    if not compact:
        if not amount:
            # An inquiry nobody has quoted has no amount, and "₹0.00" reads as
            # a quote for nothing rather than as an absence.
            return "—"
        text = CB.get_quoting().indian_currency(amount)
        # Whole rupees lose the paise, per the design. A register amount is
        # never priced to the paisa, and ".00" on every row is pure noise in a
        # column you scan vertically.
        return "₹" + (text[:-3] if text.endswith(".00") else text)
    number = float(amount)
    if abs(number) >= 1e7:
        return f"₹{number / 1e7:.1f}Cr"
    if abs(number) >= 1e5:
        return f"₹{number / 1e5:.1f}L"
    if abs(number) >= 1e3:
        return f"₹{number / 1e3:.0f}K"
    return f"₹{number:.0f}"


def status_tone(status: str) -> str:
    """Which Pill tone a register status wears.

    Won is green and lost is red in every role — see theme's semantic block.
    Everything mid-flight is accent, and a brand-new untouched inquiry is
    neutral, so "needs me to do something" and "already handled" are separable
    at a glance without reading a word.
    """
    reg = CB.get_register()
    status = (status or "").strip()
    if status == reg.CONVERTED:
        return "ok"
    if status == reg.NOT_CONVERTED:
        return "err"
    if status == reg.NEW:
        return "neutral"
    return "accent"


def waiting_view(cfg: dict, rows: list[dict] | None = None) -> list[dict]:
    """Quotations that have gone quiet — the "Waiting on a reply" tab."""
    rows = register_rows(cfg) if rows is None else rows
    if not rows:
        return []
    reg = CB.get_register()
    try:
        due = reg.awaiting_followup(rows)
    except Exception:
        return []
    today = date.today()
    out = []
    for row in due:
        sent = reg.parse_date(row.get("Quotation date", "")) or today
        count = str(row.get("Reminders sent") or "0").strip() or "0"
        try:
            n = int(float(count))
        except ValueError:
            n = 0
        out.append({
            "customer": row.get("Customer", ""),
            "item": row.get("Product asked", ""),
            "sent_days": max(0, (today - sent).days),
            "reminders": (f"{n} reminder{'s' if n != 1 else ''} sent"
                          if n else "Not yet due"),
            "num": row.get("Inquiry no", ""),
        })
    return out
