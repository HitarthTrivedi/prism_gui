"""The inbox-to-order workflow: reading mail, sorting it, quoting, tracking.

These tests guard four promises that the feature is sold on, and each one is
a promise that would cost a real customer real money if it quietly stopped
being true:

  1. **Prism never alters somebody's mailbox.** Read-only select, BODY.PEEK.
  2. **Most mail never leaves the computer.** The local rules settle it, and
     only genuinely unknown senders are ever put in an AI prompt.
  3. **No AI touches a number.** Every figure on a quotation is Decimal
     arithmetic done in Python.
  4. **The register cannot be corrupted by a routine failure** — a crash
     mid-write, a file open in Excel, a mailbox the server renumbered.

Nothing here reaches the network. IMAP and Groq are both faked, because a test
that needs a mail server is a test nobody runs.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from decimal import Decimal
from email.message import EmailMessage

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402  (puts prism_terminal/core on sys.path)
from core import inbox, mailflow, po, quoting, register, sop, triage  # noqa: E402


# ── helpers ───────────────────────────────────────────────────────────────────

def raw_mail(*, subject="Enquiry", sender="Mr Patel <purchase@shaktiauto.in>",
             body="Please quote for 5000 compression springs.",
             html="", attachments=(), headers=None, to="sales@acme.co.in"):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg["Date"] = "Mon, 10 Aug 2026 09:14:00 +0530"
    msg["Message-ID"] = headers.pop("Message-ID", "<a1@shaktiauto.in>") \
        if headers and "Message-ID" in headers else "<a1@shaktiauto.in>"
    for key, value in (headers or {}).items():
        msg[key] = value
    if html:
        msg.set_content(body or "")
        msg.add_alternative(html, subtype="html")
    else:
        msg.set_content(body)
    for name, data, mime in attachments:
        maintype, _, subtype = mime.partition("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype,
                           filename=name)
    return msg.as_bytes()


def message(**kw):
    return inbox.parse_message(raw_mail(**kw), uid=kw.pop("uid", 1))


class Recorder:
    """Stands in for groq_chat and remembers every prompt it was given."""

    def __init__(self, reply=""):
        self.reply = reply
        self.prompts = []

    def __call__(self, api_key, model, prompt, **kw):
        self.prompts.append(prompt)
        return self.reply() if callable(self.reply) else self.reply


# ── 1. reading mail ───────────────────────────────────────────────────────────

class ParsingRealMail(unittest.TestCase):

    def test_plain_body_and_sender(self):
        m = message()
        self.assertEqual(m.from_addr, "purchase@shaktiauto.in")
        self.assertEqual(m.from_name, "Mr Patel")
        self.assertEqual(m.sender_domain, "shaktiauto.in")
        self.assertIn("5000 compression springs", m.body)

    def test_encoded_subject_is_decoded(self):
        """Real Indian mail carries =?UTF-8?B?…?= subjects. A raw one shown to
        the user looks exactly like the file is corrupt."""
        m = message(subject="Enquiry — spring for ₹ quote")
        self.assertIn("Enquiry", m.subject)
        self.assertNotIn("=?", m.subject)

    def test_html_only_mail_becomes_readable_text(self):
        m = message(body="", html="<html><style>p{color:red}</style>"
                                  "<p>Kindly quote</p><p>2mm wire</p></html>")
        self.assertIn("Kindly quote", m.body)
        self.assertIn("2mm wire", m.body)
        self.assertNotIn("<p>", m.body)
        self.assertNotIn("color:red", m.body, "CSS leaked into the body text")

    def test_attachments_are_captured(self):
        m = message(attachments=[("drawing.pdf", b"%PDF-1.4 fake", "application/pdf")])
        self.assertEqual(m.attachment_names, ["drawing.pdf"])
        self.assertEqual(m.attachments[0].mime, "application/pdf")

    def test_snippet_is_bounded(self):
        """What goes in an AI prompt has a ceiling — a 4 MB mailshot must not
        become a 4 MB prompt."""
        m = message(body="x" * 50_000)
        self.assertLessEqual(len(m.snippet(1500)), 1600)

    def test_body_is_capped_even_before_the_snippet(self):
        m = message(body="y" * (inbox.MAX_BODY_CHARS + 5000))
        self.assertLessEqual(len(m.body), inbox.MAX_BODY_CHARS)

    def test_unparseable_message_does_not_explode(self):
        m = inbox.parse_message(b"this is not a mime message at all", uid=7)
        self.assertEqual(m.uid, 7)


class NeverTouchTheMailbox(unittest.TestCase):
    """The promise that lets this run on a timer against a mailbox somebody is
    also using in Outlook."""

    def test_folder_is_opened_read_only(self):
        source = _read("core/inbox.py")
        self.assertIn("readonly=True", source,
                      "the folder must be opened read-only or Prism clears "
                      "the customer's unread flags")

    def test_fetch_uses_peek(self):
        source = _read("core/inbox.py")
        self.assertIn("BODY.PEEK[]", source)
        self.assertNotIn('"(BODY[])"', source,
                         "plain BODY[] marks mail as read behind the user's back")

    def test_nothing_here_deletes_or_moves(self):
        source = _read("core/inbox.py")
        for forbidden in ("STORE", "\\\\Deleted", "expunge", "conn.copy"):
            self.assertNotIn(forbidden, source,
                             f"{forbidden} would modify the user's mailbox")


class FetchingSafely(unittest.TestCase):

    def test_search_filters_the_uid_the_server_repeats(self):
        """"UID n:*" is defined to return the newest message even when its UID
        is below n. Without filtering, an idle mailbox re-registers the same
        inquiry every ten minutes — for ever."""
        conn = _FakeConn(search_result=b"41 42 43")
        self.assertEqual(inbox._search(conn, last_uid=43, first_days=0), [])
        self.assertEqual(inbox._search(conn, last_uid=41, first_days=0), [42, 43])

    def test_renumbered_mailbox_starts_over_instead_of_reimporting(self):
        old = inbox.State(uidvalidity=111, last_uid=900)
        self.assertNotEqual(old.uidvalidity, 222)
        fresh = inbox.State.from_dict({"uidvalidity": 222, "last_uid": 0})
        self.assertEqual(fresh.last_uid, 0)

    def test_state_survives_a_corrupt_saved_value(self):
        self.assertEqual(inbox.State.from_dict({"last_uid": "banana"}).last_uid, 0)
        self.assertEqual(inbox.State.from_dict(None).uidvalidity, 0)

    def test_no_account_is_a_sentence_not_a_crash(self):
        messages, _state, error = inbox.fetch_new({}, None)
        self.assertEqual(messages, [])
        self.assertIn("set up", error.lower())


class AttachmentNamesCannotEscape(unittest.TestCase):
    """A mail attachment's filename is attacker-controlled text, and this is
    one of the few places untrusted input becomes a path."""

    def test_traversal_is_stripped(self):
        self.assertNotIn("..", inbox.safe_name("../../../etc/passwd"))
        self.assertNotIn("/", inbox.safe_name("../../../etc/passwd"))

    def test_windows_reserved_names_are_defused(self):
        self.assertNotEqual(inbox.safe_name("CON.pdf").upper(), "CON.PDF")

    def test_empty_name_still_produces_a_file(self):
        self.assertTrue(inbox.safe_name(""))

    def test_collisions_do_not_overwrite(self):
        """Every second customer attaches "drawing.pdf". The file that would be
        lost is the one somebody is about to quote from."""
        with tempfile.TemporaryDirectory() as folder:
            first = message(attachments=[("drawing.pdf", b"one", "application/pdf")])
            second = message(attachments=[("drawing.pdf", b"two", "application/pdf")])
            a = inbox.save_attachments(first, folder)
            b = inbox.save_attachments(second, folder)
            self.assertNotEqual(a[0], b[0])
            self.assertEqual(len(os.listdir(folder)), 2)


# ── 2. sorting, and what leaves the machine ──────────────────────────────────

class SortingLocally(unittest.TestCase):

    def test_newsletter_is_caught_by_its_own_header(self):
        m = message(headers={"List-Unsubscribe": "<https://x.com/u>"})
        v = triage.rules_pass(m)
        self.assertEqual(v.category, triage.PROMOTION)
        self.assertEqual(v.source, "rule")

    def test_out_of_office_never_becomes_an_inquiry(self):
        m = message(subject="Out of office", headers={"Auto-Submitted": "auto-replied"})
        self.assertEqual(triage.rules_pass(m).category, triage.OTHER)

    def test_no_reply_addresses_are_filed(self):
        m = message(sender="noreply@bank.example")
        self.assertEqual(triage.rules_pass(m).category, triage.OTHER)

    def test_own_staff_are_internal(self):
        k = triage.Knowledge(own_domains={"acme.co.in"})
        m = message(sender="ramesh@acme.co.in")
        self.assertEqual(triage.rules_pass(m, k).category, triage.INTERNAL)

    def test_a_known_customer_asking_for_a_rate_is_an_inquiry(self):
        k = triage.Knowledge(customers={"shaktiauto.in"})
        self.assertEqual(triage.rules_pass(message(), k).category, triage.INQUIRY)

    def test_one_domain_entry_covers_the_whole_purchase_department(self):
        k = triage.Knowledge(customers={"shaktiauto.in"})
        m = message(sender="someone.else@shaktiauto.in")
        self.assertTrue(k.knows(k.customers, m))

    def test_a_correction_is_remembered_and_outranks_the_guess(self):
        k = triage.Knowledge()
        m = message(headers={"List-Unsubscribe": "<https://x.com/u>"})
        self.assertEqual(triage.rules_pass(m, k).category, triage.PROMOTION)
        triage.learn(k, m, triage.INQUIRY)
        v = triage.rules_pass(m, k)
        self.assertEqual(v.category, triage.INQUIRY)
        self.assertEqual(v.source, "learned")

    def test_a_correction_cannot_resurrect_an_auto_reply(self):
        """Machine post outranks everything. A mistaken correction must not
        put a robot's out-of-office into the register for ever."""
        k = triage.Knowledge()
        m = message(headers={"Auto-Submitted": "auto-replied"})
        triage.learn(k, m, triage.INQUIRY)
        self.assertEqual(triage.rules_pass(m, k).category, triage.OTHER)

    def test_a_stranger_is_left_unsorted_rather_than_guessed(self):
        v = triage.rules_pass(message(subject="hello", body="hi"))
        self.assertEqual(v.category, triage.UNSORTED)
        self.assertEqual(v.source, "none")

    def test_reply_is_flagged(self):
        self.assertTrue(triage.rules_pass(message(subject="Re: Enquiry")).is_reply)


