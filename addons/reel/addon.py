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
    # HOME ONLY, and that is the live behaviour, not an oversight of this
    # file: widgets/sidebar.py has no reel row (Reel's slot went to
    # Artifacts, inside the rail's twelve-control budget) while
    # widgets/home_panel.py does. Both remain reachable by command, which is
    # exactly why they still need a licence gate. Whether the rail should
    # gain them back is a product decision, deliberately NOT taken here --
    # this stage changes no behaviour; changing the shelf is its own commit
    # so that reverting the decision does not revert the mechanism.
    shelves=(HOME,),
    dialog="dialogs.reel_dialog:ReelDialog",
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
