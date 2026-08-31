"""The browser layout editor for Studio reels.

The report that led here: Studio's reels kept coming out with text placed
or sized wrongly, and prompting the AI to fix it was a coin toss. The fix
is not more prompting — the reel is an HTML page before it is a video, so
the owner opens that page with an edit layer, drags things into place, and
the renderer films the SAME page with the SAME edits applied by the SAME
script. What these tests defend:

  · everything from the browser is sanitised (it is user input);
  · the editor page carries the toolbar, the apply script, and any edits
    already saved, so reopening the editor shows the fixed reel;
  · the render page gets the saved edits injected;
  · the local server round-trips Save and Save & render to callbacks;
  · in a real headless browser: click selects, drag moves, Save delivers
    the edit, and the rendered page actually shows the element moved;
  · the Reel window's button appears only when there is a Studio reel to
    edit, and Save & render restarts the render with the edits kept.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PRISM_LICENSE_OFFLINE_DEV", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

import core_bridge as CB  # noqa: E402

_app = QApplication.instance() or QApplication([])
E = CB.get_reel_edit()


def _spec() -> dict:
    return {"scenes": [
        {"type": "hook", "seconds": 3,
         "html": "<div class='safe'><h1>Hello</h1><p>World</p></div>"},
        {"type": "endcard", "seconds": 3, "html": "<h2>Bye</h2>"},
    ]}


class WhatTheBrowserSendsIsSanitised(unittest.TestCase):

    def test_a_good_edit_survives_with_its_fields_rounded(self):
        out = E.clean_edits([{"scene": 0, "path": [0, 1], "dx": 10.66,
                              "dy": -3.14159, "scale": 1.25,
                              "text": "New line"}])
        self.assertEqual(out, [{"scene": 0, "path": [0, 1], "dx": 10.7,
                                "dy": -3.1, "scale": 1.25,
                                "text": "New line"}])

    def test_junk_is_dropped_not_raised(self):
        for bad in (None, "x", 42, [{"scene": "a"}], [{"scene": 0}],
                    [{"scene": 0, "path": []}],
                    [{"scene": -1, "path": [0]}],
                    [{"scene": 0, "path": [0], "dx": 99999}],
                    [{"scene": 0, "path": [0, -3]}]):
            self.assertEqual(E.clean_edits(bad), [], bad)

    def test_a_do_nothing_edit_is_not_kept(self):
        self.assertEqual(E.clean_edits([{"scene": 0, "path": [0],
                                         "dx": 0, "dy": 0, "scale": 1}]), [])

    def test_scale_and_text_are_bounded(self):
        out = E.clean_edits([{"scene": 0, "path": [0], "scale": 999,
                              "text": "x" * 9000}])
        self.assertEqual(out[0]["scale"], 20.0)
        self.assertEqual(len(out[0]["text"]), 2000)


class TheTwoPages(unittest.TestCase):

    def test_the_editor_page_carries_toolbar_script_and_saved_edits(self):
        spec = _spec()
        spec["edits"] = [{"scene": 0, "path": [0, 0], "dx": 12, "dy": 0,
                          "scale": 1}]
        html = E.editable_html(spec)
        for marker in ("__ed-bar", "__edApply", "__SCENES__",
                       "Save &amp; render", '"dx": 12'):
            self.assertIn(marker, html)

    def test_the_render_page_gets_the_same_apply_script(self):
        html = E.apply_edits("<html><body>reel</body></html>",
                             [{"scene": 0, "path": [0], "dx": 5, "dy": 0,
                               "scale": 1}])
        self.assertIn("__edApply", html)
        self.assertIn('"dx": 5', html)
        self.assertLess(html.index("reel"), html.index("__edApply"))

    def test_no_edits_means_the_page_is_untouched(self):
        page = "<html><body>reel</body></html>"
        self.assertEqual(E.apply_edits(page, []), page)

    def test_the_renderer_applies_saved_edits(self):
        """A source check: reel_web.render must run the edits through the
        shared script, or the editor is a preview of nothing."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "prism_terminal", "core", "reel_web.py"),
                  encoding="utf-8") as f:
            source = f.read()
        self.assertIn("reel_edit.apply_edits", source)
        self.assertIn('spec.get("edits")', source)


