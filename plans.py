"""What each plan includes — the single table the app and the server share.

────────────────────────────────────────────────────────────────────────────
The idea
────────────────────────────────────────────────────────────────────────────
A licence carries a list of FEATURE names. The app never asks "which plan is
this?" — it asks "does this licence include `boq`?". That one decision is what
makes every deal shape possible without touching the app:

  · a plan is just a named set of features
  · an add-on is one feature sold on top
  · a bespoke deal for one customer is a hand-written set, and nothing in the
    app has to know it was bespoke

So this file is a convenience for humans — the sales list, the pricing page,
and the minting console. The enforcement is `licensing.has(feature)`, and it
would work identically if plans did not exist.

────────────────────────────────────────────────────────────────────────────
Why features are named after JOBS, not screens
────────────────────────────────────────────────────────────────────────────
`marketing` rather than `visual_stage`, `works` rather than `boq_dialog`. A
customer buys an outcome, and naming the feature after the outcome means the
sales conversation, the licence key and the padlock in the sidebar all use the
same word. It also survives a UI redesign: moving BOQ to a different screen
does not change what somebody bought.

────────────────────────────────────────────────────────────────────────────
Keep this in step with the server
────────────────────────────────────────────────────────────────────────────
The licence server mints the feature list into the signed token. If it and
this file disagree, the server wins — the app can only honour what it is told.
Treat this as the source of truth and copy it to the server, not the reverse.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Feature:
    key: str
    label: str
    blurb: str
    # What stops working without it, in the words a customer would use. This
    # is the paywall copy, so it has to sell rather than merely describe.
    pitch: str = ""


FEATURES: dict[str, Feature] = {
    "core": Feature(
        "core", "The pipeline",
        "Describe a job, get a plan, run it across your AI tools",
        "The heart of Prism — every licence includes it."),

    # ── the base product: Prism Studio ───────────────────────────────────
    # Reel, Studio and Motion are one capability tier and one key. Motion
    # rides "reel" on purpose (addons/motion/addon.py) — it is the same
    # purchase, not a separate one.
    "reel": Feature(
        "reel", "Reel & Studio",
        "Short vertical video and motion graphics, rendered from a script",
        "A finished reel in your brand's colours, ready to post."),

    # ── add-ons, one key each, sold on top of Studio ─────────────────────
    "boq": Feature(
        "boq", "BOQ & BOM",
        "Measure a CAD drawing: the quantities, and the parts list",
        # Says "quantities", not "priced". The engine measures and deliberately
        # leaves the Rate and Amount columns blank — the costing is the
        # customer's. Promising a priced BOQ in the paywall copy would be
        # selling something the product does not do, and the demo would be the
        # moment they found out.
        #
        # One key for BOQ and BOM: BOM ships as a mode inside the BOQ dialog
        # and is reached by BOQ's route, so they are one add-on, not two.
        "Attach the drawing and get the measured quantities, line by line, in "
        "a spreadsheet you can check against the drawing. Your rates go in "
        "the blank columns — Prism counts, you price. Give it the parts list "
        "and your stock and get the shortage list before the job starts."),

    "email": Feature(
        "email", "Email sending",
        "Send from your own account, one copy per recipient",
        "Prism drafts it, you approve it, and it goes out from your own "
        "address — never a bulk-mail service."),

    "inbox": Feature(
        "inbox", "Inquiry",
        "Read the mail, register the inquiries, quote, chase, track the order",
        "Prism reads your inbox, files every drawing, keeps your inquiry "
        "register, prices from your own rate sheet, chases the customers who "
        "go quiet and sends your SOPs — on your own computer. It stops twice: "
        "before a price goes out, and before you accept a PO."),

    "leads": Feature(
        "leads", "Leads & Outreach",
        "Find real companies and named contacts, and email them",
        "Stop buying lists. Prism finds companies that match, pulls verified "
        "contacts, writes the email and sends each person their own copy."),

    "gerber": Feature(
        "gerber", "Gerber",
        "PCB size, track width and spacing, drill size and count, measured "
        "from the Gerber files",
        "Drop the Gerber files and get the board measured on your own "
        "machine — the files are never shown to an AI."),

    "step": Feature(
        "step", "STEP",
        "Every part's size, thickness, holes and weight, measured from the "
        "3D model",
        "Drop the STEP model and get every part measured on your own "
        "machine, then draft, ask or edit — the model is never shown to an "
        "AI."),
}


@dataclass(frozen=True)
class Plan:
    key: str
    label: str
    who: str                        # who this is for, in one line
    includes: tuple[str, ...]
    # Sold alongside it. Not a promise of price — just what to offer next,
    # which is the question the sales call actually gets stuck on.
    addons: tuple[str, ...] = ()
    note: str = ""


PLANS: dict[str, Plan] = {
    # ── the base product ─────────────────────────────────────────────────
    "studio": Plan(
        "studio", "Prism Studio",
        "Every customer starts here — the pipeline plus Reel & Studio",
        includes=("core", "reel"),
        addons=("boq", "email", "inbox", "leads", "gerber", "step"),
        note="The base product. Everything else is an add-on sold on top, "
             "one key each, and a licence is Studio plus whichever add-ons "
             "the customer bought."),

    # ── everything ───────────────────────────────────────────────────────
    "complete": Plan(
        "complete", "Prism Complete",
        "Studio plus every add-on — the whole product",
        includes=tuple(FEATURES),
        addons=(),
        note="Everything, including anything added later in the same major "
             "version. The easiest one to sell and the easiest to support."),
}

ORDER = ("studio", "complete")

# A licence with nothing set at all still gets this. Never empty: a customer
# whose licence arrives malformed should see a working pipeline and a support
# message, not an app with every button padlocked.
FALLBACK = ("core",)


def features_for(plan_key: str) -> tuple[str, ...]:
    plan = PLANS.get((plan_key or "").strip().lower())
    return plan.includes if plan else FALLBACK


def label(feature_key: str) -> str:
    feature = FEATURES.get(feature_key)
    return feature.label if feature else feature_key.upper()


def blurb(feature_key: str) -> str:
    feature = FEATURES.get(feature_key)
    return feature.blurb if feature else ""


def pitch(feature_key: str) -> str:
    feature = FEATURES.get(feature_key)
    return feature.pitch or (feature.blurb if feature else "")


def plan_of(features) -> str:
    """Best-guess plan name for a set of features — for display only.

    A bespoke licence matches nothing, and that is fine: it shows as "Custom",
    which is what it is. Nothing branches on this.
    """
    owned = set(features or ())
    for key in ORDER:
        if set(PLANS[key].includes) == owned:
            return PLANS[key].label
    return "Custom"


def missing_from(plan_key: str) -> tuple[str, ...]:
    """What this plan does NOT include — the upsell list, in order."""
    have = set(features_for(plan_key))
    return tuple(k for k in FEATURES if k not in have)
