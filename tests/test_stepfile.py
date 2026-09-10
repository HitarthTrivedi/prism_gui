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

# Where the real customer jobs live on this machine — an env var with the
# old hardcoded Mac path as its fallback. See tests/sample_jobs.py.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sample_jobs  # noqa: E402

from core import stepfile as SF  # noqa: E402

HAVE = SF.available()[0]
REAL = sample_jobs.path("step_file_demo", "Assem1.STEP")


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


@unittest.skipUnless(HAVE, "cadquery not installed")
class TheBriefForTheImageAgent(unittest.TestCase):
    """/step-auto's prompt: exact measured figures in, the model kept out."""

    @classmethod
    def setUpClass(cls):
        cls.path = os.path.join(tempfile.mkdtemp(), "block.step")
        _box_with_hole(cls.path)
        cls.brief = SF.auto_brief(SF.analyse(cls.path, mode="plastic"))

    def test_the_measured_figures_are_in_it_verbatim(self):
        self.assertIn("60.00 x 40.00 x 8.00 mm", self.brief)
        self.assertIn("Ø5 x 1", self.brief)

    def test_it_says_the_model_is_not_shared(self):
        self.assertIn("MEASURED OFFLINE", self.brief)
        self.assertIn("is not shared", self.brief)

    def test_it_forbids_invented_numbers(self):
        self.assertIn("EXACTLY the numbers above", self.brief)
        self.assertIn("do not round", self.brief)

    def test_it_forbids_fake_flat_patterns_and_tolerances(self):
        """ChatGPT's first real sheet labelled a decorative view 'FLAT
        PATTERN' and invented a ±0.05 tolerance note — both are the kind of
        plausible extra a fabricator would act on."""
        self.assertIn("Never label any view 'flat pattern'", self.brief)
        self.assertIn("Do not state any tolerance", self.brief)

    def test_every_figure_is_two_decimals(self):
        for number in re.findall(r"\d+\.(\d+)", self.brief):
            self.assertLessEqual(len(number), 2)


@unittest.skipUnless(HAVE and os.path.exists(REAL),
                     "cadquery missing, or " + (sample_jobs.missing(
                         "step_file_demo", "Assem1.STEP") or ""))
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
            svg = os.path.join(out, SF.view_name("Assem1", name, 0))
            self.assertTrue(os.path.exists(svg), svg)
            self.assertGreater(os.path.getsize(svg), 5000, svg)
        self.assertIn("101.00 x 93.00 x 71.00", html)
        # The sheet itself carries the model's name, and so does its title.
        self.assertEqual(os.path.basename(drawn["html"]),
                         "Assem1 - drawing sheet.html")


class ThePlanIsValidatedNotTrusted(unittest.TestCase):
    """/step-ask: whatever the agent answers, only the two executable ops
    survive, and only with sane numbers."""

    def test_a_fenced_json_plan_parses(self):
        plan, _ = SF.parse_plan([
            'Here you go:\n```json\n{"changes": [{"op": "enlarge_hole", '
            '"part": "top", "dia_mm": 5, "new_dia_mm": 6.5, "why": "M6"}], '
            '"advice": ["add draft"]}\n```'])
        self.assertEqual(plan["changes"], [
            {"op": "enlarge_hole", "part": "top", "dia_mm": 5.0,
             "new_dia_mm": 6.5, "why": "M6"}])
        self.assertEqual(plan["advice"], ["add draft"])

    def test_a_shrink_or_unknown_op_is_dropped(self):
        plan, _ = SF.parse_plan([
            '{"changes": [{"op": "enlarge_hole", "part": "x", "dia_mm": 6, '
            '"new_dia_mm": 5}, {"op": "delete_part", "part": "x"}, '
            '{"op": "scale", "part": "x", "factor": 99}], "advice": []}'])
        self.assertEqual(plan["changes"], [])

    def test_garbage_returns_none_with_a_sentence(self):
        plan, why = SF.parse_plan(["no json here", ""])
        self.assertIsNone(plan)
        self.assertIn("no JSON plan", why)

    def test_the_newest_capture_wins(self):
        older = '{"changes": [], "advice": ["old"]}'
        newer = '{"changes": [], "advice": ["new"]}'
        plan, _ = SF.parse_plan([older, newer])
        self.assertEqual(plan["advice"], ["new"])


