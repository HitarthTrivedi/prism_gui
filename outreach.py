"""Cold outreach, written into the inquiry register the sales team already has.

Pure functions over plain dicts and one file. No Qt, no widgets, and the
engine only ever through `core_bridge` -- the same shape, and for the same
reason, as `email_config.py` and `inquiry_config.py` next door.

Why this is a root module rather than something inside `addons/leads/`:
both Leads & Outreach and Email inquiry automation have to agree on what a
`Stage` of "Emailed" means, and no add-on may import another. Putting these
readers in either package would couple the two add-ons -- the exact coupling
the add-on split exists to remove. Both import this instead.

────────────────────────────────────────────────────────────────────────────
One book
────────────────────────────────────────────────────────────────────────────
A lead that has been mailed is written into `inquiries.csv` as an ordinary
register row. Not a second spreadsheet: the register is already the file the
team opens in Excel on the shared drive, and `core/register.py` already
solves atomic writes, the Excel lock and -- the part that matters here --
reading forgivingly enough that a human can add a column or type a row
without Prism destroying it.

Everything outreach needs rides in four EXTRA columns. They are deliberately
not members of `register.COLUMNS`: `save()` unions the known columns with
whatever else it finds, so extras round-trip untouched and the engine does
not have to change at all.

    Source          who put this row here -- Outreach / Inbound / Sales
    Stage           where the cold approach has got to
    Touches         how many nudges have gone
    Do not email    THE HUMAN'S COLUMN. Anything in it and we never send.

`Do not email` is the only one a person is expected to write, and it is the
brake: a wrong address, a colleague, somebody who asked to be left alone.
Blank on almost every row, so it costs the team nothing until it is needed.

────────────────────────────────────────────────────────────────────────────
How a reply finds its way home
────────────────────────────────────────────────────────────────────────────
Nothing here stores a Message-ID, because `mailer.send_bulk()` returns
`(sent, failed)` and never hands one back. It does not need to:
`register.find_by_thread()` already falls back to matching the sender's
address against `row["Email"]` across the OPEN statuses, and an outreach row
is `Status = "New"` -- which is an open status -- precisely so that it
qualifies. Proven code, no engine signature to widen.
"""
from __future__ import annotations

import datetime
import os
import threading

# ── the four extra columns ───────────────────────────────────────────────
SOURCE = "Source"
STAGE = "Stage"
TOUCHES = "Touches"
DO_NOT_EMAIL = "Do not email"

COLUMNS = (SOURCE, STAGE, TOUCHES, DO_NOT_EMAIL)

# ── who put the row here ─────────────────────────────────────────────────
OUTREACH = "Outreach"       # found by Leads and mailed by Prism
INBOUND = "Inbound"         # arrived by itself; the register's normal case
SALES = "Sales"             # typed into the sheet by a person

# ── where a cold approach has got to ─────────────────────────────────────
TO_EMAIL = "To email"       # queued, nothing sent yet
EMAILED = "Emailed"         # the opener has gone
REPLIED = "Replied"         # they answered -- it is an ordinary inquiry now

PENDING_STAGES = (TO_EMAIL, EMAILED)

GUIDE_FILENAME = "How to use this sheet.txt"

# One process writes this file (see docs/DEFERRED.md, "One register, one
# writer"). Within it, the Leads screen and the Inquiry screen can both
# reach the register, so every read-modify-write here takes this lock and
# every one of them re-reads from disk rather than trusting a list it has
# been holding. `register.save()` rewrites the WHOLE file from whatever it
# is handed -- a stale list silently erases rows somebody else just added.
LOCK = threading.RLock()


def _register():
    """The engine's register module. Imported late so this file stays
    importable in a bare interpreter and cheap to import in a test."""
    import core_bridge as CB
    return CB.get_register()


def _today() -> str:
    return datetime.date.today().strftime("%d-%m-%Y")


# ── reading a row ────────────────────────────────────────────────────────

def source_of(row: dict) -> str:
    return (row.get(SOURCE) or "").strip()


def stage_of(row: dict) -> str:
    return (row.get(STAGE) or "").strip()


def touches_of(row: dict) -> int:
    """How many nudges have gone. Junk reads as none -- a person typing
    "two" into the cell must not stop the row being chased."""
    try:
        return int(str(row.get(TOUCHES) or "0").strip() or 0)
    except ValueError:
        return 0


def is_blocked(row: dict) -> bool:
    """The human brake. Anything at all in the cell means never send."""
    return bool((row.get(DO_NOT_EMAIL) or "").strip())