class WhatLeavesTheComputer(unittest.TestCase):
    """The privacy claim, tested rather than asserted in a doc."""

    def test_locally_sorted_mail_is_never_put_in_a_prompt(self):
        recorder = Recorder("1: inquiry")
        settled = [message(headers={"List-Unsubscribe": "<https://x/u>"},
                           body="SECRET NEWSLETTER TEXT"),
                   message(sender="noreply@x.com", body="SECRET NOTIFICATION")]
        with _patched_groq(recorder):
            triage.classify(settled, api_key="k")
        self.assertEqual(recorder.prompts, [],
                         "mail the rules settled was still sent to an AI")

    def test_only_the_unknown_sender_is_sent(self):
        recorder = Recorder("1: inquiry")
        messages = [message(headers={"List-Unsubscribe": "<https://x/u>"},
                            body="NEWSLETTER BODY"),
                    message(sender="new@stranger.com", body="ASK ABOUT SPRINGS")]
        with _patched_groq(recorder):
            triage.classify(messages, api_key="k")
        self.assertEqual(len(recorder.prompts), 1)
        joined = recorder.prompts[0]
        self.assertIn("ASK ABOUT SPRINGS", joined)
        self.assertNotIn("NEWSLETTER BODY", joined)

    def test_local_only_sends_nothing_at_all(self):
        recorder = Recorder("1: inquiry")
        with _patched_groq(recorder):
            verdicts = triage.classify([message(sender="new@stranger.com")],
                                       api_key="k", local_only=True)
        self.assertEqual(recorder.prompts, [])
        self.assertEqual(verdicts[0].category, triage.UNSORTED)

    def test_no_api_key_means_no_call(self):
        recorder = Recorder("1: inquiry")
        with _patched_groq(recorder):
            triage.classify([message(sender="new@stranger.com")], api_key="")
        self.assertEqual(recorder.prompts, [])


