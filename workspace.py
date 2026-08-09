"""Where each person's work lives, and who is allowed to read it.

────────────────────────────────────────────────────────────────────────────
The layout
────────────────────────────────────────────────────────────────────────────
    <workspace root>/                 chosen in Settings. Local by default;
      prism-team.json                 point it at a Google Drive Desktop,
      _company/                       OneDrive, Dropbox or network folder and
      members/                        the whole team shares one workspace.
        sales-ravi/
          runs/          this person's history
          files/         this person's working files
        marketing-nita/
          runs/
          files/

    ~/.prism/                         NEVER shared, whatever the root is:
      config.json                     their Groq key, their agent choices
      license.json                    their licence and designation key
      chrome/                         their browser profile

That split is the point. The manager needs to read what the team produced, so
runs and files go in the workspace. The manager has no business holding
somebody's API key, so settings and credentials stay on the member's own
machine and are never written to the shared folder at all.

`_company/` is the shared shelf — brand assets, templates, the price list.
Every role can read it; only an admin writes to it.

────────────────────────────────────────────────────────────────────────────
Who sees what
────────────────────────────────────────────────────────────────────────────
readable_members() is the single answer to that question, and every screen
that lists work goes through it:

    a working role   → exactly one folder, their own
    an admin role    → every member's folder
    no role at all   → one folder, the personal default

There is one place the rule is written and one function that applies it. A
second copy of the rule is how a History dialog ends up showing everything to
everybody six months from now.

────────────────────────────────────────────────────────────────────────────
What this does not do
────────────────────────────────────────────────────────────────────────────
Prism enforces this; the operating system does not. If the workspace is on a
shared drive that a member's laptop can reach, that member can open Finder and
read another role's folder. Prism will not show it to them; the filesystem
will hand it over.

Say so plainly to a customer who asks. The part that IS solid is the role
itself: it comes from a signed designation key and cannot be changed by
editing anything on the machine.
"""
from __future__ import annotations

import json
import os
import re
import time

import paths
import roles as R

TEAM_FILE = "prism-team.json"
COMPANY_DIR = "_company"
MEMBERS_DIR = "members"

# Used when Prism has no company licence at all — the single-user case, which
# is still most customers. One member, no role, everything as it always was.
SOLO = "personal"


# ── where the root is ──────────────────────────────────────────────────────
def default_root() -> str:
    """A local workspace, for someone who has not pointed Prism anywhere."""
    return paths.user_dir("workspace")


def root(cfg: dict | None = None) -> str:
    """The workspace root. Settings can move it onto a shared/synced folder.

    Falls back to the local default if the configured path has gone — an
    unplugged network drive or a signed-out Drive client must not take the app
    down, and a member who cannot reach the share should still be able to
    work.
    """
    configured = ((cfg or {}).get("workspace_root") or "").strip()
    if configured:
        expanded = os.path.expanduser(configured)
        if os.path.isdir(expanded):
            return expanded
        # Only fall back for a path that has vanished. A path that merely does
        # not exist yet is created below, because that is a first run.
        parent = os.path.dirname(expanded.rstrip(os.sep))
        if parent and os.path.isdir(parent):
            return expanded
    return default_root()


def is_shared(cfg: dict | None = None) -> bool:
    """True when the workspace looks like a synced or network folder.

    Used to word the UI honestly — a member should be told when their work is
    landing somewhere their manager can read.

    Reads what was CONFIGURED, not what root() resolved to. A share that is
    unreachable right now still means this member's work is destined for it,
    and root() would have fallen back to the local folder — telling them their
    work is private on the one afternoon the office NAS is down is exactly the
    wrong time to be reassuring.
    """
    configured = ((cfg or {}).get("workspace_root") or "").strip()
    path = (configured or root(cfg)).replace("\\", "/").lower()
    markers = ("google drive", "googledrive", "/gdrive", "dropbox",
               "onedrive", "icloud", "/volumes/", "//", "nextcloud", "box sync")
    return any(m in path for m in markers)


# ── member ids ─────────────────────────────────────────────────────────────
def slug(text: str) -> str:
    """A folder-safe piece of a member id."""
    cleaned = re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower())
    return cleaned.strip("-")[:32]


def member_id(role: str, name: str) -> str:
    """The stable folder name for a person: role first, so an `ls` of the
    workspace reads as an org chart rather than an alphabetical list."""
    parts = [p for p in (slug(role), slug(name)) if p]
    return "-".join(parts) or SOLO


# ── the roster ─────────────────────────────────────────────────────────────
def team_path(cfg: dict | None = None) -> str:
    return os.path.join(root(cfg), TEAM_FILE)


def load_team(cfg: dict | None = None) -> list[dict]:
    """Everyone the manager has registered: [{mid, name, role}, …].

    Lives in the workspace rather than in config.json so that one shared
    folder describes the whole team — a new member pointed at the workspace
    picks up the roster without anybody re-typing it.
    """
    try:
        with open(team_path(cfg), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    members = data.get("members")
    if not isinstance(members, list):
        return []
    out = []
    for m in members:
        if isinstance(m, dict) and m.get("mid") and m.get("role"):
            out.append({"mid": str(m["mid"]), "name": str(m.get("name") or ""),
                        "role": str(m["role"])})
    return out


def save_team(members: list[dict], cfg: dict | None = None) -> None:
    """Write the roster. Admin-only at the UI level; not enforced here,
    because a member whose laptop can write the folder can write the file
    whatever this function does."""
    target = root(cfg)
    os.makedirs(target, exist_ok=True)
    payload = {
        "_comment": "Prism team roster. One entry per person with a "
                    "designation key. Managed from Settings → Team.",
        "updated": int(time.time()),
        "members": [{"mid": m["mid"], "name": m.get("name", ""),
                     "role": m["role"]} for m in members],
    }
    tmp = team_path(cfg) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, team_path(cfg))