def is_pending(row: dict) -> bool:
    """A cold approach that has not been answered yet.

    These are kept out of the daily worklist tabs: a few hundred of them
    would bury the handful of real inquiries that arrived this morning,
    which is the opposite of the point.
    """
    return stage_of(row) in PENDING_STAGES


def is_outreach(row: dict) -> bool:
    """Any row this module put in the book, answered or not."""
    return source_of(row) in (OUTREACH, SALES) or bool(stage_of(row))


# ── where the book lives ─────────────────────────────────────────────────

def register_path(cfg: dict) -> str:
    """The register CSV, or "" when Email inquiry automation is not set up.

    Empty is a real answer, not a failure: a customer who bought Leads and
    not Inquiry has no book to write into, and every caller here treats ""
    as "do nothing" rather than inventing a folder in their home directory.
    """
    folder = ((cfg or {}).get("inquiry") or {}).get("folder") or ""
    folder = folder.strip()
    if not folder:
        return ""
    return os.path.join(folder, _register().FILENAME)


# ── building a row ───────────────────────────────────────────────────────

def row_for_lead(lead: dict, rows: list[dict]) -> dict:
    """One register row for one person we are about to mail.

    `lead` is a plain dict -- company / name / email / product -- so this
    module never imports the prospector. The offering side shapes the data;
    the same rule an intent handler follows.

    The number is not decoration. `register.merge_in()` keys on `Inquiry no`
    when there is one and falls back to (email, date, product) when there is
    not -- and a batch of leads with no number and a blank product line
    would collapse into a single row on that fallback. Numbering every row
    is what stops that.
    """
    reg = _register()
    row = reg.blank_row()
    row["Inquiry no"] = reg.next_number(rows)
    row["Date received"] = _today()
    row["Customer"] = (lead.get("company") or "").strip()
    row["Contact person"] = (lead.get("name") or "").strip()
    row["Email"] = (lead.get("email") or "").strip()
    row["Product asked"] = (lead.get("product") or "").strip()
    row["Status"] = reg.NEW
    row["Last contact"] = _today()
    row[SOURCE] = OUTREACH
    row[STAGE] = EMAILED
    row[TOUCHES] = "1"
    row[DO_NOT_EMAIL] = ""
    return row


def adopt_hand_rows(rows: list[dict]) -> int:
    """Number and stamp the rows a person typed. Returns how many.

    Sales adds somebody by typing an address into a blank row and nothing
    else -- no number, no status, no box to tick. That is the whole
    interaction, and it is deliberately the smallest one available.

    A row is theirs if it has an address, no number and no Source. Mutates
    in place, because the caller is holding the list it will save, and is
    idempotent: once stamped, a row no longer matches.
    """
    reg = _register()
    adopted = 0
    for row in rows:
        if (row.get("Email") or "").strip() and \
                not (row.get("Inquiry no") or "").strip() and \
                not source_of(row):
            row["Inquiry no"] = reg.next_number(rows)
            row["Date received"] = row.get("Date received") or _today()
            row["Status"] = (row.get("Status") or "").strip() or reg.NEW
            row[SOURCE] = SALES
            row[STAGE] = TO_EMAIL
            row[TOUCHES] = "0"
            adopted += 1
    return adopted


# ── the outreach queue ───────────────────────────────────────────────────

def queued(rows: list[dict]) -> list[dict]:
    """Rows waiting for their first message -- what sales typed in."""
    return [r for r in rows
            if stage_of(r) == TO_EMAIL
            and (r.get("Email") or "").strip()
            and not is_blocked(r)]


def due_touches(rows: list[dict], after_days: int = 3,
                max_touches: int = 2, today=None) -> list[dict]:
    """Cold approaches that have gone quiet and are owed a nudge.

    The register is the schedule, exactly as it is for the quotation chaser
    next door: who is due comes from `Touches` and `Last contact`, two
    columns the owner can see and edit, and there is no second hidden queue
    to drift out of step with them.

    Deliberately a parallel to `register.awaiting_followup()` rather than a
    widening of it. That one gates on a Status of Quoted / Following up /
    Negotiating, which a cold lead at "New" can never hold, and teaching it
    about stages would mean changing the engine for a rule that only makes
    sense on this side.
    """
    today = today or datetime.date.today()
    reg = _register()
    due = []
    for row in rows:
        if stage_of(row) != EMAILED or is_blocked(row):
            continue
        if not (row.get("Email") or "").strip():
            continue
        if touches_of(row) >= max_touches:
            continue
        last = reg.parse_date(row.get("Last contact", ""))
        if last and (today - last).days >= after_days:
            due.append(row)
    return due