class TheLocalServer(unittest.TestCase):

    def setUp(self):
        self.saved, self.rendered = [], []
        self.url, self.stop = E.serve(
            _spec(), on_save=self.saved.append, on_render=self.rendered.append)

    def tearDown(self):
        self.stop()
        self.stop()          # calling twice must be harmless

    def _post(self, path, payload):
        import json
        import urllib.request
        req = urllib.request.Request(
            self.url.rstrip("/") + path, method="POST",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())

    def test_the_page_is_served_on_loopback_only(self):
        import urllib.request
        self.assertTrue(self.url.startswith("http://127.0.0.1:"))
        with urllib.request.urlopen(self.url, timeout=5) as r:
            body = r.read().decode()
        self.assertIn("__ed-bar", body)
        self.assertIn("Hello", body)

    def test_save_and_render_reach_their_callbacks_cleaned(self):
        edit = {"scene": 0, "path": [0, 0], "dx": 30, "dy": -12, "scale": 1.1}
        answer = self._post("/save", {"edits": [edit, {"scene": "junk"}]})
        self.assertTrue(answer["ok"])
        self.assertEqual(len(self.saved), 1)
        self.assertEqual(self.saved[0][0]["dx"], 30)
        self.assertEqual(len(self.saved[0]), 1)         # the junk one dropped
        self._post("/render", {"edits": [edit]})
        self.assertEqual(len(self.rendered), 1)

    def test_anything_else_is_404(self):
        import urllib.error
        import urllib.request
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(self.url + "secret", timeout=5)


def _playwright_ready() -> bool:
    try:
        ok, _why = CB.studio_available()
        return ok
    except Exception:                                   # noqa: BLE001
        return False


@unittest.skipUnless(_playwright_ready(), "playwright/browser not available")
class InARealBrowser(unittest.TestCase):
    """The whole loop, headless: open, click, drag, save — then film the
    page the renderer would film and see the element actually moved."""

    def test_click_drag_save_and_the_render_page_shows_the_move(self):
        from playwright.sync_api import sync_playwright
        saved: list = []
        url, stop = E.serve(_spec(), on_save=saved.append)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(viewport={"width": 900, "height": 700})
                page.goto(url, wait_until="load")
                page.wait_for_selector("#__ed-bar")
                h1 = page.locator("#s0 h1")
                h1.wait_for(state="visible")

                box = h1.bounding_box()
                page.mouse.move(box["x"] + 5, box["y"] + 5)
                page.mouse.down()
                page.mouse.move(box["x"] + 65, box["y"] + 45, steps=4)
                page.mouse.up()
                self.assertIn("__ed-sel", h1.get_attribute("class") or "")

                page.click("#__ed-bigger")
                page.click("#__ed-save")
                deadline = time.monotonic() + 5
                while not saved and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(saved, "Save never reached the callback")
                edits = saved[0]
                target = next(e for e in edits if e["path"] == [0, 0])
                self.assertGreater(target["dx"], 10)
                self.assertGreater(target["scale"], 1.0)

                # Now the page the RENDERER films, with those edits applied.
                spec = _spec()
                spec["edits"] = edits
                from core import reel_web
                html = E.apply_edits(reel_web.build_html(spec),
                                     E.clean_edits(edits))
                page2 = browser.new_page(viewport={"width": 1080,
                                                   "height": 1920})
                page2.set_content(html, wait_until="load")
                page2.evaluate("t => window.__seek(t)", 1500)
                translate = page2.eval_on_selector(
                    "#s0 h1", "el => getComputedStyle(el).translate")
                self.assertNotIn(translate, ("none", ""),
                                 "the render page did not move the element")
                browser.close()
        finally:
            stop()


