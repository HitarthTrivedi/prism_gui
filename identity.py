"""Who Prism thinks you are, for the rest of the app to ask.

One module, one question: `identity.current()` → the signed-in member. Every
screen that cares about role, colour, folder or visibility reads it from here
rather than reaching into licensing or workspace itself.

    {"mid": "sales-ravi", "name": "Ravi", "role": "sales",
     "org": "lic_8842", "admin": False}

Where it comes from
───────────────────
The designation key stored beside the licence, verified on every read against
the company licence currently on the machine (licensing/designation.py). If
there is no designation key — the single-user case, which is still most
customers — the answer is the personal identity: no role, Prism's own colour,
one folder, everything exactly as it was before roles existed.

Verified on read, not trusted from a settings file. The verification is a
signature check over a few hundred bytes, so doing it properly costs nothing
and means there is no cached "I am the manager" for anyone to edit.

Viewing as somebody else
────────────────────────
An admin can look into another member's profile — that is the whole reason an
MD buys this. `view_as()` changes which folder the History and files screens
read, and NOTHING else: it cannot grant a permission, it is never persisted,
and it is refused outright if the signed-in member is not an admin. The real
identity stays `current()` throughout, so anything that writes still writes as
the actual person.
"""
from __future__ import annotations

import threading

import licensing
import roles as R
import workspace as W
from licensing import designation, keys

_lock = threading.Lock()
_cached: dict | None = None
_viewing: dict | None = None      # an admin looking at someone else. Never saved.

PERSONAL = {"mid": W.SOLO, "name": "", "role": "", "org": "", "admin": False}


def _compute() -> dict:
    data = licensing.store.load(licensing.user_dir())
    key = (data.get("designation") or "").strip()
    if not key:
        return dict(PERSONAL)

    org = licensing.state().license_id
    if not org:
        # A designation key without a company licence means nothing — it is
        # the licence that says the firm has paid. Fall back to personal
        # rather than to the role the unverifiable key claims.
        return dict(PERSONAL)

    try:
        claims = designation.verify(key, org=org, public_keys=keys.public_keys())
    except licensing.TokenError:
        # A key that no longer verifies (licence re-issued, key tampered with)
        # drops this copy to personal. Deliberately NOT to an error state: the
        # member can still do their own work, and the alternative is a laptop
        # that will not open because somebody renewed a licence.
        return dict(PERSONAL)

    role = claims.get("role", "")
    return {
        "mid": claims.get("mid") or W.SOLO,
        "name": claims.get("name") or "",
        "role": role if R.get(role) else "",
        "org": org,
        "admin": R.is_admin(role),
    }


def current() -> dict:
    """The real signed-in member. Cached; call reload() after activation."""
    global _cached
    with _lock:
        if _cached is None:
            try:
                _cached = _compute()
            except Exception:              # noqa: BLE001
                # Same principle as licensing.state(): an unexpected failure
                # in here must never lock somebody out of their own work.
                _cached = dict(PERSONAL)
        return dict(_cached)


def display_name(cfg: dict | None = None) -> str:
    """What to call this person on screen, or "" if nobody has said.

    A team member's name arrives inside their signed designation key and is
    not the customer's to type. A SOLO copy has no key and therefore had no
    name at all — every screen called them "This computer", permanently, with
    nowhere to change it. So the config carries a plain display name for that
    case, and the signed one still wins wherever it exists: a member cannot
    rename themselves past what their firm issued.

    Below both of those, the licence key itself already carries a name — who
    the licence was sold to (a solo buyer's own name, or the firm's, for a
    team) — so a copy that has activated a licence but typed nothing of its
    own reads as that name rather than the generic "This computer" every
    caller falls back to. It is not cached the way `current()` is: the
    licence can be changed or released without touching a designation key, so
    this reads licensing.state() fresh each call.
    """
    signed = (current().get("name") or "").strip()
    if signed:
        return signed
    typed = str((cfg or {}).get("display_name") or "").strip()
    if typed:
        return typed
    return (licensing.state().customer or "").strip()


def reload() -> dict:
    """Forget the cached identity — after activating a designation key."""
    global _cached, _viewing
    with _lock:
        _cached = None
        _viewing = None
    return current()


def activate(key: str) -> dict:
    """Store and adopt a designation key. Raises TokenError if it is not ours,
    not for this licence, or altered."""
    org = licensing.state().license_id
    if not org:
        raise licensing.TokenError(
            "no_licence",
            "Enter your company licence key first — a designation key only "
            "works alongside it.")
    claims = designation.verify(key.strip(), org=org,
                                public_keys=keys.public_keys())
    licensing.store.update(licensing.user_dir(), designation=key.strip())
    return reload()


def clear() -> dict:
    """Drop the designation key and go back to a personal copy."""
    licensing.store.update(licensing.user_dir(), designation="")
    return reload()


# ── viewing as somebody else ───────────────────────────────────────────────
def view_as(mid: str | None) -> dict:
    """Point the reading screens at another member's folder.

    Refused unless the signed-in member is an admin, and refused for anyone
    outside what workspace.readable_members() allows — so the check lives in
    one place and this cannot drift away from it.
    """
    global _viewing
    me = current()
    if not mid or mid == me["mid"]:
        _viewing = None
        return me
    if not me["admin"]:
        raise PermissionError("Only an owner or manager can open another "
                              "member's profile.")
    import core_bridge as CB
    cfg = CB.config.load()
    if not W.may_read(cfg, me, mid):
        raise PermissionError("That member is not in your workspace.")
    entry = next(m for m in W.readable_members(cfg, me) if m["mid"] == mid)
    _viewing = {"mid": mid, "name": entry.get("name", ""),
                "role": entry.get("role", ""), "org": me["org"],
                "admin": False}
    return dict(_viewing)


def viewing() -> dict:
    """Whose work the reading screens should show — the member being viewed
    if an admin has switched, otherwise the signed-in member."""
    with _lock:
        if _viewing is not None:
            return dict(_viewing)
    return current()


def is_viewing_other() -> bool:
    return _viewing is not None


def hue() -> int:
    """The accent colour for this copy of Prism."""
    return R.hue(current().get("role", ""))


def describe() -> str:
    """One line for the window title and the rail: 'Ravi · Sales'."""
    me = current()
    label = R.label(me.get("role", ""))
    name = me.get("name", "")
    if name and label:
        return f"{name} · {label}"
    return name or label or ""
