"""Measuring a PCB job, and the three ways the obvious implementation lies.

Every number here has a naive computation that looks right and isn't, and
each one was caught on a real customer job rather than reasoned about:

  · **Size is not the bounding box.** A 2018 four-layer job measured
    3.600 x 3.750 in across its ink and 3.550 x 3.550 in across its actual
    outline. The difference is two fiducials and a legend block sitting
    outside the board edge — 10% of the area, straight into the price.

  · **The smallest gap is usually noise.** The same job's tightest copper
    pair is 1 mil apart, at one connector footprint, on a board routed
    throughout to 10 mil. A 2013 job's raw minimum was 0.0078 mm — three
    tenths of a mil, which is not a clearance, it is two shapes meant to
    touch that rounded apart. Reported as the headline, either number makes
    a buildable board look unbuildable.

  · **The smallest aperture may barely exist.** 8 mil of track over 2.3
    inches, against 304 inches at 50 mil, is a true minimum and a
    misleading one.

And two format traps that make a parser silently return nothing at all
rather than fail: a drill supplied as a Gerber of flashed pads (older jobs
still ship this way), and four-digit D-codes, which a `D\\d{2,3}` pattern
matches nowhere — so every hole on that job vanishes without an error.

The synthetic fixtures below are boards whose true answers are known by
construction. The real-job checks at the bottom skip when the sample folder
is absent, which is how CI sees them.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import textwrap
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "prism_terminal"))

from core import gerber as G  # noqa: E402


def _write(dirpath: str, name: str, body: str) -> str:
    path = os.path.join(dirpath, name)
    with open(path, "w") as fh:
        fh.write(textwrap.dedent(body).lstrip())
    return path


# A 50 x 30 mm board. The outline layer also carries a 5 x 5 mm legend box
# well outside the board edge — exactly the thing that inflates a bounding
# box, and the reason this fixture is not simply a rectangle.
OUTLINE_50x30 = """
    %FSLAX34Y34*%
    %MOMM*%
    %ADD10C,0.100*%
    D10*
    X0Y0D02*
    X500000Y0D01*
    X500000Y300000D01*
    X0Y300000D01*
    X0Y0D01*
    X600000Y400000D02*
    X650000Y400000D01*
    X650000Y450000D01*
    X600000Y450000D01*
    X600000Y400000D01*
    M02*
    """

# Two horizontal tracks, 0.2 mm wide, whose centres are 1.2 mm apart — so
# the copper-to-copper gap is exactly 1.0 mm. Plus a 0.5 mm track elsewhere,
# so the minimum width has something to be the minimum OF.
COPPER = """
    %FSLAX34Y34*%
    %MOMM*%
    %ADD10C,0.200*%
    %ADD11C,0.500*%
    D10*
    X50000Y50000D02*
    X200000Y50000D01*
    X50000Y62000D02*
    X200000Y62000D01*
    D11*
    X50000Y95000D02*
    X200000Y95000D01*
    M02*
    """

DRILL_EXCELLON = """
    M48
    INCH
    T1C0.0236
    T2C0.0394
    T3C0.1000
    %
    T01
    X001000Y001000
    X002000Y001000
    X003000Y001000
    T02
    X004000Y002000
    T03
    M30
    """


class TheBoardIsItsOutlineNotItsInk(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        _write(self.dir, "job.gko", OUTLINE_50x30)
        _write(self.dir, "job.gtl", COPPER)

    def test_the_legend_box_outside_the_board_does_not_count(self):
        """The bounding box of this outline layer is 65 x 45 mm. The board
        is 50 x 30. Getting that wrong is a 95% over-estimate of area."""
        job = G.analyse(G.gather([self.dir]))
        w, h = job["answers"]["pcb_size_mm"]
        self.assertAlmostEqual(w, 50.0, places=2)
        self.assertAlmostEqual(h, 30.0, places=2)

    def test_it_says_how_the_size_was_arrived_at(self):
        """A size with no stated method cannot be argued with, and this one
        has to be arguable — it is the number the price is built on."""
        job = G.analyse(G.gather([self.dir]))
        self.assertTrue(job["board"]["confident"])
        self.assertIn("closed outline", job["board"]["method"])
        self.assertEqual(job["board"]["source"], "job.gko")

    def test_a_job_with_no_outline_says_so_loudly(self):
        """Falling back to the copper bounding box is legitimate. Doing it
        quietly is not — the customer is owed the caveat before the quote."""
        alone = tempfile.mkdtemp()
        _write(alone, "job.gtl", COPPER)
        job = G.analyse(G.gather([alone]))
        self.assertFalse(job["board"]["confident"])
        self.assertTrue(any("NO BOARD OUTLINE" in w for w in job["warnings"]))


class TrackWidthCarriesItsOwnContext(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        _write(self.dir, "job.gko", OUTLINE_50x30)
        _write(self.dir, "job.gtl", COPPER)
        self.job = G.analyse(G.gather([self.dir]))

    def test_the_minimum_is_the_smallest_aperture_actually_drawn_with(self):
        self.assertAlmostEqual(
            self.job["answers"]["min_track_width_mm"], 0.2, places=3)

    def test_every_width_reports_how_much_of_it_there_is(self):
        """8 mil across 2.3 inches and 8 mil across the whole board are the
        same headline and different jobs. Segment count and trace length are
        what let a fab tell them apart."""
        widths = self.job["copper"][0]["widths"]
        self.assertEqual([round(w["width_mm"], 3) for w in widths], [0.2, 0.5])
        for w in widths:
            self.assertGreater(w["segments"], 0)
            self.assertGreater(w["length_mm"], 0)

    def test_pads_are_not_mistaken_for_tracks(self):
        """A 3 mm flashed pad is not a 3 mm trace. Only DRAWN copper counts."""
        padded = tempfile.mkdtemp()
        _write(padded, "job.gtl", """
            %FSLAX34Y34*%
            %MOMM*%
            %ADD10C,0.200*%
            %ADD11C,3.000*%
            D11*
            X100000Y100000D03*
            D10*
            X50000Y50000D02*
            X200000Y50000D01*
            M02*
            """)
        job = G.analyse(G.gather([padded]))
        widths = job["copper"][0]["widths"]
        self.assertEqual([round(w["width_mm"], 3) for w in widths], [0.2])


class SpacingTellsTheRuleFromTheOutlier(unittest.TestCase):

    def test_the_gap_is_between_copper_edges_not_centrelines(self):
        """Two 0.2 mm tracks 1.2 mm apart centre-to-centre are 1.0 mm apart
        as copper. Measuring centrelines overstates every clearance by a
        track width."""
        d = tempfile.mkdtemp()
        _write(d, "job.gko", OUTLINE_50x30)
        _write(d, "job.gtl", COPPER)
        job = G.analyse(G.gather([d]))
        self.assertAlmostEqual(
            job["answers"]["min_track_spacing_mm"], 1.0, places=2)

    def test_a_hairline_below_the_snap_tolerance_is_not_a_clearance(self):
        """Two shapes meant to touch, rounded apart by the file's own
        coordinate resolution. On a real 2013 job that hairline was 0.0078
        mm and became the reported minimum spacing — three tenths of a mil,
        which no fab on earth quotes against."""
        d = tempfile.mkdtemp()
        _write(d, "job.gtl", """
            %FSLAX34Y34*%
            %MOMM*%
            %ADD10C,0.200*%
            D10*
            X50000Y50000D02*
            X100000Y50000D01*
            X102050Y50000D02*
            X150000Y50000D01*
            X50000Y70000D02*
            X150000Y70000D01*
            M02*
            """)
        job = G.analyse(G.gather([d]))
        sp = job["copper"][0]["spacing"]
        self.assertGreater(sp["snapped"], 0)
        self.assertGreater(sp["min_mm"], 0.5)

    def test_the_distribution_comes_back_with_the_minimum(self):
        """The busiest bucket is the design rule; the minimum may be one
        footprint. Reporting only the minimum hides which of those it is."""
        d = tempfile.mkdtemp()
        _write(d, "job.gtl", COPPER)
        job = G.analyse(G.gather([d]))
        self.assertTrue(job["copper"][0]["spacing"]["histogram"])

    def test_clear_polarity_is_subtracted_not_added(self):
        """A plane is one dark region with its clearances knocked out in
        clear polarity. Treating those as copper merges every net on the
        board into one island, and spacing comes back as 'nothing to
        measure' on the very layer that needed measuring most."""
        d = tempfile.mkdtemp()
        _write(d, "plane.gtl", """
            %FSLAX34Y34*%
            %MOMM*%
            %ADD10C,0.100*%
            %LPD*%
            G36*
            X0Y0D02*
            X400000Y0D01*
            X400000Y400000D01*
            X0Y400000D01*
            X0Y0D01*
            G37*
            %LPC*%
            G36*
            X190000Y0D02*
            X210000Y0D01*
            X210000Y400000D01*
            X190000Y400000D01*
            X190000Y0D01*
            G37*
            M02*
            """)
        job = G.analyse(G.gather([d]))
        sp = job["copper"][0]["spacing"]
        self.assertEqual(sp["islands"], 2)
        self.assertAlmostEqual(sp["min_mm"], 2.0, places=2)


