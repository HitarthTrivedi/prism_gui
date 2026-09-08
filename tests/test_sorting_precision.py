"""
The bins have to be right in BOTH directions
────────────────────────────────────────────
Sorting mail into inquiry · order · payment · promotion · supplier · internal
is the part of this product that can lose money, and it can lose it two ways:

  **A false negative** — a real inquiry, order or reply filed as noise. The
  customer never hears back. Nobody finds out, because the evidence is a mail
  that looks like it was never sent.

  **A false positive** — marketing, or a supplier's own quotation, filed as a
  customer inquiry. The register fills with sales that do not exist, and a
  register you cannot trust is one nobody opens.

Neither is acceptable, so both are tested here, deliberately adversarially.
The mailshot subjects are real ones taken from the mailbox that produced the
bug reports; the business ones are how Indian manufacturing actually writes.

Anything genuinely ambiguous is expected to come back UNSORTED. That is not a
failure — it is the system saying "a person should look", which is the honest
answer and is surfaced on screen.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "prism_terminal"))

from core import inbox, triage  # noqa: E402


def m(subject="", body="", sender="someone@stranger.example", **kw):
    return inbox.Message(uid=1, from_addr=sender, subject=subject,
                         body=body, **kw)


def sort(subject="", body="", sender="someone@stranger.example",
         know=None, **kw):
    return triage.rules_pass(m(subject, body, sender, **kw), know)


# ── false negatives: business that must never be dropped ─────────────────────

class RealBusinessIsNeverMissed(unittest.TestCase):

    def test_every_way_an_indian_factory_asks_for_a_price(self):
        for subject in (
            "Enquiry for compression springs - request for quotation",
            "Inquiry: SS 304 fasteners",
            "RFQ - 5000 nos mild steel brackets",
            "Request for quotation",
            "Kindly quote your best price",
            "Please quote for the attached drawing",
            "Need your price list for spring steel",
            "Budgetary offer required for tooling",
            "Quote for 200 nos bearings",
        ):
            with self.subTest(subject=subject):
                self.assertEqual(sort(subject).category, triage.INQUIRY, subject)

    def test_the_ask_hidden_in_a_body(self):
        for body in (
            "Dear Sir, kindly quote for the below items at the earliest.",
            "Please quote us your best price for 500 pcs.",
            "We require a quotation for the attached drawing.",
            "Awaiting your quotation. Regards, Purchase Dept",
            "Let us know your price and delivery for the same.",
        ):
            with self.subTest(body=body):
                self.assertEqual(sort("Regarding requirement", body).category,
                                 triage.INQUIRY, body)

    def test_an_order_placed_in_words_not_as_a_file(self):
        """The most valuable message the system can receive. It used to need a
        file called PO-something attached before it counted."""
        for body in (
            "Please treat this as our purchase order for 5000 nos.",
            "We are placing an order for the quoted items.",
            "We hereby place an order as per your quotation dated 12th.",
            "Kindly process the order and confirm dispatch.",
            "We confirm the order. Please proceed with production.",
        ):
            with self.subTest(body=body):
                self.assertEqual(sort("Order", body).category, triage.ORDER, body)

    def test_a_purchase_order_as_an_attachment_still_wins(self):
        msg = m("Our PO", "Attached.", attachments=[
            inbox.Attachment(name="PO-4471.pdf", mime="application/pdf")])
        self.assertEqual(triage.rules_pass(msg).category, triage.ORDER)

    def test_a_known_customer_asking_is_still_an_inquiry(self):
        know = triage.Knowledge(customers={"shaktiauto.in"})
        v = sort("Requirement", "Please send your rate.",
                 sender="purchase@shaktiauto.in", know=know)
        self.assertEqual(v.category, triage.INQUIRY)


class AConversationIsNeverThrownAway(unittest.TestCase):
    """A reply is somebody answering a quotation we sent. It is the most
    valuable mail in the box and the easiest to mistake for nothing."""

    def test_a_reply_is_never_treated_as_a_mailshot(self):
        """Even when the sender's system stamps an unsubscribe link on
        everything it sends, which plenty of real companies do."""
        msg = m("Re: Quotation QTN-26-27-0042", "Yes, please proceed.",
                list_unsubscribe="<https://crm.example/u>",
                in_reply_to="<qtn-42@acme.co.in>")
        self.assertFalse(inbox.says_it_is_bulk(msg),
                         "its body would never have been downloaded")

    def test_references_alone_are_enough(self):
        msg = m("Quotation", "Approved.", list_unsubscribe="<https://x/u>",
                references=["<qtn-42@acme.co.in>"])
        self.assertFalse(inbox.says_it_is_bulk(msg))

    def test_an_out_of_office_is_still_a_robot(self):
        """Automatic mail is a reply too, and must not slip through on that."""
        msg = m("Re: Quotation", "I am on leave until Monday.",
                auto_submitted="auto-replied", in_reply_to="<x@y>")
        self.assertTrue(inbox.says_it_is_bulk(msg))
        self.assertEqual(triage.rules_pass(msg).category, triage.OTHER)


# ── false positives: noise that must never become a sale ─────────────────────

class MarketingNeverBecomesAnInquiry(unittest.TestCase):
    """Subjects taken from the real mailbox that produced the bug report."""

    REAL_MAILSHOTS = [
        ("jobalerts-noreply@linkedin.com", "US-Technical Specialist at Apple"),
        ("alerts@ziprecruiter.com", "Hitarth, Riverside Payments may want to hire you"),
        ("student@internshala.com", "11+ new internships for Information Technology"),
        ("coursera@m.learn.coursera.org", "Coursera Plus now Rs 7,499/year: Save on"),
        ("hello@students.udemy.com", "More skills. More savings."),
        ("nike@official.nike.in", "Race the Night Away"),
        ("connect@hello.thesouledstore.com", "New Fits Inside"),
        ("updates@mail.quillbot.com", "Write. Refine. Save. 40% off Premium"),
        ("alerts@workremot.com", "Data Entry Clerk at Tesla"),
        ("communication@comm.adidas.in", "Come Back to the Original: Samba"),
    ]

    def test_none_of_them_reach_the_register(self):
        for sender, subject in self.REAL_MAILSHOTS:
            with self.subTest(sender=sender):
                v = sort(subject, sender=sender, list_unsubscribe="<https://x/u>")
                self.assertNotIn(v.category, triage.ACTIONABLE, subject)

    def test_marketing_offering_a_quote_is_still_marketing(self):
        self.assertEqual(
            sort("Special offer - get a free quote today").category,
            triage.PROMOTION)

    def test_words_that_are_not_evidence_on_their_own(self):
        """Left out of the stranger rule deliberately. Each of these is a word
        an inquiry uses and so does everything else."""
        for subject in ("Rate your experience with us",
                        "Your offer is waiting",
                        "New requirement in your area",
                        "Order your free sample today"):
            with self.subTest(subject=subject):
                self.assertNotIn(sort(subject).category, triage.ACTIONABLE, subject)

    def test_a_notification_is_not_an_inquiry(self):
        for sender in ("no-reply@render.com", "noreply@skool.com",
                       "notifications@github.com", "mailer-daemon@x.com"):
            with self.subTest(sender=sender):
                self.assertEqual(sort("Something happened", sender=sender).category,
                                 triage.OTHER)


class BulkPlatformsAnnounceThemselves(unittest.TestCase):
    """An unsubscribe link is the famous header, not the only one. In a real
    40-message sample the only mail the rules could not place was Atlassian's
    notifications, which carry List-Help and a Salesforce Marketing Cloud
    Feedback-ID and no unsubscribe header at all — and one of them reached the
    register as a customer inquiry."""

    def test_the_headers_atlassian_actually_sends(self):
        msg = m("New comment on Welcome To Lvlup Ventures Pitch Competitions",
                sender="info@e.atlassian.com",
                list_help="<https://click.e.atlassian.com/subscription_center.aspx>",
                feedback_id="524000040:108057733:136.147.141.72:sfmktgcld")
        self.assertTrue(inbox.says_it_is_bulk(msg))
        self.assertEqual(triage.rules_pass(msg).category, triage.PROMOTION)

    def test_a_mailing_list_id_counts(self):
        msg = m("Weekly digest", sender="digest@list.example",
                list_id="<members.list.example>")
        self.assertEqual(triage.rules_pass(msg).category, triage.PROMOTION)

    def test_each_one_says_which_header_gave_it_away(self):
        for field, expected in (("list_unsubscribe", "unsubscribe"),
                                ("list_id", "mailing list"),
                                ("list_help", "mailing-list"),
                                ("feedback_id", "bulk mailing platform")):
            with self.subTest(field=field):
                msg = m("Hello", **{field: "x"})
                self.assertIn(expected, inbox.bulk_header(msg))
                self.assertIn(expected, triage.rules_pass(msg).reason)

    def test_a_real_person_carries_none_of_them(self):
        self.assertEqual(inbox.bulk_header(m("Enquiry", sender="raj@steel.in")), "")

    def test_a_bulk_platform_cannot_hide_a_real_inquiry(self):
        """The safety net: whatever the headers claim, a subject asking for a
        price is still read in full — see mailflow's worth_reading."""
        subject = "Enquiry for compression springs - request for quotation"
        self.assertTrue(triage.asks_for_a_price(subject.lower(), ""))


