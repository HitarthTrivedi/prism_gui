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
         "A .zip or .rar exactly as the customer sent it. Nothing has to be "
         "unpacked or renamed first."),
        ("chart", "Measured on this machine",
         "Board size, track width and spacing, drill sizes and counts — read "
         "out of the Gerber files by Prism itself."),
        ("lock", "The design never leaves",
         "Only the measured numbers are handed to the AI stage. The Gerber "
         "files are never attached to anything."),
        ("pencil", "Then a quote or a spec",
         "Ask for a fabrication note, a price breakdown or a customer reply "
         "— written from the numbers alone."),
    ]

    PLACEHOLDERS = [
        ("reply with our price for 500 pieces",
         "Optional. Say what to do with the numbers once they are measured "
         "— or leave it blank and just take the five figures. Measuring "
         "starts the moment the file lands, either way."),
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


# EmailPanel lives in widgets/email_panel.py now — a launcher in the shape
# of the Email-automation screen, not a brochure. Re-exported here so the
# import path the rest of the app and the tests use keeps working.
