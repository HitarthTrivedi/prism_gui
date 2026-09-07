"""BOQ and BOM: the run titles History has to recognise.

BOQ had no test file at all until this one. `addons/boq/dialog.py` is 600
lines, it is a paid feature, and it measures a customer's drawing and
produces the quantities they price from — while Gerber, which has one
prospective customer and is not in daily use, has four test files. That
imbalance is how the bug below survived.

The bug
───────
`widgets/panel_base._RUN_PREFIXES` (now derived from the add-on manifests)
decides which add-on wrote a run, by matching the START of its recorded
title. The titles themselves are f-strings inside the dialogs. Nothing tied
the two together, and the old `_RUN_PREFIXES` comment said so — it listed
the four other files whose f-strings it was matching against.

Commit 6b16cbb scaffolded BOM mode and replaced the dialog's hardcoded
`"BOQ"` with `self._doc`, so runs started being recorded as

    "Bill of Quantities — 500 brackets"

while the prefix table still said `"BOQ — "`. From that commit until this
one, `kind_of()` returned `""` for **every BOQ and BOM run**: no add-on chip
in History, the prefix never stripped from the title, and the add-on's own
front door unable to find its recent runs.

Nothing raised. Nothing was logged. The only symptom was a missing chip.

The fix is structural rather than a corrected literal: the dialog now takes
its prefix from its own manifest, so the two cannot disagree again. This file
is what makes that checkable — it reads the title the dialog actually
composes and feeds it to the same lookup History uses.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication                # noqa: E402

from addons import registry                               # noqa: E402
from addons.boq.dialog import BoqDialog                   # noqa: E402

_app = QApplication.instance() or QApplication([])

CFG = {"api_key": "k"}


def _dialog(mode: str = "boq") -> BoqDialog:
    return BoqDialog(CFG, [], None, mode=mode)


class TheRunTitleIsRecognisedByHistory(unittest.TestCase):
    """The regression test for the bug in this file's docstring."""

    def test_a_boq_run_title_is_attributed_to_boq(self):
        dialog = _dialog("boq")
        dialog.request = "500 brackets"
        title = f"{dialog._run_prefix}{dialog.request}"
        self.assertEqual(
            registry.kind_of(title), "boq",
            "History cannot tell that %r came from BOQ, so the run shows no "
            "add-on chip, keeps its prefix in the title, and does not appear "
            "in BOQ's own recent-runs list. Nothing raises when this breaks."
            % title)

    def test_a_bom_run_title_is_attributed_to_bom(self):
        dialog = _dialog("bom")
        dialog.request = "spring assembly"
        title = f"{dialog._run_prefix}{dialog.request}"
        self.assertEqual(registry.kind_of(title), "bom")

    def test_the_two_modes_are_told_apart(self):
        """They share a dialog and a licence key. If their prefixes collide,
        every BOM run is filed as a BOQ run and the mistake is invisible."""
        self.assertNotEqual(_dialog("boq")._run_prefix,
                            _dialog("bom")._run_prefix)

    def test_the_prefix_comes_from_the_manifest(self):
        """Not merely equal to it today — taken from it, so the dialog and
        the prefix table cannot drift apart again."""
        for key in ("boq", "bom"):
            with self.subTest(mode=key):
                self.assertEqual(_dialog(key)._run_prefix,
                                 registry.by_key(key).run_prefixes[0])

    def test_titles_written_before_the_fix_are_still_recognised(self):
        """Every BOQ run recorded between 6b16cbb and the fix is titled with
        the long form. Those records exist on customers' machines; dropping
        them from History would be a second, quieter bug."""
        self.assertEqual(registry.kind_of("Bill of Quantities — 500 brackets"),
                         "boq")
        self.assertEqual(registry.kind_of("Bill of Materials — spring"), "bom")


class TheTwoModesAreOneDialog(unittest.TestCase):
    """BOM is BOQ with `mode="bom"`. The point of that is that BOM inherits
    every fix BOQ gets; the risk is that the two drift in what they say."""

    def test_the_document_name_follows_the_mode(self):
        self.assertEqual(_dialog("boq")._doc, "Bill of Quantities")
        self.assertEqual(_dialog("bom")._doc, "Bill of Materials")

    def test_an_unknown_mode_falls_back_to_boq(self):
        """`mode` reaches this constructor from a rail command; an unexpected
        value must open the ordinary document, not crash or open nothing."""
        self.assertEqual(_dialog("nonsense").mode, "boq")

    def test_the_window_title_is_the_document_name(self):
        self.assertEqual(_dialog("bom").windowTitle(), "Bill of Materials")

    def test_both_modes_construct(self):
        """The cheapest possible guard on a 600-line dialog that had no test
        file at all: it builds, in both modes, without raising."""
        for key in ("boq", "bom"):
            with self.subTest(mode=key):
                self.assertIsNotNone(_dialog(key))


if __name__ == "__main__":
    unittest.main()