@unittest.skipUnless(HAVE, "cadquery not installed")
class ThePromptsCarryNumbersNotTheModel(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.path = os.path.join(tempfile.mkdtemp(), "block.step")
        _box_with_hole(cls.path)
        cls.report = SF.analyse(cls.path, mode="plastic")

    def test_groq_hears_the_figures_and_the_confidentiality(self):
        p = SF.ask_prompt(self.report, "make it lighter")
        self.assertIn("60.00 x 40.00 x 8.00", p)
        self.assertIn("make it lighter", p)
        self.assertIn("cannot be shown to you", p)

    def test_the_planner_gets_the_schema_and_the_honest_out(self):
        p = SF.plan_prompt(self.report, "q", "advice text")
        self.assertIn('"enlarge_hole"', p)
        self.assertIn('"scale"', p)
        self.assertIn("never shrunk", p)
        self.assertIn("empty changes list", p)


@unittest.skipUnless(HAVE, "cadquery not installed")
class ChangesLandOnACopy(unittest.TestCase):
    """apply_plan edits real geometry and the re-measure proves it."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.path = os.path.join(cls.dir, "block.step")
        _box_with_hole(cls.path)

    def test_a_hole_is_enlarged_and_nothing_else_moves(self):
        out = os.path.join(self.dir, "bigger.step")
        done = SF.apply_plan(self.path, {"changes": [
            {"op": "enlarge_hole", "part": "all", "dia_mm": 5.0,
             "new_dia_mm": 6.0, "why": ""}], "advice": []}, out)
        self.assertTrue(any("1 hole(s) enlarged" in l for l in done["log"]))
        part = SF.analyse(out, mode="plastic")["parts"][0]
        self.assertEqual(part["size_mm"], (60.0, 40.0, 8.0))
        self.assertEqual(part["holes"], [{"dia_mm": 6.0, "count": 1}])

    def test_a_scaled_part_keeps_its_holes_as_holes(self):
        out = os.path.join(self.dir, "scaled.step")
        SF.apply_plan(self.path, {"changes": [
            {"op": "scale", "part": "all", "factor": 1.5, "why": ""}],
            "advice": []}, out)
        part = SF.analyse(out, mode="plastic")["parts"][0]
        self.assertEqual(part["size_mm"], (90.0, 60.0, 12.0))
        self.assertEqual(part["holes"], [{"dia_mm": 7.5, "count": 1}])

    def test_the_original_file_is_untouched(self):
        before = open(self.path, "rb").read()
        SF.apply_plan(self.path, {"changes": [
            {"op": "scale", "part": "all", "factor": 2, "why": ""}],
            "advice": []}, os.path.join(self.dir, "x.step"))
        self.assertEqual(open(self.path, "rb").read(), before)

    def test_a_plan_that_lands_nowhere_refuses_to_write(self):
        out = os.path.join(self.dir, "never.step")
        with self.assertRaises(SF.StepError):
            SF.apply_plan(self.path, {"changes": [
                {"op": "enlarge_hole", "part": "no-such-part",
                 "dia_mm": 5.0, "new_dia_mm": 6.0, "why": ""}],
                "advice": []}, out)
        self.assertFalse(os.path.exists(out))


class TheReviewPageComesBeforeTheBuild(unittest.TestCase):
    """The user confirms against a page they can see — a table of every
    dimension before → after and the drawing — and only then is
    modified.step written."""

    PLAN = {"changes": [{"op": "enlarge_hole", "part": "p", "dia_mm": 5.0,
                         "new_dia_mm": 6.0, "why": "fitting"}],
            "advice": ["add draft"]}
    REPORT = {"file": "x.step", "mode": "plastic",
              "overall_mm": (60.0, 40.0, 8.0),
              "parts": [{"name": "p", "size_mm": (60.0, 40.0, 8.0),
                         "thickness_mm": 6.0, "volume_cm3": 38.0,
                         "holes": [{"dia_mm": 5.0, "count": 1},
                                   {"dia_mm": 6.0, "count": 1}]}],
              "warnings": []}

    def test_prediction_merges_an_enlarged_hole_into_its_new_group(self):
        parts = SF.predicted_parts(self.REPORT, self.PLAN)
        self.assertEqual(parts[0]["holes"], [{"dia_mm": 6.0, "count": 2}])
        self.assertEqual(parts[0]["size_mm"], (60.0, 40.0, 8.0))

    def test_prediction_scales_every_figure(self):
        parts = SF.predicted_parts(self.REPORT, {"changes": [
            {"op": "scale", "part": "all", "factor": 2.0, "why": ""}],
            "advice": []})
        self.assertEqual(parts[0]["size_mm"], (120.0, 80.0, 16.0))
        self.assertEqual(parts[0]["holes"][0], {"dia_mm": 10.0, "count": 1})

    def test_the_page_says_nothing_is_built_yet(self):
        out = tempfile.mkdtemp()
        page = open(SF.review_html(self.REPORT, self.PLAN, out,
                                   question="fit 6mm"),
                    encoding="utf-8").read()
        self.assertIn("Nothing is built yet", page)
        self.assertIn("Hole Ø5 → Ø6", page)
        self.assertIn("60.00 x 40.00 x 8.00", page)
        self.assertIn("class='changed'", page)
        self.assertIn("add draft", page)
        self.assertIn("fit 6mm", page)

    def test_after_the_build_the_page_says_re_measured(self):
        out = tempfile.mkdtemp()
        after = {"parts": [{"name": "p", "size_mm": (60.0, 40.0, 8.0),
                            "thickness_mm": 5.9, "volume_cm3": 37.5,
                            "holes": [{"dia_mm": 6.0, "count": 2}]}]}
        page = open(SF.review_html(self.REPORT, self.PLAN, out,
                                   after=after), encoding="utf-8").read()
        self.assertIn("BUILT", page)
        self.assertIn("re-measured", page)
        self.assertNotIn("Nothing is built yet", page)

    def test_after_the_build_both_drawings_are_on_the_page(self):
        out = tempfile.mkdtemp()
        names = SF.names(self.REPORT)
        for name in (names["png"], names["png_after"]):
            open(os.path.join(out, name), "wb").write(b"png")
        after = {"parts": [{"name": "p", "size_mm": (60.0, 40.0, 8.0),
                            "thickness_mm": 5.9, "volume_cm3": 37.5,
                            "holes": [{"dia_mm": 6.0, "count": 2}]}]}
        page = open(SF.review_html(self.REPORT, self.PLAN, out,
                                   after=after), encoding="utf-8").read()
        # URL-quoted in the src attribute — the name carries spaces.
        self.assertIn("x%20-%20drawing%20sheet%20after%20change.png", page)
        self.assertIn("from the BUILT file", page)

    def test_before_the_build_only_the_received_drawing_shows(self):
        out = tempfile.mkdtemp()
        names = SF.names(self.REPORT)
        for name in (names["png"], names["png_after"]):
            open(os.path.join(out, name), "wb").write(b"png")
        page = open(SF.review_html(self.REPORT, self.PLAN, out),
                    encoding="utf-8").read()
        self.assertNotIn("after%20change.png", page)
        self.assertIn("x%20-%20drawing%20sheet.png", page)


    def test_the_terminal_builds_only_after_the_page_and_the_yes(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = open(os.path.join(root, "prism_terminal", "prism.py"),
                   encoding="utf-8").read()
        body = src[src.index("def cmd_step_ask("):src.index("def cmd_gerber(")]
        self.assertLess(body.index("review_html"),
                        body.index("Reviewed the page — build"))
        self.assertLess(body.index("Reviewed the page — build"),
                        body.index("apply_plan"))


@unittest.skipUnless(HAVE and os.path.exists(REAL),
                     "cadquery missing, or " + (sample_jobs.missing(
                         "step_file_demo", "Assem1.STEP") or ""))
class ChangesOnTheCustomersEnclosure(unittest.TestCase):
    """Witnessed on the real assembly: one hole grows, names and every
    other figure hold still."""

    def test_only_the_named_hole_on_the_named_part_changes(self):
        out = os.path.join(tempfile.mkdtemp(), "m.step")
        SF.apply_plan(REAL, {"changes": [
            {"op": "enlarge_hole", "part": "top", "dia_mm": 6.2,
             "new_dia_mm": 8.0, "why": ""}], "advice": []}, out)
        by = {p["name"]: p for p in SF.analyse(out, "metal")["parts"]}
        self.assertEqual(set(by), {"top", "bottom", "side"})
        top = {h["dia_mm"] for h in by["top"]["holes"]}
        self.assertIn(8.0, top)
        self.assertNotIn(6.2, top)
        self.assertEqual(by["top"]["size_mm"], (101.0, 93.0, 71.0))
        self.assertEqual(by["side"]["size_mm"], (92.0, 68.5, 6.0))
        self.assertIn(5.2, {h["dia_mm"] for h in by["bottom"]["holes"]})


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

    def test_step_auto_is_dispatched_before_step(self):
        """startswith("/step") would swallow "/step-auto" — the auto branch
        must be checked first or the command silently runs plain /step."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = open(os.path.join(root, "prism_terminal", "prism.py"),
                   encoding="utf-8").read()
        self.assertIn("def cmd_step_auto(", src)
        self.assertLess(src.index('line.startswith("/step-auto")'),
                        src.index('line.startswith("/step") or'))

    def test_step_auto_never_uploads_the_model(self):
        """The only attachment /step-auto builds is Prism's OWN render; the
        customer's STEP file must never be in the file list."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = open(os.path.join(root, "prism_terminal", "prism.py"),
                   encoding="utf-8").read()
        body = src[src.index("def cmd_step_auto("):
                   src.index("def cmd_step_ask(")]
        self.assertIn('F.attach(drawn["png"])', body)
        self.assertNotIn("F.attach(target", body)
        self.assertIn("STEP file stays here", body)

    def test_step_ask_is_dispatched_and_never_uploads_the_model(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = open(os.path.join(root, "prism_terminal", "prism.py"),
                   encoding="utf-8").read()
        self.assertLess(src.index('line.startswith("/step-ask")'),
                        src.index('line.startswith("/step") or'))
        body = src[src.index("def cmd_step_ask("):
                   src.index("def cmd_gerber(")]
        self.assertNotIn("F.attach(target", body)
        self.assertIn('F.attach(drawn["png"])', body)
        self.assertIn("groq_chat", body)
        self.assertIn('out["modified"]', body)


class EveryFileCarriesTheModelsName(unittest.TestCase):
    """An estimator keeps ten jobs' sheets in one folder, and ten files all
    called dimensions.xlsx are ten files nobody can tell apart. Every
    deliverable now starts with the customer's own file name, and where the
    folders go is the person's choice (the GUI asks; the terminal has
    /step-folder). Pure functions — no cadquery needed."""

    def test_the_stem_is_the_customers_own_name(self):
        self.assertEqual(SF.stem_of("~/Downloads/Assem1.STEP"), "Assem1")
        self.assertEqual(SF.stem_of("housing v2.stp"), "housing v2")

    def test_the_stem_is_safe_on_windows_and_never_empty(self):
        self.assertEqual(SF.stem_of('bad:name?<x>.stp'), "badnamex")
        self.assertEqual(SF.stem_of(""), "model")
        self.assertEqual(SF.stem_of("?.stp"), "model")   # nothing legal left
        self.assertLessEqual(len(SF.stem_of("x" * 200 + ".step")), 60)

    def test_every_deliverable_starts_with_the_stem(self):
        out = SF.names("Assem1")
        for key, name in out.items():
            self.assertTrue(name.startswith("Assem1 - "), (key, name))
        self.assertEqual(out["xlsx"], "Assem1 - dimensions.xlsx")
        self.assertEqual(out["modified"], "Assem1 - modified.step")
        self.assertEqual(SF.view_name("Assem1", "top", 1),
                         "Assem1 - view top.svg")
        self.assertEqual(SF.ai_sheet_name("Assem1", 1, ".png"),
                         "Assem1 - AI drawing sheet 1.png")

    def test_names_read_the_stem_off_a_report(self):
        report = {"file": "Assem1.STEP", "stem": "Assem1"}
        self.assertEqual(SF.names(report)["png"], "Assem1 - drawing sheet.png")
        # An older report without a stem still names correctly.
        self.assertEqual(SF.names({"file": "x.step"})["review"],
                         "x - change review.html")

    def test_the_folder_is_named_after_the_model_under_the_chosen_root(self):
        root = tempfile.mkdtemp()
        got = SF.output_dir("/anywhere/Assem1.STEP", root)
        self.assertEqual(got, os.path.join(root, "Assem1"))
        self.assertFalse(os.path.exists(got))    # writers create it

    def test_a_second_run_never_overwrites_the_first(self):
        root = tempfile.mkdtemp()
        first = SF.output_dir("/anywhere/Assem1.STEP", root)
        os.makedirs(first)
        self.assertEqual(SF.output_dir("/anywhere/Assem1.STEP", root), first,
                         "an empty folder is reused, not numbered")
        open(os.path.join(first, "Assem1 - dimensions.xlsx"), "w").close()
        second = SF.output_dir("/anywhere/Assem1.STEP", root)
        self.assertEqual(second, os.path.join(root, "Assem1 (2)"))
        os.makedirs(second)
        open(os.path.join(second, "f"), "w").close()
        self.assertEqual(SF.output_dir("/anywhere/Assem1.STEP", root),
                         os.path.join(root, "Assem1 (3)"))

    def test_no_root_means_the_desktop_folder(self):
        got = SF.output_dir("/anywhere/Assem1.STEP", "")
        self.assertEqual(os.path.dirname(got), SF.DEFAULT_OUT_ROOT)
        self.assertTrue(SF.DEFAULT_OUT_ROOT.endswith("Prism Step"))

    def test_the_review_page_names_the_modified_file(self):
        report = dict(TheReviewPageComesBeforeTheBuild.REPORT, stem="x")
        out = tempfile.mkdtemp()
        path = SF.review_html(report, TheReviewPageComesBeforeTheBuild.PLAN,
                              out, question="q")
        self.assertEqual(os.path.basename(path), "x - change review.html")
        self.assertIn("x - modified.step", open(path, encoding="utf-8").read())

    def test_the_terminal_uses_the_shared_names_and_the_chosen_root(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = open(os.path.join(root, "prism_terminal", "prism.py"),
                   encoding="utf-8").read()
        measured = src[src.index("def _step_measured("):src.index("def cmd_step(")]
        self.assertIn('SF.output_dir(target, cfg.get("step_out_dir"', measured)
        self.assertIn('SF.names(report)["xlsx"]', measured)
        self.assertNotIn('"dimensions.xlsx"', src)
        self.assertNotIn('"drawing_after.png"', src)
        self.assertNotIn('"modified.step"', src)
        # /step-folder must be dispatched before the /step prefix swallows it.
        self.assertIn("def cmd_step_folder(", src)
        self.assertLess(src.index('line.startswith("/step-folder")'),
                        src.index('line.startswith("/step") or'))

    def test_the_config_knows_the_key(self):
        from core import config as C
        self.assertIn("step_out_dir", C.DEFAULT)
        self.assertEqual(C.DEFAULT["step_out_dir"], "")


@unittest.skipUnless(HAVE, "cadquery not installed")
class TheSheetIsDrawnByPrismNotAnAI(unittest.TestCase):
    """The dimensioned drawing sheet — three orthographic views per part
    with the sizes on dimension lines, a hole table, notes and a title
    block — comes out of the geometry itself, in a second, with no image
    model in the loop. Checked on a box whose every figure is known."""

    @classmethod
    def setUpClass(cls):
        cls.path = os.path.join(tempfile.mkdtemp(), "Bracket A.step")
        _box_with_hole(cls.path)
        cls.report = SF.analyse(cls.path, mode="metal")
        cls.shape = cls.report["_shapes"][0][1]
        cls.svg = SF.sheet_svg(cls.report)

    def test_the_three_views_project_the_right_extents(self):
        """Front sees X by Z, top sees X by Y, side sees Y by Z — the box is
        60 x 40 x 8, so the projections must measure exactly that."""
        want = {"FRONT VIEW": (60, 8), "TOP VIEW": (60, 40),
                "SIDE VIEW": (40, 8)}
        for title, n, xdir, _axes in SF._VIEWS:
            proj = SF._project(self.shape, n, xdir)
            self.assertIsNotNone(proj, title)
            xmin, xmax, ymin, ymax = proj["bb"]
            self.assertAlmostEqual(xmax - xmin, want[title][0], places=2, msg=title)
            self.assertAlmostEqual(ymax - ymin, want[title][1], places=2, msg=title)
            self.assertTrue(proj["visible"], title)

    def test_the_hole_shows_up_as_hidden_lines_in_the_side_view(self):
        """Looking from the side, a through hole is inside the material —
        hidden-line removal must draw it dashed, not drop it."""
        proj = SF._project(self.shape, (1, 0, 0), (0, 1, 0))
        self.assertTrue(proj["hidden"])

    def test_every_view_is_titled_and_dimensioned_in_mm(self):
        for title in ("FRONT VIEW", "TOP VIEW", "SIDE VIEW"):
            self.assertIn(title, self.svg)
        for figure in ("60.00", "40.00", "8.00"):
            self.assertIn(f">{figure}<", self.svg)
        self.assertIn("millimetres (mm)", self.svg)

    def test_the_hole_table_notes_and_title_block_are_there(self):
        self.assertIn("HOLES (", self.svg)
        self.assertIn("Ø5 x 1", self.svg)
        self.assertIn("NOTES:", self.svg)
        self.assertIn("JOB NAME:", self.svg)
        self.assertIn("Bracket A.step", self.svg)
        self.assertIn("DRAWN BY:", self.svg)
        self.assertIn("Measured offline by Prism", self.svg)
        self.assertIn("CRC SHEET", self.svg)

    def test_every_figure_on_the_sheet_is_two_decimals(self):
        for number in re.findall(r"\d+\.(\d+)<", self.svg):
            self.assertLessEqual(len(number), 2)

    def test_the_sheet_lands_under_the_models_name(self):
        out = tempfile.mkdtemp()
        drawn = SF.render_sheet(self.report, out)
        self.assertEqual(os.path.basename(drawn["svg"]),
                         "Bracket A - drawing sheet.svg")
        self.assertEqual(os.path.basename(drawn["html"]),
                         "Bracket A - drawing sheet.html")
        html = open(drawn["html"], encoding="utf-8").read()
        self.assertIn("<svg", html)
        self.assertIn("60.00 x 40.00 x 8.00", html)

    def test_a_part_with_no_geometry_still_gets_a_line(self):
        report = dict(self.report, _shapes=[])
        svg = SF.sheet_svg(report)
        self.assertIn("no geometry to draw", svg)
        self.assertIn("JOB NAME:", svg)

    def test_a_narrow_dimension_puts_its_figure_outside_the_arrows(self):
        sh = SF._Sheet()
        sh.dim_h(100, 110, 50, 6.0)          # 10px wide: the figure won't fit
        narrow = "".join(sh.items)
        self.assertIn(">6.00<", narrow)
        self.assertIn('x="132.0"', narrow)   # beside, not between
        sh = SF._Sheet()
        sh.dim_h(100, 300, 50, 60.0)         # 200px: the figure sits above
        self.assertIn('x="200.0"', "".join(sh.items))


class TheImageStageGetsItsBudget(unittest.TestCase):
    """The AI-drawn sheet was coming back as a blurred preview: a generic
    visual turn waits 60s and gives up after 12s if no picture has shown,
    while ChatGPT's image model takes minutes and previews progressively.
    Both surfaces now tell the engine a picture IS the deliverable."""

    def _src(self, *parts):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return open(os.path.join(root, *parts), encoding="utf-8").read()

    def test_the_terminal_promises_a_picture(self):
        src = self._src("prism_terminal", "prism.py")
        body = src[src.index("def cmd_step_auto("):src.index("def cmd_step_ask(")]
        self.assertIn('image_stages={"visual"}', body)

    def test_the_terminal_draws_with_chatgpt_only_and_never_falls_over(self):
        src = self._src("prism_terminal", "prism.py")
        body = src[src.index("def cmd_step_auto("):src.index("def cmd_step_ask(")]
        self.assertIn('artist = "ChatGPT"', body)
        self.assertIn("failover=False", body)
        self.assertNotIn('agents.get("visual")', body)

    def test_the_engine_gives_a_promised_stage_minutes_not_seconds(self):
        src = self._src("prism_terminal", "core", "automation.py")
        self.assertIn("image_stages=None", src)
        block = src[src.index("elif stage in promised:"):]
        block = block[:block.index("else:")]
        cap = int(re.search(r"want, cap, grace = 1, (\d+), None", block).group(1))
        self.assertGreaterEqual(cap, 300)

    def test_a_preview_that_changes_is_not_finished(self):
        """The wait watches the images' sources and sizes, and the page's
        own 'creating image' text — not just how many images there are."""
        src = self._src("prism_terminal", "core", "automation.py")
        body = src[src.index("def _wait_for_images("):src.index("def _wait_for_files(")]
        self.assertIn("sig != last_sig", body)
        self.assertIn("creating image", body)
        self.assertIn("not busy", body)


if __name__ == "__main__":
    unittest.main()
