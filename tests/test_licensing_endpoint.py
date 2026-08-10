"""The licence server address a shipped build talks to.

One constant, guarded on its own, because of how it went wrong: a one-line
change to `DEFAULT_SERVER` rode along inside a commit about cold-start
timeouts. Nothing failed. Every test passed. The app built, started, and
self-tested clean — and every customer activation in that build would have
gone to a host the signing keys are not documented against.

That is the shape of failure worth a dedicated test: a single value, changed
by accident, with no symptom until it is in front of a paying customer.

It also has to stay a DOMAIN rather than a hosting provider's own address. The
domain is the only thing that lets the licence server move — another host,
another region, off a free tier — without shipping a new app to everyone who
already installed one.
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
PRODUCTION_HOST = "api.alphakore.in"

# Hosting providers. A build pinned to one of these cannot be moved off it.
PROVIDER_DOMAINS = ("onrender.com", "railway.app", "herokuapp.com",
                    "vercel.app", "fly.dev", "ngrok.io", "ngrok-free.app",
                    "trycloudflare.com", "amazonaws.com", "azurewebsites.net")


def _repo(*parts: str) -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        *parts)


class TheShippedAddress(unittest.TestCase):

    def test_it_is_the_production_host(self):
        self.assertEqual(urlsplit(client.DEFAULT_SERVER).hostname, PRODUCTION_HOST)

    def test_it_is_not_pinned_to_a_hosting_provider(self):
        host = urlsplit(client.DEFAULT_SERVER).hostname or ""
        for provider in PROVIDER_DOMAINS:
            self.assertFalse(
                host.endswith(provider),
                f"DEFAULT_SERVER is pinned to {provider}. Point the domain at "
                f"the host instead — otherwise this binary can never be moved "
                f"off that provider.")

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

    def test_shipping_md_names_the_same_host(self):
        path = _repo("SHIPPING.md")
        if not os.path.exists(path):
            self.skipTest("SHIPPING.md not present")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn(PRODUCTION_HOST, text)


if __name__ == "__main__":
    unittest.main()
