"""A step the owner switched off stays off.

Reported 2026-09-07: "Make the images" unticked before the run, and the run
opened the image tool anyway. The reel's image maker is not a planned stage
— the engine inserts it whenever Prism Studio is in the run, gated on a
config key the plan screen never touches — so unticking its row removed the
row and changed nothing. Now the plan screen tells the engine what was left
out, by name, and the insertion honours it.

The engine test stops the run at the point the stages have been assembled
(should_stop fires before the browser starts), and reads the assembly off
what the engine announced.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402
from core import automation as AU  # noqa: E402

CFG = {"agents": {"content": "ChatGPT", "media": "Prism Studio"}}
STAGES = [("content", "ChatGPT", ["Write the reel."]),
          ("media", "Prism Studio", ["Film it."])]


class TheEngineHonoursTheSkip(unittest.TestCase):

    def _announced(self, **kw):
        said = []
        with mock.patch.object(AU.ui, "info", side_effect=lambda m: said.append(str(m))), \
             mock.patch.object(AU.ui, "warn", side_effect=lambda m: said.append(str(m))), \
             mock.patch.object(AU.ui, "ok", side_effect=lambda m: said.append(str(m))):
            out = AU.run({}, CFG, custom_stages=STAGES, query="make a reel",
                         should_stop=lambda: True, **kw)
        self.assertEqual(out, ({}, {}))          # stopped before the browser
        return "\n".join(said)

    def test_by_default_studio_makes_its_own_pictures(self):
        said = self._announced()
        self.assertIn("will search the web and make up to", said)

    def test_an_unticked_image_step_makes_none(self):
        said = self._announced(skip_stages=["visual"])
        self.assertNotIn("will search the web and make up to", said)
        self.assertIn("left out of the plan", said)

    def test_leaving_out_another_step_does_not_touch_the_pictures(self):
        said = self._announced(skip_stages=["leads", "audio"])
        self.assertIn("will search the web and make up to", said)


class ThePlanScreenSaysWhatWasLeftOut(unittest.TestCase):

    def test_unticked_rows_by_stage_key(self):
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from widgets.agents_panel import AgentsPanel
        panel = AgentsPanel()
        panel.set_content(
            {"visual": {"needed": True, "questions": ["Make the pictures."]},
             "content": {"needed": True, "questions": ["Write it."]},
             "media": {"needed": True, "questions": ["Film it."]}},
            {"visual": "ChatGPT", "content": "ChatGPT", "media": "Prism Studio"})
        self.assertEqual(panel.left_out_stages(), [])
        next(r for r in panel.rows() if r.stage == "visual").set_included(False)
        self.assertEqual(panel.left_out_stages(), ["visual"])
        self.assertNotIn("visual", panel.selected_agents())


if __name__ == "__main__":
    unittest.main()
