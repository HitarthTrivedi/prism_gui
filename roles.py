"""Who is sitting in front of Prism, and what that means.

────────────────────────────────────────────────────────────────────────────
The shape of the thing
────────────────────────────────────────────────────────────────────────────
A company buys ONE licence and gets two kinds of key:

    company key      PRSM-…    identifies the firm. Everyone types this.
    designation key  PRSD-…    identifies the person's job. One per member.

The designation key is what decides which role this copy of Prism runs as.
It is checked against the company key rather than being free text, so nobody
promotes themselves to Manager by editing a settings file — see
licensing/designation.py for how that check works.

Each role gets:

  · its own folder in the workspace, and sees nothing outside it
  · its own history — what THIS person asked Prism to do
  · a default set of pipeline stages and add-ons suited to the job
  · its own accent colour, so a glance at the window says whose copy it is

Roles marked `admin` (Owner and Manager) are the exception: they can switch
into any other member's profile and read that person's history. That is the
one asymmetry in the system and it is deliberate — an MD buying Prism for a
team wants to know what the team is doing with it.

────────────────────────────────────────────────────────────────────────────
What this is NOT
────────────────────────────────────────────────────────────────────────────
Folder separation is enforced by Prism, not by the operating system. If the
workspace sits on a shared drive that a member's laptop can reach, that member
can open Finder and read another role's folder directly. Prism will not show
it to them; the filesystem will hand it over.

This is honest organisation and a real deterrent, not a security boundary. The
signed role claim is the part that IS solid: the role itself cannot be forged
without our signing key.

────────────────────────────────────────────────────────────────────────────
Choosing the roles
────────────────────────────────────────────────────────────────────────────
These are the divisions that actually exist in the firms Prism is sold into —
small and mid-size manufacturing, engineering, IT services and marketing
agencies in India — rather than an org chart from a large corporate. Notes on
each are in its `blurb` and in the stage list, which is the more interesting
half: it is a claim about which parts of the pipeline that job really uses.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Role:
    key: str
    label: str
    blurb: str
    icon: str
    # Accent hue in degrees. theme.py rebuilds the whole accent ramp from this,
    # keeping the design system's lightness and saturation curve — so a role
    # changes the hue of the app without changing its contrast anywhere.
    hue: int
    # Pipeline categories this role is set up with out of the box. Not a
    # restriction: the member can still turn any stage on in Settings. It is
    # what Prism configures for them so the first run makes sense.
    stages: tuple[str, ...] = ()
    # Add-ons this role is offered, IF the company licence includes them.
    # Never grants anything — the licence is still the authority.
    addons: tuple[str, ...] = ()
    # Can read every other member's folder and history.
    admin: bool = False
    # Suggested one-line "what do you do", which steers every prompt.
    profile: str = ""


# The colour Prism has always been. Kept as the no-role default so an
# individual customer — who has no company key and no designation — sees
# exactly the app they saw before any of this existed.
GENERAL_HUE = 210

ROLES: dict[str, Role] = {
    # ── the two that can see everything ──────────────────────────────────
    "owner": Role(
        "owner", "Owner / MD",
        "Everything, plus every other member's work and history",
        "archive", 278, admin=True,
        stages=("research", "leads", "brains", "content", "presentation",
                "summary"),
        addons=("boq", "email", "reel", "bom"),
        profile="owner of the company, reviewing work across every department",
    ),
    "manager": Role(
        "manager", "Manager",
        "Runs the team — can open any member's profile and history",
        "user", 245, admin=True,
        stages=("research", "leads", "brains", "content", "presentation",
                "summary"),
        addons=("boq", "email", "reel", "bom"),
        profile="manager coordinating a team's output and checking their work",
    ),

    # ── the working roles ────────────────────────────────────────────────
    # Sales gets `leads` and `email`, and is the main reason both exist.
    "sales": Role(
        "sales", "Sales & Business Development",
        "Finding prospects, outreach, quotations and proposals",
        "chart", 142,
        stages=("research", "leads", "brains", "content", "presentation",
                "summary"),
        addons=("email",),
        profile="B2B salesperson finding prospects and writing outreach",
    ),
    # The "posts maker" job. The only role that gets the full visual chain —
    # images, reel, audio — because it is the only one that ships artwork.
    "marketing": Role(
        "marketing", "Marketing & Design",
        "Social posts, creatives, campaigns, reels and brand material",
        "image", 322,
        stages=("research", "brains", "content", "visual", "media", "audio",
                "presentation", "summary"),
        addons=("reel", "email"),
        profile="digital marketer producing posts, creatives and campaigns",
    ),
    # Manufacturing and site work: this is where BOQ and BOM earn their keep.
    "operations": Role(
        "operations", "Operations & Production",
        "Site and plant work — BOQ, BOM, work orders, method statements",
        "sliders", 26,
        stages=("research", "brains", "content", "presentation", "summary"),
        addons=("boq", "bom"),
        profile="operations engineer producing site and production documents",
    ),
    "engineering": Role(
        "engineering", "Engineering & Development",
        "Code, internal tools, technical documentation and specs",
        "code", 190,
        stages=("research", "brains", "development", "content", "summary"),
        addons=(),
        profile="software engineer building tools and technical documentation",
    ),
    # Purchase and accounts are one desk in most firms this size.
    "accounts": Role(
        "accounts", "Purchase & Accounts",
        "Quotations, purchase orders, vendor comparison and costing",
        "file", 165,
        stages=("research", "brains", "content", "presentation", "summary"),
        addons=("bom", "email"),
        profile="purchase and accounts officer comparing vendors and costing jobs",
    ),
    "hr": Role(
        "hr", "HR & Admin",
        "Job posts, offer letters, policies and internal circulars",
        "mail", 352,
        stages=("research", "brains", "content", "presentation", "summary"),
        addons=("email",),
        profile="HR and admin officer writing internal and hiring documents",
    ),
}

# Order the pickers show them in: the two admin roles first, because the
# person doing the first setup is almost always one of them.
ORDER = ("owner", "manager", "sales", "marketing", "operations",
         "engineering", "accounts", "hr")


def get(key: str) -> Role | None:
    return ROLES.get((key or "").strip().lower())


def label(key: str) -> str:
    role = get(key)
    return role.label if role else ""


def hue(key: str) -> int:
    """The accent hue for a role, or Prism's own for anyone without one."""
    role = get(key)
    return role.hue if role else GENERAL_HUE


def is_admin(key: str) -> bool:
    role = get(key)
    return bool(role and role.admin)


def ordered() -> list[Role]:
    return [ROLES[k] for k in ORDER if k in ROLES]


def default_agents(key: str, available: dict) -> dict:
    """Pick one tool per stage this role uses, from the registry.

    Used to fill in a new member's settings so their first run is sensible
    instead of empty. `available` is agents.CATEGORIES, passed in rather than
    imported so this module stays free of the engine and can be unit-tested on
    its own.
    """
    role = get(key)
    if not role:
        return {}
    chosen = {}
    for stage in role.stages:
        if stage == "summary":
            continue                       # picked from the others at run time
        names = (available.get(stage) or {}).get("agents") or []
        if names:
            # First in the category list is the registry's own preference —
            # agents.py orders each category best-first for exactly this.
            chosen[stage] = names[0]
    return chosen
