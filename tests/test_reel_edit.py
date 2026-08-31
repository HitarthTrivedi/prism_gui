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


class TheWorkbenchCard(unittest.TestCase):
    """The place reels are actually made — a task's "Make the video" step.
    The finished card gets Edit the layout beside Play video, but only when
    the video really is a Studio reel (its spec, saved beside it, carries
    HTML scenes)."""

    def _card(self):
        from widgets.output_panel import StageCard
        return StageCard("media", "Prism Studio")

    def _reel_on_disk(self, spec) -> str:
        import json
        d = tempfile.mkdtemp()
        mp4 = os.path.join(d, "reel_123.mp4")
        open(mp4, "wb").write(b"\x00")
        with open(mp4[:-4] + ".json", "w") as f:
            json.dump(spec, f)
        return mp4

    def test_a_studio_reel_lights_the_button(self):
        card = self._card()
        mp4 = self._reel_on_disk(_spec())
        card.set_done(["Made on this machine"], mp4)
        card.set_collapsed(False)      # a finished step folds itself away
        self.assertTrue(card.edit_btn.isVisibleTo(card))
        seen = []
        card.edit_reel.connect(seen.append)
        card.edit_btn.click()
        self.assertEqual(seen, [mp4])

    def test_a_quick_reel_or_no_spec_does_not(self):
        card = self._card()
        mp4 = self._reel_on_disk({"scenes": [{"type": "hook"}]})
        card._set_url(mp4)
        self.assertFalse(card.edit_btn.isVisibleTo(card))
        card._set_url("https://chat.openai.com/c/abc")   # a tab, not a file
        self.assertFalse(card.edit_btn.isVisibleTo(card))

    def test_the_panel_bubbles_it_and_the_window_answers(self):
        from widgets.output_panel import OutputPanel
        src_panel = open(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "widgets", "output_panel.py"), encoding="utf-8").read()
        self.assertIn("card.edit_reel.connect(self.edit_reel.emit)", src_panel)
        src_win = open(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "main_window.py"), encoding="utf-8").read()
        self.assertIn("output_panel.edit_reel.connect(self._edit_reel_layout)",
                      src_win)
        self.assertIn("def _on_reel_edits_rendered", src_win)
        self.assertIn("ReelWorker(ctx[\"spec\"], out, studio=True)", src_win)


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


class TheArtifactsScreen(unittest.TestCase):
    """A reel made by describing a task, not by opening Reel/Studio, still
    lands in Artifacts once it's rendered — and until this, that was a dead
    end: no button anywhere led back to the browser editor for it."""

    def _reel_on_disk(self, folder, spec, name="reel_1"):
        import json
        mp4 = os.path.join(folder, name + ".mp4")
        open(mp4, "wb").write(b"\x00")
        with open(mp4[:-4] + ".json", "w") as f:
            json.dump(spec, f)
        return mp4

    def _edit_button(self, row):
        from PySide6.QtWidgets import QPushButton
        hits = [b for b in row.findChildren(QPushButton)
                if b.toolTip() == "Edit the layout"]
        return hits[0] if hits else None

    def test_a_studio_reel_gets_an_edit_action(self):
        from widgets.artifacts_panel import ArtifactsPanel
        folder = tempfile.mkdtemp()
        mp4 = self._reel_on_disk(folder, _spec())
        with mock.patch.object(CB.config, "ARTIFACTS_DIR", folder):
            panel = ArtifactsPanel({})
            row = panel._row(mp4)
        btn = self._edit_button(row)
        self.assertIsNotNone(btn)
        seen = []
        panel.edit_reel.connect(seen.append)
        btn.click()
        self.assertEqual(seen, [mp4])

    def test_a_quick_reel_or_no_spec_gets_none(self):
        from widgets.artifacts_panel import ArtifactsPanel
        folder = tempfile.mkdtemp()
        quick = self._reel_on_disk(
            folder, {"scenes": [{"type": "hook"}]}, "reel_2")
        bare = os.path.join(folder, "reel_3.mp4")
        open(bare, "wb").write(b"\x00")
        panel = ArtifactsPanel({})
        self.assertIsNone(self._edit_button(panel._row(quick)))
        self.assertIsNone(self._edit_button(panel._row(bare)))

    def test_a_non_video_artifact_gets_none(self):
        from widgets.artifacts_panel import ArtifactsPanel
        folder = tempfile.mkdtemp()
        doc = os.path.join(folder, "quote.pdf")
        open(doc, "wb").write(b"\x00")
        panel = ArtifactsPanel({})
        self.assertIsNone(self._edit_button(panel._row(doc)))

    def test_the_window_answers_it_the_same_way(self):
        src = open(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "main_window.py"), encoding="utf-8").read()
        self.assertIn(
            "self.artifacts_panel.edit_reel.connect(self._edit_reel_layout)",
            src)


