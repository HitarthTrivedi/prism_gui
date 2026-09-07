"""Motion Graphics — a scene-graph video with camera, charts and diagrams."""
from __future__ import annotations

from addons.manifest import ACCENT, HOME, SOON, Addon

MANIFEST = Addon(
    key="motion",
    label="Motion Graphics",
    # NOT built yet, and this is the honest place to say so. The engine's own
    # core/motion/render.py carries _DISABLED_PENDING_ASSET_FIX = True and
    # is_available() returns False unconditionally, so CB.motion_available()
    # can never say yes in this release.
    #
    # Until now that fact lived in a hardcoded tuple inside a render method --
    # `soon = key in ("bom", "motion")` in widgets/home_panel.py -- which is
    # an EIGHTH place add-on identity was written down, and not even a table.
    # It is also why BOM was unclickable: BOM shipped and works
    # (boq_available() is True), but it was still sitting in that tuple next
    # to Motion, which genuinely does not.
    status=SOON,
    chip="Motion",              # the history pill has no room for both words
    # The same licence feature as Reel/Studio -- Motion is the same "media"
    # capability tier, not a separate purchase, matching the existing
    # "Prism Reel"/"Prism Studio" -> "reel" agent mapping.
    feature="reel",
    tip="A scene-graph video with camera, charts & diagrams",
    blurb="A scene-graph video with camera, charts & diagrams",
    icon="video",
    tone=ACCENT,
    order=60,
    # HOME ONLY, and for a stronger reason than Reel's: this add-on cannot
    # run at all (see `status` above), so a rail row would advertise
    # something that opens nothing. Settled 2026-09-07 and pinned by
    # tests/test_addon_contract.py's GOLDEN_HOME.
    shelves=(HOME,),
    dialog="addons.motion.dialog:MotionDialog",
    probe="core_bridge:motion_available",
    remedy="ffmpeg",
    kind="motion",
    # Note the lower-case display prefix. It matches what the dialog actually
    # writes, which is not what BOQ and Gerber write, and this table is the
    # first place that inconsistency has been visible in one glance.
    run_prefixes=("motion — ", "/motion "),
    # core/motion/ is a SUBPACKAGE, and packaging/prism.spec's engine
    # enumeration filters `name.endswith(".py")` over core/*.py -- so these
    # modules have never been listed in any frozen build. Declaring them here
    # is what lets S6's recursive walk pick them up.
    engine=("motion.generate", "motion.render", "motion.schema"),
    agents=("Prism Motion",),
)
