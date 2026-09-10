"""The Leads & Outreach front door.

A brochure-shaped launcher, like the other add-on panels: it explains the
screen and opens the workbench dialog (wired by the manifest's `dialog=`, so
this file never imports the dialog itself).
"""
from __future__ import annotations

import theme
from widgets.panel_base import AddonFrontDoor


class LeadsPanel(AddonFrontDoor):
    TITLE = "Leads & Outreach"
    BLURB = ("Bring a list of leads. Prism qualifies each against what you sell "
             "and writes an email grounded in that company's own why-now.")
    ICON = "user"
    HEADLINE = "Bring a sheet of leads to begin"
    DETAIL = "An Excel or CSV export — names, titles, companies, emails."
    ACTION = "Open the workbench"
    ACTION_ICON = "user"
    KIND = "leads"

    STEPS = [
        ("user", "Bring your list",
         "An Excel or CSV export — the sheet you already trust. Prism reads it "
         "as-is; nothing has to be reformatted first."),
        ("bulb", "Each lead is qualified",
         "Six named checks — fit, need, timing, authority, budget, competition "
         "— each marked with the evidence behind it, or honestly left unknown."),
        ("pencil", "An email is written for each",
         "Grounded in that company's own recent news, and using only the value "
         "claims you approve. No invented numbers."),
        ("mail", "You read it, then send",
         "Each message goes out one-per-person from your own account — after "
         "you have read it. Prism prepares; you press Send."),
    ]

    PLACEHOLDERS = [
        ("A sheet of automation & digital-manufacturing leaders at large plants",
         "Prism qualifies every row and writes to the hot ones — you send."),
    ]

    def build(self):
        self.HUE = theme.INFO
        super().build()
