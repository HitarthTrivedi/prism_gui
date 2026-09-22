"""The Gerber front door."""
from __future__ import annotations


import theme
from widgets.panel_base import (
    AddonFrontDoor,
)


class GerberPanel(AddonFrontDoor):
    TITLE = "Gerber"
    BLURB = ("PCB size, track width & spacing, drill size and count — "
             "measured from the Gerber files, not guessed.")
    ICON = "file"
    HEADLINE = "Drop a Gerber job to begin"
    DETAIL = ("A .zip or .rar exactly as the customer sent it — the design "
              "is measured here and never leaves this machine.")
    ACTION = "Attach a job"
    KIND = "gerber"

    STEPS = [
        ("paperclip", "Drop the job",
         "Attach the customer .zip or .rar Gerber archive directly."),
        ("chart", "Measured on this machine",
         "Board size, track width, spacing, and drill counts are extracted."),
        ("lock", "The design never leaves",
         "Only measured numbers are processed — Gerber files stay private."),
        ("pencil", "Quote or spec",
         "Generates ready-to-send fabrication notes, price breakdowns, or replies."),
    ]

    PLACEHOLDERS = [
        ("Reply with our price for 500 pieces",
         "Generates a priced fabrication quote from measured PCB specifications."),
        ("Fabrication note & PCB inspection summary",
         "Summarizes board size, track width/spacing, and drill counts for manufacturing."),
    ]

    def build(self):
        self.HUE = theme.ACCENT
        super().build()

    def tool_roles(self):
        """Mirrors GerberDialog._write_up() — one writer, and it is shown
        nothing but the numbers."""
        agents = self._agents()
        return [
            ("pencil", "Writes the numbers up",
             "Your Writing tool, or Reasoning if you have not set one. It is "
             "handed the five measured figures and nothing else — never a "
             "file and never a path.",
             next((agents[s] for s in ("content", "brains")
                   if agents.get(s)), "")),
        ]
