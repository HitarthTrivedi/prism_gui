"""core/gerber_form.py — the measured figures land in the CLIENT'S form.

The request behind this: FCC's F-SAL-01 quotation sheet, with a cell for
every figure Prism measures. The client's form is the format — Prism only
fills the cells whose labels it recognises, never touches a formula, and
leaves everything unmeasured exactly as drawn.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "prism_terminal"))

from core import gerber_form as GF  # noqa: E402

try:
    import openpyxl
    HAVE = True
except Exception:                                   # pragma: no cover
    HAVE = False

FCC = ("/Users/hitarthtrivedi/Documents/PythonProgram/prism-ai-flow/"
       "gerber_test/gerber data/F-SAL-01 Rev-00 QUOTATION FORM.xlsx")

JOB = {
    "answers": {
        "pcb_size_mm": (60.0, 73.0),
        "array_size_mm": (120.0, 73.0),
        "pcbs_per_array": 2,
        "min_track_width_mm": 2.999994,
        "min_track_spacing_mm": 2.043706,
        "min_drill_mm": 0.999998,
        "min_pitch_mm": 5.0,
        "min_smt_pad": "0.30 x 0.60 mm",
        "drill_count": 80,
        "layers": 2,
    },
    "drills": {"tools": [{"dia_mm": 0.999998, "hits": 20},
                         {"dia_mm": 1.3, "hits": 60},
                         {"dia_mm": 9.9, "hits": 0}],   # unused tool
               "total": 80},
}


@unittest.skipUnless(HAVE, "openpyxl not installed")
class TheLabelsFindTheirCells(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.tpl = os.path.join(cls.dir, "form.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws["A1"] = "Board X"
        ws["A2"] = "Board Y"
        ws["C1"] = "Min Line"
        ws["C2"] = "Smallest Hole"
        ws["E1"] = "Pcs / Array"
        ws["E2"] = "Pitch"
        ws["A3"] = "No. of Holes"
        ws["B3"] = "=B20"                 # their arithmetic
        ws["A4"] = "Cu. Wt Finish"        # nothing measured for this
        ws["C4"] = "Min.SMT Length"
        ws["E4"] = "Min.SMT Width"
        ws["A6"] = "HOLE SIZE"
        ws["B6"] = "NO.OF HOLES/ARRAY"
        ws["A7"], ws["B7"] = 8, 0         # pre-printed placeholders
        ws["A8"], ws["B8"] = 10, 0
        ws["A9"], ws["B9"] = 12, 0
        ws["A10"] = "TOTAL DRILL"
        ws["B10"] = "=SUM(B7:B9)"
        wb.save(cls.tpl)
        cls.out = os.path.join(cls.dir, "filled.xlsx")
        cls.result = GF.fill_form(JOB, cls.tpl, cls.out)
        cls.ws = openpyxl.load_workbook(cls.out).active

    def test_each_label_gets_the_value_beside_it_two_decimals(self):
        self.assertEqual(self.ws["B1"].value, 60.0)
        self.assertEqual(self.ws["B2"].value, 73.0)
        self.assertEqual(self.ws["D1"].value, 3.0)
        self.assertEqual(self.ws["D2"].value, 1.0)
        self.assertEqual(self.ws["F1"].value, 2)
        self.assertEqual(self.ws["F2"].value, 5.0)

    def test_smt_length_is_the_longer_side(self):
        self.assertEqual(self.ws["D4"].value, 0.6)
        self.assertEqual(self.ws["F4"].value, 0.3)

    def test_their_formulas_are_never_overwritten(self):
        self.assertEqual(self.ws["B3"].value, "=B20")
        self.assertEqual(self.ws["B10"].value, "=SUM(B7:B9)")

    def test_an_unmeasured_label_is_left_as_drawn(self):
        self.assertIsNone(self.ws["B4"].value)

    def test_the_drill_table_holds_the_real_tools_and_zeroed_leftovers(self):
        # Two used tools written; the unused Ø9.9 (0 hits) never appears;
        # the third placeholder row is zeroed so their SUM stays honest.
        self.assertEqual((self.ws["A7"].value, self.ws["B7"].value), (1.0, 20))
        self.assertEqual((self.ws["A8"].value, self.ws["B8"].value), (1.3, 60))
        self.assertEqual(self.ws["B9"].value, 0)
        self.assertIsNone(self.ws["A9"].value)
        self.assertEqual(self.result["drill_rows"], 2)

    def test_the_template_itself_is_untouched(self):
        ws = openpyxl.load_workbook(self.tpl).active
        self.assertIsNone(ws["B1"].value)
        self.assertEqual(ws["A7"].value, 8)


@unittest.skipUnless(HAVE and os.path.exists(FCC),
                     "the client's real form is not on this machine")
class TheClientsRealForm(unittest.TestCase):
    """Witnessed against FCC's actual F-SAL-01 sheet."""

    @classmethod
    def setUpClass(cls):
        cls.out = os.path.join(tempfile.mkdtemp(), "fcc.xlsx")
        cls.result = GF.fill_form(JOB, FCC, cls.out,
                                  meta={"customer": "Test Co",
                                        "part": "PCB-001"})
        cls.ws = openpyxl.load_workbook(cls.out)["Table 1"]

    def test_the_figures_land_in_fccs_own_cells(self):
        self.assertEqual(self.ws["D8"].value, 60.0)    # Board X
        self.assertEqual(self.ws["D9"].value, 73.0)    # Board Y
        self.assertEqual(self.ws["B18"].value, 3.0)    # Min Line
        self.assertEqual(self.ws["B19"].value, 2.04)   # Min Space
        self.assertEqual(self.ws["B20"].value, 1.0)    # Smallest Hole
        self.assertEqual(self.ws["B8"].value, 2)       # No Layer
        self.assertEqual(self.ws["B7"].value, "Test Co")
        self.assertEqual(self.ws["D7"].value, "PCB-001")

    def test_fccs_totals_still_come_from_fccs_formulas(self):
        self.assertEqual(self.ws["B22"].value, "=B52")
        self.assertEqual(self.ws["B52"].value, "=SUM(B30:B51)")

    def test_the_drill_table_carries_the_measured_tools(self):
        self.assertEqual((self.ws["A30"].value, self.ws["B30"].value),
                         (1.0, 20))
        self.assertEqual((self.ws["A31"].value, self.ws["B31"].value),
                         (1.3, 60))

    def test_the_companys_photos_and_layout_survive_byte_for_byte(self):
        """The client's form is their document — logo, drawing layout,
        print setup and all. openpyxl's save() rebuilt those wrong (the
        logo drawing shrank 12KB → 1KB, printer settings vanished), which
        is why filling is a zip-level patch: every part of the file except
        the one sheet XML must be BYTE-identical to the template."""
        import zipfile
        with zipfile.ZipFile(FCC) as tin, zipfile.ZipFile(self.out) as tout:
            self.assertEqual(set(tin.namelist()), set(tout.namelist()))
            changed = [n for n in tin.namelist()
                       if tin.read(n) != tout.read(n)]
            self.assertEqual(changed, ["xl/worksheets/sheet1.xml"])
            # And even in that one file, the client's own namespace
            # prefixes are untouched — a prefix rename is what makes
            # Excel call the file corrupt.
            sheet = tout.read("xl/worksheets/sheet1.xml").decode()
            self.assertIn('mc:Ignorable="x14ac', sheet)


class TheDialogRemembersTheTemplate(unittest.TestCase):

    def test_the_gui_offers_and_uses_the_clients_format(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = open(os.path.join(root, "dialogs", "gerber_dialog.py"),
                   encoding="utf-8").read()
        self.assertIn('cfg.get("gerber_form_template")', src)
        self.assertIn("get_gerber_form", src)
        # Filling runs as part of measuring, not as a separate chore.
        measured = src[src.index("def _on_measured("):
                       src.index("def _on_measure_failed(")]
        self.assertIn("_fill_forms", measured)


if __name__ == "__main__":
    unittest.main()
