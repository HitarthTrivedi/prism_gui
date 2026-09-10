"""The pictures a reel is handed, and what the asset pipeline does to them.

Pixel-level, on synthetic files, because the only test collect() had ran
"against records rather than files" — and so nobody noticed that cutout()
was destroying the most common inputs. Each case below is one that went
wrong on a real reel or in a real measurement (2026-09-07):

  · a picture that already has transparency was flattened to RGB, its
    transparent pixels read as a black (or white) background, and every
    letter in that colour was punched out — a "Brand" wordmark reached the
    reel as one red "d";
  · a client's real transparent logo was reported to the art director as
    "opaque, has its own background", so it got boxed and could never claim
    the logo slot;
  · a mark on a white card came back with a hard sawtooth edge and a halo
    of white that showed on every dark scene;
  · white lettering on a coloured badge, and the white panels of a
    screenshot, were cleared along with the card they sat on.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402  (puts prism_terminal/core on sys.path)
from core import assets as A  # noqa: E402

from PIL import Image, ImageDraw, ImageFont  # noqa: E402


def _font(size=90):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "C:/Windows/Fonts/arialbd.ttf",
                 "/System/Library/Fonts/Supplemental/Arial Bold.ttf"):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _px(im):
    """(alpha channel, rgb) as numpy arrays."""
    import numpy as np
    im = im.convert("RGBA")
    arr = np.asarray(im)
    return arr[..., 3], arr[..., :3]


class Files(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="prism-assets-")

    def save(self, im, name):
        p = os.path.join(self.dir, name)
        im.save(p)
        return p


class APictureThatAlreadyHasTransparency(Files):

    def _wordmark(self, clear=(0, 0, 0, 0), ink=(20, 20, 20, 255)):
        im = Image.new("RGBA", (800, 300), clear)
        ImageDraw.Draw(im).text((40, 90), "ACME LTD", font=_font(), fill=ink)
        return im

    def test_is_kept_as_it_is(self):
        """The wordmark case: transparent pixels stored as (0,0,0,0)."""
        src = self.save(self._wordmark(), "mark.png")
        got = A.prepare(src, self.dir)
        self.assertTrue(got["alpha"])
        self.assertEqual(got["how"], "its own transparency")
        a, rgb = _px(Image.open(got["path"]))
        dark = ((a > 0) & (rgb.max(axis=2) < 60)).sum()
        self.assertGreater(dark, 5000, "the black letters must survive")

    def test_white_on_a_badge_survives_too(self):
        """Transparent pixels stored as (255,255,255,0), white lettering."""
        im = Image.new("RGBA", (800, 300), (255, 255, 255, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([40, 40, 760, 260], radius=40, fill=(40, 140, 70, 255))
        d.text((120, 90), "ACME", font=_font(), fill=(255, 255, 255, 255))
        src = self.save(im, "badge.png")
        got = A.prepare(src, self.dir)
        a, rgb = _px(Image.open(got["path"]))
        white = ((a > 0) & (rgb.min(axis=2) > 240)).sum()
        self.assertGreater(white, 3000, "the white lettering must survive")

    def test_the_soft_edge_is_preserved(self):
        im = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
        ImageDraw.Draw(im).ellipse([50, 50, 350, 350], fill=(200, 30, 30, 255))
        im = im.resize((200, 200), Image.LANCZOS)      # anti-aliased rim
        src = self.save(im, "disc.png")
        a, _ = _px(Image.open(A.prepare(src, self.dir)["path"]))
        self.assertGreater(((a > 0) & (a < 255)).sum(), 50)

    def test_it_is_reported_as_transparent_and_can_be_the_logo(self):
        src = self.save(self._wordmark(), "theirs.png")
        table = A.collect([src], self.dir)
        self.assertIn("logo", table)
        self.assertTrue(table["logo"]["alpha"])
        self.assertIn("transparent PNG", A.manifest(table))
        self.assertNotIn("OPAQUE", A.manifest(table))

    def test_an_rgba_file_with_no_transparent_pixels_is_not_transparent(self):
        im = Image.new("RGBA", (300, 300), (255, 255, 255, 255))
        src = self.save(im, "opaque_rgba.png")
        self.assertFalse(A.has_real_alpha(src))


class AMarkOnAFlatCard(Files):

    def _logo_on_white(self):
        im = Image.new("RGB", (800, 300), (255, 255, 255))
        d = ImageDraw.Draw(im)
        d.ellipse([50, 50, 250, 250], fill=(40, 140, 70))
        d.ellipse([110, 110, 190, 190], fill=(255, 255, 255))   # a counter
        d.text((300, 90), "Green", font=_font(), fill=(20, 20, 20))
        # soften the edges like a real export
        return im.resize((400, 150), Image.LANCZOS).resize((800, 300), Image.LANCZOS)

    def test_the_card_goes_and_the_edge_is_soft(self):
        src = self.save(self._logo_on_white(), "logo.png")
        got = A.prepare(src, self.dir)
        self.assertTrue(got["alpha"])
        self.assertEqual(got["how"], "cut from a flat background")
        a, rgb = _px(Image.open(got["path"]))
        self.assertGreater((a == 0).mean(), 0.3, "the white card is gone")
        self.assertGreater(((a > 0) & (a < 255)).sum(), 100, "a soft edge")

    def test_there_is_no_white_halo(self):
        src = self.save(self._logo_on_white(), "logo.png")
        a, rgb = _px(Image.open(A.prepare(src, self.dir)["path"]))
        halo = ((a == 255) & (rgb.min(axis=2) > 215)).sum()
        # The old cut-out kept 1,299 fully-opaque near-white pixels on this
        # very image. A few stray pixels are the anti-aliasing of the text
        # itself; a halo is hundreds.
        self.assertLess(halo, 60, f"{halo} near-white opaque pixels kept")

    def test_a_letters_counter_shows_through(self):
        src = self.save(self._logo_on_white(), "logo.png")
        a, _ = _px(Image.open(A.prepare(src, self.dir)["path"]))
        # The ring's centre is at the original (150,150); after trim it has
        # moved, so look for a hole INSIDE the ring's bounding box instead.
        h, w = a.shape
        ring = a[:, : w // 3]                     # the disc is on the left
        cy, cx = ring.shape[0] // 2, ring.shape[1] // 2
        self.assertEqual(int(ring[cy, cx]), 0, "the counter must be transparent")

    def test_the_colour_of_the_card_is_taken_out_of_the_edge(self):
        """A pixel that was 50/50 ink and white card comes back as ink at
        half alpha, not as a pale pixel at full alpha."""
        im = Image.new("RGB", (300, 300), (255, 255, 255))
        ImageDraw.Draw(im).rectangle([100, 100, 200, 200], fill=(0, 0, 0))
        im = im.resize((150, 150), Image.LANCZOS).resize((300, 300), Image.LANCZOS)
        src = self.save(im, "square.png")
        a, rgb = _px(Image.open(A.prepare(src, self.dir)["path"]))
        edge = (a > 40) & (a < 215)
        self.assertGreater(edge.sum(), 20)
        self.assertLess(rgb[edge].mean(), 90,
                        "edge pixels should be near-ink, not washed out")


class AWhiteScreenshot(Files):
    """White at all four corners, an interface in between — the case the
    four-pixel corner check got wrong every time."""

    def _shot(self):
        im = Image.new("RGB", (1200, 800), (255, 255, 255))
        d = ImageDraw.Draw(im)
        d.rectangle([40, 40, 1160, 150], fill=(30, 60, 120))
        d.text((60, 45), "Dashboard", font=_font(), fill=(255, 255, 255))
        for i in range(3):
            d.rectangle([60 + i * 380, 220, 380 + i * 380, 720],
                        outline=(200, 200, 200), width=3)
            d.text((80 + i * 380, 260), f"Card {i + 1}", font=_font(), fill=(20, 20, 20))
        return im

    def test_its_white_panels_are_not_punched_out(self):
        src = self.save(self._shot(), "shot.png")
        got = A.prepare(src, self.dir)
        a, rgb = _px(Image.open(got["path"]))
        white_text = ((a > 0) & (rgb.min(axis=2) > 240)).sum()
        self.assertGreater(white_text, 2000, "the header's white text survives")
        self.assertLess((a == 0).mean(), 0.45, "only the outer margin goes")

    def test_it_never_becomes_the_logo(self):
        src = self.save(self._shot(), "shot.png")
        table = A.collect([src], self.dir)
        self.assertNotIn("logo", table)
        self.assertEqual(list(table), ["art1"])


class APhotograph(Files):

    def _photo(self):
        im = Image.new("RGB", (1200, 800))
        px = im.load()
        for y in range(800):
            for x in range(1200):
                px[x, y] = (120 + y // 8, 160 + y // 10, 220 - y // 6)
        return im

    def test_is_left_alone_and_said_to_be_one(self):
        src = self.save(self._photo(), "sky.jpg")
        got = A.prepare(src, self.dir)
        self.assertFalse(got["alpha"])
        self.assertEqual(got["how"], "photograph")
        self.assertEqual(got["path"], src)

    def test_the_art_director_is_told_how_to_use_it(self):
        src = self.save(self._photo(), "sky.jpg")
        said = A.manifest(A.collect([src], self.dir))
        self.assertIn("OPAQUE", said)
        self.assertIn("object-fit: cover", said)
        self.assertIn("FULL-BLEED", said)
        self.assertIn("Never a bare <img>", said)

    def test_a_transparent_one_is_told_it_needs_no_box(self):
        im = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
        ImageDraw.Draw(im).ellipse([40, 40, 260, 260], fill=(200, 30, 30, 255))
        src = self.save(im, "disc.png")
        said = A.manifest(A.collect([src], self.dir))
        self.assertIn("need no backing", said)
        self.assertNotIn("OPAQUE", said)


class FlatBackgroundIsMeasuredOnTheBorder(Files):

    def test_one_odd_corner_does_not_veto_a_flat_card(self):
        im = Image.new("RGB", (400, 400), (255, 255, 255))
        d = ImageDraw.Draw(im)
        d.ellipse([100, 100, 300, 300], fill=(0, 0, 0))
        d.point((0, 0), fill=(0, 0, 0))                 # a JPEG artefact
        self.assertTrue(A.has_flat_background(self.save(im, "card.png")))

    def test_a_gradient_edge_is_not_flat(self):
        self.assertFalse(A.has_flat_background(
            self.save(APhotograph._photo(self), "sky.png")))


if __name__ == "__main__":
    unittest.main()
