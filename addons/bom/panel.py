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
         "A DXF or PDF general-arrangement drawing — or nothing at all, a "
         "written description of the assembly works on its own."),
        ("chart", "Prism measures the parts",
         "Part counts, cut lengths and plate areas are taken locally by "
         "Prism's own geometry engine. No AI sees the drawing at this step."),
        ("file", "You get a checkable CSV",
         "Every measured figure is written to a CSV before anything is "
         "generated, so you can audit the take-off."),
        ("pencil", "Then the BOM is written up",
         "The measured parts go to your writing tool, which turns them into a "
         "grouped Bill of Materials with materials and grades."),
    ]

    PLACEHOLDERS = [
        ("Parts list to fabricate this over-band magnetic separator",
         "Attach the GA drawing and Prism measures the parts."),
        ("BOM for one 36x24 jaw crusher, 100 TPH",
         "No drawing needed — the parts come out of the words."),
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


