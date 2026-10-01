"""
Prism — the record of every email sent from this computer
───────────────────────────────────────────────────────────
One plain JSON file, `~/Prism Email/sent.json`, one entry per press of Send:
when, to whom, the subject, who got it and who did not, what was attached.
The Email screen reads it back as a table, so "did that go?" is answered by
looking, not by remembering.

It is a file in a folder the owner can open, on purpose — the same rule the
inquiry register follows. A History run record is still written as well
(that is what the History screen reads); this one is the owner's copy, in
the owner's words, and it survives whatever History does.

The folder can be moved with cfg["email"]["folder"]; tests point it at a
temp directory the same way.
"""
from __future__ import annotations

from send_ledger import (  # noqa: E402,F401  (the ledger itself lives there)
    DEFAULT_DIR, FILE, KEEP, folder, load, path, record, sent_today)


# ── words for the table ───────────────────────────────────────────────────────

def describe_to(entry: dict) -> str:
    to = entry.get("to") or []
    if not to:
        return "—"
    if len(to) == 1:
        first = to[0]
        name = (first.get("name") or "").strip()
        return f"{name} <{first['email']}>" if name else first.get("email", "—")
    if entry.get("list_name"):
        return f"{len(to)} people ({entry['list_name']})"
    return f"{len(to)} people"


def describe_result(entry: dict) -> str:
    sent = len(entry.get("sent") or [])
    failed = len(entry.get("failed") or [])
    total = len(entry.get("to") or [])
    if entry.get("stopped"):
        return f"Stopped after {sent}"
    if failed and sent:
        return f"{sent} sent, {failed} failed"
    if failed:
        return "Failed" if total <= 1 else f"All {failed} failed"
    return "Sent" if total <= 1 else f"All {sent} sent"