class TheHistoryDialog(unittest.TestCase):
    """A reel from days ago, found again through History, is no less
    editable than one still fresh on the workbench."""

    def _dialog(self):
        from dialogs.history_dialog import HistoryDialog
        with mock.patch.object(CB.config, "load", return_value={}):
            return HistoryDialog(None)

    @staticmethod
    def _run_record(path: str, record: dict):
        import json
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f)
        from PySide6.QtWidgets import QListWidgetItem
        from dialogs.history_dialog import _PATH_ROLE
        item = QListWidgetItem()
        item.setData(_PATH_ROLE, path)
        return item

    def test_a_studio_reel_link_lights_the_button(self):
        import json
        d = self._dialog()
        run_dir = tempfile.mkdtemp()
        mp4 = os.path.join(run_dir, "reel_5.mp4")
        open(mp4, "wb").write(b"\x00")
        with open(mp4[:-4] + ".json", "w") as f:
            json.dump(_spec(), f)
        record = {"query": "make a reel", "links": {"content": mp4}}
        item = self._run_record(os.path.join(run_dir, "run_1.json"), record)
        d._show(item)
        self.assertEqual(d._current_reel, mp4)
        self.assertTrue(d.edit_reel_btn.isVisibleTo(d))
        seen = []
        d.edit_reel.connect(seen.append)
        with mock.patch.object(d, "accept") as accept:
            d._edit_current_reel()
        accept.assert_called_once()
        self.assertEqual(seen, [mp4])

    def test_no_reel_leaves_the_button_hidden(self):
        d = self._dialog()
        run_dir = tempfile.mkdtemp()
        record = {"query": "draft an email", "links": {}}
        item = self._run_record(os.path.join(run_dir, "run_2.json"), record)
        d._show(item)
        self.assertEqual(d._current_reel, "")
        self.assertFalse(d.edit_reel_btn.isVisibleTo(d))
        d._edit_current_reel()   # must not raise with nothing selected

    def test_a_quick_reel_link_leaves_the_button_hidden(self):
        import json
        d = self._dialog()
        run_dir = tempfile.mkdtemp()
        mp4 = os.path.join(run_dir, "reel_6.mp4")
        open(mp4, "wb").write(b"\x00")
        with open(mp4[:-4] + ".json", "w") as f:
            json.dump({"scenes": [{"type": "hook"}]}, f)   # a Quick reel
        record = {"query": "make a reel", "links": {"content": mp4}}
        item = self._run_record(os.path.join(run_dir, "run_3.json"), record)
        d._show(item)
        self.assertEqual(d._current_reel, "")
        self.assertFalse(d.edit_reel_btn.isVisibleTo(d))

    def test_switching_runs_clears_a_stale_reel(self):
        """Selecting an email run right after a reel run must drop the old
        mp4 — the button pointed at the previous row's video otherwise."""
        import json
        d = self._dialog()
        run_dir = tempfile.mkdtemp()
        mp4 = os.path.join(run_dir, "reel_7.mp4")
        open(mp4, "wb").write(b"\x00")
        with open(mp4[:-4] + ".json", "w") as f:
            json.dump(_spec(), f)
        reel_item = self._run_record(
            os.path.join(run_dir, "run_4.json"),
            {"query": "make a reel", "links": {"content": mp4}})
        d._show(reel_item)
        self.assertTrue(d.edit_reel_btn.isVisibleTo(d))
        email_item = self._run_record(
            os.path.join(run_dir, "run_5.json"),
            {"query": "draft an email", "links": {}})
        d._show(email_item)
        self.assertEqual(d._current_reel, "")
        self.assertFalse(d.edit_reel_btn.isVisibleTo(d))

    def test_the_window_answers_it_the_same_way(self):
        src = open(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "main_window.py"), encoding="utf-8").read()
        self.assertIn("dialog.edit_reel.connect(self._edit_reel_layout)", src)


class WhatAFrozenBuildSaysWhenPlaywrightIsMissing(unittest.TestCase):
    """A downloaded Windows/macOS installer has no pip on PATH, and even a
    pip that happened to exist wouldn't touch its bundled interpreter — the
    reported bug was exactly this: an end user staring at "pip install
    playwright && playwright install chromium" with no shell to run it in
    and no way to make it true. A dev checkout (paths.is_frozen() False)
    still gets the real instruction, because there it is one."""

    def test_a_frozen_build_gets_the_plain_fact_not_the_command(self):
        with mock.patch.object(CB.paths, "is_frozen", return_value=True):
            said = CB._no_pip_in_a_frozen_build(
                "The web renderer needs Playwright:\n"
                "    pip install playwright && playwright install chromium")
        self.assertNotIn("pip install", said)
        self.assertIn("installer build", said)

    def test_a_dev_checkout_keeps_the_real_instruction(self):
        with mock.patch.object(CB.paths, "is_frozen", return_value=False):
            said = CB._no_pip_in_a_frozen_build(
                "The web renderer needs Playwright:\n"
                "    pip install playwright && playwright install chromium")
        self.assertIn("pip install playwright", said)

    def test_an_unrelated_reason_is_left_alone_even_when_frozen(self):
        """FFmpeg missing, licence expired, whatever else can fail here —
        none of that is the pip message, and none of it should be rewritten
        into something it isn't."""
        with mock.patch.object(CB.paths, "is_frozen", return_value=True):
            said = CB._no_pip_in_a_frozen_build("FFmpeg binary is required.")
        self.assertEqual(said, "FFmpeg binary is required.")

    def test_studio_available_routes_its_failure_through_the_rewrite(self):
        with mock.patch.object(CB.paths, "is_frozen", return_value=True), \
             mock.patch.object(
                 CB.get_studio(), "available",
                 return_value=(False, "The web renderer needs Playwright:\n"
                                      "    pip install playwright && "
                                      "playwright install chromium")):
            ok, why = CB.studio_available()
        self.assertFalse(ok)
        self.assertNotIn("pip install", why)

    def test_motion_available_routes_its_failure_through_the_rewrite_too(self):
        with mock.patch.object(CB.paths, "is_frozen", return_value=True), \
             mock.patch.object(
                 CB.get_motion(), "is_available",
                 return_value=(False, "No headless browser available. "
                                      "Install Playwright: pip install "
                                      "playwright && playwright install "
                                      "chromium")):
            ok, why = CB.motion_available()
        self.assertFalse(ok)
        self.assertNotIn("pip install", why)


