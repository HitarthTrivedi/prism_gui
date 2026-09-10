"""Attached Motion artwork must arrive at the renderer as portable data."""
from __future__ import annotations

import base64
import os
import sys
import tempfile
import unittest

GUI = os.path.dirname(os.path.dirname(__file__))
ENGINE = os.path.join(GUI, "prism_terminal")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from core.motion.render import _DISABLED_PENDING_ASSET_FIX
from core.motion.resolver import resolve_motion_spec


class MotionAssetResolutionTests(unittest.TestCase):
    def test_attached_image_becomes_data_uri_before_runtime(self):
        # A one-pixel PNG: enough to prove the old broken file-path route is
        # gone without needing Chromium/FFmpeg in this unit test.
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/"
            "V4w4WQAAAABJRU5ErkJggg==")
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(png)
            path = f.name
        try:
            spec = {"project": {"duration": 1, "fps": 10},
                    "_assets": {"logo": {"path": path}},
                    "scenes": [{"id": "one", "duration": 1,
                                "nodes": [{"id": "logo", "type": "image",
                                           "src": "asset:logo", "position": [0, 0],
                                           "width": 10, "height": 10}]}]}
            resolved = resolve_motion_spec(spec)
            src = resolved["scenes"][0]["nodes"][0]["src"]
            self.assertTrue(src.startswith("data:image/png;base64,"))
            self.assertNotIn(path, src)
        finally:
            os.unlink(path)

    def test_motion_is_enabled_after_asset_resolution_fix(self):
        self.assertFalse(_DISABLED_PENDING_ASSET_FIX)


def _render_lane() -> bool:
    if os.environ.get("PRISM_RUN_RENDER_TESTS") != "1":
        return False
    import importlib
    # core.motion re-exports render() as a NAME, which shadows the module
    # for `import core.motion.render as …`; go through importlib instead.
    return importlib.import_module("core.motion.render").is_available()[0]


@unittest.skipUnless(_render_lane(), "render lane not enabled")
class AttachedImageReachesTheFilm(unittest.TestCase):
    """The check the old kill-switch comment demanded before Motion came back:
    an attached picture must be IN the rendered frames, not a broken-image
    icon. A solid red square placed dead centre on a black frame; the pixel
    at the centre of the exported MP4 must be red."""

    def test_the_attached_png_is_painted_where_the_spec_put_it(self):
        import subprocess
        from PIL import Image
        from core import ffmpeg
        import importlib
        render_module = importlib.import_module("core.motion.render")
        with tempfile.TemporaryDirectory() as folder:
            logo = os.path.join(folder, "logo.png")
            Image.new("RGB", (64, 64), (255, 0, 0)).save(logo)
            spec = {"project": {"duration": 1, "fps": 10, "width": 640, "height": 640,
                                "background": "#000000"},
                    "_assets": {"logo": {"path": logo}},
                    "scenes": [{"id": "one", "duration": 1, "nodes": [
                        {"id": "logo", "type": "image", "src": "asset:logo",
                         "position": [320, 320], "width": 200, "height": 200}]}]}
            mp4 = os.path.join(folder, "out.mp4")
            render_module.render(spec, mp4)
            frame = os.path.join(folder, "frame.png")
            subprocess.run([ffmpeg.locate(), "-y", "-loglevel", "error", "-ss", "0.5",
                            "-i", mp4, "-frames:v", "1", frame], check=True)
            img = Image.open(frame).convert("RGB")
            r, g, b = img.getpixel((320, 320))
            self.assertGreater(r, 200, (r, g, b))
            self.assertLess(g + b, 80, (r, g, b))
            # And the corner is still the background, so it is not a red
            # frame for some other reason.
            r2, g2, b2 = img.getpixel((10, 10))
            self.assertLess(r2 + g2 + b2, 60, (r2, g2, b2))