def note_touch(row: dict, today=None) -> None:
    """Count a nudge that actually went out.

    Not `register.note_reminder()`, which forces Status to "Following up" --
    correct for a quotation being chased, wrong here, where it would make a
    cold lead read as a job we have already priced.
    """
    when = today or datetime.date.today()
    row[TOUCHES] = str(touches_of(row) + 1)
    row["Last contact"] = when.strftime("%d-%m-%Y")


def mark_emailed(row: dict, today=None) -> None:
    """The opener has gone: the row is now waiting for an answer."""
    when = today or datetime.date.today()
    row[STAGE] = EMAILED
    row[TOUCHES] = str(max(1, touches_of(row)))
    row["Last contact"] = when.strftime("%d-%m-%Y")


def mark_replied(row: dict) -> None:
    """They answered. From here it is an ordinary inquiry and every path
    that already exists -- quote, chase, negotiate, PO -- takes it."""
    row[STAGE] = REPLIED


# ── writing the book ─────────────────────────────────────────────────────

def push_leads(cfg: dict, leads: list[dict]) -> tuple[int, int]:
    """Write the people we have just mailed into the register.

    `leads` are plain dicts -- company / name / email / product. The numbers
    are allocated HERE, inside the lock, against the register as it is on
    disk at this moment. Allocating them earlier is the obvious shape and
    the wrong one twice over: every row in one batch would be handed the
    same number, and a number chosen before the lock can be taken by
    somebody else's row before we write.

    Returns (added, skipped). Raises the engine's RegisterLocked when the
    file is open in Excel -- the caller shows that message as it stands,
    because it already says the useful thing.
    """
    path = register_path(cfg)
    if not path or not leads:
        return 0, 0
    reg = _register()
    with LOCK:
        # A mail check is holding a snapshot of this file and will write it
        # back when the fetch finishes; anything added now would be inside
        # that window and lost. The caller offers "try again in a moment".
        if check_in_flight():
            return 0, 0
        rows = reg.load(path)
        # Skip anyone already on the book. merge_in cannot catch a repeat
        # here -- a retry would allocate fresh numbers and every row would
        # look new -- so the address is what makes pressing Send again after
        # "close inquiries.csv in Excel" safe.
        known = {(r.get("Email") or "").strip().lower()
                 for r in rows if (r.get("Email") or "").strip()}
        fresh, skipped = [], 0
        for lead in leads:
            email = (lead.get("email") or "").strip().lower()
            if not email:
                continue
            if email in known:
                skipped += 1
                continue
            known.add(email)
            # Appended as we go so the next number sees the last one.
            row = row_for_lead(lead, rows + fresh)
            fresh.append(row)
        if not fresh:
            return 0, skipped
        merged, added, _ = reg.merge_in(rows, fresh)
        if added:
            reg.save(merged, path)
    return added, skipped


def save_merging(rows: list[dict], path: str) -> tuple[list[dict], int]:
    """Write `rows`, keeping anything that reached the file meanwhile.

    The whole answer to "register.save() is whole-file, from memory". A
    screen holds the register in a list from the moment it opens; if it
    writes that list back an hour later, every row anything else added in
    between is gone, with no error and nothing to find afterwards.

    Under the lock: re-read the disk and `merge_in(rows, disk)`. That
    returns the caller's OWN dict objects first -- so `_visible_rows`,
    `_followup_rows` and every `id(row)` comparison on the screen survive
    -- and appends only the disk rows it has not seen. Returns
    (merged, how many were rescued).

    Deletes are the one thing merging cannot express, so `drop_row` leaves
    a tombstone and this drops those rows from BOTH sides. Without it, any
    list still holding a deleted row writes it straight back the next time
    it saves -- which is worse than the clobber this function exists to fix,
    because a row the owner deliberately removed reappears.
    """
    if not path:
        return list(rows), 0
    reg = _register()
    with LOCK:
        disk = reg.load(path)
        merged, rescued, _ = reg.merge_in(list(rows), disk)
        gone = _dropped.get(os.path.abspath(path))
        if gone:
            merged = [r for r in merged
                      if (r.get("Inquiry no") or "").strip().lower()
                      not in gone]
        reg.save(merged, path)
    return merged, rescued


