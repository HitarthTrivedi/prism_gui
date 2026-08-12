"""The licence server address a shipped build talks to.

One constant, guarded on its own, because of how it went wrong: a one-line
change to `DEFAULT_SERVER` rode along inside a commit about cold-start
timeouts. Nothing failed. Every test passed. The app built, started, and
self-tested clean — and every customer activation in that build would have
gone to a host the signing keys are not documented against.

That is the shape of failure worth a dedicated test: a single value, changed
by accident, with no symptom until it is in front of a paying customer.

This file used to also forbid a hosting provider's own address, on the grounds
that only a domain lets the licence server move without shipping a new app.
That reasoning has not changed and is still correct. It is suspended anyway,
deliberately, because `api.alphakore.in` has no DNS record at all — and a
build pointed at a domain that does not resolve cannot activate ANY customer,
which is a worse problem than one that is merely hard to move later.

So the ban is gone and a documentation check stands in its place: SHIPPING.md
has to keep saying that the pin is temporary and how to undo it. A rule nobody
can follow gets ignored, and an ignored test is worse than no test; a note in
the release instructions is at least read by the person who could act on it.
"""
from __future__ import annotations

import os
import re
import sys
import unittest
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from licensing import client  # noqa: E402

# The production licence server. Changing this is a deliberate act: change it
# here and in licensing/client.py together, and check SHIPPING.md still agrees.
PRODUCTION_HOST = "prism-license-server.onrender.com"

# The domain this is meant to become, once it has a DNS record. Named here so
# the day somebody points the CNAME, the change is find-and-replace rather
# than archaeology.
INTENDED_HOST = "api.alphakore.in"


def _repo(*parts: str) -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        *parts)


class TheShippedAddress(unittest.TestCase):

    def test_it_is_the_production_host(self):
        self.assertEqual(urlsplit(client.DEFAULT_SERVER).hostname, PRODUCTION_HOST)

    def test_it_is_https(self):
        """A licence token travels over this. Plain HTTP would let anyone on
        the network read it, and anyone in the middle replace it."""
        self.assertEqual(urlsplit(client.DEFAULT_SERVER).scheme, "https")

    def test_no_trailing_slash(self):
        """Endpoints are appended to it; a trailing slash produces //activate,
        which some servers route and some 404 — and it would only show up
        against the real server."""
        self.assertFalse(client.DEFAULT_SERVER.endswith("/"), client.DEFAULT_SERVER)


class TheBuildCanStillRewriteIt(unittest.TestCase):
    """packaging/prism.spec rewrites this line when PRISM_SERVER_URL is set, so
    a test build can point at a laptop. It finds the line by regex — so the
    line has to keep the shape the regex expects, or every staging build dies
    at the packaging step with 'DEFAULT_SERVER not found'."""

    PATTERN = re.compile(r'^DEFAULT_SERVER = ".*"$', re.M)

    def test_the_specs_regex_still_matches_the_line(self):
        with open(_repo("licensing", "client.py"), encoding="utf-8") as f:
            source = f.read()
        self.assertEqual(len(self.PATTERN.findall(source)), 1,
                         "packaging/prism.spec cannot find DEFAULT_SERVER to "
                         "rewrite — staging builds will fail")

    def test_the_spec_still_uses_that_regex(self):
        """Guards the other direction: if the spec's pattern is edited, this
        pairing is how anyone finds out the two must match."""
        with open(_repo("packaging", "prism.spec"), encoding="utf-8") as f:
            spec = f.read()
        self.assertIn(r'^DEFAULT_SERVER = ".*"$', spec)


class TheDocsAgree(unittest.TestCase):
    """SHIPPING.md tells whoever does the release what to put here. If it and
    the code disagree, one of them sends somebody the wrong way at exactly the
    moment they are shipping to a customer."""

    def _shipping(self) -> str:
        path = _repo("SHIPPING.md")
        if not os.path.exists(path):
            self.skipTest("SHIPPING.md not present")
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_shipping_md_names_the_same_host(self):
        self.assertIn(PRODUCTION_HOST, self._shipping())

    def test_the_temporary_pin_is_still_written_down(self):
        """Stands in for the hosting-provider ban this file used to enforce.

        We are pinned to Render on purpose, because the domain does not
        resolve. The cost of that is real and lands later: every build made
        from this source is stuck on Render until somebody rebuilds. The only
        thing stopping that becoming permanent by forgetfulness is the note in
        the release instructions — so the note is what gets tested.

        Fails if SHIPPING.md stops mentioning the domain we are meant to move
        to, which is what would happen if somebody 'tidied up' the section
        after reading that the Render address is the current one.
        """
        text = self._shipping()
        self.assertIn(INTENDED_HOST, text,
                      "SHIPPING.md no longer says which domain the licence "
                      "server is meant to move to. Without it, the Render pin "
                      "becomes permanent because nobody knows it was meant to "
                      "be temporary.")


if __name__ == "__main__":
    unittest.main()