class DrillsSurviveBothFormatsTheyArriveIn(unittest.TestCase):

    def test_an_excellon_tool_table_is_read_in_millimetres(self):
        d = tempfile.mkdtemp()
        _write(d, "job.drl", DRILL_EXCELLON)
        job = G.analyse(G.gather([d]))
        self.assertAlmostEqual(job["answers"]["min_drill_mm"], 0.6, places=2)
        self.assertEqual(job["answers"]["drill_count"], 4)

    def test_a_declared_tool_that_drills_nothing_does_not_set_the_price(self):
        """T3 is 2.54 mm and has no hits. It is also the only tool that could
        make this job look like it needs a 0.1 in bit."""
        d = tempfile.mkdtemp()
        _write(d, "job.drl", DRILL_EXCELLON)
        job = G.analyse(G.gather([d]))
        self.assertAlmostEqual(job["answers"]["min_drill_mm"], 0.6, places=2)
        self.assertTrue(any("never used" in w for w in job["warnings"]))

    def test_a_drill_supplied_as_a_gerber_is_still_a_drill(self):
        """Older jobs ship the drill as flashed pads in a Gerber. A parser
        that only reads Excellon reports no holes at all, which reads as a
        board with no holes rather than as an unread file.

        Note the four-digit D-codes — that is how these files are written,
        and a D\\d{2,3} pattern matches none of them."""
        d = tempfile.mkdtemp()
        _write(d, "job.txt", """
            %FSTAX44Y44*%
            %MOMM*%
            %ADD9500C,1.000*%
            %ADD9501C,1.300*%
            %LPD*%
            G54D9500*
            X00100000Y00100000D03*
            X00200000D03*
            G54D9501*
            X00300000Y00100000D03*
            M02*
            """)
        job = G.analyse(G.gather([d]))
        self.assertAlmostEqual(job["answers"]["min_drill_mm"], 1.0, places=3)
        self.assertEqual(job["answers"]["drill_count"], 3)
        self.assertTrue(any("came as a GERBER" in w for w in job["warnings"]))

    def test_a_job_with_no_drill_file_says_so_rather_than_reporting_zero(self):
        d = tempfile.mkdtemp()
        _write(d, "job.gtl", COPPER)
        job = G.analyse(G.gather([d]))
        self.assertIsNone(job["answers"]["drill_count"])
        self.assertTrue(any("No drill file" in w for w in job["warnings"]))