class ASupplierQuotingUsIsNotACustomer(unittest.TestCase):
    """The subtlest false positive there is. "Quotation for compression
    springs" is the same subject line whether somebody is asking us for a
    price or sending us one — so the direction has to be read, not just the
    words. Filing a supplier's offer as a customer inquiry puts a sale in the
    register that never existed."""

    def test_a_supplier_sending_their_quotation(self):
        for body in (
            "Please find our quotation for the below items.",
            "We are pleased to quote as follows.",
            "As per your enquiry, our best price is Rs 28.50 per piece.",
            "Thank you for your enquiry. Attached is our quotation.",
            "With reference to your enquiry, we quote as follows.",
            "Our rate list is attached for your kind consideration.",
        ):
            with self.subTest(body=body):
                v = sort("Quotation for compression springs", body)
                self.assertEqual(v.category, triage.VENDOR, body)
                self.assertNotIn(v.category, triage.ACTIONABLE)

    def test_but_asking_still_wins_when_both_appear(self):
        """A real inquiry often quotes the supplier's own mail underneath it.
        If any part of the message is asking, it is an inquiry."""
        v = sort("Re: Quotation",
                 "Thank you for your enquiry earlier. Now please quote for "
                 "5000 nos of the same item.")
        self.assertEqual(v.category, triage.INQUIRY)

    def test_a_known_customer_forwarding_a_suppliers_quote(self):
        know = triage.Knowledge(customers={"shaktiauto.in"})
        v = sort("Quotation", "Please find our quotation attached.",
                 sender="purchase@shaktiauto.in", know=know)
        self.assertNotEqual(v.category, triage.INQUIRY)


