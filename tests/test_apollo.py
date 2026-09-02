"""Apollo is driven by filters, not by prose — prove it stays that way.

The bug these guard against is a real one, seen in a live run:

    Value too long: 'Context from the previous pipeline stage (RESEA…'
    exceeds 200 characters

Apollo's search API refuses any single value over 200 characters, and the
pipeline was handing it the whole inter-stage brief. The fix has two halves —
the previous stage is told to emit a fixed filter block, and Apollo is driven
by URL instead of by typing — so the tests come in two halves too: the block
must parse out of realistically messy model output, and nothing that reaches
Apollo may ever exceed the limit no matter what the model wrote.
"""
from __future__ import annotations

import os
import sys
import unittest
from urllib.parse import parse_qsl, urlsplit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402  (puts prism_terminal/core on sys.path)
from core import agents as A  # noqa: E402
from core.automation import (  # noqa: E402
    _APOLLO_FIELDS, _APOLLO_HEADCOUNT, _apollo_filters, _apollo_url)

# Apollo's own hard limit, and the reason this module exists.
APOLLO_LIMIT = 200

CLEAN = """\
Small and mid-size manufacturers in western India are the best fit here.

HANDOFF FOR APOLLO
TITLES: Founder, CEO, Managing Director, Head of Operations
INDUSTRIES: manufacturing, industrial automation
LOCATIONS: Gujarat, Maharashtra, India
HEADCOUNT: 51-100, 101-200, 201-500
KEYWORDS: factory plant production automation
"""


def query_values(url: str) -> list[str]:
    """Every parameter value in an Apollo URL, hash routing and all."""
    # The query lives after '#/people?', so urlsplit puts it in .fragment.
    frag = urlsplit(url).fragment
    return [v for _, v in parse_qsl(frag.split("?", 1)[1])]


class Parsing(unittest.TestCase):
    def test_a_clean_block_parses(self):
        got = _apollo_filters(CLEAN)
        self.assertEqual(got["TITLES"],
                         ["Founder", "CEO", "Managing Director",
                          "Head of Operations"])
        self.assertEqual(got["LOCATIONS"], ["Gujarat", "Maharashtra", "India"])
        self.assertEqual(got["HEADCOUNT"], ["51-100", "101-200", "201-500"])

    def test_markdown_the_model_added_anyway_is_stripped(self):
        """Models bold the field names however firmly you ask them not to."""
        got = _apollo_filters(
            "HANDOFF FOR APOLLO\n"
            "* **TITLES:** Plant Head, `VP Manufacturing`\n"
            "* **INDUSTRIES:** pharmaceuticals\n")
        self.assertEqual(got["TITLES"], ["Plant Head", "VP Manufacturing"])
        self.assertEqual(got["INDUSTRIES"], ["pharmaceuticals"])

    def test_declined_fields_are_dropped_not_searched_for(self):
        """Searching Apollo for the job title "any" returns nothing at all."""
        got = _apollo_filters("HANDOFF FOR APOLLO\n"
                              "TITLES: CEO\nLOCATIONS: any\nKEYWORDS: n/a\n")
        self.assertEqual(got["TITLES"], ["CEO"])
        self.assertNotIn("LOCATIONS", got)
        self.assertNotIn("KEYWORDS", got)

    def test_the_last_block_wins(self):
        """A model that restates the template first must not win over its
        real answer."""
        got = _apollo_filters(
            "HANDOFF FOR APOLLO\nTITLES: <job titles here>\n"
            "\nNow my actual answer:\n\n"
            "HANDOFF FOR APOLLO\nTITLES: Procurement Manager\n")
        self.assertEqual(got["TITLES"], ["Procurement Manager"])

    def test_prose_with_no_block_yields_nothing(self):
        """Which is what routes the run to the keyword fallback, rather than
        building a URL out of half-read sentences."""
        self.assertEqual(_apollo_filters("Here are some good leads to try."), {})

    def test_a_runaway_list_is_trimmed(self):
        got = _apollo_filters("HANDOFF FOR APOLLO\nTITLES: "
                              + ", ".join(f"Title {i}" for i in range(40)))
        self.assertLessEqual(len(got["TITLES"]), 8)