class ModalCodesAndPolarityOrder(unittest.TestCase):
    """Two defects found by measuring the same boards with an unrelated
    library (gerbonara) and an unrelated method (raster + distance
    transform), rather than by reading the code."""

    def test_a_coordinate_line_with_no_d_code_continues_the_last_one(self):
        """D01/D02/D03 are MODAL. Older CAM tools lean on it hard: the 2013
        job writes 4332 of its 4336 region points with no D-code at all.
        Acting only on an explicit D01 read 158 of that layer's 470
        objects — and then measured the clearance of a board it had mostly
        not read, without any error to say so.

        Here: one square drawn as four sides, only the first carrying D01."""
        d = tempfile.mkdtemp()
        _write(d, "job.gko", """
            %FSLAX34Y34*%
            %MOMM*%
            %ADD10C,0.100*%
            D10*
            X0Y0D02*
            X400000Y0D01*
            X400000Y300000*
            X0Y300000*
            X0Y0*
            M02*
            """)
        job = G.analyse(G.gather([d]))
        w, h = job["answers"]["pcb_size_mm"]
        self.assertAlmostEqual(w, 40.0, places=2)
        self.assertAlmostEqual(h, 30.0, places=2)

    def test_a_region_built_from_modal_points_is_still_a_region(self):
        d = tempfile.mkdtemp()
        _write(d, "job.gtl", """
            %FSLAX34Y34*%
            %MOMM*%
            %ADD10C,0.100*%
            G36*
            X0Y0D02*
            X100000Y0D01*
            X100000Y100000*
            X0Y100000*
            X0Y0*
            G37*
            M02*
            """)
        layer = G.parse_gerber(os.path.join(d, "job.gtl"))
        self.assertEqual(len(layer.regions), 1)
        self.assertAlmostEqual(G.layer_copper(layer).area, 100.0, places=1)

    def test_a_dark_object_after_a_clear_one_puts_the_copper_back(self):
        """Gerber paints in sequence. Unioning every dark object and then
        subtracting every clear one is a different picture whenever the file
        goes dark → clear → dark — and the 2013 job does exactly that, at
        lines 11, 3755 and 4524.

        Here a 10x10 square, a clear stripe through its middle, then a dark
        square filling that stripe back in. Sequentially the copper is
        whole: 100 mm². Bucketed by polarity it comes out 60."""
        d = tempfile.mkdtemp()
        _write(d, "job.gtl", """
            %FSLAX34Y34*%
            %MOMM*%
            %ADD10C,0.100*%
            %LPD*%
            G36*
            X0Y0D02*
            X100000Y0D01*
            X100000Y100000*
            X0Y100000*
            X0Y0*
            G37*
            %LPC*%
            G36*
            X40000Y0D02*
            X60000Y0D01*
            X60000Y100000*
            X40000Y100000*
            X40000Y0*
            G37*
            %LPD*%
            G36*
            X40000Y0D02*
            X60000Y0D01*
            X60000Y100000*
            X40000Y100000*
            X40000Y0*
            G37*
            M02*
            """)
        layer = G.parse_gerber(os.path.join(d, "job.gtl"))
        self.assertAlmostEqual(G.layer_copper(layer).area, 100.0, places=1)


