"""Contracts for Studio V2 identity, controls, and golden-frame parity."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

GUI = os.path.dirname(os.path.dirname(__file__))
ENGINE = os.path.join(GUI, "prism_terminal")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from core import reel_edit as edit
from core import reel_web as web


def _render_tests_enabled() -> bool:
    """Keep normal unit runs browser-free; CI/render lanes opt in explicitly."""
    return os.environ.get("PRISM_RUN_RENDER_TESTS") == "1" and web.available()[0]


def spec():
    return {"fps": 10, "design": {"css": ""}, "scenes": [{
        "type": "hook", "seconds": 1.5,
        "css": "#s0{background:#102034}.safe{position:absolute;left:120px;top:400px;color:#f8d56b;font:700 92px Arial}",
        "html": "<div class='safe'><h1>Golden frame</h1></div>"}]}


class StableElementIdentity(unittest.TestCase):
    def test_migration_persists_ids_and_new_edits_target_them(self):
        project = spec()
        edit.ensure_stable_ids(project)
        html = project["scenes"][0]["html"]
        self.assertIn('data-prism-id="el-1-1"', html)
        cleaned = edit.clean_edits([{"scene": 0, "element_id": "el-1-1",
                                     "dx": 24, "dy": -8, "scale": 1}])
        self.assertEqual(cleaned[0]["element_id"], "el-1-1")
        # A sibling added in front of the original cannot change this target.
        project["scenes"][0]["html"] = "<i data-prism-id='new'>x</i>" + html
        rendered = edit.apply_edits(web.build_html(project), cleaned)
        self.assertIn('data-prism-id="el-1-1"', rendered)

    def test_v2_modules_are_external_and_editor_has_transport(self):
        # The browser source is served inline (the page must work offline)
        # but comes from the named module files, byte for byte.
        page = edit.editable_html(spec())
        assets = os.path.join(ENGINE, "core", "studio_assets")
        for name in ("apply.js", "editor.js", "editor.css"):
            with open(os.path.join(assets, name), encoding="utf-8") as f:
                self.assertIn(f.read(), page, name)
        for token in ("studio-play", "studio-timeline", "studio-refine",
                      "studio-undo", "studio-snap", "studio-add-text",
                      "studio-add-image", "studio-add-box", "studio-seconds",
                      "studio-font-swap"):
            self.assertIn(token, page)
        self.assertNotIn("__ed-bar", page)      # V1's toolbar is gone for good

    def test_design_brief_requires_visual_reference_review_and_flags(self):
        brief = web.design_instructions(
            request="a product launch",
            assets="  asset:logo — 800x200, transparent PNG")
        self.assertIn("VISUAL REFERENCE REVIEW", brief)
        self.assertIn("asset_flags", brief)
        self.assertIn("Never invent a replacement filename", brief)

    def test_refine_endpoint_carries_sanitised_selection_context(self):
        import time
        import urllib.request
        received = []
        url, stop = edit.serve(spec(), on_refine=lambda change, ctx: received.append((change, ctx)))
        try:
            request = urllib.request.Request(
                url.rstrip("/") + "/refine", method="POST",
                data=json.dumps({"change": "make this headline warmer",
                                 "context": {"scene_index": "0", "scene_id": "scene-1",
                                             "element_id": "el-1-2", "label": "Headline"}}).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=5) as response:
                self.assertTrue(json.loads(response.read())["ok"])
            deadline = time.monotonic() + 2
            while not received and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual(received, [("make this headline warmer", {
                "scene_index": 0, "scene_id": "scene-1", "element_id": "el-1-2",
                "label": "Headline"})])
        finally:
            stop()


@unittest.skipUnless(_render_tests_enabled(), "render lane not enabled")
class StudioWorkspaceBrowser(unittest.TestCase):
    def test_workspace_mounts_transport_timeline_and_inspector(self):
        from playwright.sync_api import sync_playwright
        from core import browser as prism_browser
        url, stop = edit.serve(spec())
        try:
            with sync_playwright() as playwright:
                browser = prism_browser.launch_chromium(playwright)
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                page.goto(url, wait_until="load")
                page.wait_for_selector("#studio-timeline")
                self.assertTrue(page.locator("#studio-play").is_visible())
                self.assertEqual(page.locator("#studio-scenes .scene-card").count(), 1)
                page.click("#s0 h1")
                self.assertIn("Golden frame", page.locator("#studio-inspector").inner_text())
                browser.close()
        finally:
            stop()


@unittest.skipUnless(_render_tests_enabled(), "render lane not enabled")
class GoldenFrameParity(unittest.TestCase):
    def test_preview_and_exported_mp4_are_pixel_close_at_the_same_frame(self):
        from PIL import Image, ImageChops, ImageStat
        project = spec()
        with tempfile.TemporaryDirectory() as folder:
            preview = os.path.join(folder, "preview.png")
            mp4 = os.path.join(folder, "movie.mp4")
            exported = os.path.join(folder, "exported.png")
            web.still(project, 5, preview)
            web.render(project, mp4, check=False)
            subprocess.run([web.ffmpeg_path(), "-y", "-loglevel", "error",
                            "-ss", "0.5", "-i", mp4, "-frames:v", "1", exported],
                           check=True)
            a, b = Image.open(preview).convert("RGB"), Image.open(exported).convert("RGB")
            # H.264 is lossy, so exact bytes would be a false regression. A
            # low average channel error catches wrong seek/edit/scale output.
            mae = sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3
            self.assertLess(mae, 9.0, f"preview/export diverged (MAE {mae:.2f})")


if __name__ == "__main__":
    unittest.main()


class RouterReelsRememberTheirConversation(unittest.TestCase):
    """A reel the AI router filmed must carry `_studio` like a ReelDialog one,
    or Studio's Refine box has nothing to reopen (main_window's early return:
    "This older reel has no saved Studio conversation")."""

    def test_the_nearest_earlier_stage_with_a_url_is_the_conversation(self):
        from core import automation as AU
        stages = [("content", "Claude", ["write"]),
                  ("design", "ChatGPT", ["design"]),
                  ("media", "Prism Studio", ["film"])]
        links = {"content": "https://claude.ai/chat/1",
                 "design": "https://chatgpt.com/c/2"}
        self.assertEqual(AU._studio_conversation(stages, "media", links),
                         {"design_url": "https://chatgpt.com/c/2", "agent": "ChatGPT"})
        # A stage whose link is a local file (an earlier render) is skipped.
        links["design"] = "/runs/reel_1.mp4"
        self.assertEqual(AU._studio_conversation(stages, "media", links),
                         {"design_url": "https://claude.ai/chat/1", "agent": "Claude"})
        self.assertEqual(AU._studio_conversation(stages, "media", {}), {})
        self.assertEqual(AU._studio_conversation(stages, "nope", links), {})

    def test_run_studio_writes_it_into_the_saved_spec(self):
        import json
        from unittest import mock
        from core import automation as AU
        from core import reel_web as web
        text = json.dumps(spec())
        with tempfile.TemporaryDirectory() as runs:
            with mock.patch.object(AU, "_web_token", return_value=web.ASSET_TOKEN), \
                    mock.patch("core.config.RUNS_DIR", runs), \
                    mock.patch.object(web, "render", lambda s, out, **k: open(out, "wb").close()), \
                    mock.patch.object(web, "available", return_value=(True, "")):
                out, _note = AU._run_studio(text, [], {}, None,
                                            studio={"design_url": "https://chatgpt.com/c/2",
                                                    "agent": "ChatGPT"})
            self.assertTrue(out, _note)
            saved = json.load(open(out[:-4] + ".json"))
            self.assertEqual(saved["_studio"], {"design_url": "https://chatgpt.com/c/2",
                                                "agent": "ChatGPT"})