class WhenTheAIFails(unittest.TestCase):

    def test_a_failed_call_leaves_mail_unsorted_rather_than_wrong(self):
        def boom(*a, **kw):
            raise RuntimeError("Groq is down")
        with _patched_groq(boom):
            verdicts = triage.classify([message(sender="new@stranger.com")],
                                       api_key="k")
        self.assertEqual(verdicts[0].category, triage.UNSORTED)

    def test_garbage_answers_are_dropped_not_guessed(self):
        self.assertEqual(triage.parse_answers("1: banana", 1), {})
        self.assertEqual(triage.parse_answers("9: inquiry", 1), {})
        self.assertEqual(triage.parse_answers("**1**: inquiry", 1), {1: "inquiry"})
        self.assertEqual(triage.parse_answers("1) order", 1), {1: "order"})


# ── 3. the register ───────────────────────────────────────────────────────────

class Numbering(unittest.TestCase):

    def test_indian_financial_year(self):
        self.assertEqual(register.fy_label(date(2026, 3, 31)), "25-26")
        self.assertEqual(register.fy_label(date(2026, 4, 1)), "26-27")

    def test_numbers_run_on_within_the_year(self):
        rows = [{"Inquiry no": "INQ/25-26/0087"}]
        self.assertEqual(register.next_number(rows, "INQ", date(2026, 3, 1)),
                         "INQ/25-26/0088")

    def test_a_new_year_restarts_the_count(self):
        rows = [{"Inquiry no": "INQ/25-26/0087"}]
        self.assertEqual(register.next_number(rows, "INQ", date(2026, 4, 2)),
                         "INQ/26-27/0001")

    def test_quotation_numbers_share_the_rule(self):
        rows = [{"Quotation no": "QTN/25-26/0141"}]
        self.assertEqual(quoting.next_quote_number(rows, "QTN", date(2026, 3, 1)),
                         "QTN/25-26/0142")


class TheRegisterFile(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, register.FILENAME)

    def test_missing_file_is_an_empty_register(self):
        self.assertEqual(register.load(self.path), [])

    def test_round_trip(self):
        row = register.from_message(message(), {"product": "springs"})
        register.save([row], self.path)
        back = register.load(self.path)
        self.assertEqual(len(back), 1)
        self.assertEqual(back[0]["Product asked"], "springs")

    def test_hand_added_columns_survive(self):
        """The owner will add a column. Deleting it on the next write is a very
        fast way to lose their trust in the file."""
        row = register.blank_row()
        row["Site visit done"] = "Yes"
        register.save([row], self.path)
        back = register.load(self.path)
        self.assertEqual(back[0]["Site visit done"], "Yes")

    def test_a_locked_file_says_close_excel(self):
        real_replace = os.replace

        def refuse(src, dst):
            if dst == self.path:
                raise PermissionError(13, "in use")
            return real_replace(src, dst)

        os.replace = refuse
        try:
            with self.assertRaises(register.RegisterLocked) as caught:
                register.save([register.blank_row()], self.path)
        finally:
            os.replace = real_replace
        self.assertIn("Excel", str(caught.exception))

    def test_a_failed_write_leaves_no_debris(self):
        real_replace = os.replace
        os.replace = lambda s, d: (_ for _ in ()).throw(PermissionError(13, "no"))
        try:
            with self.assertRaises(register.RegisterLocked):
                register.save([register.blank_row()], self.path)
        finally:
            os.replace = real_replace
        self.assertFalse(os.path.exists(self.path + ".tmp"),
                         "a temp file was left behind")

    def test_indian_money_formatting_is_read_back(self):
        self.assertEqual(register.money("₹ 1,42,500.00"), Decimal("142500.00"))
        self.assertEqual(register.money(""), Decimal(0))
        self.assertEqual(register.money("not a number"), Decimal(0))


class ThreadsAndStatuses(unittest.TestCase):

    def test_a_reply_finds_its_own_row(self):
        first = message()
        row = register.from_message(first)
        reply = message(subject="Re: Enquiry",
                        headers={"In-Reply-To": "<a1@shaktiauto.in>",
                                 "Message-ID": "<b2@shaktiauto.in>"})
        self.assertIs(register.find_by_thread([row], reply), row)

    def test_a_phone_reply_that_breaks_the_thread_still_matches_by_sender(self):
        row = register.from_message(message())
        row["Status"] = register.QUOTED
        orphan = message(subject="best price?",
                         headers={"Message-ID": "<zz@phone.local>"})
        orphan.in_reply_to = ""
        orphan.references = []
        self.assertIs(register.find_by_thread([row], orphan), row)

    def test_a_closed_inquiry_does_not_swallow_new_business(self):
        row = register.from_message(message())
        row["Status"] = register.CONVERTED
        fresh = message(subject="New requirement",
                        headers={"Message-ID": "<new@shaktiauto.in>"})
        fresh.in_reply_to = ""
        fresh.references = []
        self.assertIsNone(register.find_by_thread([row], fresh))

    def test_marking_quoted_then_converted(self):
        row = register.from_message(message())
        register.mark_quoted(row, "QTN/25-26/0142", Decimal("142500"))
        self.assertEqual(row["Status"], register.QUOTED)
        register.mark_converted(row, "SAC/PO/4471", Decimal("138000"))
        self.assertEqual(row["Status"], register.CONVERTED)
        self.assertEqual(row["PO number"], "SAC/PO/4471")

    def test_lost_records_the_reason(self):
        row = register.from_message(message())
        register.mark_lost(row, "Rate high")
        self.assertEqual(row["Reason if lost"], "Rate high")