class LetteringInCopperIsNotATrack(unittest.TestCase):
    """Boards carry text: part numbers, revision marks, a logo, etched into
    the copper beside the tracks. It is copper. It is not a conductor.

    Measuring it reported a 2013 board's minimum track width as 10 mil when
    every real conductor on it is 118, and its clearance as 5 mil when the
    tightest real gap is 81. The customer's own hand-filled check sheet said
    118 and 81.9 — which is how we found out. Neither the test suite nor an
    independent Gerber library could see it: the file was being read
    correctly, and the wrong thing was being measured.

    A conductor connects to something. Lettering connects to nothing. So an
    island counts only if it carries a flashed pad."""

    LETTERED = """
        %FSLAX34Y34*%
        %MOMM*%
        %ADD10C,2.000*%
        %ADD11C,0.100*%
        %ADD12C,1.500*%
        D10*
        X50000Y50000D02*
        X250000Y50000D01*
        X50000Y150000D02*
        X250000Y150000D01*
        D12*
        X50000Y50000D03*
        X250000Y50000D03*
        X50000Y150000D03*
        X250000Y150000D03*
        D11*
        X100000Y250000D02*
        X100000Y280000D01*
        X104000Y250000D02*
        X104000Y280000D01*
        M02*
        """

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        _write(self.dir, "job.gtl", self.LETTERED)
        self.job = G.analyse(G.gather([self.dir]))
        self.row = self.job["copper"][0]

    def test_the_thin_lettering_does_not_become_the_minimum_width(self):
        """Two 2 mm bars with pads, and two 0.1 mm strokes with none. The
        answer is 2 mm."""
        self.assertAlmostEqual(
            self.job["answers"]["min_track_width_mm"], 2.0, places=3)

    def test_the_gap_between_letters_does_not_become_the_clearance(self):
        """The strokes are 0.4 mm apart centre to centre — 0.3 mm of copper
        gap, tighter than anything between the real conductors."""
        self.assertGreater(self.job["answers"]["min_track_spacing_mm"], 1.0)

    def test_it_says_how_much_it_set_aside(self):
        """Silently dropping copper is how you get a number nobody can
        argue with. The count is reported and warned about."""
        self.assertEqual(self.row["markings"], 2)
        self.assertEqual(self.row["conductors"], 2)
        self.assertTrue(any("carry no pad" in w for w in self.job["warnings"]))

    def test_the_everything_included_figure_is_still_available(self):
        """A customer who asks "what about the printing?" gets an answer.
        Etched lettering IS an etching constraint — just not track spacing."""
        self.assertLess(self.row["spacing"]["with_markings_mm"], 1.0)

    def test_a_layer_with_no_pads_at_all_is_measured_whole(self):
        """The test needs something to test against. With no flashes there
        is nothing, so measure everything rather than report nothing."""
        d = tempfile.mkdtemp()
        _write(d, "job.gtl", """
            %FSLAX34Y34*%
            %MOMM*%
            %ADD10C,0.200*%
            D10*
            X50000Y50000D02*
            X250000Y50000D01*
            X50000Y100000D02*
            X250000Y100000D01*
            M02*
            """)
        job = G.analyse(G.gather([d]))
        self.assertAlmostEqual(
            job["answers"]["min_track_width_mm"], 0.2, places=3)
        self.assertEqual(job["copper"][0]["markings"], 0)


