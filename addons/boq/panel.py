"""The BOQ and BOM front doors.

Two screens, one file: BOM is BOQ's dialog in a different mode, so the
two front doors differ only in their copy and their run prefix.
"""
from __future__ import annotations


import theme
from shell.widgets.panel_base import (
    AddonFrontDoor,
)


class BoqPanel(AddonFrontDoor):
    TITLE = "BOQ"
    BLURB = ("Quantities off a CAD drawing, or a written spec. Prism counts "
             "and measures — you price it.")
    ICON = "file"
    HEADLINE = "Attach a drawing or spec to begin"
    DETAIL = "DXF, PDF, or a written list of what's needed."
    ACTION = "Attach a file"
    KIND = "boq"

    STEPS = [
        ("paperclip", "Attach the drawing",
         "A DXF, a PDF, or nothing at all — a written description of what is "
         "needed works on its own."),
        ("chart", "Prism measures it",
         "Counts and lengths are taken locally by Prism's own geometry "
         "engine. No AI sees the drawing at this step."),
        ("file", "You get a checkable CSV",
         "Every measured figure is written to a CSV before anything is "
         "generated, so you can audit the numbers."),
        ("pencil", "Then it is written up",
         "The measured numbers go to your writing tool, which turns them "
         "into the document you send."),
    ]

    PLACEHOLDERS = [
        ("BOQ for CCTV, cabling and fibre for this site",
         "Attach the drawing and Prism measures it."),
        ("materials to build one 36x24 jaw crusher, 100 TPH",
         "No drawing needed — the quantities come out of the words."),
    ]

    def build(self):
        self.HUE = theme.ACCENT
        super().build()

    def tool_roles(self):
        """Mirrors BoqDialog._run() exactly — writer, researcher, interpreter."""
        agents = self._agents()
        writer = next((agents[s] for s in ("content", "brains")
                       if agents.get(s)), "")
        return [
            ("pencil", "Writes the BOQ up",
             "Your Writing tool, or Reasoning if you have not set one.",
             writer),
            ("book", "Checks the trade standard",
             "Your Research tool, falling back to Reasoning — used when you "
             "leave “derive from standards” switched on.",
             agents.get("research") or agents.get("brains") or ""),
            ("image", "Reads a drawing screenshot",
             "ChatGPT specifically, and only when you attach an image for it "
             "to read the legend and scope off.",
             "ChatGPT"),
        ]