class PrismStudioActuallyWorksOnACustomerMachine(unittest.TestCase):
    """The gap this closes: playwright.chromium.launch() resolves the browser
    relative to wherever `playwright.__file__` sits UNLESS told otherwise, and
    its default (PLAYWRIGHT_BROWSERS_PATH unset) is the OS cache dir —
    ~/.cache/ms-playwright or the Windows/macOS equivalent. A developer who
    ran `playwright install chromium` by hand has that folder; a customer who
    downloaded the installer never will, no matter how much Chromium
    packaging/prism.spec bundles INSIDE the app, because bundling it there
    and looking for it in the OS cache dir are two different places. This is
    the fix that makes them the same place — see core_bridge.py's
    PLAYWRIGHT_BROWSERS_PATH=0 line, right next to paths.is_frozen()."""

    def test_the_frozen_branch_carries_the_fix(self):
        src = open(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "core_bridge.py"), encoding="utf-8").read()
        frozen_branch = src[src.index("if paths.is_frozen():"):]
        self.assertIn(
            'os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")',
            frozen_branch[:frozen_branch.index("\n\ndef ")
                          if "\n\ndef " in frozen_branch else 2000])

    def test_a_frozen_build_launches_chromium_with_no_os_cache_at_all(self):
        """Proves the fix with the one thing that actually matters: a real
        browser launch, in a subprocess with no ms-playwright cache
        directory visible to it — the exact shape of a fresh customer
        install, not a developer's machine that happens to have one already.
        A subprocess, not importlib.reload(core_bridge) in-process, because
        reloading it mutates real module/sys.path state that every other
        test in this file shares."""
        import shutil as _shutil
        import subprocess
        import sys as _sys
        try:
            from playwright.sync_api import sync_playwright as _sp  # noqa: F401
        except ImportError:
            self.skipTest("playwright package not installed in this "
                          "environment — pip install -r requirements.txt")
        gui_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        script = f'''
import os, sys
sys.path.insert(0, {gui_dir!r})
from unittest import mock
import paths
import core_bridge as CB
dev_dir = CB._TERMINAL_DIR
if dev_dir not in sys.path:
    sys.path.insert(0, dev_dir)
with mock.patch.object(paths, "is_frozen", return_value=True), \\
     mock.patch.object(paths, "resource", return_value=dev_dir):
    import importlib
    importlib.reload(CB)
    ok, why = CB.studio_available()
if not ok:
    print("NOT_AVAILABLE:" + why)
    sys.exit(0)
from playwright.sync_api import sync_playwright
try:
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page()
        page.set_content("<h1>customer machine smoke test</h1>")
        assert page.inner_text("h1") == "customer machine smoke test"
        b.close()
except Exception as e:                                  # noqa: BLE001
    if "doesn't exist" in str(e) or "Executable doesn't exist" in str(e):
        print("NO_CHROMIUM:" + str(e)[:200])
        sys.exit(0)
    raise
print("LAUNCHED_OK")
'''
        env = dict(os.environ)
        env.pop("PLAYWRIGHT_BROWSERS_PATH", None)
        # A fresh, empty HOME the subprocess can't find a real
        # ~/.cache/ms-playwright under, even on this dev machine.
        fake_home = tempfile.mkdtemp()
        env["HOME"] = fake_home
        env["USERPROFILE"] = fake_home
        result = subprocess.run([_sys.executable, "-c", script],
                                env=env, capture_output=True, text=True,
                                timeout=60)
        _shutil.rmtree(fake_home, ignore_errors=True)
        if "NOT_AVAILABLE:" in result.stdout or "NO_CHROMIUM:" in result.stdout:
            self.skipTest("Chromium isn't installed in this environment "
                          "(PLAYWRIGHT_BROWSERS_PATH=0 playwright install "
                          "chromium) — see requirements.txt's playwright "
                          f"comment. ({result.stdout.strip()})")
        self.assertIn("LAUNCHED_OK", result.stdout,
                     f"stdout: {result.stdout}\nstderr: {result.stderr}")


if __name__ == "__main__":
    unittest.main()