class APlaneHasNoTracks(unittest.TestCase):
    """An internal ground or power plane is a solid copper sheet. The only
    thing in its Gerber is the clearance punched around each hole, so
    "minimum track width" on one is a category error, not a small number.

    On the 2018 job the two plane layers reported 3 mil on a board routed to
    10, and dragged the whole job's answer down with them. They still count
    toward the layer total — a 4-layer board is priced as a 4-layer board."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        _write(self.dir, "job.gtl", COPPER)
        _write(self.dir, "job.gko", OUTLINE_50x30)
        # A plane: nothing but anti-pads, two of them very close together.
        _write(self.dir, "job.gp1", """
            %FSLAX34Y34*%
            %MOMM*%
            %ADD10C,1.000*%
            D10*
            X100000Y100000D03*
            X110500Y100000D03*
            M02*
            """)
        self.job = G.analyse(G.gather([self.dir]))

    def test_the_plane_is_not_measured_for_tracks(self):
        measured = [r["name"] for r in self.job["copper"]]
        self.assertNotIn("job.gp1", measured)

    def test_the_plane_still_counts_as_a_layer(self):
        self.assertEqual(self.job["answers"]["layers"], 2)
        self.assertEqual(self.job["answers"]["routed_layers"], 1)
        self.assertEqual(self.job["answers"]["plane_layers"], 1)

    def test_it_says_the_plane_was_set_aside_and_why(self):
        self.assertTrue(any("internal plane" in w for w in self.job["warnings"]))


class AgainstTheCustomersOwnCheckSheet(unittest.TestCase):
    """The strongest witness we have: Fine Circuits filled in both jobs by
    hand, in their own spreadsheet, in mil. Every figure below is theirs.

    Four of the six matched on the day it arrived. The two that did not —
    track width and track spacing, on BOTH boards — are what taught us that
    lettering in copper was being measured as track."""

    SHEET = {
        "layer 1.zip": dict(layers=1, x_in=2.3622, y_in=2.8740,
                            width_mil=118, spacing_mil=81.9,
                            drill_mil=39.37, holes=80),
        "CAM for EI-500DT-CYP-TOP-001-V2 ERP53.rar":
                       dict(layers=2, x_in=3.5500, y_in=3.5500,
                            width_mil=10, spacing_mil=10,
                            drill_mil=18, holes=218),
    }

    def _job(self, name):
        if not os.path.isdir(REAL):
            self.skipTest("sample jobs not on this machine")
        src = os.path.join(REAL, name)
        if not os.path.exists(src):
            self.skipTest("sample missing")
        try:
            return G.analyse(G.gather([src]))
        except G.GerberError as e:
            self.skipTest(str(e))

    def _check(self, name):
        want = self.SHEET[name]
        a = self._job(name)["answers"]
        mil = G.mm_to_mil
        self.assertAlmostEqual(a["pcb_size_mm"][0] / 25.4, want["x_in"], places=3)
        self.assertAlmostEqual(a["pcb_size_mm"][1] / 25.4, want["y_in"], places=3)
        self.assertAlmostEqual(mil(a["min_drill_mm"]), want["drill_mil"], places=1)
        self.assertEqual(a["drill_count"], want["holes"])
        # Track width is exact. Spacing is his measurement of a specific
        # pair against our global minimum, so 2 mil of daylight is agreement,
        # not a pass mark set low: 5 vs 81 is what failure looked like.
        self.assertAlmostEqual(mil(a["min_track_width_mm"]), want["width_mil"],
                               delta=0.2)
        self.assertAlmostEqual(mil(a["min_track_spacing_mm"]),
                               want["spacing_mil"], delta=2.0)
        # He counts ROUTED layers — the 2018 board's two planes are not in
        # his "2", and that is the reading his own CAM report supports.
        self.assertEqual(a["routed_layers"], want["layers"])

    def test_the_2013_single_sided_job(self):
        self._check("layer 1.zip")

    def test_the_2018_four_layer_job(self):
        self._check("CAM for EI-500DT-CYP-TOP-001-V2 ERP53.rar")


class AgainstAnIndependentImplementation(unittest.TestCase):
    """gerbonara is an unrelated Gerber library. Where it is installed, the
    object counts and aperture sizes it reads must match ours exactly —
    that comparison is what found the two defects above."""

    def setUp(self):
        try:
            import gerbonara            # noqa: F401
        except ImportError:
            self.skipTest("gerbonara not installed")
        import warnings
        # gerbonara warns on every modal coordinate line — 4500 of them on
        # this job, and the exact construct Prism was fixed to handle.
        warnings.filterwarnings("ignore", category=SyntaxWarning)
        if not os.path.isdir(REAL):
            self.skipTest("sample jobs not on this machine")

    def test_object_counts_match_on_the_2013_job(self):
        from gerbonara import GerberFile
        from gerbonara.graphic_objects import Line, Flash, Region
        src = os.path.join(REAL, "layer 1.zip")
        if not os.path.exists(src):
            self.skipTest("sample missing")
        paths = G.gather([src])
        gbl = next(p for p in paths if p.lower().endswith(".gbl"))
        theirs = GerberFile.open(gbl).objects
        mine = G.parse_gerber(gbl)
        self.assertEqual(len(mine.draws),
                         sum(1 for o in theirs if isinstance(o, Line)))
        self.assertEqual(len(mine.flashes),
                         sum(1 for o in theirs if isinstance(o, Flash)))
        self.assertEqual(len(mine.regions),
                         sum(1 for o in theirs if isinstance(o, Region)))


class TheOverloadedTxtExtension(unittest.TestCase):
    """`.txt` in a Gerber folder has been seen as all three of these, and
    only looking inside tells them apart."""

    def test_an_excellon_txt_is_the_drill(self):
        d = tempfile.mkdtemp()
        path = _write(d, "job.txt", DRILL_EXCELLON)
        self.assertEqual(G.classify([path])[0]["role"], "drill")

    def test_a_gerber_txt_is_the_drill_as_flashed_pads(self):
        d = tempfile.mkdtemp()
        path = _write(d, "job.txt", """
            %FSTAX44Y44*%
            %MOMM*%
            %ADD9500C,1.000*%
            G54D9500*
            X00100000Y00100000D03*
            M02*
            """)
        self.assertEqual(G.classify([path])[0]["role"], "drill_gerber")

    def test_a_prose_txt_is_a_report_and_is_measured_from_nothing(self):
        d = tempfile.mkdtemp()
        path = _write(d, "readme.txt", """
            NCDrill File Report For: BOARD.PCB
            Tool         Hole Size          Hole Count
            T1        18mil (0.4572mm)         93
            """)
        self.assertEqual(G.classify([path])[0]["role"], "report")


class UnitsAndFormatSpecs(unittest.TestCase):

    def test_an_inch_job_comes_back_in_millimetres(self):
        """Two layers of one job have arrived in different units before.
        Everything is normalised at parse time so nothing downstream has to
        remember which."""
        d = tempfile.mkdtemp()
        _write(d, "job.gtl", """
            %FSLAX24Y24*%
            %MOIN*%
            %ADD10C,0.010*%
            D10*
            X10000Y10000D02*
            X20000Y10000D01*
            M02*
            """)
        job = G.analyse(G.gather([d]))
        self.assertAlmostEqual(
            job["answers"]["min_track_width_mm"], 0.254, places=3)

    def test_trailing_zero_suppression_is_not_read_as_leading(self):
        """%FST pads the other end. Read the wrong way the whole board is
        out by a power of ten, which is the kind of error that looks like a
        different board rather than like a bug."""
        d = tempfile.mkdtemp()
        _write(d, "job.gko", """
            %FSTAX44Y44*%
            %MOMM*%
            %ADD10C,0.100*%
            D10*
            X0Y0D02*
            X006D01*
            X006Y0073D01*
            X0Y0073D01*
            X0Y0D01*
            M02*
            """)
        job = G.analyse(G.gather([d]))
        w, h = job["answers"]["pcb_size_mm"]
        self.assertAlmostEqual(w, 60.0, places=1)
        self.assertAlmostEqual(h, 73.0, places=1)


class TheNumbersGoOutButTheDesignDoesNot(unittest.TestCase):
    """The standing rule for the whole add-on: the other AIs get the sample
    template and the company details, never the Gerber files."""

    def test_the_command_hands_an_agent_numbers_and_never_a_file(self):
        import inspect
        import prism
        src = inspect.getsource(prism.cmd_gerber)
        self.assertIn("attachments=[]", src)
        self.assertIn("no AI sees a Gerber", src)

    def test_the_shared_brief_names_no_path_and_says_the_files_are_not_attached(self):
        """agent_brief() is the one place this text is built now — the
        terminal and the GUI dialog both call it, so the confidentiality
        sentence cannot say something different, or go missing, in one of
        the two surfaces that hand an agent a job's numbers."""
        d = tempfile.mkdtemp()
        _write(d, "job.gko", OUTLINE_50x30)
        _write(d, "job.gtl", COPPER)
        _write(d, "job.drl", DRILL_EXCELLON)
        job = G.analyse(G.gather([d]))
        brief = G.agent_brief(job, "reply with our price")
        self.assertIn("reply with our price", brief)
        self.assertIn("NOT\nattached".replace("\n", " "), brief)
        self.assertIn("confidential", brief)
        self.assertNotIn(d, brief)           # no path to the real files
        self.assertNotIn(".gtl", brief)
        self.assertIn(job["answers"]["pcb_size"], brief)

    def test_the_brief_stands_on_its_own_with_no_instruction(self):
        d = tempfile.mkdtemp()
        _write(d, "job.gko", OUTLINE_50x30)
        _write(d, "job.gtl", COPPER)
        job = G.analyse(G.gather([d]))
        brief = G.agent_brief(job)
        self.assertIn("Reply with the measured figures below", brief)


