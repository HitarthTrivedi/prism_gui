"""Reel / Studio — a short video built from a task's output."""
from __future__ import annotations

from addons.manifest import ACCENT, HOME, Addon

MANIFEST = Addon(
    key="reel",
    label="Reel / Studio",
    chip="Reel",                # the history pill has no room for both names
    feature="reel",
    tip="A short video from a task",
    blurb="A short video from a task",
    icon="video",
    tone=ACCENT,
    order=50,
    # HOME ONLY. Settled 2026-09-07, after the two shelf tables had disagreed
    # about it for months: Reel's rail row went to Artifacts inside the rail's
    # twelve-control budget, and the budget is at 12 of 12 -- putting Reel back
    # means taking something else off.
    #
    # It stays reachable by command, which is exactly why its licence gate
    # matters: there is no shelf row standing between an unlicensed user and
    # the capability, and the router can put Prism Reel into a plan without
    # anybody clicking anything. See `agents=` below.
    #
    # Pinned by tests/test_addon_contract.py's GOLDEN_HOME / GOLDEN_RAIL.
    shelves=(HOME,),
    dialog="addons.reel.dialog:ReelDialog",
    probe="core_bridge:reel_available",
    # FFmpeg specifically is something Prism can fix by itself, so it gets an
    # offer rather than an apology. Everything else missing (Pillow) is a
    # broken install and needs a person.
    remedy="ffmpeg",
    kind="reel",
    run_prefixes=("/reel ",),
    engine=("reel", "reel_web", "assets"),
    # The one gate the rail cannot enforce: these are reached by name from
    # the router, not by a click, so no shelf row stands between the customer
    # and the capability.
    agents=("Prism Reel", "Prism Studio"),
)
