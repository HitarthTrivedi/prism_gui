from __future__ import annotations

import os
import sys
import tempfile
import unittest

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                "prism_terminal"))
from core import assets
from core import reel_web


class ContactSheetGuardTests(unittest.TestCase):
    def test_panel_board_is_flagged_and_not_inlined(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "board.png")
            im = Image.new("RGB", (240, 240), "#111")
            draw = ImageDraw.Draw(im)
            draw.rectangle((0, 0, 115, 115), fill="#222")
            draw.rectangle((125, 0, 239, 115), fill="#333")
            draw.rectangle((0, 125, 115, 239), fill="#444")
            draw.rectangle((125, 125, 239, 239), fill="#555")
            draw.rectangle((117, 0, 122, 239), fill="white")
            draw.rectangle((0, 117, 239, 122), fill="white")
            im.save(path)
            self.assertTrue(assets.looks_like_contact_sheet(path))
            self.assertEqual(reel_web._asset_uris({"art1": {
                "path": path, "composite": True}}), {})

            # Historical auto-crops must not be assigned by scene number.
            resolved = reel_web._asset_uris({"art1": {
                "path": path, "composite": True, "panels": [path]}}, 2)
            self.assertEqual(resolved, {})
            legacy = {"art1": {"path": path, "kind": "art"}}
            self.assertEqual(reel_web._asset_uris(legacy, 2), {})
            self.assertEqual(reel_web.missing_assets({"_assets": legacy,
                "scenes": [{"html": "<img src='asset:art1'>"}]}), ["art1"])

    def test_reference_boards_are_excluded_from_the_required_asset_plan(self):
        listing = ("  asset:art1 — REJECTED CONTACT SHEET / REFERENCE-ONLY\n"
                   "  asset:art2 — 800x1200 OPAQUE")
        self.assertEqual(reel_web.planned_assets({"assets": ["art1", "art2"]}, listing), ["art2"])

    def test_a_missing_file_is_not_mistaken_for_an_available_asset(self):
        project = {"_assets": {"art1": {"path": "/does-not-exist/prism-art.png"}},
                   "scenes": [{"html": "<img src='asset:art1'>"}]}
        self.assertEqual(reel_web.missing_assets(project), ["art1"])

    def test_visual_review_flags_are_persisted_and_enforced(self):
        import json
        design, _ = reel_web.parse_design(json.dumps({"design": {"css": ""},
            "asset_flags": [{"asset": "art1", "status": "unusable", "reason": "wrong product"}],
            "storyboard": [{"job": "hero"}]}))
        self.assertEqual(design["asset_flags"][0]["asset"], "art1")
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "photo.png")
            Image.new("RGB", (90, 150), "#a03232").save(path)
            project = {"design": design, "_assets": {"art1": {"path": path}},
                       "scenes": [{"seconds": 3, "html": "<img src='asset:art1'>"}]}
            self.assertEqual(reel_web.missing_assets(project), ["art1"])
            self.assertNotIn("data:image", reel_web.build_html(project))
            design["asset_flags"][0]["status"] = "limited"
            self.assertEqual(reel_web.missing_assets(project), [])

    def test_non_asset_structural_faults_are_reported(self):
        faults = reel_web.structural_faults({
            "scenes": [
                {"studio_id": "same", "seconds": 0.5, "html": "<div/>"},
                {"studio_id": "same", "seconds": 4, "html": "<div/>"},
            ]
        })
        self.assertTrue(any("duration" in f for f in faults))
        self.assertTrue(any("reuses studio id" in f for f in faults))


if __name__ == "__main__":
    unittest.main()