# ── the honest middle ────────────────────────────────────────────────────────

class WhatItRefusesToGuess(unittest.TestCase):
    """Saying "I don't know" is a correct answer, and a better one than a
    confident mistake in either direction. These stay unsorted and are shown
    to a person."""

    def test_genuinely_ambiguous_mail_is_left_alone(self):
        for subject, body in (
            ("Regarding our discussion", "As agreed on the call. Regards."),
            ("Documents", "Please see attached."),
            ("Meeting on Thursday", "Confirming 3pm at your office."),
        ):
            with self.subTest(subject=subject):
                self.assertEqual(sort(subject, body).category, triage.UNSORTED)

    def test_a_known_customer_being_vague_is_flagged_not_filed(self):
        know = triage.Knowledge(customers={"shaktiauto.in"})
        v = sort("Hello", "Can we talk tomorrow?",
                 sender="buyer@shaktiauto.in", know=know)
        self.assertEqual(v.category, triage.UNSORTED)
        self.assertIn("customer", v.reason)


class WordsAreMatchedAsWordsNotAsLetters(unittest.TestCase):
    """Every list in triage.py was matched with a plain `in`, and English
    words contain other words. This is not a style point — the first example
    below turned a textbook inquiry into a supplier's offer, which is the
    exact false positive this whole file exists to prevent."""

    def test_your_best_price_is_not_our_best_price(self):
        """"y-our best price" contains "our best price". Asking to be quoted
        was read as quoting."""
        self.assertEqual(sort("Kindly quote your best price").category,
                         triage.INQUIRY)
        self.assertEqual(sort("Need your price list for spring steel").category,
                         triage.INQUIRY)

    def test_a_word_inside_a_longer_word_is_not_a_match(self):
        for text, word in (("corporate", "rate"), ("glimpse", "imps"),
                           ("nutrition", "utr"), ("photography", "po")):
            with self.subTest(text=text):
                self.assertFalse(triage._has(text, (word,)),
                                 f"{word!r} matched inside {text!r}")

    def test_the_real_word_still_matches(self):
        for text, word in (("our rate is high", "rate"),
                           ("paid by imps today", "imps"),
                           ("utr no 12345", "utr")):
            with self.subTest(text=text):
                self.assertTrue(triage._has(text, (word,)))

    def test_a_phrase_split_across_a_line_break_still_matches(self):
        """Real mail wraps. "please\\nquote" is the same phrase."""
        self.assertTrue(triage._has("kindly\nquote the rate", ("kindly quote",)))

    def test_a_customer_writing_about_corporate_policy_is_not_an_inquiry(self):
        know = triage.Knowledge(customers={"shaktiauto.in"})
        v = sort("Corporate policy update",
                 "Please note our corporate address has changed.",
                 sender="admin@shaktiauto.in", know=know)
        self.assertEqual(v.category, triage.UNSORTED)


class EveryVerdictSaysWhy(unittest.TestCase):
    """A sorting nobody can check is a sorting nobody should trust — the
    screen shows this reason beside every row."""

    def test_a_reason_is_always_given_when_a_rule_fired(self):
        for subject, body in (
            ("Enquiry for springs", ""),
            ("Order", "We are placing an order."),
            ("Quotation", "Please find our quotation."),
            ("Special offer", ""),
        ):
            with self.subTest(subject=subject):
                v = sort(subject, body)
                self.assertEqual(v.source, "rule")
                self.assertTrue(v.reason.strip(), f"{subject} gave no reason")

    def test_a_correction_outranks_every_guess(self):
        """The one thing a customer can teach it. It must stick, even against
        a rule that would fire loudly the other way."""
        know = triage.Knowledge(learned={"news@shop.example": triage.INQUIRY})
        v = sort("50% off everything", sender="news@shop.example",
                 list_unsubscribe="<https://x/u>", know=know)
        self.assertEqual(v.category, triage.INQUIRY)
        self.assertEqual(v.source, "learned")


if __name__ == "__main__":
    unittest.main()
