"""The off-frame check has to know when overflow is actually invisible.

The owner's run of 15 Sep 2026: a routed Studio reel wrote and filmed all
four scenes clean, then failed export — "an image (img, 719x1937) runs off
the frame" — with no MP4 written. The saved spec (~/.prism/runs/reel_*.json,
loaded straight into a real browser to settle this) showed the truth: scene
1's photo sits in `.s1-photo{...;overflow:hidden}`, at exactly
(367, 0, 713, 1920) — dead inside the 1080x1920 frame — with a slow
scale-in entrance animation (`s1SlowScale`, 1.06 -> 1.0) on the `<img>`
inside it. Measured live at the check's own 0.75-of-scene point, the
animation had not quite settled: `transform: matrix(1.00868, …)`, still
0.868% oversized, giving the IMG element's own unclipped box as
(364, -8, 719, 1937) — a few pixels past every edge. Nothing the viewer
ever actually sees leaves the frame; the wrapper clips it. The check
measured the wrong element.

`window.__check()` now walks from the image up to its scene root and, if
any ancestor clips overflow, judges THAT ancestor's box instead of the
image's own — the box that actually decides what paints. Pinned here,
against a real headless browser (CSS transforms and computed overflow
can't be faked convincingly, and this check exists specifically because
Python-side geometry math was wrong once already for this same class of
bug): a clipped, animating, or plain oversized image inside a properly
positioned wrapper is left alone; an image with no such wrapper, or one
whose *wrapper* is itself off frame, is still caught.

Gated like Studio's other browser tests (`test_studio_v2.py`): set
PRISM_RUN_RENDER_TESTS=1 to run it; normal unit runs stay browser-free.
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "prism_terminal")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core import reel_web as RW      # noqa: E402


def _render_tests_enabled() -> bool:
    return os.environ.get("PRISM_RUN_RENDER_TESTS") == "1" and RW.available()[0]


def _faults_for(scene_css: str, scene_html: str, design_css: str = "",
                at: float = 0.75) -> list[str]:
    """One scene, laid out for real and checked at `at` -- the same 0.75
    fraction build_spec()'s per-scene inspect() and render()'s own
    preflight both use, by default."""
    with _page_on(scene_css, scene_html, design_css, at) as page:
        return page.evaluate("() => window.__check()") or []


import contextlib      # noqa: E402


@contextlib.contextmanager
def _page_on(scene_css: str, scene_html: str, design_css: str = "",
             at: float = 0.75):
    """The built page, seeked to `at`, for a test that needs to look at
    more than just the fault list (e.g. an element's raw geometry)."""
    from playwright.sync_api import sync_playwright
    from core import browser as prism_browser

    spec = {"design": {"name": "x", "css": design_css},
            "scenes": [{"seconds": 3, "cut": "push", "css": scene_css,
                       "html": scene_html}]}
    fps = 30
    html = RW.build_html(spec, fps)
    plan, _ = RW._plan(spec, fps)
    with sync_playwright() as p:
        browser = prism_browser.launch_chromium(p, args=["--hide-scrollbars"])
        page = browser.new_page(viewport={"width": RW.W, "height": RW.H},
                                device_scale_factor=1)
        try:
            page.set_content(html, wait_until="load")
            RW._seek_page(page, plan[0]["start"] + plan[0]["dur"] * at)
            yield page
        finally:
            browser.close()


# A tiny embedded image -- loads instantly, no network, deterministic.
_TEST_PNG = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACgAAAAoCAIAAAADnC86AAAA"
    "T0lEQVR4nO3NMQHAMBDEsI/RFE5hF1bXHAFnyImA1vc+cwJH1mkswsx2jTV4VWqswatSYw"
    "1elRpr8KrUWINXpcYavCo11uBVqbEGr5rL4x+ozgGQmEjf5AAAAABJRU5ErkJggg==")
_ANY_IMG = f"<img src='{_TEST_PNG}' alt=''>"