class LengthLimit(unittest.TestCase):
    """The actual regression. Truncation is the guarantee behind the prompt's
    request — a prompt can be ignored, this cannot."""

    def test_one_enormous_value_is_capped(self):
        got = _apollo_filters("HANDOFF FOR APOLLO\nTITLES: " + "X" * 500,
                              cap=180)
        self.assertEqual(len(got["TITLES"][0]), 180)

    def test_no_url_value_can_exceed_apollos_limit(self):
        """Feed it the exact shape that broke the live run: the whole
        inter-stage context blob, with a filter block buried in it."""
        blob = ("Context from the previous pipeline stage (RESEARCH) — it "
                "already includes the distilled findings of every stage "
                "before it. Build directly on this brief:\n\n"
                + "long research prose. " * 500
                + "\n\nHANDOFF FOR APOLLO\n"
                + "TITLES: " + "Very Senior Head Of " * 30 + "\n"
                + "INDUSTRIES: " + "manufacturing " * 40 + "\n"
                + "LOCATIONS: Gujarat\nHEADCOUNT: 51-100\n")
        filters = _apollo_filters(blob, cap=180)
        url = _apollo_url("https://app.apollo.io/#/people", filters)
        for value in query_values(url):
            self.assertLess(len(value), APOLLO_LIMIT, f"{value[:60]}… too long")

    def test_the_context_header_never_becomes_a_filter(self):
        """The failing value was the context header itself. It is prose, it
        matches no field name, and it must simply not survive."""
        filters = _apollo_filters(
            "Context from the previous pipeline stage (RESEARCH) — build on "
            "this brief:\n\nHANDOFF FOR APOLLO\nTITLES: CEO\n")
        flat = " ".join(v for values in filters.values() for v in values)
        self.assertNotIn("Context from the previous", flat)


class UrlBuilding(unittest.TestCase):
    def test_verified_emails_are_always_demanded(self):
        """Without it the table fills with rows whose email is locked — which
        is the entire reason to pay for Apollo rather than guess addresses."""
        url = _apollo_url("https://app.apollo.io/#/people",
                          _apollo_filters(CLEAN))
        self.assertIn("contactEmailStatusV2[]=verified", url)

    def test_headcount_labels_become_apollos_range_pairs(self):
        url = _apollo_url("https://app.apollo.io/#/people",
                          {"HEADCOUNT": ["51-100", "10001+"]})
        values = query_values(url)
        self.assertIn("51,100", values)
        self.assertIn("10001,1000000", values)

    def test_every_label_the_prompt_offers_can_be_mapped(self):
        """The handoff spec lists the allowed HEADCOUNT labels. If the two
        lists drift, the filter is silently dropped and searches come back
        unfiltered — so they are checked against each other here."""
        spec = A.AGENT_REGISTRY["Apollo"]["handoff_spec"]
        line = next(ln for ln in spec.splitlines() if ln.startswith("HEADCOUNT:"))
        offered = [w.strip() for w in
                   line.split(":", 1)[1].replace("one or more of", "").split(",")]
        for label in offered:
            self.assertIn(label, _APOLLO_HEADCOUNT,
                          f"the prompt offers {label!r} but no mapping exists")

    def test_an_unknown_headcount_label_is_skipped_not_passed_through(self):
        url = _apollo_url("https://app.apollo.io/#/people",
                          {"HEADCOUNT": ["about fifty people"]})
        self.assertNotIn("about", url)

    def test_industry_keywords_get_the_field_hint_they_need(self):
        """Apollo ignores the keyword filter unless told which company fields
        to match it against."""
        url = _apollo_url("https://app.apollo.io/#/people",
                          {"INDUSTRIES": ["manufacturing"]})
        self.assertIn("includedOrganizationKeywordFields[]=tags", url)

    def test_no_filters_still_produces_a_usable_search_page(self):
        url = _apollo_url("https://app.apollo.io/#/people", {})
        self.assertTrue(url.startswith("https://app.apollo.io/#/people?"))


