"""core/gerber_clean.py — drop what lies outside the board outline and write
the layers back out for the CAM operator to compare.

The rules it defends, each one about NOT destroying a production file:

  · wholly outside → removed; wholly inside → kept untouched; crossing the
    edge → kept and listed (cutting is the operator's call);
  · a pad that kisses the edge is inside (the margin);
  · a layer that sits off the board altogether means the outline is offset,
    and then nothing is removed and the layer is flagged — while a layer
    that is mostly legend strokes beside the board is still cleaned;
  · non-image files — the outline itself, drills, reports — copy through;
  · the cleaned file is still a valid Gerber (it re-opens in gerbonara) and
    Prism's own five numbers measured on it are unchanged.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge as CB  # noqa: E402

G = CB.get_gerber()
try:
    CLEAN = CB.get_gerber_clean()
    HAVE = CLEAN.HAVE_GERBONARA and CLEAN.HAVE_SHAPELY
except Exception:                                   # noqa: BLE001
    HAVE = False

REAL = "/Users/hitarthtrivedi/Documents/PythonProgram/prism-ai-flow/gerber_test"

# RS-274X, 3.4 format in mm: X600000 = 60.0000 mm.
HEADER = "%FSLAX34Y34*%\n%MOMM*%\n"


def _line(x0, y0, x1, y1):
    return (f"X{int(x0 * 1e4)}Y{int(y0 * 1e4)}D02*\n"
            f"X{int(x1 * 1e4)}Y{int(y1 * 1e4)}D01*\n")


def _flash(x, y):
    return f"X{int(x * 1e4)}Y{int(y * 1e4)}D03*\n"


def _outline(w=60.0, h=40.0) -> str:
    return (HEADER + "%ADD10C,0.100*%\nD10*\n"
            + _line(0, 0, w, 0) + _line(w, 0, w, h)
            + _line(w, h, 0, h) + _line(0, h, 0, 0) + "M02*\n")


def _copper() -> str:
    """Three tracks and a pad inside a 60 x 40 board, one track wholly
    outside, one pad wholly outside, one track crossing the right edge, and
    one pad exactly touching the edge."""
    return (HEADER + "%ADD10C,0.250*%\n%ADD11R,1.000X1.000*%\nD10*\n"
            + _line(5, 5, 30, 5)            # inside
            + _line(5, 10, 30, 10)          # inside
            + _line(5, 15, 30, 15)          # inside
            + _line(70, 5, 80, 5)           # wholly outside (x 70..80)
            + _line(55, 20, 65, 20)         # crosses the right edge at x=60
            + "D11*\n"
            + _flash(20, 30)                # inside
            + _flash(90, 30)                # wholly outside
            + _flash(59.5, 30)              # kisses the edge (59..60 within margin)
            + "M02*\n")


def _job(folder: str) -> list[str]:
    paths = []
    for name, text in (("board.gko", _outline()), ("board.gtl", _copper()),
                       ("board.gbs", _copper())):
        p = os.path.join(folder, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        paths.append(p)
    notes = os.path.join(folder, "readme.txt")
    with open(notes, "w", encoding="utf-8") as f:
        f.write("Customer notes — 2 layer, 1.6 mm.\n")
    paths.append(notes)
    return paths


@unittest.skipUnless(HAVE, "gerbonara/shapely not installed")
class CleaningASmallBoard(unittest.TestCase):

    def setUp(self):
        self.src = tempfile.mkdtemp(prefix="prism-clean-src-")
        self.out = tempfile.mkdtemp(prefix="prism-clean-out-")
        self.paths = _job(self.src)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.report = CLEAN.clean_job(self.paths, self.out)

    def _layer(self, name):
        return next(l for l in self.report["layers"] if l["name"] == name)

    def test_the_outline_is_the_boards(self):
        self.assertAlmostEqual(self.report["outline"]["width_mm"], 60.0, 2)
        self.assertAlmostEqual(self.report["outline"]["height_mm"], 40.0, 2)

    def test_outside_goes_inside_stays_crossing_is_kept_and_listed(self):
        copper = self._layer("board.gtl")
        self.assertEqual(copper["objects"], 8)
        self.assertEqual(copper["removed"], 2)        # one track, one pad
        self.assertEqual(copper["crossing"], 1)       # the x 55..65 track
        self.assertEqual(copper["kept"], 6)           # 3 + crossing + 2 pads
        self.assertFalse(copper["suspicious"])
        self.assertEqual(len(copper["removed_list"]), 2)
        self.assertEqual(len(copper["crossing_list"]), 1)

    def test_a_pad_kissing_the_edge_is_not_thrown_away(self):
        removed = self._layer("board.gtl")["removed_list"]
        for d in removed:
            self.assertGreater(d["x0"], 60.0, d)

    def test_the_cleaned_file_is_a_valid_gerber_with_the_right_count(self):
        from gerbonara import GerberFile
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            again = GerberFile.open(os.path.join(self.out, "board.gtl"))
        self.assertEqual(len(again.objects), 6)

    def test_prisms_own_numbers_are_unchanged_on_the_cleaned_job(self):
        """Removing what is outside must not move a single figure inside."""
        before = G.analyse([os.path.join(self.src, "board.gko"),
                            os.path.join(self.src, "board.gtl")])["answers"]
        after = G.analyse([os.path.join(self.out, "board.gko"),
                           os.path.join(self.out, "board.gtl")])["answers"]
        self.assertEqual(before["min_track_width_mm"],
                         after["min_track_width_mm"])
        self.assertEqual(before["pcb_size"], after["pcb_size"])

    def test_the_outline_and_the_notes_are_copied_through(self):
        names = {c["name"] for c in self.report["copied"]}
        self.assertIn("board.gko", names)
        self.assertIn("readme.txt", names)
        self.assertTrue(os.path.exists(os.path.join(self.out, "readme.txt")))

    def test_a_before_and_after_picture_of_every_cleaned_layer(self):
        """What the CAM operator opens with the graphics team: one page,
        each layer before and after, side by side."""
        page = os.path.join(self.out, "compare.html")
        self.assertTrue(os.path.exists(page))
        html = open(page, encoding="utf-8").read()
        for name in ("board.gtl", "board.gbs"):
            self.assertIn(name, html)
            for tag in ("before", "after"):
                rel = os.path.join("previews", f"{name} {tag}.svg")
                self.assertIn(rel, html)
                self.assertTrue(os.path.exists(os.path.join(self.out, rel)))

    def test_a_report_is_written_beside_the_layers(self):
        self.assertTrue(os.path.exists(os.path.join(self.out, "cleaning_report.txt")))
        self.assertTrue(os.path.exists(os.path.join(self.out, "cleaning_report.csv")))
        text = open(os.path.join(self.out, "cleaning_report.txt"),
                    encoding="utf-8").read()
        self.assertIn("board.gtl", text)
        self.assertIn("crossing the edge (kept)", text)
        self.assertIn("removed:", text)


@unittest.skipUnless(HAVE, "gerbonara/shapely not installed")
class RefusingToDestroyALayer(unittest.TestCase):

    def test_an_offset_layer_is_flagged_and_left_alone(self):
        """A copper layer whose origin is 100 mm off the outline's would
        read as "everything is outside". That is never a cleaning job."""
        src = tempfile.mkdtemp()
        out = tempfile.mkdtemp()
        with open(os.path.join(src, "board.gko"), "w") as f:
            f.write(_outline())
        shifted = (HEADER + "%ADD10C,0.250*%\nD10*\n"
                   + _line(105, 5, 130, 5) + _line(105, 10, 130, 10)
                   + _line(105, 15, 130, 15) + "M02*\n")
        with open(os.path.join(src, "board.gtl"), "w") as f:
            f.write(shifted)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            report = CLEAN.clean_job([os.path.join(src, "board.gko"),
                                      os.path.join(src, "board.gtl")], out)
        copper = report["layers"][0]
        self.assertTrue(copper["suspicious"])
        self.assertEqual(copper["removed"], 0)
        self.assertTrue(any("origin mismatch" in w for w in report["warnings"]))
        from gerbonara import GerberFile
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.assertEqual(len(GerberFile.open(
                os.path.join(out, "board.gtl")).objects), 3)

    def test_a_legend_of_many_strokes_beside_the_board_is_still_cleaned(self):
        """Real jobs carry the job name beside the board as hundreds of
        short strokes — more objects than the board's own pads. That is
        junk to remove, not an origin mismatch."""
        src = tempfile.mkdtemp()
        out = tempfile.mkdtemp()
        with open(os.path.join(src, "board.gko"), "w") as f:
            f.write(_outline())
        # Lettering: 120 hairline strokes 0.8 mm long. Board: 30 pads of 2 mm.
        strokes = "".join(_line(-3, 1 + i * 0.3, -2.2, 1.2 + i * 0.3)
                          for i in range(120))
        pads = "".join(_flash(5 + 5 * (i % 10), 8 + 8 * (i // 10))
                       for i in range(30))
        with open(os.path.join(src, "board.gtl"), "w") as f:
            f.write(HEADER + "%ADD10C,0.100*%\n%ADD11R,2.000X2.000*%\nD10*\n"
                    + strokes + "D11*\n" + pads + "M02*\n")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            report = CLEAN.clean_job([os.path.join(src, "board.gko"),
                                      os.path.join(src, "board.gtl")], out)
        copper = report["layers"][0]
        self.assertFalse(copper["suspicious"])
        self.assertEqual(copper["removed"], 120)
        self.assertEqual(copper["kept"], 30)

    def test_a_panel_is_cleaned_against_the_whole_panel(self):
        """Three boards of 100 x 30 on a 100 x 90 frame, copper on all
        three, and a legend outside the frame. The first run on the real
        panel took ONE board as the outline and removed the other four."""
        src = tempfile.mkdtemp()
        out = tempfile.mkdtemp()
        with open(os.path.join(src, "board.gko"), "w") as f:
            f.write(HEADER + "%ADD10C,0.100*%\nD10*\n"
                    + _line(0, 0, 100, 0) + _line(100, 0, 100, 90)
                    + _line(100, 90, 0, 90) + _line(0, 90, 0, 0)
                    + _line(-3, 30, 103, 30) + _line(-3, 60, 103, 60) + "M02*\n")
        copper = "".join(_line(10, 5 + 30 * k, 90, 5 + 30 * k) for k in range(3))
        with open(os.path.join(src, "board.gtl"), "w") as f:
            f.write(HEADER + "%ADD10C,0.250*%\nD10*\n" + copper
                    + _line(110, 5, 120, 5) + "M02*\n")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            report = CLEAN.clean_job([os.path.join(src, "board.gko"),
                                      os.path.join(src, "board.gtl")], out)
        copper_row = report["layers"][0]
        self.assertFalse(copper_row["suspicious"])
        self.assertEqual(copper_row["kept"], 3)
        self.assertEqual(copper_row["removed"], 1)
        self.assertIn("panel of 3 boards", report["outline"]["source"])
        self.assertAlmostEqual(report["outline"]["height_mm"], 90.0, 2)

    def test_an_outline_that_would_take_a_third_of_the_copper_is_refused(self):
        """A 20 x 20 'outline' over a board whose copper spans 60 x 40: the
        outline is wrong, not the copper. Nothing goes."""
        src = tempfile.mkdtemp()
        out = tempfile.mkdtemp()
        with open(os.path.join(src, "board.gko"), "w") as f:
            f.write(_outline(20, 20))
        tracks = "".join(_line(2, 2 + 3 * k, 58, 2 + 3 * k) for k in range(12))
        with open(os.path.join(src, "board.gtl"), "w") as f:
            f.write(HEADER + "%ADD10C,0.250*%\nD10*\n" + tracks + "M02*\n")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            report = CLEAN.clean_job([os.path.join(src, "board.gko"),
                                      os.path.join(src, "board.gtl")], out)
        copper = report["layers"][0]
        self.assertTrue(copper["suspicious"])
        self.assertEqual(copper["removed"], 0)
        self.assertTrue(any("BY AREA" in w for w in report["warnings"]))

    def test_no_outline_is_a_sentence_not_a_guess(self):
        src = tempfile.mkdtemp()
        with open(os.path.join(src, "board.gtl"), "w") as f:
            f.write(_copper())
        with self.assertRaises(CLEAN.CleanError) as caught:
            CLEAN.clean_job([os.path.join(src, "board.gtl")], tempfile.mkdtemp())
        self.assertIn("outline", str(caught.exception).lower())


@unittest.skipUnless(HAVE and os.path.isdir(REAL), "sample jobs not here")
class TheRealSampleJob(unittest.TestCase):

    def test_the_real_panel_keeps_all_five_boards(self):
        src = os.path.join(REAL, "CT-TT-CAP12-V1.1-FAB (1).zip")
        if not os.path.exists(src):
            self.skipTest("sample missing")
        out = tempfile.mkdtemp(prefix="prism-clean-panel-")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            report = CLEAN.clean_job([src], out)
        self.assertAlmostEqual(report["outline"]["width_mm"], 184.0, 1)
        self.assertAlmostEqual(report["outline"]["height_mm"], 195.0, 1)
        top = next(l for l in report["layers"] if l["name"].endswith(".GTL"))
        self.assertFalse(top["suspicious"])
        self.assertGreater(top["kept"], 0.9 * top["objects"])

    def test_every_layer_survives_the_round_trip(self):
        src = os.path.join(REAL, "layer 1.zip")
        if not os.path.exists(src):
            self.skipTest("sample missing")
        out = tempfile.mkdtemp(prefix="prism-clean-real-")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            report = CLEAN.clean_job([src], out)
        self.assertAlmostEqual(report["outline"]["width_mm"], 60.0, 0)
        self.assertTrue(report["layers"], "no image layer was cleaned")
        from gerbonara import GerberFile
        for layer in report["layers"]:
            self.assertEqual(layer["kept"] + layer["removed"], layer["objects"])
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                again = GerberFile.open(os.path.join(out, layer["name"]))
            self.assertEqual(len(again.objects), layer["kept"], layer["name"])
            self.assertFalse(layer["suspicious"], layer["name"])


if __name__ == "__main__":
    unittest.main()
