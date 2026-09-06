"""Motion Graphics — a scene-graph video with camera, charts and diagrams."""
from __future__ import annotations

from addons.manifest import ACCENT, HOME, Addon

MANIFEST = Addon(
    key="motion",
    label="Motion Graphics",
    # The same licence feature as Reel/Studio -- Motion is the same "media"
    # capability tier, not a separate purchase, matching the existing
    # "Prism Reel"/"Prism Studio" -> "reel" agent mapping.
    feature="reel",
    tip="A scene-graph video with camera, charts & diagrams",
    blurb="A scene-graph video with camera, charts & diagrams",
    icon="video",
    tone=ACCENT,
    order=60,
    shelves=(HOME,),           # see addons/reel/addon.py for why
    dialog="dialogs.motion_dialog:MotionDialog",
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