REAL = "/Users/hitarthtrivedi/Documents/PythonProgram/prism-ai-flow/gerber_test"


class TheRulebookIsNotTheBoard(unittest.TestCase):
    """A .RUL file is the designer's rulebook: what the board was ALLOWED to
    use. The copper is what it actually uses. A speed limit and a radar
    reading — both true, different questions.

    It matters commercially rather than academically. A real job states a
    width minimum of 3.94 mil where the thinnest track actually drawn is
    11.8. A fabricator who opens the .RUL and quotes 3.94 sees a number three
    times out from ours and concludes the software is broken. Showing both
    removes the argument before it starts."""

    RUL = """
        DRC Rules Export File for PCB: BOARD.PcbDoc
        RuleKind=Width|RuleName=Width|Scope=Board|Minimum=3.94
        RuleKind=Clearance|RuleName=Clearance|Scope=Board|Minimum=7.87
        RuleKind=MinimumAnnularRing|RuleName=MinimumAnnularRing|Scope=Board|Minimum=4.92
        RuleKind=Clearance|RuleName=Abstand Pads am ASIC|Scope=Board|Minimum=1.00
        RuleKind=Clearance|RuleName=Clearance KeepOut|Scope=Board|Minimum=0.00
        """

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        _write(self.dir, "job.gko", OUTLINE_50x30)
        _write(self.dir, "job.gtl", COPPER)
        _write(self.dir, "job.rul", self.RUL)
        self.job = G.analyse(G.gather([self.dir]))

    def test_the_rules_are_read(self):
        r = self.job["rules"]
        self.assertAlmostEqual(r["min_track_width_mm"], 0.1001, places=3)
        self.assertAlmostEqual(r["min_track_spacing_mm"], 0.1999, places=3)

    def test_a_local_exception_is_not_the_board_rule(self):
        """A .RUL carries dozens of local exceptions — clearance to one ASIC,
        via to one plane. The tightest of those is not what the board was
        routed to, and taking it would report 1.00 mil here."""
        self.assertGreater(self.job["rules"]["min_track_spacing_mm"], 0.15)

    def test_the_rules_never_replace_the_measurement(self):
        """The measured figure is what limits manufacture. If the rulebook
        ever overwrote it, a board allowed 3.94 would be quoted at 3.94 no
        matter what it actually contains."""
        a = self.job["answers"]
        self.assertAlmostEqual(a["min_track_width_mm"], 0.2, places=3)
        self.assertAlmostEqual(a["min_track_spacing_mm"], 1.0, places=2)

    def test_both_appear_side_by_side(self):
        text = G.answers_text(self.job)
        self.assertIn("design rule allows 3.94 mil", text)
        self.assertIn("design rule allows 7.87 mil", text)

    def test_the_csv_carries_them_and_says_which_is_which(self):
        out = os.path.join(tempfile.mkdtemp(), "r.csv")
        G.write_report_csv(self.job, out)
        body = open(out).read()
        self.assertIn("rule_allows_track_width", body)
        self.assertIn("not what it actually uses", body)

    def test_a_job_with_no_rules_file_is_unaffected(self):
        d = tempfile.mkdtemp()
        _write(d, "job.gko", OUTLINE_50x30)
        _write(d, "job.gtl", COPPER)
        job = G.analyse(G.gather([d]))
        self.assertEqual(job["rules"], {})
        self.assertNotIn("design rule", G.answers_text(job))


