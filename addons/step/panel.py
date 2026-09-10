"""The STEP front door."""
from __future__ import annotations

import theme
from widgets.panel_base import AddonFrontDoor


class StepPanel(AddonFrontDoor):
    TITLE = "STEP"
    BLURB = ("Every part's size, thickness, holes and weight — measured "
             "from the 3D model itself, not guessed. Then draft, ask or "
             "edit.")
    ICON = "grid"
    HEADLINE = "Attach a STEP model to begin"
    DETAIL = ("A .step or .stp straight from the customer — measured here, "
              "on this machine, and it never leaves.")
    ACTION = "Attach a model"
    KIND = "step"

    STEPS = [
        ("paperclip", "Attach the model",
         "One .step / .stp file or several. Prism asks once where you want "
         "the files kept, then makes a folder per model, every file named "
         "after it."),
        ("chart", "Measured and drawn on this machine",
         "Every part's formed size, sheet or wall thickness, every hole by "
         "diameter, volume and weight — read from the real geometry by "
         "Prism itself. An Excel sheet and a dimensioned drawing sheet "
         "(front, top and side views, sizes in mm) every time, no AI."),
        ("lock", "The model never leaves",
         "Draft, Ask and Edit hand an AI only the measured numbers and "
         "Prism's own plain render of the parts. The STEP file is never "
         "attached to anything, and edits are made here, on a copy."),
        ("pencil", "Then draft, ask or edit",
         "Draft a dimensioned drawing sheet; ask what to change and get a "
         "reviewed plan; or have the plan applied to a copy of the model "
         "and re-measured."),
    ]

    PLACEHOLDERS = [
        ("how do I make this lighter?",
         "Ask. Groq answers from the measured figures alone and a reasoning "
         "tool turns it into an exact plan on a review page. Nothing is "
         "changed."),
        ("fit M8 bolts instead of M6",
         "Edit. The same plan, then — once you confirm on the review page — "
         "the holes are enlarged on a COPY of the model and it is measured "
         "again. Draft needs no text at all."),
    ]

    def build(self):
        self.HUE = theme.ACCENT
        super().build()

    def tool_roles(self):
        """Mirrors StepDialog: ChatGPT draws a Draft; the reasoning tool
        reviews the plan for Ask and Edit. Both see numbers and Prism's own
        render only."""
        agents = self._agents()
        return [
            ("image", "Draws the styled sheet (Draft)",
             "ChatGPT, always — its image model is the one that draws a "
             "dimension sheet well from a numbers-only brief. It is handed "
             "the measured figures and Prism's own plain render — never "
             "the model. Prism's own dimensioned sheet is made regardless.",
             "ChatGPT"),
            ("bulb", "Reviews the change plan (Ask, Edit)",
             "Your Reasoning tool, falling back to Writing or Research. It "
             "turns Groq's suggestions into the exact changes Prism can "
             "apply, from the numbers alone.",
             next((agents[s] for s in ("brains", "content", "research")
                   if agents.get(s)), "")),
        ]