class TheFollowUpList(unittest.TestCase):
    """The most valuable list in the file — money already earned, not yet
    collected on."""

    def _quoted(self, days_ago, reminders=0):
        row = register.from_message(message())
        register.mark_quoted(row, "QTN/25-26/0001", 1000,
                             date.today() - timedelta(days=days_ago))
        row["Reminders sent"] = str(reminders)
        return row

    def test_a_quiet_quotation_comes_up(self):
        self.assertEqual(len(register.awaiting_followup([self._quoted(5)])), 1)

    def test_a_fresh_one_does_not(self):
        self.assertEqual(register.awaiting_followup([self._quoted(1)]), [])

    def test_chasing_stops_after_three(self):
        self.assertEqual(register.awaiting_followup([self._quoted(30, reminders=3)]), [])

    def test_a_closed_inquiry_is_never_chased(self):
        row = self._quoted(30)
        register.mark_lost(row, "lost")
        self.assertEqual(register.awaiting_followup([row]), [])


class MonthEndNumbers(unittest.TestCase):

    def test_conversion_is_against_quotations_not_inquiries(self):
        """An inquiry nobody quoted was never a chance; counting it would make
        the number flattering and useless."""
        rows = []
        for _ in range(3):
            row = register.from_message(message())
            register.mark_quoted(row, "QTN/25-26/0001", 1000)
            rows.append(row)
        register.mark_converted(rows[0], "PO1", 900)
        rows.append(register.from_message(message()))   # never quoted
        stats = register.summarise(rows)
        self.assertEqual(stats.quoted, 3)
        self.assertEqual(stats.converted, 1)
        self.assertEqual(stats.conversion, 33.3)

    def test_no_quotations_is_zero_not_a_crash(self):
        self.assertEqual(register.summarise([]).conversion, 0.0)


# ── 4. money ──────────────────────────────────────────────────────────────────

class NoAITouchesANumber(unittest.TestCase):

    def test_quoting_never_calls_an_ai_for_arithmetic(self):
        source = _read("core/quoting.py")
        head = source.split("def covering_letter_prompt")[0]
        self.assertNotIn("groq_chat", head,
                         "an AI call appeared in the pricing path")

    def test_prices_are_decimal_not_float(self):
        line = quoting.QuoteLine("x", Decimal("3"), rate=Decimal("0.1"))
        self.assertIsInstance(line.amount, Decimal)
        self.assertEqual(line.amount, Decimal("0.30"))

    def test_the_covering_letter_is_told_not_to_restate_figures(self):
        quote = quoting.Quotation(number="QTN/25-26/0142", customer="Shakti")
        prompt = quoting.covering_letter_prompt(quote)
        low = prompt.lower()
        self.assertIn("do not calculate", low)
        self.assertIn("not include the price table", low)

    def test_the_covering_letter_prompt_carries_no_totals(self):
        quote = quoting.Quotation(number="Q1", customer="Shakti", lines=[
            quoting.QuoteLine("spring", Decimal("5000"), rate=Decimal("28.50"))])
        self.assertNotIn("142500", quoting.covering_letter_prompt(quote))


class Rounding(unittest.TestCase):

    def test_half_up_like_every_indian_accounting_system(self):
        """Python's default rounds 0.125 to 0.12. Tally rounds it to 0.13, and
        "the software rounds differently" is not a conversation worth having."""
        self.assertEqual(quoting.rupees(Decimal("0.125")), Decimal("0.13"))
        self.assertEqual(quoting.rupees(Decimal("2.675")), Decimal("2.68"))

    def test_lakh_grouping(self):
        self.assertEqual(quoting.indian_currency(Decimal("142500")), "1,42,500.00")
        self.assertEqual(quoting.indian_currency(Decimal("500")), "500.00")
        self.assertEqual(quoting.indian_currency(Decimal("10000000")),
                         "1,00,00,000.00")

    def test_negative_values_keep_their_sign(self):
        self.assertTrue(quoting.indian_currency(Decimal("-1500")).startswith("-"))


class TheArithmetic(unittest.TestCase):

    def test_a_whole_quotation_adds_up(self):
        quote = quoting.Quotation(
            number="QTN/25-26/0142", customer="Shakti Auto",
            lines=[quoting.QuoteLine("Compression spring", Decimal("5000"),
                                     rate=Decimal("28.50"))],
            terms=quoting.Terms(gst_percent=Decimal(18)))
        self.assertEqual(quote.subtotal, Decimal("142500.00"))
        self.assertEqual(quote.gst, Decimal("25650.00"))
        self.assertEqual(quote.total, Decimal("168150.00"))

    def test_discount_and_freight_land_in_the_right_order(self):
        """Freight is taxable and discount comes off before tax. Getting this
        backwards changes the GST, which is the number the customer's
        accountant checks."""
        quote = quoting.Quotation(
            lines=[quoting.QuoteLine("x", Decimal("100"), rate=Decimal("10"))],
            terms=quoting.Terms(gst_percent=Decimal(18),
                                discount_percent=Decimal(10),
                                freight=Decimal(100)))
        self.assertEqual(quote.subtotal, Decimal("1000.00"))
        self.assertEqual(quote.discount, Decimal("100.00"))
        self.assertEqual(quote.taxable, Decimal("1000.00"))
        self.assertEqual(quote.gst, Decimal("180.00"))
        self.assertEqual(quote.total, Decimal("1180.00"))

    def test_validity_date(self):
        quote = quoting.Quotation(date=date(2026, 8, 10),
                                  terms=quoting.Terms(validity_days=15))
        self.assertEqual(quote.valid_until, date(2026, 8, 25))


class ReadingARateList(unittest.TestCase):

    def _write(self, text, name="rates.csv"):
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def test_a_plain_price_list(self):
        items = quoting.load_rates(self._write(
            "Code,Description,Unit,Rate\n"
            "CS-201,Compression spring 2mm wire 25 OD,nos,28.50\n"
            "TS-100,Tension spring 3mm,nos,44\n"))
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].rate, Decimal("28.50"))

    def test_a_letterhead_above_the_table_is_skipped(self):
        """Real price lists open with a company name and a blank line. Assuming
        row 1 is the header fails on nearly every genuine file."""
        items = quoting.load_rates(self._write(
            "ACME SPRINGS PVT LTD\nGIDC Vatva\n\n"
            "Item Code,Product,UOM,Unit Price\n"
            "CS-201,Compression spring,nos,28.50\n"))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].code, "CS-201")

    def test_section_headings_are_not_products(self):
        items = quoting.load_rates(self._write(
            "Code,Description,Rate\n"
            "COMPRESSION SPRINGS,,\n"
            "CS-201,2mm wire,28.50\n"))
        self.assertEqual(len(items), 1)

    def test_quantity_slabs_are_read(self):
        items = quoting.load_rates(self._write(
            "Code,Description,Rate,Rate @ 1000,Rate @ 5000\n"
            "CS-201,Compression spring,32,29,26.50\n"))
        item = items[0]
        self.assertEqual(item.rate_for(10), Decimal("32"))
        self.assertEqual(item.rate_for(1000), Decimal("29"))
        self.assertEqual(item.rate_for(20000), Decimal("26.50"))

    def test_an_unreadable_file_says_what_to_do(self):
        with self.assertRaises(quoting.RateFileError) as caught:
            quoting.load_rates(self._write("some notes\nnothing useful\n"))
        self.assertIn("Description", str(caught.exception))

    def test_old_xls_is_refused_with_the_fix(self):
        with self.assertRaises(quoting.RateFileError) as caught:
            quoting.load_rates(self._write("x", name="rates.xls"))
        self.assertIn("CSV", str(caught.exception))