class TheOneSheetForEveryJob(unittest.TestCase):
    """The customer's last request: "make excel sheet for data of all gerber
    file" — a row per BOARD across every job, in the column order and the
    units his own spreadsheet already uses, so he can paste rather than
    re-key.

    Pinned because it went missing once. An edit that rewrote the two
    functions on either side of it took this one with it, and nothing failed
    until a live run reached for it by name — the report had already been
    written and saved, so it looked like the run had worked."""

    def _jobs(self):
        d = tempfile.mkdtemp()
        _write(d, "a.gko", OUTLINE_50x30)
        _write(d, "a.gtl", COPPER)
        _write(d, "a.drl", DRILL_EXCELLON)
        return [("board-a", G.analyse(G.gather([d])))]

    def test_it_exists_and_writes_a_file(self):
        self.assertTrue(callable(getattr(G, "write_summary_csv", None)))
        out = os.path.join(tempfile.mkdtemp(), "summary.csv")
        G.write_summary_csv(self._jobs(), out)
        self.assertTrue(os.path.getsize(out) > 0)

    def test_the_columns_are_the_ones_his_sheet_uses(self):
        """His sheet reads LAYER, PCB SIZE, TRACK WIDTH, TRACK SPACING, MIN
        DRILL SIZE, TOTAL DRILL — and it is in mil. Matching that is the
        whole value; a better layout he has to re-key is worth less."""
        out = os.path.join(tempfile.mkdtemp(), "summary.csv")
        G.write_summary_csv(self._jobs(), out)
        header = open(out).readline()
        for column in ("LAYERS", "PCB SIZE", "TRACK WIDTH (mil)",
                       "TRACK SPACING (mil)", "MIN DRILL SIZE (mil)",
                       "TOTAL DRILL"):
            self.assertIn(column, header)

    def test_every_job_gets_a_row_and_the_files_are_named_underneath(self):
        out = os.path.join(tempfile.mkdtemp(), "summary.csv")
        G.write_summary_csv(self._jobs(), out)
        body = open(out).read()
        self.assertIn("board-a", body)
        self.assertIn("IDENTIFIED AS", body)      # layer identification
        self.assertIn("a.gtl", body)

    def test_the_row_says_what_it_was_checked_against(self):
        """A row reproducing the job's own CAM report is worth more than one
        that only reproduces itself, and the difference should be visible
        without having to ask."""
        out = os.path.join(tempfile.mkdtemp(), "summary.csv")
        G.write_summary_csv(self._jobs(), out)
        self.assertIn("CHECKED AGAINST", open(out).readline())
        self.assertIn("geometry only", open(out).read())