# Numbers somebody has deleted in this session. `save_merging` merges rows
# back off the disk, which is how a screen's stale snapshot stops erasing
# other people's work -- but the same mechanism would resurrect a row the
# owner deliberately removed, from any list still holding it. A tombstone
# is the smallest thing that makes "deleted" mean deleted. In memory only:
# one machine writes this file, so the process is the unit that matters,
# and a tombstone file on a shared drive is a new thing to go stale.
#
# Keyed by FILE as well as number, because an inquiry number is only unique
# within one book -- two customers' registers both start at 0001, and so do
# two temp directories in one test run.
_dropped: dict = {}


def drop_row(path: str, inquiry_no: str) -> bool:
    """Remove one row by number, under the lock, from a fresh read.

    Its own function because `save_merging` is exactly wrong here: it would
    read the row back off the disk and restore it on the very next write.
    The one case where merging is not what you want.
    """
    if not path or not (inquiry_no or "").strip():
        return False
    reg = _register()
    wanted = inquiry_no.strip().lower()
    with LOCK:
        _dropped.setdefault(os.path.abspath(path), set()).add(wanted)
        rows = reg.load(path)
        keep = [r for r in rows
                if (r.get("Inquiry no") or "").strip().lower() != wanted]
        if len(keep) == len(rows):
            return False
        reg.save(keep, path)
    return True


# ── standing aside for the mail check ────────────────────────────────────
#
# `mailflow.check()` loads the register, fetches IMAP, and saves at the end
# -- seconds to minutes later, on a worker thread. It is engine code in a
# submodule shared with the CLI, so it may not import this module and may
# not take this lock; and holding the lock across a mail fetch would freeze
# every save on the UI thread behind it.
#
# So the push stands aside instead. `begin_check` sets the flag under the
# lock and `push_leads` tests it under the lock, which is mutual exclusion
# with no waiting: a push cannot start inside a check, and a check cannot
# start inside a push. It costs the leads user at most one "try again in a
# moment" while the mail is being read.
_check_depth = 0


def begin_check() -> None:
    global _check_depth
    with LOCK:
        _check_depth += 1


def end_check() -> None:
    global _check_depth
    with LOCK:
        _check_depth = max(0, _check_depth - 1)


def check_in_flight() -> bool:
    with LOCK:
        return _check_depth > 0


def apply_to_row(cfg: dict, inquiry_no: str, change) -> bool:
    """Re-read the book, change one row by number, write it back.

    The safe shape for every edit this module and the Inquiry screen make
    between full refreshes: the row that gets changed is the one on disk
    now, not the one the screen was holding when the user clicked.
    """
    path = register_path(cfg)
    if not path or not inquiry_no:
        return False
    reg = _register()
    with LOCK:
        rows = reg.load(path)
        row = reg.find(rows, inquiry_no)
        if row is None:
            return False
        change(row)
        reg.save(rows, path)
    return True


# ── the sheet explains itself ────────────────────────────────────────────

_GUIDE = """How to use this sheet
=====================

This is your inquiry book. Prism writes to it and so can you.

Prism fills in every column except one.

  Do not email    This column is yours. Put anything in it -- an x will do
                  -- and Prism will never send that person a message. Use
                  it for a wrong address, for somebody in your own company,
                  or for anyone who has asked to be left alone.

To add somebody, type their email address into a blank row at the bottom.
Nothing else is needed -- no number, no status. Prism fills the rest in the
next time it runs, and sends them an opening message.

What the columns mean

  Source          Outreach = Prism found them.  Sales = you typed them in.
                  Inbound  = they wrote to us first.
  Stage           To email = queued.  Emailed = the opener has gone.
                  Replied  = they answered, and it is a normal inquiry now.
  Touches         How many follow-up nudges have been sent.

Two things worth knowing

  Sorting or filtering in Excel is fine -- do as you like. But if you MOVE
  or RENAME a column, Prism puts it back where it was the next time it
  writes. Add your own columns at the end if you need them; those are kept.

  Close this file in Excel when you are done. While it is open on your
  screen Prism cannot write to it, and it will tell you so rather than
  losing anything.
"""


def write_sheet_guide(cfg: dict) -> str:
    """Drop a short explainer beside the register, once.

    The people who live in this sheet all day may never open Prism's own
    screens, so the sheet has to say what it is. Never overwritten: if it
    is there, somebody may have added to it.
    """
    path = register_path(cfg)
    if not path:
        return ""
    guide = os.path.join(os.path.dirname(path), GUIDE_FILENAME)
    if os.path.exists(guide):
        return guide
    try:
        os.makedirs(os.path.dirname(guide), exist_ok=True)
        with open(guide, "w", encoding="utf-8") as f:
            f.write(_GUIDE)
    except OSError:
        return ""
    return guide
