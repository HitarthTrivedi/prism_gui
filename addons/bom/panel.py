"""The BOM front door.

Its own screen and its own rail row, but BOQ's dialog in a different
mode -- which is why addons/bom/addon.py declares provided_by="boq"
rather than pretending to own a dialog it does not have.
"""
from __future__ import annotations

import theme
from widgets.panel_base import (
    AddonFrontDoor,
)


class BomPanel(AddonFrontDoor):
    TITLE = "BOM"
    BLURB = ("The parts list to fabricate it — off a CAD drawing, or a written "
             "spec. Prism counts and measures the parts; you price them.")
    ICON = "list"
    HEADLINE = "Attach a fabrication drawing or spec to begin"
    DETAIL = "DXF, PDF, or a written description of what is built."
    ACTION = "Attach a file"
    KIND = "bom"

    STEPS = [
        ("paperclip", "Attach the drawing",
         "Upload a GA drawing (DXF/PDF) or describe the assembly."),
        ("chart", "Prism measures the parts",
         "Part counts, cut lengths, and plate areas are measured locally."),
        ("file", "Audit the take-off",
         "Review verified part quantities in a clean, checkable CSV."),
        ("pencil", "Export Bill of Materials",
         "Outputs an organized BOM grouped by material, grade, and size."),
    ]

    PLACEHOLDERS = [
        ("Parts list to fabricate this over-band magnetic separator",
         "Measures your GA drawing to extract plate sizes, beam lengths, and hardware."),
        ("BOM for one 36x24 jaw crusher, 100 TPH",
         "Generates a complete fabrication parts list directly from specifications."),
    ]

    def build(self):
        self.HUE = theme.ACCENT
        super().build()

    def tool_roles(self):
        """Mirrors BoqDialog(mode='bom')._run() — writer, researcher, interpreter."""
        agents = self._agents()
        writer = next((agents[s] for s in ("content", "brains")
                       if agents.get(s)), "")
        return [
            ("pencil", "Writes the BOM up",
             "Your Writing tool, or Reasoning if you have not set one.",
             writer),
            ("book", "Checks material grades & sizes",
             "Your Research tool, falling back to Reasoning — used when you "
             "leave “derive from standards” switched on.",
             agents.get("research") or agents.get("brains") or ""),
            ("image", "Reads a drawing screenshot",
             "ChatGPT specifically, and only when you attach an image for it "
             "to read the legend and scope off.",
             "ChatGPT"),
        ]


