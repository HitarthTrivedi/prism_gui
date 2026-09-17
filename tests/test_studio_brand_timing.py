"""The client's accent colour has to be known WHILE the design conversation
is writing scenes, not only once the reel is already filmed.

The owner's run of 15 Sep 2026: a routed Studio reel (no research step;
Artwork ran before Design) wrote and filmed all five scenes, then failed
export — "the client's accent colour #4ab50a appears nowhere in the
design". The colour was real, and Round 33's per-scene correction (see
tests/test_scene_by_scene.py) SHOULD have caught it -- except `studio_brand`
was still `{}` for the whole design conversation. It had been seeded once,
early, from the user's own attachment alone, and that attachment yielded
nothing usable. `#4ab50a` was only ever discovered by `_run_studio()`'s OWN
render-time fallback, sampled from `attachments + pipeline_files` -- which,
because the Artwork stage runs before Design, already held the two pictures
Artwork had made. The design conversation was never told, and Round 33's
check ran the whole time against an empty brand.

Pinned here:

  · `_brand_from_images` gathers only image paths, calls `reel.sample_brand`
    with them, and answers {} for nothing/nothing-usable -- the piece both
    call sites now share;
  · the design stage re-samples from attachments + pipeline_files -- the
    SAME set `_run_studio()` already falls back to -- when nothing has
    supplied a brand yet, and does so AFTER the research-read fallback, so
    a client's own published colours still win when both are available;
  · `_run_studio()`'s own fallback uses the same helper, unchanged in
    outcome.

No browser, no PIL rendering: `reel.sample_brand` is mocked, since what is
under test is the WIRING and the ORDER, not the pixel-reading.
"""
from __future__ import annotations

import inspect
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "prism_terminal")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core import automation as AU     # noqa: E402
from core import reel as PILLOW       # noqa: E402


class GatheringTheImages(unittest.TestCase):

    def test_only_image_paths_are_offered_to_the_sampler(self):
        seen = []
        with mock.patch.object(PILLOW, "sample_brand",
                               side_effect=lambda paths: seen.append(list(paths)) or {"accent": "#fff"}):
            got = AU._brand_from_images([
                {"path": "/x/photo.PNG"}, {"path": "/x/notes.pdf"},
                {"path": "/x/logo.jpg"}, {"name": "no path key"}, {},
            ])
        self.assertEqual(seen, [["/x/photo.PNG", "/x/logo.jpg"]])
        self.assertEqual(got, {"accent": "#fff"})

    def test_nothing_to_sample_never_calls_the_sampler(self):
        with mock.patch.object(PILLOW, "sample_brand") as sb:
            self.assertEqual(AU._brand_from_images([]), {})
            self.assertEqual(AU._brand_from_images([{"path": "/x.pdf"}]), {})
            self.assertEqual(AU._brand_from_images(None), {})
        sb.assert_not_called()

    def test_a_sampler_that_finds_nothing_usable_answers_empty(self):
        with mock.patch.object(PILLOW, "sample_brand", return_value={}):
            self.assertEqual(AU._brand_from_images([{"path": "/x.png"}]), {})
        with mock.patch.object(PILLOW, "sample_brand", return_value=None):
            self.assertEqual(AU._brand_from_images([{"path": "/x.png"}]), {})


class TheDesignStageIsToldTheColourItWillActuallyFilmIn(unittest.TestCase):

    def _run_source(self) -> str:
        return inspect.getsource(AU.run)

    def test_the_fallback_samples_attachments_plus_pipeline_files(self):
        src = self._run_source()
        i = src.index("if not studio_brand:\n")
        j = src.index("studio_brand = _brand_from_images(", i)
        self.assertLess(j - i, 1400, "not the design-stage fallback block")
        call = src[j:src.index(")\n", j) + 1]
        self.assertIn("attachments", call)
        self.assertIn("pipeline_files", call)

    def test_research_is_tried_first_and_the_artwork_fallback_comes_after(self):
        """A client's own published colours are read off their real site;
        a sampled photo is a heuristic guess. Research must not be skipped
        just because an earlier picture happens to sample cleanly."""
        src = self._run_source()
        research_at = src.index("if not studio_brand and research_stage:")
        fallback_at = src.index("studio_brand = _brand_from_images(", research_at)
        self.assertLess(research_at, fallback_at)

    def test_the_fallback_only_fires_when_nothing_else_supplied_a_brand(self):
        src = self._run_source()
        research_at = src.index("if not studio_brand and research_stage:")
        i = src.index("studio_brand = _brand_from_images(", research_at)
        guard = src[max(0, i - 1600):i]
        self.assertIn("if not studio_brand:", guard)

    def test_build_spec_is_given_studio_brand(self):
        """Round 33's per-scene correction is worthless if the colour it is
        checking against is still empty by the time scenes are written."""
        src = self._run_source()
        i = src.index("spec = _web.build_spec(")
        self.assertIn("brand=studio_brand", src[i:i + 400])


class RunStudioSharesTheSameSampler(unittest.TestCase):

    def test_the_render_time_fallback_uses_the_shared_helper(self):
        src = inspect.getsource(AU._run_studio)
        self.assertIn("_brand_from_images(attachments or [])", src)
        self.assertNotIn("_pillow.sample_brand(imgs)", src,
                         "the duplicated inline sampler should be gone")


if __name__ == "__main__":
    unittest.main()
