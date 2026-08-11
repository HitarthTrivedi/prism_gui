"""The Inquiry Automation screen.

The engine is covered by tests/test_mailflow.py. These are about the part the
customer actually touches, and they defend four things that are easy to break
without noticing:

  · **Setup keeps what it was given.** A password or a folder lost on save is
    discovered at 9am on a Monday, not here.
  · **The screen tells the truth about the sorting.** Every message shows what
    it was called and WHY — a sorting nobody can check is a sorting nobody
    should trust.
  · **A correction sticks.** It is the only way the customer teaches Prism
    anything, and a correction that quietly does not save is worse than no
    correction button at all.
  · **No jargon reaches the screen.** Same rule as the rest of the app: no
    "IMAP", no "UID", no category keys leaking out as identifiers.

Every test that would write settings patches config.save. A test suite that
overwrites the developer's own ~/.prism/config.json — their Groq key, their
agent choices — would be a rather expensive way to find a typo.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date
from email.message import EmailMessage

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

import core_bridge as CB  # noqa: E402
from core import inbox, mailflow, register, triage  # noqa: E402
from dialogs import inquiry_dialog as UI  # noqa: E402
from dialogs.inquiry_setup_dialog import (  # noqa: E402
    InquirySetupDialog, is_ready, settings_of)
from widgets import sidebar  # noqa: E402

_app = QApplication.instance() or QApplication([])


class _NoSave:
    """Stop a dialog writing to the real ~/.prism/config.json."""

    def __enter__(self):
        self.saved = []
        self.original = CB.config.save
        CB.config.save = lambda cfg: self.saved.append(dict(cfg))
        return self

    def __exit__(self, *exc):
        CB.config.save = self.original
        return False


def message(subject="Enquiry", sender="Mr Patel <purchase@shaktiauto.in>",
            body="Kindly quote 5000 nos compression spring 2mm.", headers=None):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = "sales@acme.co.in"
    msg["Date"] = "Mon, 10 Aug 2026 09:14:00 +0530"
    msg["Message-ID"] = f"<{abs(hash(subject + sender))}@x>"
    for key, value in (headers or {}).items():
        msg[key] = value
    msg.set_content(body)
    return inbox.parse_message(msg.as_bytes(), uid=1)


def ready_cfg(folder: str) -> dict:
    return {"api_key": "", "inquiry": {
        "account": {"address": "sales@acme.co.in", "password": "p",
                    "host": "mail.acme.co.in", "port": 993, "folder": "INBOX"},
        "folder": folder, "rate_list": "", "cost_sheet": "",
        "company": "Acme Springs", "signature": "Sales",
        "terms": {"gst_percent": 18, "validity_days": 15,
                  "payment": "advance", "delivery": "3 weeks"},
        "followup_days": 3, "local_only": True,
        "knowledge": {"own_domains": ["acme.co.in"],
                      "customers": ["shaktiauto.in"], "vendors": [],
                      "learned": {}},
        "state": {}}}


# ── setup ─────────────────────────────────────────────────────────────────────

class SetupKeepsWhatItIsGiven(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp()

    def test_it_builds_with_nothing_configured(self):
        dialog = InquirySetupDialog({})
        self.assertEqual(dialog.tabs.count(), 4)

    def test_a_full_round_trip(self):
        dialog = InquirySetupDialog({})
        dialog.addr.setText("sales@acme.co.in")
        dialog.password.setText("secret")
        dialog.host.setText("mail.acme.co.in")
        dialog.work_folder.edit.setText(self.folder)
        dialog.company.setText("Acme Springs")
        dialog.gst.setValue(12)
        dialog.validity.setValue(30)
        dialog.customers.setPlainText("shaktiauto.in\nBuyer@GujaratMotors.in")
        with _NoSave():
            dialog._save()

        saved = settings_of(dialog.cfg)
        self.assertEqual(saved["account"]["address"], "sales@acme.co.in")
        self.assertEqual(saved["account"]["password"], "secret")
        self.assertEqual(saved["folder"], self.folder)
        self.assertEqual(saved["terms"]["gst_percent"], 12)
        self.assertEqual(saved["terms"]["validity_days"], 30)

    def test_customer_lines_are_normalised(self):
        """People type "@shaktiauto.in" and mixed case. The engine matches on
        a bare lowercase domain, so one stray @ would silently stop a whole
        customer being recognised."""
        dialog = InquirySetupDialog({})
        dialog.addr.setText("a@b.c")
        dialog.password.setText("p")
        dialog.work_folder.edit.setText(self.folder)
        dialog.customers.setPlainText(" @ShaktiAuto.in \n\nBuyer@GujaratMotors.IN\n")
        with _NoSave():
            dialog._save()
        self.assertEqual(settings_of(dialog.cfg)["knowledge"]["customers"],
                         ["shaktiauto.in", "buyer@gujaratmotors.in"])

    def test_a_blank_password_keeps_the_saved_one(self):
        """Re-opening setup to fix a typo must not cost a trip to the
        provider's app-password page."""
        cfg = ready_cfg(self.folder)
        dialog = InquirySetupDialog(cfg)
        self.assertEqual(dialog.password.text(), "")
        dialog.company.setText("Changed")
        with _NoSave():
            dialog._save()
        self.assertEqual(settings_of(dialog.cfg)["account"]["password"], "p")

    def test_corrections_survive_reopening_setup(self):
        """Learned senders live in the same block as the hand-typed lists. If
        saving the form dropped them, every correction the customer ever made
        would vanish the next time they changed their GST rate."""
        cfg = ready_cfg(self.folder)
        cfg["inquiry"]["knowledge"]["learned"] = {"x@y.com": "vendor"}
        dialog = InquirySetupDialog(cfg)
        dialog.password.setText("p")
        with _NoSave():
            dialog._save()
        self.assertEqual(settings_of(dialog.cfg)["knowledge"]["learned"],
                         {"x@y.com": "vendor"})

    def test_the_reading_bookmark_survives_too(self):
        """Otherwise editing a setting re-imports the last month of mail as
        fresh inquiries."""
        cfg = ready_cfg(self.folder)
        cfg["inquiry"]["state"] = {"uidvalidity": 7, "last_uid": 900}
        dialog = InquirySetupDialog(cfg)
        dialog.password.setText("p")
        with _NoSave():
            dialog._save()
        self.assertEqual(settings_of(dialog.cfg)["state"]["last_uid"], 900)

    def test_the_server_is_guessed_when_never_tested(self):
        """Somebody who types their address and presses Save without pressing
        Test must not meet a failure about a server they never entered."""
        dialog = InquirySetupDialog({})
        dialog.addr.setText("sales@acme.co.in")
        dialog.password.setText("p")
        dialog.work_folder.edit.setText(self.folder)
        with _NoSave():
            dialog._save()
        self.assertEqual(settings_of(dialog.cfg)["account"]["host"],
                         "imap.acme.co.in")

    def test_the_folder_is_created(self):
        target = os.path.join(self.folder, "Prism Inquiries")
        dialog = InquirySetupDialog({})
        dialog.addr.setText("a@b.c")
        dialog.password.setText("p")
        dialog.work_folder.edit.setText(target)
        with _NoSave():
            dialog._save()
        self.assertTrue(os.path.isdir(target))


