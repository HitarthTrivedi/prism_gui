"""Finding people on X/Twitter through a search engine (source_x).

X is a walled garden — no Exa, no free API — so the finder goes through a
`site:x.com` web search and parses profiles out of the results. These tests are
network-free: the DDG HTML parser runs on a fixture, and the full
find→rank→draft pipeline runs against a monkey-patched searcher, so the ranking,
dedupe and opener logic is proven without a single request.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prospector import source_x as X  # noqa: E402


# A trimmed but realistic DuckDuckGo html result: every link is uddg-encoded,
# and each result carries both a title anchor and a result__snippet anchor.
_DDG_HTML = """
<div class="result results_links web-result">
 <h2 class="result__title">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fx.com%2Fikpe_kunyi&amp;rut=a">Kunyi (@ikpe_kunyi) on X</a>
 </h2>
 <a class="result__snippet" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fx.com%2Fikpe_kunyi&amp;rut=a">founder roll call — what are you building? indie hackers &amp; AI agents</a>
</div>
<div class="result results_links web-result">
 <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fblog&amp;rut=b">A blog / not a profile</a>
 <a class="result__snippet" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fblog&amp;rut=b">nothing to see</a>
</div>
"""

_ANOMALY = '<html><head><link rel="canonical" href="https://duckduckgo.com/">' \
           '</head><body>anomaly detected, please try again</body></html>'


class ParsingDuckDuckGo(unittest.TestCase):

    def test_it_pulls_the_x_url_and_drops_the_rest(self):
        rows = X._parse_ddg(_DDG_HTML)
        urls = {r["url"] for r in rows}
        self.assertIn("https://x.com/ikpe_kunyi", urls)
        self.assertNotIn("https://example.com/blog", urls)   # non-X dropped

    def test_the_bio_snippet_survives(self):
        rows = X._parse_ddg(_DDG_HTML)
        best = max((r for r in rows if "ikpe_kunyi" in r["url"]),
                   key=lambda r: len(r["snippet"]))
        self.assertIn("what are you building", best["snippet"].lower())

    def test_the_anomaly_page_parses_to_nothing(self):
        self.assertEqual(X._parse_ddg(_ANOMALY), [])


class ProfileFromResult(unittest.TestCase):

    def test_handle_name_and_root_profile(self):
        p = X._profile_from({"url": "https://x.com/ikpe_kunyi",
                             "title": "Kunyi (@ikpe_kunyi) on X", "snippet": "hi"})
        self.assertEqual(p.handle, "ikpe_kunyi")
        self.assertEqual(p.name, "Kunyi")
        self.assertFalse(p.is_post)

    def test_a_status_link_is_flagged_as_a_post(self):
        p = X._profile_from({"url": "https://x.com/somedev/status/123",
                             "title": "Some Dev on X: shipping", "snippet": "x"})
        self.assertEqual(p.handle, "somedev")
        self.assertTrue(p.is_post)

    def test_x_own_routes_are_not_people(self):
        self.assertIsNone(X._profile_from({"url": "https://x.com/search?q=hi",
                                           "title": "Search", "snippet": ""}))


class TheWholePipeline(unittest.TestCase):
    """find() against a fake searcher — no network, real dedupe/rank/draft."""

    CANNED = {
        "q1": [
            {"url": "https://x.com/ikpe_kunyi", "title": "Kunyi (@ikpe_kunyi) on X",
             "snippet": "founder roll call what are you building? indie hackers, "
                        "AI agents and SaaS builders welcome"},
            {"url": "https://x.com/quietdev/status/9", "title": "Quiet Dev on X: shipping",
             "snippet": "building an AI automation tool, solo founder"},
            {"url": "https://example.com/x", "title": "blog", "snippet": "no"},
        ],
        "q2": [
            {"url": "https://x.com/ikpe_kunyi", "title": "Kunyi on X", "snippet": "short"},
            {"url": "https://x.com/quietdev", "title": "Quiet Dev (@quietdev) on X",
             "snippet": "developer building tools"},
        ],
    }

    def setUp(self):
        self._real = X._search
        X._search = lambda q, keys: self.CANNED[q]

    def tearDown(self):
        X._search = self._real

    def _run(self):
        terms = ["founder", "indie", "saas", "ai", "agent", "developer",
                 "build", "automation", "solo", "tool"]
        return X.find(list(self.CANNED), keys={}, terms=terms,
                      offer="Prism, an on-device automation engine", delay=0)

    def test_dedupes_by_handle_and_drops_non_people(self):
        ranked = self._run()
        handles = [p.handle for p in ranked]
        self.assertEqual(sorted(handles), ["ikpe_kunyi", "quietdev"])  # blog gone
        self.assertEqual(len(handles), len(set(handles)))              # no dupes

    def test_the_open_inviter_ranks_first(self):
        ranked = self._run()
        self.assertEqual(ranked[0].handle, "ikpe_kunyi")
        self.assertIn("inviting connection", ranked[0].fit_reason)

    def test_dedupe_keeps_the_richer_bio(self):
        ranked = self._run()
        kunyi = next(p for p in ranked if p.handle == "ikpe_kunyi")
        self.assertIn("roll call", kunyi.bio.lower())        # the long one, not "short"

    def test_every_profile_gets_a_personalised_opener(self):
        for p in self._run():
            self.assertTrue(p.opener)
            self.assertIn("Prism", p.opener)
        ranked = self._run()
        self.assertTrue(ranked[0].opener.startswith("Hey Kunyi"))


if __name__ == "__main__":
    unittest.main()
