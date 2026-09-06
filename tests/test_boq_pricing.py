"""Tests for core.boq_price — the deterministic pricing + Excel-export layer.

Every number of record in a BOQ is arithmetic, not a generation. These tests
pin that arithmetic AND the two honesty guarantees the add-on sells on:

  · a library rate is auto-applied only when its unit matches the measured
    quantity (never price a length at a per-cum rate), and
  · an item with no rate is flagged, never quietly dropped or guessed.

The engine has no test suite of its own (prism_terminal ships none), so this
lives in the GUI repo and reaches core.boq_price through core_bridge — the same
path the dialog uses.
"""
import os
import sys
from decimal import Decimal

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import core_bridge as CB

bp = CB.get_boq_price()
RateItem = bp.quoting.RateItem


def _item(desc, unit, qty, rate, section="Measured Works"):
    return bp.BoqItem(description=desc, unit=unit, quantity=qty,
                      rate=rate, section=section)


# ── model arithmetic ──────────────────────────────────────────────────────────

def test_item_amount_is_qty_times_rate():
    it = _item("Plaster", "sqm", "10", "245")
    assert it.amount == Decimal("2450.00")
    assert it.priced


def test_item_unpriced_when_rate_zero():
    it = _item("Beam", "m", "60", "0")
    assert not it.priced
    assert it.amount == Decimal("0.00")


def test_rollup_subtotal_contingency_gst_grand():
    boq = bp.Boq(items=[_item("A", "sqm", "10", "100"),    # 1000
                        _item("B", "nos", "2", "500")],    # 1000
                 contingency_pct=Decimal("5"), gst_pct=Decimal("18"))
    assert boq.subtotal() == Decimal("2000.00")
    assert boq.contingency_amount() == Decimal("100.00")   # 5% of 2000
    assert boq.pre_tax_total() == Decimal("2100.00")
    assert boq.gst_amount() == Decimal("378.00")           # 18% of 2100
    assert boq.grand_total() == Decimal("2478.00")


def test_pct_fields_tolerate_int_and_float():
    """The dialog will assign these from widgets — they must not have to be
    Decimal to compute correctly."""
    boq = bp.Boq(items=[_item("A", "sqm", "10", "100")])
    boq.contingency_pct = 5      # int
    boq.gst_pct = 18.0           # float
    assert boq.contingency_amount() == Decimal("50.00")
    assert boq.grand_total() == Decimal("1239.00")         # (1000+50)*1.18


def test_sections_group_in_first_seen_order():
    boq = bp.Boq(items=[_item("A", "sqm", 1, 1, section="Finishes"),
                        _item("B", "cum", 1, 1, section="Concrete"),
                        _item("C", "sqm", 1, 1, section="Finishes")])
    names = [name for name, _ in boq.sections()]
    assert names == ["Finishes", "Concrete"]
    assert len(dict(boq.sections())["Finishes"]) == 2


# ── measured take-off -> BOQ, with the unit guard ─────────────────────────────

def test_boq_from_measured_builds_items_with_right_units():
    q = {"unit": "meters",
         "lengths_by_layer": {"WALL": 100.0},
         "areas_by_layer": {"FLOOR": 50.0},
         "block_counts": {"DOOR": 4}}
    boq = bp.boq_from_measured(q)
    units = {it.description: it.unit for it in boq.items}
    assert units == {"WALL": "m", "FLOOR": "sqm", "DOOR": "nos"}


def test_auto_rate_applies_only_on_matching_unit():
    rates = [RateItem(code="PL-01",
                      description="12 mm internal cement plaster CM 1:6",
                      unit="sqm", rate=Decimal("245")),
             RateItem(code="BW-01",
                      description="Brickwork in CM 1:6 230 mm",
                      unit="cum", rate=Decimal("6300"))]
    q = {"unit": "meters",
         "areas_by_layer": {"internal cement plaster": 10.0},   # sqm == PL-01
         "lengths_by_layer": {"brickwork wall": 20.0}}          # m  != BW-01 cum
    boq = bp.boq_from_measured(q, rate_items=rates)
    by = {it.description: it for it in boq.items}
    assert by["internal cement plaster"].rate == Decimal("245")   # unit matched
    assert by["brickwork wall"].rate == Decimal("0")              # guarded
    assert "conversion" in by["brickwork wall"].remark
    assert by["brickwork wall"] in boq.unpriced()