@unittest.skipUnless(_render_tests_enabled(), "render lane not enabled")
class AClippedImageIsJudgedByItsWrapper(unittest.TestCase):

    # The exact scene geometry from the failed run (positions, sizes, the
    # entrance animation), with the copy and the picture themselves
    # replaced by placeholders -- the client's own words do not belong in
    # this repository, only the CSS mechanism that broke the check.
    _OWNERS_SCENE_CSS = (
        ".s1-wrap{position:absolute;inset:0;background:var(--bg);}"
        ".s1-photo{position:absolute;top:0;right:0;width:66%;height:100%;"
        "z-index:20;overflow:hidden;}"
        ".s1-photo img{width:100%;height:100%;object-fit:cover;"
        "object-position:60% 38%;"
        "animation:s1SlowScale 4500ms cubic-bezier(.37,0,.63,1) both;}"
        "@keyframes s1SlowScale{from{transform:scale(1.06);}"
        "to{transform:scale(1);}}")
    _OWNERS_SCENE_HTML = (
        "<div class='s1-wrap'><div class='s1-photo'>"
        f"{_ANY_IMG}</div></div>")

    def test_the_owners_reel_no_longer_fails(self):
        faults = _faults_for(self._OWNERS_SCENE_CSS, self._OWNERS_SCENE_HTML)
        self.assertEqual(faults, [])

    def test_the_scene_genuinely_still_overshoots_its_own_box(self):
        """Proves the test above is exercising the real bug, not passing
        because nothing was ever off frame to begin with: the IMAGE
        ELEMENT's own (unclipped) box at the real check point still
        overshoots the frame -- this is a live animation mid-settle, the
        same as the owner's run, and the fix is what keeps it from being
        reported, not the scene happening to be clean."""
        with _page_on(self._OWNERS_SCENE_CSS, self._OWNERS_SCENE_HTML) as page:
            r = page.evaluate(
                "() => document.querySelector('img').getBoundingClientRect()")
        self.assertGreater(r["bottom"], RW.H)
        self.assertLess(r["top"], 0)

    def test_a_settling_scale_animation_inside_a_clipping_wrapper_is_clean(self):
        faults = _faults_for(
            ".wrap{position:absolute;left:200px;top:200px;width:400px;"
            "height:400px;overflow:hidden;}"
            ".wrap img{width:100%;height:100%;object-fit:cover;"
            "animation:zoom 3000ms linear both;}"
            "@keyframes zoom{from{transform:scale(1.06);}to{transform:scale(1);}}",
            f"<div class='wrap'>{_ANY_IMG}</div>")
        self.assertEqual(faults, [])

    def test_a_plain_oversized_child_in_a_clipping_wrapper_is_clean(self):
        """Not just mid-animation -- any child bigger than its clipping
        parent, however it got that way, is masked the same way."""
        faults = _faults_for(
            ".wrap{position:absolute;left:100px;top:100px;width:300px;"
            "height:300px;overflow:hidden;}"
            ".wrap img{width:150%;height:150%;object-fit:cover;}",
            f"<div class='wrap'>{_ANY_IMG}</div>")
        self.assertEqual(faults, [])

    def test_an_image_with_no_wrapper_off_frame_is_still_caught(self):
        faults = _faults_for(
            ".bad{position:absolute;left:900px;top:0;width:400px;height:400px;}",
            f"<img class='bad' src='{_TEST_PNG}' alt=''>")
        self.assertEqual(len(faults), 1)
        self.assertIn("runs off the frame", faults[0])

    def test_a_wrapper_that_is_itself_off_frame_is_still_caught(self):
        """Clipping does not excuse a MISPLACED wrapper -- only an
        oversized child inside a correctly placed one."""
        faults = _faults_for(
            ".wrap{position:absolute;left:900px;top:0;width:400px;"
            "height:400px;overflow:hidden;}"
            ".wrap img{width:100%;height:100%;object-fit:cover;}",
            f"<div class='wrap'>{_ANY_IMG}</div>")
        self.assertEqual(len(faults), 1)
        self.assertIn("runs off the frame", faults[0])

    def test_clip_and_overflow_x_y_variants_all_count_as_clipping(self):
        for rule in ("overflow:hidden", "overflow:clip",
                     "overflow-x:hidden;overflow-y:hidden"):
            with self.subTest(rule=rule):
                faults = _faults_for(
                    f".wrap{{position:absolute;left:200px;top:200px;"
                    f"width:400px;height:400px;{rule};}}"
                    ".wrap img{width:130%;height:130%;object-fit:cover;}",
                    f"<div class='wrap'>{_ANY_IMG}</div>")
                self.assertEqual(faults, [])

    def test_a_visible_scroll_container_does_not_count_as_clipping(self):
        """overflow:auto/scroll/visible do not hide anything by themselves —
        only hidden/clip actually guarantee nothing paints outside the box."""
        for rule in ("overflow:visible", "overflow:auto"):
            with self.subTest(rule=rule):
                faults = _faults_for(
                    f".wrap{{position:absolute;left:900px;top:0;"
                    f"width:400px;height:400px;{rule};}}"
                    ".wrap img{width:100%;height:100%;object-fit:cover;}",
                    f"<div class='wrap'>{_ANY_IMG}</div>")
                self.assertEqual(len(faults), 1)


if __name__ == "__main__":
    unittest.main()
