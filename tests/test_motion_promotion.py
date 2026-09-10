"""Phase 5 of the inspo benchmark: the promotion gate.

  · the checklist is the roadmap's acceptance list, word for word;
  · the static proofs hold: core/motion never names git and imports no
    network or licence layer;
  · a spec that breaks a criterion is reported as failed with evidence,
    and the editable project is written before anything can fail;
  · render lane: the fixture is promoted on this platform, and the same
    brand goes through the lab, the runtime and the Studio page.
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

GUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(GUI, "prism_terminal")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from core.motion import promotion  # noqa: E402
from core.motion.fixtures import materials_fixture  # noqa: E402

ROADMAP = os.path.join(GUI, "docs", "INSPO_BENCHMARK_ROADMAP.md")


def _render_lane() -> bool:
    if not os.environ.get("PRISM_RUN_RENDER_TESTS"):
        return False
    return importlib.import_module("core.motion.render").is_available()[0]


class TheChecklist(unittest.TestCase):
    def test_it_is_the_roadmaps_acceptance_list(self):
        with open(ROADMAP, encoding="utf-8") as fh:
            doc = " ".join(fh.read().split())
        for key, group, text in promotion.CRITERIA:
            self.assertIn(text.replace("The file probe", "`ffprobe`"), doc, key)
        self.assertEqual([g for _, g, _ in promotion.CRITERIA].count("visual"), 6)
        self.assertEqual([g for _, g, _ in promotion.CRITERIA].count("motion"), 4)
        self.assertEqual([g for _, g, _ in promotion.CRITERIA].count("technical"), 5)

    def test_the_static_proofs_hold(self):
        self.assertEqual(promotion.static_faults(), {"no_git": [], "local_only": []})

    def test_a_broken_spec_fails_with_evidence_and_leaves_the_project(self):
        spec = materials_fixture(360, 640, fps=12)
        spec["scenes"][1]["nodes"][1]["children"][0]["position"] = [3000, 3000]   # unbridgeable
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(promotion._review, "review_sheet",
                                  side_effect=RuntimeError("no browser here")):
            report = promotion.evaluate(spec, folder, preview_check=False)
            self.assertTrue(os.path.isfile(os.path.join(folder, "promotion_spec.json")))
            self.assertTrue(os.path.isfile(os.path.join(folder, "promotion.md")))
            with open(os.path.join(folder, "promotion.json"), encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["promoted"], False)
        self.assertFalse(report["promoted"])
        rows = {r["key"]: r for r in report["criteria"]}
        self.assertEqual(rows["handoff_bridge"]["status"], "fail")
        self.assertIn("cannot be handed", rows["handoff_bridge"]["evidence"])
        self.assertEqual(rows["editable_on_failure"]["status"], "pass")
        self.assertEqual(rows["no_git"]["status"], "pass")
        self.assertEqual(rows["local_only"]["status"], "pass")
        self.assertEqual(rows["hierarchy"]["status"], "manual")
        self.assertIn("FAIL", promotion.markdown(report))
        self.assertIn(report["platform"]["os"], promotion.markdown(report))

    def test_an_opening_subject_that_never_returns_is_named(self):
        spec = materials_fixture(360, 640, fps=12)
        spec["scenes"][2]["nodes"][1]["children"][0]["continuity_key"] = "other"
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(promotion._review, "review_sheet",
                                  side_effect=RuntimeError("skip")):
            report = promotion.evaluate(spec, folder, preview_check=False)
        rows = {r["key"]: r for r in report["criteria"]}
        self.assertEqual(rows["resolves"]["status"], "fail")
        self.assertIn("does not return", rows["resolves"]["evidence"])


@unittest.skipUnless(_render_lane(), "render lane not enabled")
class OnThisPlatform(unittest.TestCase):
    def test_the_fixture_is_promoted_and_the_same_prompt_runs_everywhere(self):
        with tempfile.TemporaryDirectory() as folder:
            # a small, fast fixture stands in for the 1080x1920/60 one the CLI runs
            small = materials_fixture(360, 640, fps=12, brand="Aperture", tagline="See the signal.")
            report = promotion.evaluate(small, os.path.join(folder, "motion"))
            self.assertTrue(report["promoted"], [r for r in report["criteria"] if r["status"] == "fail"])
            self.assertEqual(sorted(report["manual"]), ["hierarchy", "review_states"])
            from core.motion import studio
            page = studio.editable_html(small)
            self.assertIn("Aperture", page)
            from core.cinematic import CinematicTheme, build_demo_spec, render_previews
            stills = render_previews(build_demo_spec(
                CinematicTheme(brand="Aperture", tagline="See the signal."), fps=24),
                os.path.join(folder, "lab"))
            self.assertTrue(stills)


if __name__ == "__main__":
    unittest.main()
