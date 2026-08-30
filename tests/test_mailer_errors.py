"""explain_error() is the translator between an smtplib failure and the
sentence that actually unblocks a customer — but it only helps anyone if
every call site that catches an smtplib exception actually routes it
through here. workers.SendWorker and VerifyWorker used to emit the bare
exception text instead (a real bug found 2026-08-31 debugging a live send
failure), which meant a plain "timed out" reached friendly.py and read as
"no internet connection" — misleading for what is actually a port-specific
block, not a general connectivity problem.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402  (puts prism_terminal/core on sys.path)
from core import mailer  # noqa: E402


class ExplainingATimeout(unittest.TestCase):
    def test_suggests_the_other_port_not_the_one_that_just_failed(self):
        """Telling someone on 587 to 'try 587' fixes nothing."""
        on_587 = mailer.explain_error("timed out", "me@example.com", 587)
        on_465 = mailer.explain_error("timed out", "me@example.com", 465)
        self.assertIn("465", on_587)
        self.assertNotIn("try port 587", on_587.lower())
        self.assertIn("587", on_465)
        self.assertNotIn("try port 465", on_465.lower())

    def test_names_the_real_cause_not_just_the_symptom(self):
        problem = mailer.explain_error("timed out", "me@example.com", 587)
        self.assertIn("blocking outbound mail", problem)


class ExplainingAnAuthFailure(unittest.TestCase):
    def test_gmail_gets_the_app_password_instructions(self):
        problem = mailer.explain_error(
            "(535, b'5.7.8 Username and Password not accepted')",
            "me@gmail.com")
        self.assertIn("APP PASSWORD", problem)
        self.assertIn("apppasswords", problem)

    def test_an_unknown_provider_still_gets_pointed_at_an_app_password(self):
        problem = mailer.explain_error(
            "(535, b'5.7.8 Username and Password not accepted')",
            "me@some-random-host.example")
        self.assertIn("app password", problem.lower())


class ExplainingDnsFailures(unittest.TestCase):
    def test_getaddrinfo_failure_names_the_real_cause(self):
        problem = mailer.explain_error(
            "[Errno -2] Name or service not known", "me@example.com")
        self.assertIn("resolve", problem.lower())

    def test_temporary_resolution_failure_is_also_recognised(self):
        """A different glibc DNS error string (EAI_AGAIN vs EAI_NONAME) for
        the same class of problem — both must be recognised, not just one."""
        problem = mailer.explain_error(
            "[Errno -3] Temporary failure in name resolution", "me@example.com")
        self.assertIn("resolve", problem.lower())


if __name__ == "__main__":
    unittest.main()
