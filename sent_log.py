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

import datetime as _dt
import json
import os
import tempfile

DEFAULT_DIR = os.path.join(os.path.expanduser("~"), "Prism Email")
FILE = "sent.json"
KEEP = 5000


def folder(cfg: dict) -> str:
    return ((cfg or {}).get("email") or {}).get("folder") or DEFAULT_DIR


def path(cfg: dict) -> str:
    return os.path.join(folder(cfg), FILE)


def load(cfg: dict) -> list[dict]:
    """Every entry, newest first. A missing or unreadable file is an empty
    list — the screen must open whatever state the disk is in."""
    try:
        with open(path(cfg), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [e for e in reversed(data) if isinstance(e, dict)]


def record(cfg: dict, *, to: list[dict], subject: str, body: str,
           sent: list[str], failed: list, attachments: list[str],
           list_name: str = "", stopped: bool = False) -> dict:
    """Append one entry and return it. Never raises into a send that has
    already gone out — a log that cannot be written is reported, not fatal."""
    now = _dt.datetime.now()
    entry = {
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M"),
        "to": [{"email": r.get("email", ""), "name": r.get("name", "")}
               for r in to],
        "subject": subject,
        "body": body,
        "sent": list(sent),
        "failed": [[e, str(err)] for e, err in failed],
        "attachments": list(attachments),
        "list_name": list_name,
        "stopped": bool(stopped),
    }
    entries = list(reversed(load(cfg)))
    entries.append(entry)
    entries = entries[-KEEP:]
    os.makedirs(folder(cfg), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".sent-", suffix=".json", dir=folder(cfg))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path(cfg))
    return entry


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
