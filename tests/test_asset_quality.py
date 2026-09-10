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

            panels = assets.split_contact_sheet(path, folder)
            self.assertEqual(len(panels), 7)
            # Scene-aware resolution returns one tile, never the board.
            resolved = reel_web._asset_uris({"art1": {
                "path": path, "composite": True, "panels": panels}}, 2)
            self.assertIn("art1", resolved)
            self.assertLess(len(resolved["art1"]), 200000)


if __name__ == "__main__":
    unittest.main()