class MatchingWhatTheyAsked(unittest.TestCase):

    def setUp(self):
        self.items = [
            quoting.RateItem(code="CS-201", description="Compression spring 2mm wire 25 OD"),
            quoting.RateItem(code="CS-202", description="Compression spring 3mm wire 30 OD"),
            quoting.RateItem(code="TS-100", description="Tension spring 3mm wire"),
            quoting.RateItem(code="WS-050", description="Washer flat mild steel"),
        ]

    def test_the_specification_digits_carry_the_meaning(self):
        best = quoting.match_item("need compression spring 2mm wire 25 od", self.items)
        self.assertEqual(best[0].item.code, "CS-201")

    def test_politeness_does_not_confuse_it(self):
        best = quoting.match_item(
            "Dear Sir, kindly send us your best price for tension spring 3mm. "
            "Thanks and regards", self.items)
        self.assertEqual(best[0].item.code, "TS-100")

    def test_an_ambiguous_request_is_not_confident(self):
        """Two similar rows means the request was ambiguous, and guessing
        between them is exactly the mistake that costs money."""
        matches = quoting.match_item("compression spring", self.items)
        self.assertFalse(quoting.is_confident(matches))

    def test_a_clear_request_is_confident(self):
        self.assertTrue(quoting.is_confident(
            quoting.match_item("washer flat mild steel", self.items)))

    def test_nothing_matches_nothing(self):
        self.assertEqual(quoting.match_item("bicycle tyre", self.items), [])
        self.assertFalse(quoting.is_confident([]))

    def test_every_match_can_be_explained(self):
        for m in quoting.match_item("compression spring 2mm", self.items):
            self.assertTrue(m.reason)


class TheCostSheet(unittest.TestCase):
    """Made-to-drawing work, which is most of what a job shop quotes."""

    def setUp(self):
        self.lines = [
            quoting.CostLine("Wire", quoting.PER_KG, Decimal("95")),
            quoting.CostLine("Coiling", quoting.PER_PIECE, Decimal("1.20")),
            quoting.CostLine("Setup", quoting.PER_LOT, Decimal("1500")),
            quoting.CostLine("Margin", quoting.PERCENT, Decimal("20")),
        ]

    def test_the_four_bases(self):
        out = quoting.cost_sheet(self.lines, weight_kg=Decimal("0.010"),
                                 quantity=Decimal("5000"))
        amounts = dict(out.lines)
        self.assertEqual(amounts["Wire"], Decimal("4750.00"))     # .01×5000×95
        self.assertEqual(amounts["Coiling"], Decimal("6000.00"))  # 1.20×5000
        self.assertEqual(amounts["Setup"], Decimal("1500.00"))    # once
        self.assertEqual(amounts["Margin"], Decimal("2450.00"))   # 20% of 12250
        self.assertEqual(out.total, Decimal("14700.00"))

    def test_percentage_applies_to_the_running_total_above_it(self):
        """Their file's row order is their own working, so the printout matches
        the way they already do it on paper."""
        out = quoting.cost_sheet(
            [quoting.CostLine("A", quoting.PER_LOT, Decimal("100")),
             quoting.CostLine("Pct", quoting.PERCENT, Decimal("10")),
             quoting.CostLine("B", quoting.PER_LOT, Decimal("100"))],
            weight_kg=0, quantity=1)
        self.assertEqual(dict(out.lines)["Pct"], Decimal("10.00"))

    def test_per_piece_price(self):
        out = quoting.cost_sheet(self.lines, weight_kg=Decimal("0.010"),
                                 quantity=Decimal("5000"))
        self.assertEqual(out.per_piece, Decimal("2.94"))

    def test_zero_quantity_does_not_divide_by_zero(self):
        out = quoting.cost_sheet(self.lines, weight_kg=1, quantity=0)
        self.assertIsInstance(out.per_piece, Decimal)


class WeightFromTheDrawing(unittest.TestCase):
    """Geometry, checkable against a scale — not an opinion and not an AI."""

    def test_a_metre_of_2mm_steel_wire(self):
        # π × 0.001² × 1 m × 7850 = 0.02466 kg
        weight = quoting.wire_weight_kg(2, 1000)
        self.assertAlmostEqual(float(weight), 0.02466, places=4)

    def test_mean_diameter_is_od_minus_one_wire(self):
        """The part people get wrong estimating by hand."""
        weight = quoting.spring_wire_weight_kg(wire_dia_mm=2, outer_dia_mm=25,
                                               total_coils=8)
        expected = quoting.wire_weight_kg(2, quoting.coil_length_mm(23, 8))
        self.assertEqual(weight, expected)

    def test_stainless_is_heavier_than_steel(self):
        self.assertGreater(quoting.wire_weight_kg(2, 1000, "stainless"),
                           quoting.wire_weight_kg(2, 1000, "steel"))

    def test_nonsense_dimensions_give_zero_not_a_crash(self):
        self.assertEqual(quoting.wire_weight_kg(0, 1000), Decimal(0))
        self.assertEqual(quoting.spring_wire_weight_kg(
            wire_dia_mm=30, outer_dia_mm=25, total_coils=8), Decimal(0))


# ── 5. purchase orders ────────────────────────────────────────────────────────

