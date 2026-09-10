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


class TheDrawingNeverReachesAnAI(unittest.TestCase):
    """The owner's rule for every measuring add-on, made to hold for BOQ too
    (10 Sep 2026): the drawing is measured here; an AI only ever sees the
    numbers. Until now the writing stage attached the CAD file itself."""

    class _Capture:
        seen = {}

        def __init__(self, *a, **kw):
            TheDrawingNeverReachesAnAI._Capture.seen = {"args": a, "kwargs": kw}
            self.done = self.failed = self

        def connect(self, *_):
            pass

        def start(self):
            pass

    def test_the_writer_is_handed_templates_and_notes_but_never_the_drawing(self):
        from unittest import mock
        from addons.boq import dialog as BD
        d = _dialog()
        d.q = {"layers": ["WALLS"], "lengths_by_layer": {"WALLS": 12.0},
               "areas_by_layer": {}, "block_counts": {}, "unit": "m",
               "scope_total_layers": 1}
        d.cad_path = "/secret/site.dxf"
        d.summary = "WALLS 12.00 m"
        d.request = "BOQ for the site"
        d.templates = [{"path": "/x/template.xlsx", "name": "template.xlsx"}]
        d.notes = [{"path": "/x/notes.txt", "name": "notes.txt"}]
        d.writer_agent = "ChatGPT"
        with mock.patch.object(BD, "AutomationWorker", self._Capture):
            d._write()
        files = self._Capture.seen["args"][2]
        names = [f["name"] for f in files]
        self.assertEqual(names, ["template.xlsx", "notes.txt"])
        for f in files:
            self.assertFalse(f["path"].lower().endswith((".dxf", ".dwg")))
        prompt = self._Capture.seen["kwargs"]["custom_stages"][0][2][0]
        self.assertIn("NOT attached", prompt)
        self.assertNotIn("attached to this message", prompt)
        self.assertNotIn("/secret/site.dxf", prompt)

    def test_the_terminal_command_keeps_the_same_rule(self):
        import inspect
        import core_bridge as CB
        src = inspect.getsource(CB.get_boq().__class__) if False else ""
        import importlib, sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "prism_terminal"))
        text = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "prism_terminal", "prism.py"),
            encoding="utf-8").read()
        self.assertIn("write_files = templates + note_files", text)
        self.assertNotIn("write_files = ([cad_file] if cad_file else [])", text)


class ASampleBoqDefinesTheDeliverable(unittest.TestCase):
    """Attach one of the firm's own BOQs and the writer is told to make THAT
    document, filled with this drawing's numbers -- the drawing itself
    still never goes (10 Sep 2026)."""

    def test_a_docx_xlsx_or_pdf_is_a_template_and_goes_to_the_writer(self):
        import core_bridge as CB
        boq = CB.get_boq()
        cad, templates, images, notes = boq.classify_inputs([
            {"path": "/x/site.dwg", "name": "site.dwg"},
            {"path": "/x/last_year_boq.xlsx", "name": "last_year_boq.xlsx"},
            {"path": "/x/sample.pdf", "name": "sample.pdf"},
            {"path": "/x/legend.png", "name": "legend.png"}])
        self.assertEqual([t["name"] for t in templates],
                         ["last_year_boq.xlsx", "sample.pdf"])
        self.assertEqual([c["name"] for c in cad], ["site.dwg"])

    def test_the_writer_is_told_the_sample_defines_the_document(self):
        import core_bridge as CB
        boq = CB.get_boq()
        with_sample = boq.formatting_prompt("WALLS 12.00 m", has_template=True)
        self.assertIn("A SAMPLE BOQ IS ATTACHED", with_sample)
        self.assertIn("defines what you are making", with_sample)
        self.assertIn("do not copy the sample's rows or quantities", with_sample)
        without = boq.formatting_prompt("WALLS 12.00 m", has_template=False)
        self.assertNotIn("SAMPLE BOQ", without)

    def test_the_front_door_says_so(self):
        from addons.boq.panel import BoqPanel
        titles = [step[1] for step in BoqPanel.STEPS]
        self.assertIn("Attach a sample BOQ too", titles)

    def test_the_writer_keeps_the_good_habits_of_the_best_boq(self):
        import core_bridge as CB
        prompt = CB.get_boq().formatting_prompt("WALLS 12.00 m", has_template=True)
        for phrase in ("reference table of the measured figures",
                       "decide — count it once or keep both",
                       "size storage, power and switching",
                       "use them as mounting or routing points"):
            self.assertIn(phrase, prompt)


class TheMeasurementIsATable(unittest.TestCase):
    """The owner's screenshot of 10 Sep: the measured figures shown as the
    prompt text in a 120 px box. Now a table, one row per measured item,
    the way the CSV has it. The prompt text is still what the AI gets."""

    Q = {"unit": "unspecified", "unit_code": 0, "unit_confirmed": False,
         "notes": ["Full conversion couldn't be read, so a minimal fallback was used"],
         "lengths_by_layer": {"BOUNDARY WALL": 1091.18, "Concrete Road": 579.23},
         "areas_by_layer": {"Building": 2227.57},
         "block_counts": {"EP": 22, "MAIN-GATE-7M": 2},
         "block_layers": {"EP": ["Electric Pole"], "MAIN-GATE-7M": ["gates"]},
         "layers": ["0", "BOUNDARY WALL", "Building", "Concrete Road",
                    "Electric Pole", "gates"],
         "entity_count": 29661}

    def test_one_row_per_measured_item_in_csv_order(self):
        from addons.boq.measured import MeasuredTable, rows_for
        rows = rows_for(self.Q)
        self.assertEqual([r[0] for r in rows],
                         ["BOUNDARY WALL", "Concrete Road", "Building", "EP",
                          "MAIN-GATE-7M"])
        self.assertEqual([r[1] for r in rows],
                         ["Length", "Length", "Area", "Count", "Count"])
        t = MeasuredTable()
        t.set_quantities(self.Q)
        shown = t.rows()
        self.assertEqual(len(shown), 5)
        self.assertEqual(shown[0], ("BOUNDARY WALL", "Length", "BOUNDARY WALL",
                                    "1,091.18", "unspecified"))
        self.assertEqual(shown[2], ("Building", "Area", "Building", "2,227.57",
                                    "sq unspecified"))
        self.assertEqual(shown[3], ("EP", "Count", "Electric Pole", "22", "nos"))

    def test_the_header_and_warnings_say_what_the_text_said(self):
        from addons.boq.measured import MeasuredTable
        t = MeasuredTable()
        t.set_quantities(self.Q)
        self.assertIn("29,661 entities", t.header.text())
        self.assertIn("6 layers", t.header.text())
        self.assertTrue(t.warn.isVisibleTo(t))
        self.assertIn("Unit not confirmed", t.warn.text())
        self.assertIn("minimal fallback", t.warn.text())
        self.assertIn("All 6 layers", t.layers.text())

    def test_the_window_fills_the_table_and_keeps_the_prompt_text(self):
        import tempfile
        from unittest import mock
        import core_bridge as CB
        d = _dialog()
        d.cad_path = "/x/site.dwg"
        with mock.patch.object(CB.config, "RUNS_DIR", tempfile.mkdtemp()), \
                mock.patch.object(CB.config, "save_artifact"):
            d._on_measured(self.Q, ["a note"])
        self.assertEqual(len(d.meas_table.rows()), 5)
        self.assertIn("LENGTHS BY LAYER", d.summary)     # the AI's text, intact
        self.assertTrue(d.meas_box.isVisibleTo(d))
