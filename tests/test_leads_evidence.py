"""The lead drawer's evidence: what a qualified dossier found, shown with its
sources — and, because it is drawn from web search results, shown safely."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402  (puts prism_terminal/core on sys.path)
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

_app = QApplication.instance() or QApplication([])

from addons.leads import evidence as EV  # noqa: E402
from prospector.models import Dimension, Dossier, Lead, Signal  # noqa: E402


def _dossier(**over):
    base = dict(
        lead=Lead(name="Asha", email="a@x.com", fit_score=90.0),
        verdict="hot", score=91, confidence=0.7,
        summary="Owner-led fabricator expanding capacity.",
        dimensions=[
            Dimension("Fit", "pass", "Runs a 60-person plant", "company site"),
            Dimension("Timing", "warn", "Expansion announced", "press"),
            Dimension("Budget", "unknown", "", ""),
            Dimension("Competition", "fail", "Already has a vendor", "linkedin.com"),
        ],
        signals=[Signal(title="Opens second plant in Pune",
                        snippet="The company said it will add 40 jobs.",
                        url="https://example.com/news", published="2026-09-02",
                        source="economictimes.com")],
        signal_status="found")
    base.update(over)
    return Dossier(**base)


def _texts(widgets) -> list:
    out = []
    for w in widgets:
        if isinstance(w, QLabel):
            out.append(w.text())
        out += [lab.text() for lab in w.findChildren(QLabel)]
    return out


def _all(dos) -> list:
    return _texts(EV.build(dos))


def _drawer_texts(cockpit) -> list:
    out = []
    lay = cockpit._drawer_lay
    for i in range(lay.count()):
        w = lay.itemAt(i).widget()
        if w is not None:
            out += _texts([w])
    return out


# ── what is shown ────────────────────────────────────────────────────────────

def test_the_verdict_and_score_lead():
    head = _texts(EV.headline(_dossier()))
    assert "HOT" in head and "91 / 100" in head
    assert any("70%" in t for t in head)
    assert any("Owner-led fabricator" in t for t in head)


def test_every_dimension_is_shown_with_its_evidence_and_its_source():
    texts = _all(_dossier())
    for name in ("Fit", "Timing", "Budget", "Competition"):
        assert name in texts
    assert "Runs a 60-person plant" in texts
    assert "Source: company site" in texts
    assert {"Pass", "Watch", "Unknown", "Fail"} <= set(texts)


def test_an_unknown_dimension_says_unknown_instead_of_pretending():
    assert any("No evidence found" in t for t in _all(_dossier()))


def test_the_why_now_signal_shows_headline_source_date_and_a_link():
    texts = _all(_dossier())
    assert "Opens second plant in Pune" in texts
    assert "economictimes.com · 2 Sep 2026" in texts
    link = [t for t in texts if "Read the source" in t][0]
    assert 'href="https://example.com/news"' in link


def test_no_news_is_stated_not_invented():
    texts = _all(_dossier(signals=[], signal_status="none"))
    assert any("doesn't invent a reason" in t for t in texts)


def test_a_failed_news_search_is_not_reported_as_no_news():
    texts = _all(_dossier(signals=[], signal_status="source_error"))
    assert any("search failed" in t for t in texts)
    assert not any("doesn't invent" in t for t in texts)


def test_an_unqualified_or_failed_lead_shows_no_evidence_block():
    bare = Dossier(lead=Lead(name="A"), verdict="cold", score=0)
    assert EV.build(bare) == [] and EV.headline(bare) == [] and EV.detail(bare) == []


# ── the web is not trusted ───────────────────────────────────────────────────

def test_only_http_links_are_ever_clickable():
    assert EV.safe_url("https://a.com/x") == "https://a.com/x"
    assert EV.safe_url("http://a.com") == "http://a.com"
    for bad in ("javascript:alert(1)", "file:///C:/Windows", "data:text/html,x",
                "ftp://a.com", "//a.com", "", "https://a.com/ x"):
        assert EV.safe_url(bad) == "", bad


def test_a_hostile_headline_is_plain_text_never_markup():
    hostile = "<img src=x onerror=alert(1)><b>bold</b>"
    dos = _dossier(signals=[Signal(title=hostile, snippet=hostile, source="evil.com")])
    widgets = EV.detail(dos)                    # kept alive: Qt deletes children with the parent
    shown = [lab for w in widgets for lab in w.findChildren(QLabel)
             if hostile in lab.text()]
    assert shown, "the headline should be shown, literally"
    assert all(lab.textFormat() == Qt.PlainText for lab in shown)


def test_a_javascript_url_gets_no_link_at_all():
    dos = _dossier(signals=[Signal(title="t", url="javascript:alert(1)", source="s")])
    assert not any("Read the source" in t for t in _all(dos))


def test_a_url_cannot_break_out_of_the_href():
    dos = _dossier(signals=[Signal(title="t", url='https://a.com/"onmouseover="x', source="s")])
    link = [t for t in _all(dos) if "Read the source" in t]
    assert link
    # the quote is entity-escaped, so it can never close the attribute early
    assert '&quot;onmouseover=&quot;x' in link[0] and '"onmouseover="x' not in link[0]


def test_dates_are_friendly_and_a_non_date_survives():
    assert EV.when("2026-09-02") == "2 Sep 2026"
    assert EV.when("last Tuesday") == "last Tuesday"
    assert EV.when("") == ""


def test_a_long_snippet_is_clipped():
    assert len(EV.clip("word " * 200)) <= EV._SNIPPET_MAX + 1
    assert EV.clip("short") == "short"


# ── in the drawer ────────────────────────────────────────────────────────────

def test_the_drawer_shows_the_evidence_for_a_qualified_lead():
    from addons.leads import cockpit as CK
    c = CK.LeadsCockpit()
    c.set_dossiers([_dossier()])
    c._table.setCurrentCell(0, 1)
    texts = _drawer_texts(c)
    assert "HOT" in texts and "Runs a 60-person plant" in texts
    assert "Opens second plant in Pune" in texts


def test_the_verdict_is_the_first_thing_in_the_drawer():
    from addons.leads import cockpit as CK
    c = CK.LeadsCockpit()
    c.set_dossiers([_dossier()])
    c._table.setCurrentCell(0, 1)
    assert "HOT" in _texts([c._drawer_lay.itemAt(0).widget()])


def test_an_unqualified_lead_shows_no_verdict_and_says_why():
    from addons.leads import cockpit as CK
    c = CK.LeadsCockpit()
    c.set_dossiers([], None, [Lead(name="Nobody", fit_score=55.0)])
    c._table.setCurrentCell(0, 1)
    texts = _drawer_texts(c)
    assert "HOT" not in texts and "WHY NOW" not in texts     # no evidence block
    assert any("Not qualified yet" in t for t in texts)
