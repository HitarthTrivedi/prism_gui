"""STEP — a 3D model measured on this machine, then drafted, asked about
or edited. The model itself is never shown to an AI."""
from __future__ import annotations

from addons import names
from addons.manifest import ACCENT, RAIL, HOME, Addon, Offer

MANIFEST = Addon(
    key="step",
    label="STEP",
    # Its own key since 2026-09-10: STEP is sold as its own add-on
    # (plans.FEATURES["step"]). It rode "boq" before that, so every licence
    # that held "boq" on that date was granted "step" server-side and nobody
    # lost access when this line changed.
    feature="step",
    tip="Every part's size, thickness, holes and weight — measured from "
        "the 3D model itself, never seen by an AI. Then draft, ask or edit",
    blurb="Measured off the 3D model, then draft, ask or edit",
    icon="grid",
    tone=ACCENT,
    # Between Gerber (30) and Email (40): the three measuring add-ons sit
    # together on the shelf, and Email keeps its place after them.
    order=35,
    shelves=(RAIL, HOME),
    screen="step",
    panel="addons.step.panel:StepPanel",
    dialog="addons.step.dialog:StepDialog",
    # Unlike Gerber this add-on has a HARD dependency: cadquery, which
    # carries OpenCascade. The probe says so before the first model is
    # dropped, and the dialog's own message names the pip install.
    probe="core_bridge:step_available",
    remedy="cadquery",
    kind="step",
    # "STEP — " is what addons/step/dialog.py stamps on every run record
    # (f"STEP — {Draft|Ask|Edit}: …"); "/step" covers the terminal's
    # /step, /step-auto and /step-ask titles in one prefix.
    run_prefixes=("STEP — ", "/step"),
    engine=("stepfile",),
    # Nobody wants this yet. Inquiry is the obvious consumer -- an order
    # arrives with a model attached -- and the day it does, that is one
    # `wants=` entry and one button, not an import.
    offers=(Offer(names.MEASURE_MODEL,
                  "addons.step.contract:open_with_files",
                  "Measure this model"),),
)