class EveryJobWeHaveStillReadsRight(unittest.TestCase):
    """The standing rule: a fix found on one job must not move another.

    Every real customer job has its answers in tests/gerber_samples.json,
    and a new job goes in the day it arrives. This is not belt and braces —
    each of the last four fixes came from exactly ONE job failing, and three
    of them touched code every other job goes through. Modal D-codes, the
    lettering test, merging three drill files, aperture macros: any of those
    could have quietly moved a board that was already right.

    Two tiers, and the distinction is the point. A WITNESSED value has a
    source outside Prism — the customer's own check sheet, or the CAM report
    shipped inside the job — so breaking one means Prism is wrong. A LOCKED
    value is only what Prism reads today, so breaking one means something
    changed and a human has to say whether it improved. Never promote a
    locked value without an actual witness.
    """

    @classmethod
    def setUpClass(cls):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "gerber_samples.json")
        with open(path) as fh:
            cls.samples = {k: v for k, v in json.load(fh).items()
                           if not k.startswith("_")}

    def _measure(self, name):
        if not os.path.isdir(REAL):
            self.skipTest("sample jobs not on this machine")
        if (self.samples[name].get("slow")
                and not os.environ.get("PRISM_SLOW_TESTS")):
            # The twelve-layer board takes five minutes. That is fine for a
            # customer waiting on an answer and not fine on every run, so it
            # is opt-in — and named here rather than quietly dropped.
            self.skipTest(f"{name} is slow; set PRISM_SLOW_TESTS=1 to include it")
        src = os.path.join(REAL, name)
        if not os.path.exists(src):
            self.skipTest(f"{name} not on this machine")
        try:
            return G.analyse(G.gather([src]))["answers"]
        except G.GerberError as e:
            self.skipTest(str(e))

    def _compare(self, got, want, name, tier, tol=0.002):
        for key, expected in want.items():
            actual = got.get(key)
            msg = f"{name} [{tier}] {key}: expected {expected}, got {actual}"
            if isinstance(expected, list):
                self.assertIsNotNone(actual, msg)
                for e, a in zip(expected, actual):
                    self.assertAlmostEqual(e, a, delta=tol, msg=msg)
            elif isinstance(expected, float):
                self.assertIsNotNone(actual, msg)
                self.assertAlmostEqual(expected, actual, delta=tol, msg=msg)
            else:
                self.assertEqual(expected, actual, msg)

    def test_every_sample_job(self):
        """One subTest per job, so a break names the job and the figure
        rather than stopping at the first one."""
        for name, spec in self.samples.items():
            with self.subTest(job=name):
                got = self._measure(name)
                self._compare(got, spec.get("witnessed", {}), name, "witnessed")
                for key, (expected, tol) in spec.get(
                        "witnessed_tolerance", {}).items():
                    actual = got.get(key)
                    self.assertIsNotNone(actual, f"{name}: {key} not measured")
                    self.assertAlmostEqual(
                        expected, actual, delta=tol,
                        msg=f"{name} [witnessed±{tol}] {key}: "
                            f"expected ~{expected}, got {actual}")
                self._compare(got, spec.get("locked", {}), name, "locked")

    def test_the_file_says_where_each_number_came_from(self):
        """A pinned number with no stated source is a number nobody can
        re-check, and in six weeks nobody will remember whether it was
        measured or merely observed."""
        for name, spec in self.samples.items():
            with self.subTest(job=name):
                self.assertTrue(spec.get("what"), f"{name}: no description")
                if spec.get("witnessed") or spec.get("witnessed_tolerance"):
                    self.assertTrue(spec.get("witness"),
                                    f"{name}: witnessed values with no witness named")


class TheJobsOwnCamReportIsAWitness(unittest.TestCase):
    """Altium wrote a .DRR in 2018 stating 218 holes across ten tools. It is
    the only figure this job carries that nobody here produced, so it is the
    check that cannot be argued with.

    The five measured numbers are pinned separately, against the customer's
    own check sheet — see AgainstTheCustomersOwnCheckSheet."""

    def test_the_2018_job_reproduces_its_own_cam_report(self):
        if not os.path.isdir(REAL):
            self.skipTest("sample jobs not on this machine")
        src = os.path.join(REAL, "CAM for EI-500DT-CYP-TOP-001-V2 ERP53.rar")
        if not os.path.exists(src):
            self.skipTest("sample missing")
        try:
            job = G.analyse(G.gather([src]))
        except G.GerberError as e:
            self.skipTest(str(e))
        checks = G.crosscheck(job)
        self.assertTrue(checks)
        for c in checks:
            self.assertTrue(c["agrees"], f"{c['what']}: {c}")


if __name__ == "__main__":
    unittest.main()