class TheReelWindow(unittest.TestCase):

    def _dialog(self, runs_dir: str = ""):
        from dialogs.reel_dialog import ReelDialog
        with mock.patch.object(CB.config, "RUNS_DIR",
                               runs_dir or tempfile.mkdtemp()):
            return ReelDialog({"agents": {"content": "ChatGPT"}}, [], None)

    def test_the_last_studio_reel_is_back_on_the_bench(self):
        """Closing the window after a render must not orphan the reel: the
        spec is saved beside the video so Edit the layout still works."""
        import json
        runs = tempfile.mkdtemp()
        spec = _spec()
        with open(os.path.join(runs, "reel_100.json"), "w") as f:
            json.dump(spec, f)
        with open(os.path.join(runs, "reel_099.json"), "w") as f:
            json.dump({"scenes": [{"type": "hook"}]}, f)   # a Quick reel
        d = self._dialog(runs)
        self.assertTrue(d.edit_btn.isEnabled())
        self.assertEqual(len(d.spec["scenes"]), 2)
        self.assertTrue(d.out_path.endswith("reel_100.mp4"))

    def test_a_quick_reel_alone_does_not_light_the_button(self):
        import json
        runs = tempfile.mkdtemp()
        with open(os.path.join(runs, "reel_099.json"), "w") as f:
            json.dump({"scenes": [{"type": "hook", "heading": "x"}]}, f)
        d = self._dialog(runs)
        self.assertFalse(d.edit_btn.isEnabled())

    def test_the_button_waits_for_a_studio_reel(self):
        d = self._dialog()
        self.assertFalse(d.edit_btn.isEnabled())
        d.spec = _spec()
        d._studio_last = False                     # the template renderer
        d._refresh_edit_btn()
        self.assertFalse(d.edit_btn.isEnabled(),
                         "a Quick reel is not a web page — nothing to edit")
        d._studio_last = True
        d._refresh_edit_btn()
        self.assertTrue(d.edit_btn.isEnabled())

    def test_edit_opens_the_served_page_in_the_browser(self):
        d = self._dialog()
        d.spec = _spec()
        d._studio_last = True
        stop = mock.Mock()
        fake = mock.Mock()
        fake.serve.return_value = ("http://127.0.0.1:1/", stop)
        import dialogs.reel_dialog as mod
        with mock.patch.object(CB, "get_reel_edit", return_value=fake), \
                mock.patch.object(mod.QDesktopServices, "openUrl") as opened:
            d._edit_layout()
        fake.serve.assert_called_once()
        opened.assert_called_once()
        self.assertIn("browser", d.status.text())

    def test_save_and_render_keeps_the_edits_and_restarts_the_render(self):
        d = self._dialog()
        d.spec = _spec()
        d._studio_last = True
        d.out_path = os.path.join(tempfile.mkdtemp(), "reel_1.mp4")
        stopped = []
        d._edit_stop = lambda: stopped.append(True)
        edits = [{"scene": 0, "path": [0, 0], "dx": 30, "dy": 0, "scale": 1}]
        with mock.patch.object(d, "_start_render") as render:
            d._on_edits_rendered(edits)
        self.assertEqual(d.spec["edits"], edits)
        self.assertTrue(stopped, "the editor server must be stopped")
        render.assert_called_once_with(d.spec, studio=True)
        import json
        with open(d.out_path[:-4] + ".json", encoding="utf-8") as f:
            self.assertEqual(json.load(f)["edits"], edits)

    def test_a_plain_save_keeps_the_edits_and_says_so(self):
        d = self._dialog()
        d.spec = _spec()
        d.out_path = os.path.join(tempfile.mkdtemp(), "reel_2.mp4")
        d._on_edits_saved([{"scene": 0, "path": [0], "dx": 5, "dy": 0,
                            "scale": 1}])
        self.assertEqual(len(d.spec["edits"]), 1)
        self.assertIn("Save & render", d.status.text())


if __name__ == "__main__":
    unittest.main()