def test_user_unit_override_is_trusted():
    rates = [RateItem(code="BW-01", description="Brickwork 230 mm",
                      unit="cum", rate=Decimal("6300"))]
    q = {"unit": "meters", "lengths_by_layer": {"brickwork": 5.0}}
    boq = bp.boq_from_measured(q, mapping={"brickwork": {"unit": "cum"}},
                               rate_items=rates)
    assert boq.items[0].rate == Decimal("6300")   # user asserted cum -> applied


# ── amount in words (Indian numbering) ────────────────────────────────────────

def test_amount_in_words_indian_system():
    assert bp.amount_in_words(Decimal("0")) == "Rupees zero only"
    assert (bp.amount_in_words(Decimal("152450"))
            == "Rupees one lakh fifty two thousand four hundred fifty only")
    assert (bp.amount_in_words(Decimal("12300000"))
            == "Rupees one crore twenty three lakh only")
    assert "paise" in bp.amount_in_words(Decimal("100.50"))


# ── starter library ───────────────────────────────────────────────────────────

def test_starter_library_matches_a_clear_item():
    rates = bp.starter_rate_items()
    assert len(rates) > 20
    matches = bp.quoting.match_item("internal cement plaster 12mm", rates)
    assert matches and matches[0].item.code == "PL-01"


# ── Excel export ──────────────────────────────────────────────────────────────

def test_write_boq_xlsx_two_sheets_and_live_formulas(tmp_path):
    import openpyxl
    boq = bp.Boq(title="Test", items=[
        _item("Plaster", "sqm", "10", "245", section="Finishes"),
        _item("Flooring", "sqm", "5", "950", section="Finishes")],
        contingency_pct=Decimal("3"), gst_pct=Decimal("18"))
    out = str(tmp_path / "boq.xlsx")
    bp.write_boq_xlsx(boq, out)
    wb = openpyxl.load_workbook(out)
    assert wb.sheetnames == ["Bill of Quantities", "Abstract of Cost"]
    formulas = [c.value for row in wb["Bill of Quantities"].iter_rows()
                for c in row if isinstance(c.value, str) and c.value.startswith("=")]
    assert any(f.startswith("=D") and "*E" in f for f in formulas)   # =Qty*Rate
    assert any(f.startswith("=SUM(") for f in formulas)              # section total
    absrefs = [c.value for row in wb["Abstract of Cost"].iter_rows()
               for c in row if isinstance(c.value, str)
               and "Bill of Quantities" in c.value]
    assert absrefs                                                    # abstract is live


def test_write_boq_xlsx_survives_unpriced_item(tmp_path):
    boq = bp.Boq(items=[_item("Beam", "m", "60", "0")])
    out = str(tmp_path / "b.xlsx")
    bp.write_boq_xlsx(boq, out)
    assert os.path.exists(out)


def test_interstate_uses_single_igst(tmp_path):
    import openpyxl
    boq = bp.Boq(items=[_item("A", "sqm", "10", "100")],
                 gst_pct=Decimal("18"), interstate=True)
    out = str(tmp_path / "ig.xlsx")
    bp.write_boq_xlsx(boq, out)
    text = " ".join(str(c.value)
                    for row in openpyxl.load_workbook(out)["Bill of Quantities"].iter_rows()
                    for c in row if c.value)
    assert "IGST" in text and "CGST" not in text


def test_write_boq_csv_has_items_and_totals(tmp_path):
    boq = bp.Boq(items=[_item("A", "sqm", "10", "100")])
    out = str(tmp_path / "b.csv")
    bp.write_boq_csv(boq, out)
    data = open(out, encoding="utf-8").read()
    assert "Grand total" in data and "1000.00" in data