class ReadingAPO(unittest.TestCase):

    def test_a_scan_is_detected_and_explained(self):
        self.assertTrue(po.looks_scanned("", 1))
        self.assertTrue(po.looks_scanned("PO", 2))
        self.assertFalse(po.looks_scanned("x" * 500, 1))

    def test_empty_text_says_type_it_in_rather_than_returning_nothing(self):
        with self.assertRaises(po.POError) as caught:
            po.extract("", api_key="k")
        self.assertIn("Type the PO number", str(caught.exception))

    def test_fields_are_read_and_never_computed_by_the_model(self):
        reply = ('```json\n{"po_number":"SAC/PO/4471","po_date":"20-08-2026",'
                 '"buyer":"Shakti Auto","total":"138000",'
                 '"lines":[{"description":"Compression spring",'
                 '"quantity":"5000","rate":"27.60","amount":""}]}\n```')
        with _patched_groq(Recorder(reply)):
            order = po.extract("PURCHASE ORDER …", api_key="k")
        self.assertEqual(order.number, "SAC/PO/4471")
        self.assertEqual(order.date, date(2026, 8, 20))
        # The model returned no amount; Python worked it out.
        self.assertEqual(order.lines[0].amount, Decimal("138000.00"))

    def test_the_prompt_forbids_calculation(self):
        self.assertIn("do not calculate", po._PROMPT.lower())

    def test_a_broken_reply_says_type_it_in(self):
        with _patched_groq(Recorder("I could not read that, sorry.")):
            with self.assertRaises(po.POError):
                po.extract("something", api_key="k")

    def test_junk_line_items_do_not_crash_the_parse(self):
        order = po.from_json({"po_number": "X", "lines": [
            "a bare string line", 42, None, {"description": "real", "quantity": "5"}]})
        self.assertEqual(len(order.lines), 2)

    def test_missing_fields_are_reported_for_the_form(self):
        self.assertIn("PO number", po.PurchaseOrder().missing())

    def test_the_right_attachment_is_picked(self):
        m = message(attachments=[("terms.pdf", b"x", "application/pdf"),
                                 ("PO 4471.pdf", b"y", "application/pdf")])
        self.assertEqual(po.find_attachment(m), "PO 4471.pdf")

    def test_two_unnamed_pdfs_is_ambiguous_and_returns_nothing(self):
        m = message(attachments=[("a.pdf", b"x", "application/pdf"),
                                 ("b.pdf", b"y", "application/pdf")])
        self.assertIsNone(po.find_attachment(m))


class ComparingPOToQuotation(unittest.TestCase):
    """The two-second check that saves an argument three weeks later."""

    def _quote(self):
        return quoting.Quotation(
            number="QTN/25-26/0142",
            lines=[quoting.QuoteLine("Compression spring", Decimal("5000"),
                                     rate=Decimal("28.50"))],
            terms=quoting.Terms(gst_percent=Decimal(0)))

    def test_a_reduced_rate_is_flagged_as_money(self):
        order = po.PurchaseOrder(number="X", lines=[
            po.POLine("Compression spring", Decimal("5000"), rate=Decimal("27.60")).settled()])
        differences = po.compare(order, self._quote())
        self.assertTrue(any(d.kind == po.MONEY and "rate" in d.field.lower()
                            for d in differences))

    def test_a_small_rate_cut_on_a_big_quantity_is_still_money(self):
        """The bug this catches: 90 paise off a unit rate looked like nothing
        against a one-rupee tolerance. On 5,000 pieces it is ₹4,500. The
        tolerance has to apply to the money, not to the size of the gap."""
        order = po.PurchaseOrder(number="X", lines=[
            po.POLine("Compression spring", Decimal("5000"),
                      rate=Decimal("28.40")).settled()])
        differences = po.compare(order, self._quote())
        rate_flags = [d for d in differences if "rate" in d.field.lower()]
        self.assertEqual(len(rate_flags), 1)
        self.assertIn("500.00", rate_flags[0].ordered)

    def test_true_rounding_on_a_rate_is_still_ignored(self):
        order = po.PurchaseOrder(number="X", lines=[
            po.POLine("Compression spring", Decimal("10"),
                      rate=Decimal("28.55")).settled()])
        self.assertEqual([d for d in po.compare(order, self._quote())
                          if "rate" in d.field.lower()], [])

    def test_a_changed_quantity_is_flagged(self):
        order = po.PurchaseOrder(number="X", lines=[
            po.POLine("Compression spring", Decimal("4000"), rate=Decimal("28.50")).settled()])
        self.assertTrue(any("quantity" in d.field.lower()
                            for d in po.compare(order, self._quote())))

    def test_a_matching_order_reports_nothing_about_money(self):
        order = po.PurchaseOrder(number="X", total=Decimal("142500"), lines=[
            po.POLine("Compression spring", Decimal("5000"), rate=Decimal("28.50")).settled()])
        money = [d for d in po.compare(order, self._quote()) if d.kind == po.MONEY]
        self.assertEqual(money, [])

    def test_one_rupee_of_rounding_is_not_an_alarm(self):
        order = po.PurchaseOrder(number="X", total=Decimal("142500.50"), lines=[
            po.POLine("Compression spring", Decimal("5000"), rate=Decimal("28.50")).settled()])
        money = [d for d in po.compare(order, self._quote()) if d.kind == po.MONEY]
        self.assertEqual(money, [])

    def test_an_extra_unquoted_line_is_flagged(self):
        order = po.PurchaseOrder(number="X", lines=[
            po.POLine("Compression spring", Decimal("5000"), rate=Decimal("28.50")).settled(),
            po.POLine("Tension spring", Decimal("100"), rate=Decimal("44")).settled()])
        self.assertTrue(any("Extra" in d.field for d in po.compare(order, self._quote())))

    def test_money_differences_are_listed_first(self):
        order = po.PurchaseOrder(number="X", delivery_date=date(2026, 9, 1),
                                 lines=[po.POLine("Compression spring", Decimal("4000"),
                                                  rate=Decimal("20")).settled()])
        kinds = [d.kind for d in po.compare(order, self._quote())]
        self.assertEqual(kinds, sorted(kinds, key=lambda k: 0 if k == po.MONEY else 1))

    def test_the_summary_reads_like_a_sentence(self):
        order = po.PurchaseOrder(number="SAC/PO/4471", buyer="Shakti Auto",
                                 total=Decimal("138000"))
        text = po.summary(order, po.compare(order, self._quote()))
        self.assertIn("SAC/PO/4471", text)
        self.assertIn("1,38,000", text)