class RegistryWiring(unittest.TestCase):
    """The runner is only reached if the registry says Apollo is a search
    tool, and the filter block only gets written if the spec is attached.
    Both are one dict key, and both fail silently."""

    def test_apollo_is_marked_as_a_search_tool(self):
        self.assertEqual(A.AGENT_REGISTRY["Apollo"].get("search_tool"), "apollo")

    def test_apollo_carries_a_handoff_spec(self):
        self.assertTrue(A.AGENT_REGISTRY["Apollo"].get("handoff_spec"))

    def test_the_spec_names_every_field_the_parser_reads(self):
        spec = A.AGENT_REGISTRY["Apollo"]["handoff_spec"]
        for field in _APOLLO_FIELDS:
            self.assertIn(f"{field}:", spec)

    def test_the_cap_sits_under_apollos_limit(self):
        self.assertLess(A.AGENT_REGISTRY["Apollo"]["max_query_chars"],
                        APOLLO_LIMIT)

    def test_no_chat_tool_claims_a_handoff_spec(self):
        """A spec on a chat agent would replace its prose handoff with filter
        fields and quietly break that stage."""
        for name, cfg in A.AGENT_REGISTRY.items():
            if cfg.get("handoff_spec"):
                self.assertTrue(cfg.get("search_tool"),
                                f"{name} has a handoff_spec but is not a search tool")



class FiltersAreDecidedBeforeApolloOpens(unittest.TestCase):
    """When Apollo is the FIRST stage there is no previous stage to write the
    filter block — a live run typed a full prose prompt into Apollo's keyword
    box and got nothing. Now Groq writes the block locally first, the stage
    prompt carries it verbatim, and the fallback is a few words, never a
    sentence."""

    def test_the_groq_prompt_demands_the_exact_block(self):
        from core import mailer
        p = mailer.apollo_filter_prompt("email plastics manufacturers in Gujarat")
        self.assertIn("HANDOFF FOR APOLLO", p)
        for field in _APOLLO_FIELDS:
            self.assertIn(f"{field}:", p)
        self.assertIn("nothing else", p)
        self.assertIn("comma-separated", p)

    def test_a_block_carrying_prompt_parses_straight_into_filters(self):
        """The whole point: the research stage's own prompt must parse into
        the same URL filters as the raw block."""
        from core import mailer
        block = CLEAN[CLEAN.index("HANDOFF"):]
        research, _ = mailer.discovery_prompts("goal", "Apollo", block)
        self.assertEqual(_apollo_filters(research), _apollo_filters(block))
        self.assertNotIn("Your ONLY task", research)

    def test_without_a_block_the_old_prompt_survives(self):
        from core import mailer
        research, _ = mailer.discovery_prompts("find agencies", "Apollo")
        self.assertIn("Your ONLY task", research)

    def test_the_discovery_flow_builds_the_block_with_groq(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = open(os.path.join(root, "prism_terminal", "prism.py"),
                   encoding="utf-8").read()
        body = src[src.index("def _discover_recipients("):]
        body = body[:body.index("\ndef ", 10)]
        self.assertIn("apollo_filter_prompt", body)
        self.assertIn("groq_chat", body)

    def test_the_fallback_is_words_not_a_sentence(self):
        from core.automation import _apollo_fallback_query
        q = _apollo_fallback_query(
            "Your ONLY task is to build a prospect list for this request: "
            "email the best plastics manufacturers in Gujarat about Prism.")
        self.assertLessEqual(len(q), 60)
        self.assertLessEqual(len(q.split()), 6)
        self.assertNotIn(":", q)

    def test_the_fallback_survives_an_empty_brief(self):
        from core.automation import _apollo_fallback_query
        self.assertEqual(_apollo_fallback_query(""), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
