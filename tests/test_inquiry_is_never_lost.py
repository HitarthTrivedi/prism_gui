"""
A real inquiry must never be silently dropped
─────────────────────────────────────────────
A friend sent a genuine test inquiry to a real mailbox and it never appeared.
Reading the mailbox directly showed exactly why:

    uid  bulk?  verdict    src    sender / subject
  10257  -      unsorted   none   parthsoni49585@gmail.com
                                  Enquiry for compression springs -
                                  request for quotation

The message was fetched. It was not a mailshot. The local rules simply had no
opinion about it, so it went to the AI — and that day's log says:

    batch 3 failed: Groq is rate-limiting your API key
    batch 4 failed: Groq is rate-limiting your API key
    ── done in 70.3s — 260 fetched, 0 new inquiry(ies), 0 order(s) ──

Two separate holes, both pinned below:

  1. `_INQ_WORDS` was only ever consulted for senders ALREADY in the customer
     list. A stranger asking for a price had no rule at all — which is to say
     the one case the whole feature exists for was the one case with no rule.
  2. When the AI could not be reached, the message stayed "unsorted" — the
     same word used for mail Prism read and found unclear. Indistinguishable
     on screen, in a list of 260.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "prism_terminal"))

from core import inbox, mailflow, triage  # noqa: E402


def _message(subject, body="", sender="parthsoni49585@gmail.com", **kw):
    return inbox.Message(uid=1, from_addr=sender, subject=subject, body=body, **kw)


# ── the message that was lost ────────────────────────────────────────────────

class TheInquiryThatWasMissed(unittest.TestCase):
    """The exact subject line, from the real mailbox."""

    SUBJECT = "Enquiry for compression springs - request for quotation"

    def test_it_is_recognised_without_any_ai(self):
        verdict = triage.rules_pass(_message(self.SUBJECT))
        self.assertEqual(verdict.category, triage.INQUIRY)
        self.assertEqual(verdict.source, "rule",
                         "a first inquiry must not depend on a working API key")

    def test_it_is_actionable_so_it_reaches_the_register(self):
        """Being sorted is not enough — only actionable mail gets a row."""
        self.assertTrue(triage.rules_pass(_message(self.SUBJECT)).actionable)

    def test_it_survives_the_ai_being_unreachable(self):
        """The whole point: no network, no key, no Groq — still found."""
        msg = _message(self.SUBJECT)
        verdicts = triage.classify([msg], api_key="", local_only=True)
        self.assertEqual(verdicts[0].category, triage.INQUIRY)


class AStrangerAskingForAPrice(unittest.TestCase):
    """The rule used to apply only to senders already known. A company's first
    contact with a new customer is, by definition, from a stranger."""

    def test_the_usual_ways_of_asking_are_all_caught(self):
        for subject in (
            "Enquiry for compression springs",
            "Inquiry - stainless fasteners",
            "Request for quotation - 500 pcs",
            "RFQ: mild steel brackets",
            "Please quote for the attached drawing",
            "Kindly quote your best price",
            "Need your price list",
            "Budgetary offer required",
            "Quote for 200 nos bearings",
        ):
            with self.subTest(subject=subject):
                v = triage.rules_pass(_message(subject))
                self.assertEqual(v.category, triage.INQUIRY, subject)

    def test_the_ask_can_be_in_the_body_instead(self):
        v = triage.rules_pass(_message(
            "Regarding our discussion",
            "Hello, further to our call please send us your quotation for "
            "the items listed below."))
        self.assertEqual(v.category, triage.INQUIRY)

    def test_a_known_customer_still_works_as_before(self):
        know = triage.Knowledge(customers={"parthsoni49585@gmail.com"})
        v = triage.rules_pass(_message("Enquiry for springs"), know)
        self.assertEqual(v.category, triage.INQUIRY)


class ItStillDoesNotCallMarketingAnInquiry(unittest.TestCase):
    """Being willing to be wrong about an inquiry is not permission to turn the
    whole inbox into one. These are the real subject lines that were sitting
    beside the missed message in the same mailbox."""

    def test_a_mailshot_is_still_a_promotion(self):
        for sender, subject in (
            ("jobalerts-noreply@linkedin.com", "US-Technical Specialist at Apple"),
            ("coursera@m.learn.coursera.org", "Coursera Plus now Rs 7,499/year: Save on"),
            ("hello@students.udemy.com", "More skills. More savings."),
            ("nike@official.nike.in", "Race the Night Away"),
            ("alerts@workremot.com", "Data Entry Clerk at Tesla"),
        ):
            with self.subTest(sender=sender):
                v = triage.rules_pass(_message(subject, sender=sender,
                                               list_unsubscribe="<https://x>"))
                self.assertNotEqual(v.category, triage.INQUIRY)

    def test_a_special_offer_is_marketing_not_a_request_for_one(self):
        v = triage.rules_pass(_message("Special offer - get a free quote today"))
        self.assertEqual(v.category, triage.PROMOTION,
                         "marketing is tested before the inquiry rule for "
                         "exactly this sentence")

    def test_rate_and_offer_alone_are_not_enough(self):
        """Left out of the stranger rule on purpose: 'Rate your experience'
        and 'Offer ends today' are not somebody asking to be quoted."""
        for subject in ("Rate your experience with us",
                        "Your offer is waiting",
                        "New requirement in your area"):
            with self.subTest(subject=subject):
                self.assertEqual(triage.rules_pass(_message(subject)).category,
                                 triage.UNSORTED, subject)

    def test_an_out_of_office_saying_quotation_is_still_a_robot(self):
        v = triage.rules_pass(_message("Re: quotation", auto_submitted="auto-replied"))
        self.assertEqual(v.category, triage.OTHER)


# ── when the AI cannot be reached ────────────────────────────────────────────

class ABatchThatFailedIsNotABatchThatWasRead(unittest.TestCase):
    """"Prism read this and is unsure" and "Prism never managed to read it"
    were the same word on screen. Only the second means something may have
    been missed."""

    def setUp(self):
        self.msg = _message("Regarding the drawing", "See attached.",
                            sender="someone@unknown.example")

    def _classify_with_failing_ai(self):
        from core import router
        original = router.groq_chat

        def _boom(*a, **k):
            raise RuntimeError("Groq is rate-limiting your API key.")

        router.groq_chat = _boom
        try:
            return triage.classify([self.msg], api_key="k", model="m")
        finally:
            router.groq_chat = original

    def test_the_verdict_says_it_was_never_read(self):
        verdicts = self._classify_with_failing_ai()
        self.assertEqual(verdicts[0].category, triage.UNSORTED)
        self.assertEqual(verdicts[0].source, "failed")
        self.assertIn("couldn't reach", verdicts[0].reason.lower())

    def test_the_check_says_so_out_loud(self):
        result = mailflow.Result(fetched=1, counts={triage.UNSORTED: 1})
        result.sorted_mail = list(zip([self.msg], self._classify_with_failing_ai()))
        self.assertEqual(len(result.unsorted_by_failure), 1)
        self.assertIn("couldn't be sorted", result.headline())

    def test_ordinary_unsorted_mail_is_not_reported_as_a_failure(self):
        """Mail the rules read and found unclear is normal, not an alarm."""
        result = mailflow.Result(fetched=1, counts={triage.UNSORTED: 1})
        result.sorted_mail = [(self.msg, triage.Verdict(triage.UNSORTED, "none"))]
        self.assertEqual(result.unsorted_by_failure, [])
        self.assertNotIn("couldn't be sorted", result.headline())

    def test_a_clean_check_says_nothing_about_it(self):
        result = mailflow.Result(fetched=2, counts={triage.INQUIRY: 2})
        result.sorted_mail = [(self.msg, triage.Verdict(triage.INQUIRY, "rule"))]
        self.assertNotIn("couldn't be sorted", result.headline())


class TheRealInquiryNeverReachesTheAiAtAll(unittest.TestCase):
    """Belt and braces: the message that was lost must now be settled before
    any batch is built, so a rate limit cannot touch it."""

    def test_no_call_is_made_for_it(self):
        from core import router
        calls = []
        original = router.groq_chat

        def _count(*a, **k):
            calls.append(a)
            return ""

        router.groq_chat = _count
        try:
            triage.classify(
                [_message("Enquiry for compression springs - request for quotation")],
                api_key="k", model="m")
        finally:
            router.groq_chat = original
        self.assertEqual(calls, [], "it is settled by rule, so nothing is sent")


if __name__ == "__main__":
    unittest.main()