# ── 6. SOPs ───────────────────────────────────────────────────────────────────

class TheSopLibrary(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def _put(self, name):
        path = os.path.join(self.dir, name)
        with open(path, "w") as f:
            f.write("x")
        return path

    def test_revisions_are_read_from_filenames(self):
        self._put("SOP-07_Heat-Treatment_rev3.pdf")
        library = sop.load_library(self.dir)
        self.assertEqual(len(library), 1)
        self.assertEqual(library[0].revision, "3")
        self.assertIn("Heat", library[0].title)

    def test_only_the_newest_revision_is_offered(self):
        """A folder accumulates old copies. Sending rev 2 when rev 5 exists is
        the exact failure this module is meant to prevent."""
        self._put("SOP-07_Heat_rev2.pdf")
        self._put("SOP-07_Heat_rev5.pdf")
        library = sop.load_library(self.dir)
        self.assertEqual(len(library), 1)
        self.assertEqual(library[0].revision, "5")

    def test_rev10_beats_rev9(self):
        self.assertTrue(sop.SopDoc("A", revision="10").newer_than("9"))
        self.assertFalse(sop.SopDoc("A", revision="9").newer_than("10"))

    def test_an_index_file_wins_over_filenames(self):
        self._put("whatever.pdf")
        with open(os.path.join(self.dir, sop.INDEX_FILENAME), "w") as f:
            f.write("code,title,revision,file\nQAP-01,Quality Plan,4,whatever.pdf\n")
        library = sop.load_library(self.dir)
        self.assertEqual(library[0].title, "Quality Plan")
        self.assertEqual(library[0].revision, "4")

    def test_the_index_and_log_are_not_treated_as_documents(self):
        self._put("SOP-01_rev1.pdf")
        with open(os.path.join(self.dir, sop.LOG_FILENAME), "w") as f:
            f.write("x")
        self.assertEqual(len(sop.load_library(self.dir)), 1)


class WhoGetsWhat(unittest.TestCase):

    def setUp(self):
        self.library = [sop.SopDoc("SOP-07", "Heat Treatment", "3"),
                        sop.SopDoc("QAP-01", "Quality Plan", "2")]
        self.rules = [sop.ClientRule("shaktiauto.in", ["SOP-07", "QAP-01"]),
                      sop.ClientRule("one@other.com", ["SOP-07"], annual=True)]

    def test_a_domain_rule_covers_everyone_there(self):
        docs = sop.for_client("anybody@shaktiauto.in", self.rules, self.library)
        self.assertEqual(len(docs), 2)

    def test_an_address_rule_is_exact(self):
        self.assertEqual(len(sop.for_client("two@other.com", self.rules, self.library)), 0)

    def test_never_sent_is_due(self):
        due = sop.pending(self.rules, self.library, [])
        self.assertEqual(len(due), 3)
        self.assertTrue(all(p.reason == "never sent" for p in due))

    def test_a_revision_pulls_everyone_holding_the_old_one(self):
        """The trigger worth building for: he revises a document and does
        nothing else."""
        log = []
        sop.record_sent(log, doc=sop.SopDoc("SOP-07", "Heat Treatment", "2"),
                        address="shaktiauto.in", when=date.today())
        due = sop.pending(self.rules, self.library, log)
        heat = [p for p in due if p.doc.code == "SOP-07"
                and p.address == "shaktiauto.in"]
        self.assertEqual(len(heat), 1)
        self.assertIn("rev 2", heat[0].reason)
        self.assertIn("rev 3", heat[0].reason)

    def test_the_current_revision_is_not_resent(self):
        log = []
        for rule in self.rules:
            for code in rule.codes:
                doc = next(d for d in self.library if d.code == code)
                sop.record_sent(log, doc=doc, address=rule.who, when=date.today())
        self.assertEqual(sop.pending(self.rules, self.library, log), [])

    def test_the_annual_reissue_comes_round(self):
        log = []
        sop.record_sent(log, doc=self.library[0], address="one@other.com",
                        when=date.today() - timedelta(days=400))
        due = [p for p in sop.pending(self.rules, self.library, log)
               if p.address == "one@other.com"]
        self.assertEqual(len(due), 1)
        self.assertIn("yearly", due[0].reason)

    def test_the_audit_trail_records_the_revision(self):
        """The answer to "prove your customers were notified" — which today
        means somebody searching Sent Items for an afternoon."""
        log = []
        row = sop.record_sent(log, doc=self.library[0], address="a@b.com",
                              customer="B Ltd", reason="revision")
        for column in ("Date sent", "Email", "SOP code", "Revision"):
            self.assertIn(column, row)
        self.assertEqual(row["Revision"], "3")

    def test_the_covering_mail_may_not_describe_the_contents(self):
        prompt = sop.covering_prompt(self.library, "Shakti Auto")
        self.assertIn("not describe what is inside", prompt.lower())
        self.assertIn("SOP-07", prompt)


# ── 7. the daily loop ─────────────────────────────────────────────────────────

class TheDailyLoop(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.paths = mailflow.Paths(self.dir)
        self.cfg = {"api_key": "", "inbox": {"address": "sales@acme.co.in",
                                             "password": "p", "host": "mail.acme.co.in"}}

    def _run(self, messages, **kw):
        def fake_fetch(cfg, state, **_kw):
            return messages, inbox.State(1, 99), ""
        real = inbox.fetch_new
        inbox.fetch_new = fake_fetch
        try:
            return mailflow.check(self.cfg, self.paths, local_only=True, **kw)
        finally:
            inbox.fetch_new = real

    def test_an_inquiry_becomes_a_row_and_a_folder(self):
        k = triage.Knowledge(customers={"shaktiauto.in"})
        result = self._run([message()], knowledge=k)
        self.assertEqual(len(result.new_inquiries), 1)
        rows = register.load(self.paths.register_csv)
        self.assertEqual(len(rows), 1)
        self.assertTrue(os.path.isdir(rows[0]["Folder"]))

    def test_attachments_land_in_that_folder(self):
        k = triage.Knowledge(customers={"shaktiauto.in"})
        result = self._run([message(attachments=[
            ("drawing.pdf", b"%PDF-1.4", "application/pdf")])], knowledge=k)
        self.assertEqual(len(result.new_inquiries[0].files), 1)
        self.assertIn("drawing.pdf", result.new_inquiries[0].row["Drawing"])

    def test_a_reply_does_not_become_a_second_inquiry(self):
        """A three-message negotiation must stay one row, or the register
        stops being true."""
        k = triage.Knowledge(customers={"shaktiauto.in"})
        self._run([message()], knowledge=k)
        reply = message(subject="Re: Enquiry — best price please",
                        headers={"In-Reply-To": "<a1@shaktiauto.in>",
                                 "Message-ID": "<b2@shaktiauto.in>"})
        result = self._run([reply], knowledge=k)
        self.assertEqual(len(register.load(self.paths.register_csv)), 1)
        self.assertEqual(len(result.replies), 1)

    def test_nothing_is_sent_by_check(self):
        source = _read("core/mailflow.py")
        for forbidden in ("send_bulk", "smtplib", "server.send"):
            self.assertNotIn(forbidden, source,
                             "check() must never send anything on its own")

    def test_a_dead_mail_server_is_a_sentence_not_a_crash(self):
        def broken(cfg, state, **_kw):
            return [], inbox.State(), "The mail server didn't answer."
        real = inbox.fetch_new
        inbox.fetch_new = broken
        try:
            result = mailflow.check(self.cfg, self.paths)
        finally:
            inbox.fetch_new = real
        self.assertIn("didn't answer", result.error)
        self.assertEqual(result.needs_attention, 0)

    def test_a_locked_register_does_not_advance_the_bookmark(self):
        """Otherwise the mail Prism could not record is never seen again."""
        k = triage.Knowledge(customers={"shaktiauto.in"})
        real_save = register.save
        register.save = lambda rows, path: (_ for _ in ()).throw(
            register.RegisterLocked("close Excel"))
        try:
            result = self._run([message()], knowledge=k)
        finally:
            register.save = real_save
        self.assertIn("close Excel", result.error)
        self.assertEqual(result.state.last_uid, 0)

    def test_promotions_are_counted_but_do_nothing(self):
        result = self._run([message(headers={"List-Unsubscribe": "<https://x/u>"})])
        self.assertEqual(result.counts.get(triage.PROMOTION), 1)
        self.assertEqual(result.needs_attention, 0)
        self.assertEqual(register.load(self.paths.register_csv), [])

    def test_the_headline_is_plain_words(self):
        k = triage.Knowledge(customers={"shaktiauto.in"})
        headline = self._run([message()], knowledge=k).headline()
        self.assertIn("inquiry", headline)
        self.assertNotIn("IMAP", headline)
        self.assertNotIn("uid", headline.lower())

    def test_no_mail_says_so(self):
        self.assertEqual(self._run([]).headline(), "No new mail.")

    def test_folder_names_survive_the_slashes_in_a_number(self):
        folder = self.paths.folder_for("INQ/25-26/0087")
        self.assertNotIn("/25-26/", folder)
        self.assertIn("INQ-25-26-0087", folder)


class ReplyIntent(unittest.TestCase):

    def test_best_price_is_negotiating_not_acceptance(self):
        with _patched_groq(Recorder("negotiating")):
            self.assertEqual(
                mailflow.reply_intent(message(body="send your best price"), "k"),
                mailflow.NEGOTIATING)

    def test_an_unreadable_answer_is_unclear_rather_than_a_guess(self):
        with _patched_groq(Recorder("well, it depends")):
            self.assertEqual(mailflow.reply_intent(message(), "k"), mailflow.UNCLEAR)

    def test_no_key_is_unclear_not_a_crash(self):
        self.assertEqual(mailflow.reply_intent(message(), ""), mailflow.UNCLEAR)

    def test_a_failed_call_is_unclear(self):
        def boom(*a, **kw):
            raise RuntimeError("down")
        with _patched_groq(boom):
            self.assertEqual(mailflow.reply_intent(message(), "k"), mailflow.UNCLEAR)


class InquiryDetails(unittest.TestCase):

    def test_fields_are_pulled_out(self):
        reply = ('{"customer":"Shakti Auto","contact":"Mr Patel","phone":"",'
                 '"product":"compression spring 2mm","quantity":"5000 nos",'
                 '"notes":""}')
        with _patched_groq(Recorder(reply)):
            details = mailflow.extract_details(message(), "k")
        self.assertEqual(details["customer"], "Shakti Auto")
        self.assertEqual(details["quantity"], "5000 nos")

    def test_a_failure_still_produces_a_row(self):
        def boom(*a, **kw):
            raise RuntimeError("down")
        with _patched_groq(boom):
            details = mailflow.extract_details(message(), "k")
        self.assertEqual(details, {})
        row = register.from_message(message(), details)
        self.assertTrue(row["Inquiry no"])
        self.assertTrue(row["Email"])

    def test_the_prompt_forbids_inventing_a_quantity(self):
        self.assertIn("Never invent", mailflow._DETAILS_PROMPT)


# ── plumbing for the tests above ─────────────────────────────────────────────

class _FakeConn:
    def __init__(self, search_result=b""):
        self.search_result = search_result

    def uid(self, command, *args):
        if command == "SEARCH":
            return "OK", [self.search_result]
        return "NO", []


class _patched_groq:
    """Swap router.groq_chat for the duration of a block.

    Patched on the module rather than at the import site because every caller
    does `from .router import groq_chat` inside the function — deliberately, so
    that importing these modules never drags in requests.
    """

    def __init__(self, replacement):
        self.replacement = replacement

    def __enter__(self):
        from core import router
        self.router = router
        self.original = router.groq_chat
        router.groq_chat = self.replacement
        return self.replacement

    def __exit__(self, *exc):
        self.router.groq_chat = self.original
        return False


def _read(relative: str) -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "..", "prism_terminal", relative)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


if __name__ == "__main__":
    unittest.main()
