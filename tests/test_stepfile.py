"""core/stepfile.py — /step, the estimator's first hour done offline.

Ground truth is the customer's own hand-made drawing sheet for the demo
assembly (step_file_demo/Assem1.STEP, SolidWorks, three sheet-metal
parts): the formed views on its right-hand side give top = 101 x 93 x 71,
side = 92 x 68.5 with 6 mm flanges, and the holes Ø13 / Ø6.2 / Ø9 / Ø5.2.
Those numbers are pinned here as witnessed — if they move, the reading is
wrong, not the drawing.

Synthetic truth-by-construction backs it: a box of known size with one
known hole, exported to STEP and read back.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "prism_terminal"))

from core import stepfile as SF  # noqa: E402

HAVE = SF.available()[0]
REAL = ("/Users/hitarthtrivedi/Documents/PythonProgram/prism-ai-flow/"
        "step_file_demo/Assem1.STEP")


def _box_with_hole(path: str):
    """A 60 x 40 x 8 mm block with one Ø5 through hole — every figure
    known by construction."""
    import cadquery as cq
    part = (cq.Workplane("XY").box(60, 40, 8)
            .faces(">Z").workplane().hole(5))
    cq.exporters.export(part, path)


@unittest.skipUnless(HAVE, "cadquery not installed")
class ABoxOfKnownSize(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.path = os.path.join(tempfile.mkdtemp(), "block.step")
        _box_with_hole(cls.path)
        cls.report = SF.analyse(cls.path, mode="plastic")

    def test_the_size_is_the_boxs(self):
        self.assertEqual(len(self.report["parts"]), 1)
        self.assertEqual(self.report["parts"][0]["size_mm"], (60.0, 40.0, 8.0))
        self.assertEqual(self.report["overall_mm"], (60.0, 40.0, 8.0))

    def test_the_hole_is_found_once_at_its_diameter(self):
        holes = self.report["parts"][0]["holes"]
        self.assertEqual(holes, [{"dia_mm": 5.0, "count": 1}])

    def test_volume_is_the_boxs_minus_the_hole(self):
        expected = (60 * 40 * 8 - 3.14159 * 2.5 ** 2 * 8) / 1000
        self.assertAlmostEqual(self.report["parts"][0]["volume_cm3"],
                               expected, delta=0.05)

    def test_plastic_mode_prices_the_shot_not_the_sheet(self):
        text = SF.report_text(self.report)
        self.assertIn("plastic moulding", text)
        self.assertIn("wall≈", text)
        self.assertIn("ABS", text)

    def test_every_figure_is_two_decimals(self):
        for number in re.findall(r"\d+\.(\d+)", SF.report_text(self.report)):
            self.assertLessEqual(len(number), 2)


@unittest.skipUnless(HAVE and os.path.exists(REAL),
                     "cadquery or the demo assembly not on this machine")
class TheCustomersOwnEnclosure(unittest.TestCase):
    """Witnessed against the fab's hand-made drawing sheet."""

    @classmethod
    def setUpClass(cls):
        cls.report = SF.analyse(REAL, mode="metal")
        cls.by_name = {p["name"]: p for p in cls.report["parts"]}

    def test_the_three_parts_keep_their_names(self):
        self.assertEqual(set(self.by_name), {"top", "bottom", "side"})

    def test_the_top_cover_matches_the_drawing(self):
        self.assertEqual(self.by_name["top"]["size_mm"], (101.0, 93.0, 71.0))

    def test_the_side_panel_matches_the_drawing(self):
        self.assertEqual(self.by_name["side"]["size_mm"], (92.0, 68.5, 6.0))

    def test_the_drawings_named_holes_are_all_found(self):
        top = {h["dia_mm"] for h in self.by_name["top"]["holes"]}
        bottom = {h["dia_mm"] for h in self.by_name["bottom"]["holes"]}
        self.assertIn(13.0, top)
        self.assertIn(6.2, top)
        self.assertIn(9.0, bottom)
        self.assertIn(5.2, bottom)

    def test_the_sheet_reads_as_one_millimetre(self):
        for part in self.report["parts"]:
            self.assertGreater(part["thickness_mm"], 0.8)
            self.assertLess(part["thickness_mm"], 1.05)

    def test_the_report_says_formed_not_flat(self):
        self.assertIn("FORMED", SF.report_text(self.report))

    def test_the_excel_sheet_carries_every_part(self):
        import openpyxl
        out = os.path.join(tempfile.mkdtemp(), "dimensions.xlsx")
        SF.write_xlsx(self.report, out)
        wb = openpyxl.load_workbook(out)
        body = "\n".join(str(c.value) for row in wb["Parts"].iter_rows()
                         for c in row if c.value is not None)
        for name in ("top", "bottom", "side"):
            self.assertIn(name, body)
        self.assertIn("101.0", body)
        self.assertEqual(wb["Holes"].max_row - 1,
                         sum(len(p["holes"]) for p in self.report["parts"]))

    def test_the_drawing_sheet_shows_every_part(self):
        out = tempfile.mkdtemp()
        drawn = SF.render_sheet(self.report, out)
        html = open(drawn["html"], encoding="utf-8").read()
        for name in ("top", "bottom", "side"):
            self.assertIn(name, html)
            svg = os.path.join(out, f"{name}.svg")
            self.assertTrue(os.path.exists(svg), svg)
            self.assertGreater(os.path.getsize(svg), 5000, svg)
        self.assertIn("101.00 x 93.00 x 71.00", html)


class TheTerminalDoor(unittest.TestCase):

    def test_step_and_s_reach_the_command(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = open(os.path.join(root, "prism_terminal", "prism.py"),
                   encoding="utf-8").read()
        self.assertIn("def cmd_step(", src)
        self.assertIn('line.startswith("/step")', src)
        self.assertIn('line == "/s" or line.startswith("/s ")', src)
        self.assertIn("no AI sees the STEP file", src)

    def test_the_mode_words_are_metal_and_plastic(self):
        self.assertEqual(SF.MODES, ("metal", "plastic"))


if __name__ == "__main__":
    unittest.main()