class Readiness(unittest.TestCase):

    def test_nothing_configured(self):
        self.assertFalse(is_ready({}))

    def test_a_configured_account(self):
        self.assertTrue(is_ready(ready_cfg(tempfile.mkdtemp())))

    def test_a_rate_list_is_not_required_to_start(self):
        """Deliberate: the read-only half is the half that sells this, and
        demanding a price list up front would stop somebody trying it."""
        cfg = ready_cfg(tempfile.mkdtemp())
        cfg["inquiry"]["rate_list"] = ""
        self.assertTrue(is_ready(cfg))

    def test_a_missing_folder_is_not_ready(self):
        cfg = ready_cfg(tempfile.mkdtemp())
        cfg["inquiry"]["folder"] = ""
        self.assertFalse(is_ready(cfg))


# ── the screen ────────────────────────────────────────────────────────────────

class TheScreen(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.cfg = ready_cfg(self.folder)
        self.dialog = UI.InquiryDialog(self.cfg)

    def test_three_tabs_in_phase_order(self):
        self.assertEqual(self.dialog.tabs.count(), 3)

    def test_it_opens_with_an_empty_register_rather_than_an_error(self):
        self.assertEqual(self.dialog.register_table.rowCount(), 0)

    def _result(self):
        known = triage.Knowledge.from_dict(self.cfg["inquiry"]["knowledge"])
        messages = [
            message(),
            message("Sale!", "promo@x.example", "buy now",
                    {"List-Unsubscribe": "<https://x/u>"}),
            message("Out of office", "away@y.example", "back Monday",
                    {"Auto-Submitted": "auto-replied"}),
        ]
        verdicts = [triage.rules_pass(m, known) for m in messages]
        result = mailflow.Result()
        result.sorted_mail = list(zip(messages, verdicts))
        result.counts = triage.summarise(verdicts)
        result.fetched = len(messages)
        result.state = inbox.State(1, 99)
        result.knowledge = known
        return result

    def test_every_message_shows_what_it_was_called_and_why(self):
        self.dialog._fill_arrived(self._result())
        table = self.dialog.arrived
        self.assertEqual(table.rowCount(), 3)
        for row in range(table.rowCount()):
            self.assertTrue(table.item(row, 2).text(), "no category shown")
            self.assertTrue(table.item(row, 3).text(), "no reason shown")

    def test_the_newsletter_says_why_it_was_filed(self):
        self.dialog._fill_arrived(self._result())
        reasons = [self.dialog.arrived.item(r, 3).text()
                   for r in range(self.dialog.arrived.rowCount())]
        self.assertTrue(any("unsubscribe" in r for r in reasons), reasons)

    def test_categories_are_words_not_engine_keys(self):
        self.dialog._fill_arrived(self._result())
        shown = {self.dialog.arrived.item(r, 2).text()
                 for r in range(self.dialog.arrived.rowCount())}
        for key in ("inquiry", "promotion", "other", "unsorted"):
            self.assertNotIn(key, shown, f"the raw key {key!r} reached the screen")

    def test_a_correction_is_remembered(self):
        self.dialog._fill_arrived(self._result())
        self.dialog.arrived.setCurrentCell(1, 0)          # the newsletter
        index = self.dialog.recategorise.findData("inquiry")
        self.dialog.recategorise.setCurrentIndex(index)
        with _NoSave():
            self.dialog._correct()
        learned = settings_of(self.dialog.cfg)["knowledge"]["learned"]
        self.assertEqual(learned.get("promo@x.example"), "inquiry")

    def test_a_correction_updates_the_row_in_front_of_them(self):
        self.dialog._fill_arrived(self._result())
        self.dialog.arrived.setCurrentCell(1, 0)
        self.dialog.recategorise.setCurrentIndex(
            self.dialog.recategorise.findData("vendor"))
        with _NoSave():
            self.dialog._correct()
        self.assertIn("Supplier", self.dialog.arrived.item(1, 2).text())

    def test_correcting_with_nothing_selected_does_nothing(self):
        self.dialog._fill_arrived(self._result())
        self.dialog.arrived.setCurrentCell(-1, -1)
        with _NoSave() as guard:
            self.dialog._correct()
        self.assertEqual(guard.saved, [])

    def test_the_bookmark_and_corrections_are_persisted_after_a_check(self):
        result = self._result()
        triage.learn(result.knowledge, "someone@new.example", "vendor")
        with _NoSave():
            self.dialog._remember(result)
        saved = settings_of(self.dialog.cfg)
        self.assertEqual(saved["state"]["last_uid"], 99)
        self.assertEqual(saved["knowledge"]["learned"].get("someone@new.example"),
                         "vendor")

    def test_the_register_table_fills_from_the_csv(self):
        rows = [register.from_message(message())]
        register.save(rows, mailflow.Paths(self.folder).register_csv)
        self.dialog._refresh_register()
        self.assertEqual(self.dialog.register_table.rowCount(), 1)
        self.assertIn("INQ/", self.dialog.register_table.item(0, 0).text())

    def test_an_empty_follow_up_list_says_so_rather_than_being_blank(self):
        self.dialog._refresh_register()
        self.assertEqual(self.dialog.followups.count(), 1)
        self.assertIn("Nothing is waiting", self.dialog.followups.item(0).text())

    def test_a_quiet_quotation_appears_on_the_chase_list(self):
        row = register.from_message(message())
        register.mark_quoted(row, "QTN/26-27/0001", 142500,
                             date.today().replace(day=1))
        register.save([row], mailflow.Paths(self.folder).register_csv)
        self.dialog._refresh_register()
        self.assertIn("QTN/26-27/0001", self.dialog.followups.item(0).text())

    def test_the_whole_callback_path_after_a_check(self):
        """What the worker actually calls back into. Everything above tests a
        piece of it; this is the button."""
        result = self._result()
        rows = [register.from_message(message())]
        register.save(rows, mailflow.Paths(self.folder).register_csv)
        with _NoSave():
            self.dialog._checked(result)
        self.assertEqual(self.dialog.arrived.rowCount(), 3)
        self.assertEqual(self.dialog.register_table.rowCount(), 1)
        self.assertTrue(self.dialog.check_btn.isEnabled(), "button left disabled")
        self.assertFalse(self.dialog.progress.isVisible(), "spinner left running")
        self.assertTrue(self.dialog.status.text())

    def test_the_status_line_after_a_check_is_readable(self):
        with _NoSave():
            self.dialog._checked(self._result())
        line = self.dialog.status.text().lower()
        for word in ("imap", "uid", "verdict", "none"):
            self.assertNotIn(word, line, f"{word!r} reached the status line")

    def test_a_failed_check_re_enables_the_button(self):
        """Otherwise one bad afternoon on the mail server leaves the customer
        with a dead button and no way to try again but restarting."""
        shown = []
        self.dialog._explain = lambda message: shown.append(message)
        self.dialog._check_failed("The mail server didn't answer.")
        self.assertTrue(self.dialog.check_btn.isEnabled())
        self.assertFalse(self.dialog.progress.isVisible())
        self.assertEqual(shown, ["The mail server didn't answer."])

    def test_an_error_with_no_mail_fetched_saves_nothing(self):
        """A locked register leaves the bookmark alone on purpose, so the same
        mail comes back next time. Saving here would lose it."""
        result = mailflow.Result()
        result.error = "Close inquiries.csv in Excel and try again."
        result.fetched = 0
        self.dialog._explain = lambda message: None
        with _NoSave() as guard:
            self.dialog._checked(result)
        self.assertEqual(guard.saved, [])

    def test_a_locked_register_does_not_crash_the_screen(self):
        original = register.load
        register.load = lambda p: (_ for _ in ()).throw(
            register.RegisterLocked("close Excel"))
        try:
            self.dialog._refresh_register()
        finally:
            register.load = original
        self.assertEqual(self.dialog.register_table.rowCount(), 0)


class NoJargonOnScreen(unittest.TestCase):
    """Same rule as the rest of the app. This feature is the one most likely
    to leak it, because its subject matter IS the plumbing."""

    FORBIDDEN = ("imap", "uid", "smtp", "mime", "traceback", "verdict",
                 "payload", "unsorted")

    def test_category_labels(self):
        for label in UI.CATEGORY_LABELS.values():
            low = label.lower()
            for word in self.FORBIDDEN:
                self.assertNotIn(word, low, f"{label!r} contains {word!r}")

    def test_every_category_the_engine_can_produce_has_a_label(self):
        """A category with no label shows the raw engine key on screen."""
        for key in triage.CATEGORIES:
            self.assertIn(key, UI.CATEGORY_LABELS, f"{key} has no label")
        self.assertIn("unsorted", UI.CATEGORY_LABELS)

    def test_source_labels_explain_rather_than_name(self):
        for label in UI.SOURCE_LABELS.values():
            self.assertNotIn("rule", label.lower().replace("by a rule", ""))


class ItIsOnTheShelf(unittest.TestCase):

    def _entry(self):
        for _group, items in sidebar.SECONDARY:
            for item in items:
                if item[0] == "inquiry":
                    return item
        return None

    def test_it_is_in_the_sidebar(self):
        self.assertIsNotNone(self._entry(), "Inquiry Automation is not on the rail")

    def test_it_is_gated_on_the_inbox_feature(self):
        """Otherwise every customer sees it whether they bought it or not."""
        self.assertEqual(self._entry()[4], "inbox")

    def test_it_sits_above_boq(self):
        """It is the only add-on used every day, so it goes where the eye
        lands. BOQ is occasional; this is the reason the app gets opened."""
        keys = [item[0] for _group, items in sidebar.SECONDARY for item in items]
        self.assertLess(keys.index("inquiry"), keys.index("boq"))

    def test_the_icon_exists(self):
        """A name with no glyph behind it draws nothing — an invisible button
        on the rail, which reads as a broken build rather than a missing icon."""
        from widgets import icons
        known = set(icons._STROKED) | set(icons._FILLED)
        self.assertIn(self._entry()[2], known)

    def test_the_main_window_routes_it(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), "main_window.py"),
                encoding="utf-8") as f:
            source = f.read()
        self.assertIn('key == "inquiry"', source)
        self.assertIn('_authorized_then("inbox"', source)


class TheFeatureIsSellable(unittest.TestCase):

    def test_the_plan_table_knows_about_it(self):
        import plans
        self.assertIn("inbox", plans.FEATURES)

    def test_it_is_inclusive_for_manufacturers(self):
        import plans
        self.assertIn("inbox", plans.PLANS["works"].includes)

    def test_it_is_an_addon_for_agencies(self):
        import plans
        self.assertIn("inbox", plans.PLANS["studio"].addons)

    def test_the_pitch_does_not_overpromise_automation(self):
        """The product stops twice, on purpose. Copy that says otherwise
        writes a cheque the software will not cash."""
        import plans
        pitch = plans.FEATURES["inbox"].pitch.lower()
        self.assertIn("stops twice", pitch)


if __name__ == "__main__":
    unittest.main()