def upsert_member(cfg: dict, mid: str, name: str, role: str) -> list[dict]:
    """Add or update one person in the roster, keyed on member id."""
    members = [m for m in load_team(cfg) if m["mid"] != mid]
    members.append({"mid": mid, "name": name, "role": role})
    members.sort(key=lambda m: (R.ORDER.index(m["role"])
                                if m["role"] in R.ORDER else 99, m["name"]))
    save_team(members, cfg)
    return members


# ── per-member folders ─────────────────────────────────────────────────────
def member_dir(mid: str, cfg: dict | None = None, *parts: str) -> str:
    return os.path.join(root(cfg), MEMBERS_DIR, mid or SOLO, *parts)


def ensure_member(mid: str, cfg: dict | None = None) -> str:
    """Create this member's folders if they are not there yet."""
    base = member_dir(mid, cfg)
    for sub in ("runs", "files"):
        os.makedirs(os.path.join(base, sub), exist_ok=True)
    os.makedirs(os.path.join(root(cfg), COMPANY_DIR), exist_ok=True)
    return base


def _is_solo(mid: str, cfg: dict | None = None) -> bool:
    """A single-user copy that has not been pointed at a shared workspace."""
    return (mid or SOLO) == SOLO and root(cfg) == default_root()


def runs_dir(mid: str, cfg: dict | None = None) -> str:
    """Where this member's history lives.

    A personal copy keeps using ~/.prism/runs, the folder it has always used.
    That is not tidiness — it is the difference between an existing customer
    upgrading and finding their history where they left it, and one upgrading
    to an empty History window and concluding Prism threw their work away.
    Nothing is migrated, because nothing needs to be: only a company install
    with a designation key ever moves.
    """
    if _is_solo(mid, cfg):
        return paths.user_dir("runs")
    return member_dir(mid, cfg, "runs")


def files_dir(mid: str, cfg: dict | None = None) -> str:
    return member_dir(mid, cfg, "files")


def company_dir(cfg: dict | None = None) -> str:
    """The shared shelf every role may read."""
    return os.path.join(root(cfg), COMPANY_DIR)


def known_members(cfg: dict | None = None) -> list[str]:
    """Member ids that actually have a folder, roster or no roster.

    Read off the filesystem rather than from prism-team.json so a manager
    still sees somebody's work if the roster file is stale or was never
    written — the folder is the fact, the roster is the description.
    """
    base = os.path.join(root(cfg), MEMBERS_DIR)
    try:
        return sorted(d for d in os.listdir(base)
                      if os.path.isdir(os.path.join(base, d))
                      and not d.startswith("."))
    except OSError:
        return []


# ── the access rule ────────────────────────────────────────────────────────
def readable_members(cfg: dict, identity: dict | None = None) -> list[dict]:
    """Every member this copy of Prism may show, most relevant first.

    THE access rule. Every screen that lists work — History, the files panel,
    the completion window — asks this and shows only what comes back.

    Returns [{mid, name, role, is_self}], with the signed-in member first so
    an admin opening History still sees their own work at the top.
    """
    me = (identity or {}).get("mid") or SOLO
    my_role = (identity or {}).get("role") or ""
    roster = {m["mid"]: m for m in load_team(cfg)}

    if not R.is_admin(my_role):
        # A working role sees itself and nothing else. Not filtered from a
        # longer list — the longer list is never built.
        entry = roster.get(me, {"mid": me, "name": (identity or {}).get("name", ""),
                                "role": my_role})
        return [{**entry, "is_self": True}]

    seen, out = set(), []
    for mid in [me] + [m["mid"] for m in load_team(cfg)] + known_members(cfg):
        if mid in seen:
            continue
        seen.add(mid)
        entry = roster.get(mid, {"mid": mid, "name": "", "role": ""})
        out.append({**entry, "is_self": mid == me})
    return out


def unreachable(cfg: dict | None = None) -> str:
    """"" if all is well, else what to tell the member.

    root() silently falls back to the local folder when a share is missing, so
    nothing is ever lost — but silence is the problem. The member keeps
    working and their manager sees an empty profile for that day, and draws
    the wrong conclusion about both.
    """
    configured = ((cfg or {}).get("workspace_root") or "").strip()
    if not configured:
        return ""
    if os.path.isdir(os.path.expanduser(configured)):
        return ""
    return ("Your team workspace can't be reached, so today's work is being "
            "saved on this computer only — it will not appear for your "
            "manager until the folder is back. Check that your shared drive "
            "is connected, or that Google Drive is signed in.")


def may_read(cfg: dict, identity: dict | None, mid: str) -> bool:
    """Is this member's folder readable by whoever is signed in?"""
    return any(m["mid"] == mid for m in readable_members(cfg, identity))
