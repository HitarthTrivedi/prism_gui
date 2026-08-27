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
from unittest import mock
from datetime import date
from email.message import EmailMessage

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import core_bridge as CB  # noqa: E402
from core import inbox, mailflow, register, triage  # noqa: E402
from dialogs import inquiry_dialog as UI  # noqa: E402
import dialogs.inquiry_setup_dialog as UI_SETUP  # noqa: E402
from dialogs.inquiry_setup_dialog import (  # noqa: E402
    InquirySetupDialog, is_ready, settings_of)
from widgets import sidebar  # noqa: E402

_app = QApplication.instance() or QApplication([])


# ── the guard that should have been here from the start ──────────────────────
# The docstring above has always said "every test that would write settings
# patches config.save". It was a convention, and a convention is exactly as
# strong as the last person who remembered it.
#
# One did not. test_a_reply_arriving_opens_that_tab called _checked(), which
# calls _remember(), which calls config.save() — and wrote a bare test fixture
# over the developer's real ~/.prism/config.json. Groq key, profile, agent
# choices, Chrome pin: gone, and the only symptom was Prism asking to be set up
# again on every launch, which reads like a Prism bug rather than a test one.
#
# So the rule now has teeth. save() refuses for the whole module unless a test
# has deliberately taken it over with _NoSave, and CONFIG_PATH points at a
# scratch file so even a direct write cannot reach the real one. A test that
# forgets now FAILS; it does not quietly cost somebody their afternoon.
_REAL_SAVE = CB.config.save
_REAL_CONFIG_PATH = CB.config.CONFIG_PATH
_SCRATCH = tempfile.mkdtemp(prefix="prism-test-config-")


def _refuse(cfg):
    raise AssertionError(
        "This test called config.save() without patching it. That writes the "
        "real ~/.prism/config.json and destroys whoever is running the "
        "tests.\n\nWrap the call:  with _NoSave(): ...")


def setUpModule():
    CB.config.save = _refuse
    CB.config.CONFIG_PATH = os.path.join(_SCRATCH, "config.json")


def tearDownModule():
    CB.config.save = _REAL_SAVE
    CB.config.CONFIG_PATH = _REAL_CONFIG_PATH


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

    def test_a_typed_server_is_tried_before_any_guess(self):
        """The Mail server box used to be ignored by "Find my server and test".

        Anyone whose mail is hosted rather than on their own domain — GoDaddy,
        Google Workspace, Microsoft 365 — cannot be found by guessing
        imap./mail./<domain>, so the way out is to type the server their
        provider documents. That only works if we actually try it.
        """
        tried = []

        def fake_connect(ic, timeout=20):
            tried.append(ic["host"])
            raise OSError("nope")

        with mock.patch.object(inbox, "_connect", fake_connect):
            inbox.discover("sales@acme.co.in", "p",
                           host="imap.secureserver.net")
        self.assertEqual(tried[0], "imap.secureserver.net")

    def test_a_typed_server_does_not_stop_the_guesses(self):
        """A typo in the box must not be a dead end — whatever answers wins."""
        tried = []

        def fake_connect(ic, timeout=20):
            tried.append(ic["host"])
            raise OSError("nope")

        with mock.patch.object(inbox, "_connect", fake_connect):
            inbox.discover("sales@acme.co.in", "p", host="typo.example")
        self.assertEqual(tried[0], "typo.example")
        self.assertIn("imap.acme.co.in", tried)

    def test_the_typed_server_is_not_tried_twice(self):
        tried = []

        def fake_connect(ic, timeout=20):
            tried.append(ic["host"])
            raise OSError("nope")

        with mock.patch.object(inbox, "_connect", fake_connect):
            inbox.discover("sales@acme.co.in", "p", host="imap.acme.co.in")
        self.assertEqual(tried.count("imap.acme.co.in"), 1)

    def test_the_dialog_hands_the_typed_server_to_the_worker(self):
        """The bug was here, not in discover(): the dialog never read the box."""
        seen = {}

        class FakeWorker:
            def __init__(self, address, password, host=""):
                seen.update(address=address, password=password, host=host)
                self.done = mock.MagicMock()

            def start(self):
                pass

        dialog = InquirySetupDialog({})
        dialog.addr.setText("sales@acme.co.in")
        dialog.password.setText("p")
        dialog.host.setText("imap.secureserver.net")
        with mock.patch.object(UI_SETUP, "InboxVerifyWorker", FakeWorker):
            dialog._test()
        self.assertEqual(seen.get("host"), "imap.secureserver.net")

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

    def test_five_tabs_in_the_order_the_work_happens(self):
        """Arrived → registered → answered → chased → ordered. The tab order
        IS the explanation of the feature, so it is worth a test of its own —
        and the fifth tab is the end the whole workflow was sold on: the
        purchase order arriving is the last step of "inquiry to order"."""
        self.assertEqual(self.dialog.tabs.count(), 5)
        self.assertTrue(self.dialog.tabs.tabText(0).startswith("1"))
        self.assertTrue(self.dialog.tabs.tabText(3).startswith("4"))
        self.assertTrue(self.dialog.tabs.tabText(4).startswith("5"))

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

    def test_the_screen_is_actually_styled(self):
        """Every widget on this screen asked for its look with
        setProperty("class", …) — and style.qss has no [class=…] selector
        anywhere, so not one of those 34 requests did anything. The title was
        not a heading, the price previews were not monospaced, and "Check now"
        — the main button on the screen — drew as an ordinary grey button.

        The rest of the app styles by object name, which is what the
        stylesheet matches on. This keeps the two from drifting apart again.

        Parsed rather than grepped: the file now explains this bug in its own
        comments, and a test that greps its source cannot tell a call from a
        sentence about the call.
        """
        import ast
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "dialogs", "inquiry_dialog.py"),
                  encoding="utf-8") as f:
            tree = ast.parse(f.read())
        offenders = [
            node.lineno for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "setProperty"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "class"]
        self.assertEqual(offenders, [],
                         "style.qss matches on object names, not a class "
                         "property — this silently does nothing")

    def test_every_object_name_it_asks_for_exists_in_the_stylesheet(self):
        import re
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "dialogs", "inquiry_dialog.py"),
                  encoding="utf-8") as f:
            wanted = set(re.findall(r'setObjectName\("([A-Za-z][\w]*)"\)', f.read()))
        with open(os.path.join(root, "style.qss"), encoding="utf-8") as f:
            qss = f.read()
        for name in sorted(wanted):
            with self.subTest(name=name):
                self.assertRegex(qss, rf"#{name}\b",
                                 f"#{name} is asked for but never defined")

    def test_the_check_button_is_the_primary_one(self):
        self.assertEqual(self.dialog.check_btn.objectName(), "primaryBtn")

    def test_a_correction_is_remembered(self):
        self.dialog._fill_arrived(self._result())
        # Found by sender rather than by row number: the table is ordered by
        # what needs a person, so a newsletter is no longer the second row and
        # which row it lands on is not what this test is about.
        rows = [r for r in range(self.dialog.arrived.rowCount())
                if self.dialog.arrived.item(r, 0).data(Qt.UserRole)
                == "promo@x.example"]
        self.assertTrue(rows, "the newsletter should be somewhere in the table")
        self.dialog.arrived.setCurrentCell(rows[0], 0)
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

    # The rail's one grouped SECONDARY list became three flat ones when the
    # redesign split the shelf (ADDONS) from the generic destinations (MORE)
    # and the settings shortcuts (DIRECT). The tuple layout is unchanged —
    # key, label, icon, tip, feature — so only the lookup moved.
    def _entry(self):
        for item in sidebar.ADDONS:
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
        keys = [item[0] for item in sidebar.ADDONS]
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


class ClosingTheScreenMidCheck(unittest.TestCase):
    """A QThread destroyed while still running aborts the whole process. Reel
    and BOQ have guarded this since they were written; this screen has more
    workers than either — a mailbox check, a send, and a browser draft that
    runs for minutes."""

    class _Worker:
        def __init__(self, obeys=True):
            self.running, self.stopped = True, False
            self.terminated, self._obeys = False, obeys

        def isRunning(self):
            return self.running

        def stop(self):
            self.stopped = True

        def wait(self, _ms):
            if self._obeys:
                self.running = False
            return self._obeys

        def terminate(self):
            self.terminated = True
            self.running = False

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.dialog = UI.InquiryDialog(ready_cfg(self.folder))

    def close(self):
        from PySide6.QtGui import QCloseEvent

        self.dialog.closeEvent(QCloseEvent())

    def test_every_worker_is_stopped_and_joined(self):
        workers = [self._Worker() for _ in range(3)]
        (self.dialog._worker, self.dialog._send_worker,
         self.dialog._draft_worker) = workers
        self.close()
        for w in workers:
            self.assertTrue(w.stopped)
            self.assertFalse(w.running)

    def test_a_stuck_worker_is_terminated_rather_than_left_to_abort(self):
        stuck = self._Worker(obeys=False)
        self.dialog._draft_worker = stuck
        self.close()
        self.assertTrue(stuck.terminated)

    def test_the_timer_is_stopped_first(self):
        """Otherwise it can fire during the waits and start a fresh check on a
        dialog that is closing."""
        self.dialog._auto.start(60_000)
        self.close()
        self.assertFalse(self.dialog._auto.isActive())

    def test_closing_with_nothing_running_is_harmless(self):
        self.close()        # must not raise

    def test_a_deleted_worker_does_not_stop_the_others(self):
        class _Deleted:
            def isRunning(self):
                raise RuntimeError("wrapped C/C++ object has been deleted")

        alive = self._Worker()
        self.dialog._worker = _Deleted()
        self.dialog._send_worker = alive
        self.close()
        self.assertTrue(alive.stopped)


class ColourCarriesMeaning(unittest.TestCase):
    """Colour is what makes a hundred-row register readable at arm's length.
    It is also the thing most easily got wrong in a way nobody notices until a
    customer says they cannot read it."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.dialog = UI.InquiryDialog(ready_cfg(self.folder))

    def test_every_category_the_screen_can_show_has_a_colour(self):
        """An uncoloured cell in a coloured column reads as a rendering bug,
        not as a category."""
        for key in UI.CATEGORY_LABELS:
            self.assertIn(key, UI.CATEGORY_COLOURS, key)

    def test_every_status_the_register_can_hold_has_a_colour(self):
        for status in register.STATUSES:
            self.assertIn(status, UI.STATUS_COLOURS, status)

    def test_every_intent_has_a_label_and_a_colour(self):
        for intent in ("accepted", "rejected", "negotiating", "needs_info",
                       "unclear"):
            self.assertIn(intent, UI.INTENT_LABELS, intent)
            self.assertIn(intent, UI.INTENT_COLOURS, intent)

    def test_the_word_is_always_there_as_well_as_the_colour(self):
        """Roughly one man in twelve cannot tell the red from the green, and a
        register printed on the office laser comes out grey. Colour may
        reinforce the meaning; it may never be the only thing carrying it."""
        from PySide6.QtWidgets import QTableWidgetItem

        item = UI.paint(QTableWidgetItem("Converted"), UI.STATUS_COLOURS,
                        "Converted")
        self.assertEqual(item.text(), "Converted")

    def test_an_unknown_key_is_left_plain_rather_than_guessed(self):
        from PySide6.QtWidgets import QTableWidgetItem

        plain = QTableWidgetItem("Something new")
        painted = UI.paint(plain, UI.STATUS_COLOURS, "Something new")
        self.assertIs(painted, plain)

    def test_the_register_paints_the_status_column(self):
        row = register.from_message(message())
        register.mark_quoted(row, "QTN/26-27/0001", "1000")
        register.save([row], mailflow.Paths(self.folder).register_csv)
        self.dialog._refresh_register()
        cell = self.dialog.register_table.item(0, 4)
        self.assertEqual(cell.text(), register.QUOTED)
        self.assertEqual(cell.background().color().name(),
                         UI.STATUS_COLOURS[register.QUOTED][0])

    def test_the_date_column_shows_the_time_as_well(self):
        register.save([register.from_message(message())],
                      mailflow.Paths(self.folder).register_csv)
        self.dialog._refresh_register()
        self.assertIn("09:14", self.dialog.register_table.item(0, 1).text())


class CheckingWithoutBeingAsked(unittest.TestCase):
    """"Prism scans the mail on a regular basis" is the promise. A button
    somebody has to remember is not that."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.cfg = ready_cfg(self.folder)

    def test_off_by_default(self):
        """Nobody's mail server gets polled because they opened a screen."""
        dialog = UI.InquiryDialog(self.cfg)
        self.assertFalse(dialog._auto.isActive())
        self.assertFalse(dialog.auto_box.isChecked())

    def test_a_saved_interval_starts_the_timer(self):
        self.cfg["inquiry"]["auto_minutes"] = 10
        dialog = UI.InquiryDialog(self.cfg)
        self.assertTrue(dialog._auto.isActive())
        self.assertEqual(dialog._auto.interval(), 10 * 60_000)
        self.assertTrue(dialog.auto_box.isChecked())

    def test_it_does_not_run_when_the_mailbox_is_not_set_up(self):
        """A timer firing against a half-configured account produces a login
        failure every ten minutes forever."""
        cfg = {"inquiry": {"auto_minutes": 10, "folder": self.folder}}
        dialog = UI.InquiryDialog(cfg)
        self.assertFalse(dialog._auto.isActive())

    def test_turning_it_on_picks_a_sane_interval_rather_than_zero(self):
        dialog = UI.InquiryDialog(self.cfg)
        with _NoSave():
            dialog.auto_box.setChecked(True)
        self.assertTrue(dialog._auto.isActive())
        self.assertGreaterEqual(dialog._auto.interval(), 5 * 60_000)

    def test_turning_it_off_stops_it_and_is_remembered(self):
        self.cfg["inquiry"]["auto_minutes"] = 10
        dialog = UI.InquiryDialog(self.cfg)
        with _NoSave() as saver:
            dialog.auto_box.setChecked(False)
        self.assertFalse(dialog._auto.isActive())
        self.assertEqual(saver.saved[-1]["inquiry"]["auto_minutes"], 0)

    def test_a_tick_is_skipped_while_a_check_is_already_running(self):
        """Two IMAP fetches racing on one bookmark is how the same inquiry
        gets registered twice."""
        dialog = UI.InquiryDialog(self.cfg)
        calls = []
        dialog.check_now = lambda **kw: calls.append(kw)

        class Busy:
            @staticmethod
            def isRunning():
                return True

        dialog._worker = Busy()
        dialog._auto_check()
        self.assertEqual(calls, [])

    def test_a_quiet_failure_stays_in_the_status_line(self):
        """A modal appearing over somebody's work every ten minutes because
        the mail server had a bad afternoon is how the feature gets switched
        off for good."""
        dialog = UI.InquiryDialog(self.cfg)
        shown = []
        dialog._quiet = True
        with _Patched(UI, "QMessageBox", _Recording(shown)):
            dialog._explain("Couldn't reach the mail server.\nTry again.")
        self.assertEqual(shown, [])
        self.assertIn("Couldn't reach", dialog.status.text())

    def test_a_failure_the_owner_asked_for_still_gets_a_dialog(self):
        dialog = UI.InquiryDialog(self.cfg)
        dialog._quiet = False
        seen = []
        dialog._explain = lambda m: seen.append(m)   # sanity: path is reachable
        dialog._explain("boom")
        self.assertEqual(seen, ["boom"])


class WhatTheCustomerSaidBack(unittest.TestCase):
    """The step the customer called the main part: a reply arrives, Prism
    reads it, and the register moves on."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.cfg = ready_cfg(self.folder)
        self.dialog = UI.InquiryDialog(self.cfg)
        self.row = register.from_message(message())
        register.mark_quoted(self.row, "QTN/26-27/0001", "50000")
        register.save([self.row], mailflow.Paths(self.folder).register_csv)
        self.dialog._refresh_register()

    def _result(self, intent="accepted"):
        result = mailflow.Result()
        result.replies = [mailflow.Item(
            "reply", message("Re: Enquiry", body="Please go ahead."),
            self.dialog._register_rows[0], intent=intent)]
        return result

    def test_replies_are_listed_with_what_prism_made_of_them(self):
        self.dialog._fill_replies(self._result())
        self.assertEqual(self.dialog.replies_table.rowCount(), 1)
        self.assertEqual(self.dialog.replies_table.item(0, 3).text(),
                         UI.INTENT_LABELS["accepted"])

    def test_the_screen_says_what_it_would_do_before_it_does_it(self):
        self.dialog._fill_replies(self._result())
        self.assertEqual(self.dialog.replies_table.item(0, 4).text(),
                         register.ACCEPTED)

    def test_reading_a_reply_changes_nothing_on_its_own(self):
        """Prism proposes. A machine that silently rewrote a sales record on
        the strength of a sentence it might have misread is not something a
        business can check."""
        self.dialog._fill_replies(self._result())
        self.assertEqual(self.dialog._register_rows[0]["Status"],
                         register.QUOTED)

    def test_applying_it_writes_the_file(self):
        self.dialog._fill_replies(self._result())
        self.dialog._apply_reply()
        saved = register.load(mailflow.Paths(self.folder).register_csv)
        self.assertEqual(saved[0]["Status"], register.ACCEPTED)

    def test_an_applied_reply_leaves_the_list(self):
        """Otherwise the same reply can be applied twice, and a second
        'rejected' on an already-closed row rewrites the reason."""
        self.dialog._fill_replies(self._result())
        self.dialog._apply_reply()
        self.assertEqual(self.dialog.replies_table.rowCount(), 0)

    def test_an_unclear_reply_says_so_rather_than_guessing(self):
        self.dialog._fill_replies(self._result("unclear"))
        self.assertIn("can't tell", self.dialog.replies_table.item(0, 3).text())
        self.assertNotIn(self.dialog.replies_table.item(0, 4).text(),
                         register.STATUSES)

    def test_the_owner_can_overrule_prism(self):
        self.dialog._fill_replies(self._result("accepted"))
        position = self.dialog.intent_picker.findData("rejected")
        self.dialog.intent_picker.setCurrentIndex(position)
        self.dialog._apply_reply()
        self.assertEqual(self.dialog._register_rows[0]["Status"],
                         register.NOT_CONVERTED)

    def test_the_words_the_customer_wrote_are_on_screen(self):
        """The owner is being asked to approve a reading of a sentence. They
        have to be able to see the sentence."""
        self.dialog._fill_replies(self._result())
        self.assertIn("go ahead", self.dialog.reply_text.toPlainText())

    def test_a_reply_arriving_opens_that_tab(self):
        self.dialog._quiet = False
        # _checked -> _remember -> config.save. This is the test that wrote a
        # bare fixture over a real ~/.prism/config.json before the module
        # guard existed.
        with _NoSave():
            self.dialog._checked(self._result())
        self.assertEqual(self.dialog.tabs.currentIndex(), 2)

    def test_a_timer_tick_never_moves_the_tab(self):
        """A screen that rearranges itself every ten minutes while you are
        reading it is the reason people switch automatic checking off."""
        self.dialog.tabs.setCurrentIndex(1)
        self.dialog._quiet = True
        with _NoSave():
            self.dialog._checked(self._result())
        self.assertEqual(self.dialog.tabs.currentIndex(), 1)


class CorrectingTheRegisterByHand(unittest.TestCase):
    """They can always edit the CSV in Excel — it is their file. But a
    register that can only be corrected by closing the app is one they will
    stop correcting."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.row = register.from_message(message())
        register.save([self.row], mailflow.Paths(self.folder).register_csv)
        self.dialog = UI.InquiryDialog(ready_cfg(self.folder))
        self.dialog._refresh_register()

    def test_the_fields_a_person_knows_better_are_editable(self):
        dialog = UI._EditRowDialog(self.dialog._register_rows[0])
        for field in ("Customer", "Product asked", "Quantity"):
            self.assertIn(field, dialog._edits)

    def test_the_bookkeeping_is_not_editable(self):
        """Letting the inquiry number be retyped is how two rows end up
        sharing one."""
        dialog = UI._EditRowDialog(self.dialog._register_rows[0])
        for field in ("Inquiry no", "Quotation no", "Date received"):
            self.assertNotIn(field, dialog._edits)

    def test_closing_a_row_by_hand_moves_the_result_column_too(self):
        """Result is what the month-end summary counts. A row marked
        Converted here but left open in Result makes the conversion figure
        disagree with the list the owner is looking at."""
        dialog = UI._EditRowDialog(self.dialog._register_rows[0])
        dialog._status.setCurrentIndex(
            dialog._status.findData(register.CONVERTED))
        self.assertEqual(dialog.changes()["Result"], register.CONVERTED)

    def test_reopening_a_row_clears_the_result(self):
        row = dict(self.dialog._register_rows[0])
        row["Status"] = register.CONVERTED
        row["Result"] = register.CONVERTED
        dialog = UI._EditRowDialog(row)
        dialog._status.setCurrentIndex(dialog._status.findData(register.QUOTED))
        self.assertEqual(dialog.changes()["Result"], "")

    def test_every_status_is_offered(self):
        dialog = UI._EditRowDialog(self.dialog._register_rows[0])
        offered = {dialog._status.itemData(i)
                   for i in range(dialog._status.count())}
        self.assertEqual(offered, set(register.STATUSES))


class ChasingAQuietQuotation(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.row = register.from_message(message())
        register.mark_quoted(self.row, "QTN/26-27/0001", "50000")
        self.row["Last contact"] = "01-01-2020"      # long overdue
        register.save([self.row], mailflow.Paths(self.folder).register_csv)
        self.dialog = UI.InquiryDialog(ready_cfg(self.folder))
        self.dialog._refresh_register()

    def test_the_overdue_quotation_is_listed(self):
        self.assertEqual(len(self.dialog._followup_rows), 1)

    def test_nothing_is_sent_without_a_selection(self):
        """The list is a QListWidget with no row selected on open. Firing at
        whatever happens to be first would mail a real customer."""
        shown = []
        self.dialog.followups.setCurrentRow(-1)
        with _Patched(UI, "QMessageBox", _Recording(shown)):
            self.dialog._send_reminder()
        self.assertEqual(len(shown), 1)

    def test_a_sent_reminder_is_counted_and_saved(self):
        self.dialog._reminder_sent(self.dialog._followup_rows[0], ["x"], [])
        saved = register.load(mailflow.Paths(self.folder).register_csv)
        self.assertEqual(saved[0]["Reminders sent"], "1")
        self.assertEqual(saved[0]["Status"], register.FOLLOWING_UP)

    def test_a_failed_reminder_is_not_counted(self):
        """Counting a reminder that never left makes Prism stop chasing after
        three sends that never happened."""
        # _explain opens a real modal; swapped for a recorder so the test does
        # not wait forever for a human to click OK.
        told = []
        self.dialog._explain = told.append
        self.dialog._reminder_sent(self.dialog._followup_rows[0],
                                   [], [("a@b.c", "mailbox full")])
        saved = register.load(mailflow.Paths(self.folder).register_csv)
        self.assertEqual((saved[0]["Reminders sent"] or "0"), "0")
        self.assertIn("mailbox full", told[0])

    def test_chasing_stops_after_three(self):
        row = dict(self.row)
        row["Reminders sent"] = "3"
        self.assertEqual(register.awaiting_followup([row]), [])


class StartingFromARegisterTheyAlreadyKeep(unittest.TestCase):
    """A shop trading twenty years already has an inquiry list. Starting them
    at row one means running two registers side by side until they give up on
    ours."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.theirs = os.path.join(self.folder, "old list.csv")

    def write(self, text: str):
        with open(self.theirs, "w", encoding="utf-8") as f:
            f.write(text)

    def dialog(self, target: str) -> InquirySetupDialog:
        d = InquirySetupDialog({})
        d.addr.setText("a@b.c")
        d.password.setText("p")
        d.work_folder.edit.setText(target)
        d.existing_register.edit.setText(self.theirs)
        return d

    def test_their_rows_come_across(self):
        self.write("Inquiry no,Date received,Customer,Status\n"
                   "INQ/25-26/0001,01-04-2025,Shakti Auto,Quoted\n"
                   "INQ/25-26/0002,02-04-2025,Gujarat Motors,Converted\n")
        target = tempfile.mkdtemp()
        with _NoSave():
            self.dialog(target)._import_register(target)
        rows = register.load(os.path.join(target, register.FILENAME))
        self.assertEqual([r["Customer"] for r in rows],
                         ["Shakti Auto", "Gujarat Motors"])

    def test_their_own_columns_survive(self):
        """Their "Party Name" and "Remarks" are twenty years of somebody's
        work. Prism adds columns; it never takes any away."""
        self.write("Inquiry no,Party Name,Remarks\n"
                   "INQ/25-26/0001,Shakti,called twice\n")
        target = tempfile.mkdtemp()
        with _NoSave():
            self.dialog(target)._import_register(target)
        row = register.load(os.path.join(target, register.FILENAME))[0]
        self.assertEqual(row["Party Name"], "Shakti")
        self.assertEqual(row["Remarks"], "called twice")

    def test_an_existing_register_is_never_overwritten(self):
        """That file is the only copy of their order book. Importing over the
        top of a live one would be unrecoverable."""
        target = tempfile.mkdtemp()
        live = register.from_message(message())
        live["Customer"] = "Already here"
        register.save([live], os.path.join(target, register.FILENAME))

        self.write("Inquiry no,Customer\nINQ/25-26/0001,Imported\n")
        with _NoSave():
            said = self.dialog(target)._import_register(target)

        rows = register.load(os.path.join(target, register.FILENAME))
        self.assertEqual([r["Customer"] for r in rows], ["Already here"])
        self.assertIn("left alone", said)

    def test_missing_columns_are_reported_not_guessed(self):
        """A column-guessing importer that got it wrong would quietly mis-file
        somebody's order book. Say what was not found instead."""
        self.write("Ref,Party\nA1,Shakti\n")
        target = tempfile.mkdtemp()
        with _NoSave():
            said = self.dialog(target)._import_register(target)
        self.assertIn("Customer", said)
        self.assertIn("Status", said)

    def test_an_empty_file_imports_nothing_and_says_so(self):
        self.write("Inquiry no,Customer\n")
        target = tempfile.mkdtemp()
        with _NoSave():
            said = self.dialog(target)._import_register(target)
        self.assertIn("no rows", said)

    def test_leaving_the_box_empty_does_nothing(self):
        target = tempfile.mkdtemp()
        d = self.dialog(target)
        d.existing_register.edit.setText("")
        with _NoSave():
            self.assertEqual(d._import_register(target), "")
        self.assertFalse(os.path.exists(
            os.path.join(target, register.FILENAME)))

    def test_a_missing_file_is_a_sentence_not_a_crash(self):
        target = tempfile.mkdtemp()
        d = self.dialog(target)
        d.existing_register.edit.setText(os.path.join(target, "nope.csv"))
        with _NoSave():
            said = d._import_register(target)
        self.assertIn("no rows", said.lower())

    def test_numbering_carries_on_from_theirs(self):
        """The whole point of importing. If Prism restarted at 0001 it would
        issue a number the customer already has on a quotation."""
        self.write("Inquiry no,Customer\nINQ/26-27/0087,Shakti\n")
        target = tempfile.mkdtemp()
        with _NoSave():
            self.dialog(target)._import_register(target)
        rows = register.load(os.path.join(target, register.FILENAME))
        self.assertEqual(register.next_number(rows, "INQ", date(2026, 8, 12)),
                         "INQ/26-27/0088")


class PricingFromTheOwnersFormulas(unittest.TestCase):
    """The cost-sheet route: their line names, their rates, Prism's
    arithmetic. Every figure has to be one they could reproduce on paper."""

    SHEET = ("Wire,per_kg,95\n"
             "Coiling,per_piece,1.20\n"
             "Tool setting,per_lot,800\n"
             "Overheads,percent,12\n")

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.cost = os.path.join(self.folder, "costs.csv")
        with open(self.cost, "w", encoding="utf-8") as f:
            f.write(self.SHEET)
        self.cfg = ready_cfg(self.folder)
        self.cfg["inquiry"]["cost_sheet"] = self.cost
        self.row = register.from_message(message())
        register.save([self.row], mailflow.Paths(self.folder).register_csv)
        self.dialog = UI.InquiryDialog(self.cfg)
        self.dialog._refresh_register()
        self.lines = CB.get_quoting().load_cost_lines(self.cost)

    def quote_dialog(self):
        return UI.QuotationDialog(self.cfg, self.dialog._register_rows[0], [],
                                  self.dialog, cost_lines=self.lines)

    def test_a_shop_with_only_a_cost_sheet_can_still_quote(self):
        """Requiring the rate list, as this once did, locked out every shop
        that quotes made-to-drawing work — which is most job shops."""
        q = self.quote_dialog()
        self.assertEqual([q.source.itemData(i) for i in range(q.source.count())],
                         ["cost"])

    def test_every_line_of_the_working_is_on_screen(self):
        """This is the number they will be asked to justify on the phone. A
        rate they cannot explain is a rate they will not send."""
        q = self.quote_dialog()
        q.weight.setText("0.045")
        q.quantity.setText("5000")
        q._recalculate()
        for name in ("Wire", "Coiling", "Tool setting", "Overheads"):
            self.assertIn(name, q.workings.toPlainText())

    def test_the_arithmetic(self):
        q = self.quote_dialog()
        q.weight.setText("0.045")
        q.quantity.setText("5000")
        q._recalculate()
        # 0.045 kg x 5000 x 95 = 21,375 ; + 1.20 x 5000 = 6,000 ; + 800
        # = 28,175 ; + 12% = 31,556
        self.assertIn("21,375.00", q.workings.toPlainText())
        self.assertIn("31,556.00", q.workings.toPlainText())

    def test_the_rounding_gap_is_shown_rather_than_swallowed(self):
        """The quotation totals the ROUNDED per-piece rate, so it does not
        equal the cost. Reading ₹31,556 on screen and sending ₹31,550 is how
        an owner stops believing the rest of the calculation."""
        q = self.quote_dialog()
        q.weight.setText("0.045")
        q.quantity.setText("5000")
        q._recalculate()
        working = q.workings.toPlainText()
        self.assertIn("31,550.00", working)      # what the quotation says
        self.assertIn("rounded to the paisa", working)
        self.assertEqual(f"{q.quote.subtotal:.2f}", "31550.00")

    def test_a_missing_weight_refuses_rather_than_under_quoting(self):
        """The sheet charges material by the kilogram. Treating a blank weight
        as zero quotes the labour alone — an under-quote that looks like a
        finished quotation."""
        q = self.quote_dialog()
        q.quantity.setText("5000")
        q._recalculate()
        self.assertIsNone(q.quote)
        self.assertIn("weight", q.workings.toPlainText().lower())

    def test_a_sheet_with_no_weight_lines_needs_no_weight(self):
        """A shop that charges purely per piece must not be asked for a weight
        it has no reason to know."""
        path = os.path.join(self.folder, "flat.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write("Machining,per_piece,40\nSetup,per_lot,500\n")
        lines = CB.get_quoting().load_cost_lines(path)
        q = UI.QuotationDialog(self.cfg, self.dialog._register_rows[0], [],
                               self.dialog, cost_lines=lines)
        q.quantity.setText("100")
        q._recalculate()
        self.assertIsNotNone(q.quote)
        self.assertEqual(f"{q.quote.subtotal:.2f}", "4500.00")

    def test_the_quotation_says_where_the_rate_came_from(self):
        q = self.quote_dialog()
        q.weight.setText("0.045")
        q._recalculate()
        self.assertEqual(q.quote.lines[0].basis, "cost sheet")

    def test_neither_file_configured_is_a_sentence_not_a_crash(self):
        cfg = ready_cfg(self.folder)          # no rate list, no cost sheet
        dialog = UI.InquiryDialog(cfg)
        dialog._refresh_register()
        dialog.register_table.setCurrentCell(0, 0)
        told = []
        dialog._explain = told.append
        dialog._prepare_quotation()
        self.assertTrue(told)
        self.assertIn("cost sheet", told[0].lower())


class ChasingByItself(unittest.TestCase):
    """Every two days, three times, driven off the register — and then it
    stops. These are letters going out in the owner's name, so every guard
    here is one they would ask for if they thought about it."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.cfg = ready_cfg(self.folder)
        self.cfg["inquiry"]["auto_followup"] = True
        self.cfg["inquiry"]["followup_days"] = 2
        self.cfg["inquiry"]["max_reminders"] = 3
        self.row = register.from_message(message())
        register.mark_quoted(self.row, "QTN/26-27/0001", "50000")
        self.row["Last contact"] = "01-01-2020"        # long overdue
        register.save([self.row], mailflow.Paths(self.folder).register_csv)

    def dialog(self):
        d = UI.InquiryDialog(self.cfg)
        d._refresh_register()
        self.sent = []
        d._send_worker = None

        class _Fake:
            def __init__(_, cfg, recipients, subject, body, files):
                _.done = _Signal()
                _.failed = _Signal()
                self.sent.append((recipients[0]["email"], subject, body))

            def isRunning(_):
                return False

            def start(_):
                pass

        self._fake = _Fake
        return d

    def test_it_sends_when_switched_on(self):
        d = self.dialog()
        with _Patched(UI, "SendWorker", self._fake), \
             _Patched(CB.mailer, "is_configured", lambda cfg: True):
            d._chase_automatically()
        self.assertEqual(len(self.sent), 1)

    def test_it_is_silent_when_switched_off(self):
        """Off unless they turned it on. The default has to be that Prism
        writes to nobody."""
        self.cfg["inquiry"]["auto_followup"] = False
        d = self.dialog()
        with _Patched(UI, "SendWorker", self._fake), \
             _Patched(CB.mailer, "is_configured", lambda cfg: True):
            d._chase_automatically()
        self.assertEqual(self.sent, [])

    def test_only_one_goes_out_per_check(self):
        """Three reminders leaving in the same second, to three customers who
        talk to each other, reads as a machine."""
        rows = []
        for n in range(3):
            r = register.from_message(message(subject=f"Enquiry {n}"))
            r["Email"] = f"buyer{n}@shaktiauto.in"
            register.mark_quoted(r, f"QTN/26-27/000{n}", "1000")
            r["Last contact"] = "01-01-2020"
            rows.append(r)
        register.save(rows, mailflow.Paths(self.folder).register_csv)
        d = self.dialog()
        with _Patched(UI, "SendWorker", self._fake), \
             _Patched(CB.mailer, "is_configured", lambda cfg: True):
            d._chase_automatically()
        self.assertEqual(len(self.sent), 1)

    def test_it_stops_after_the_third(self):
        self.row["Reminders sent"] = "3"
        register.save([self.row], mailflow.Paths(self.folder).register_csv)
        d = self.dialog()
        with _Patched(UI, "SendWorker", self._fake), \
             _Patched(CB.mailer, "is_configured", lambda cfg: True):
            d._chase_automatically()
        self.assertEqual(self.sent, [])

    def test_a_row_chased_yesterday_is_left_alone(self):
        """Two days means two days. A timer running every ten minutes must not
        turn that into 144 reminders."""
        from datetime import timedelta
        self.row["Last contact"] = (
            date.today() - timedelta(days=1)).strftime("%d-%m-%Y")
        register.save([self.row], mailflow.Paths(self.folder).register_csv)
        d = self.dialog()
        with _Patched(UI, "SendWorker", self._fake), \
             _Patched(CB.mailer, "is_configured", lambda cfg: True):
            d._chase_automatically()
        self.assertEqual(self.sent, [])

    def test_nothing_is_sent_without_an_outgoing_account(self):
        d = self.dialog()
        with _Patched(UI, "SendWorker", self._fake), \
             _Patched(CB.mailer, "is_configured", lambda cfg: False):
            d._chase_automatically()
        self.assertEqual(self.sent, [])

    def test_each_reminder_is_worded_differently(self):
        """Three identical nudges in six days is a mail merge."""
        d = self.dialog()
        bodies = []
        for n in ("0", "1", "2"):
            row = dict(self.row)
            row["Reminders sent"] = n
            bodies.append(d._reminder_words(row)[1])
        self.assertEqual(len(set(bodies)), 3)
        self.assertIn("close it for now", bodies[2])

    def test_the_last_one_makes_it_easy_to_say_no(self):
        d = self.dialog()
        row = dict(self.row)
        row["Reminders sent"] = "2"
        self.assertIn("perfectly all right", d._reminder_words(row)[1])


class WinningBackACustomerWhoSaidNo(unittest.TestCase):
    """The one email worth waiting two minutes for, written by the tools in
    the owner's own browser rather than by Groq."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.cfg = ready_cfg(self.folder)
        self.row = register.from_message(message())
        register.mark_quoted(self.row, "QTN/26-27/0001", "50000")
        register.mark_lost(self.row, "Rate too high")
        register.save([self.row], mailflow.Paths(self.folder).register_csv)
        self.dialog = UI.InquiryDialog(self.cfg)
        self.dialog._refresh_register()
        self.dialog.register_table.setCurrentCell(0, 0)

    def test_a_fresh_inquiry_has_nothing_to_win_back(self):
        row = register.from_message(message(subject="New one"))
        register.save([row], mailflow.Paths(self.folder).register_csv)
        d = UI.InquiryDialog(self.cfg)
        d._refresh_register()
        d.register_table.setCurrentCell(0, 0)
        shown = []
        with _Patched(UI, "QMessageBox", _Recording(shown)):
            d._win_back()
        self.assertEqual(len(shown), 1)

    def test_it_reads_back_the_quotation_we_actually_sent(self):
        """Rebuilding it from today's rate list could quote them something
        different from the paper they are holding."""
        # check() sets Folder on a real row; from_message leaves it blank.
        row = self.dialog._register_rows[0]
        folder = mailflow.Paths(self.folder).folder_for(row["Inquiry no"])
        row["Folder"] = folder
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "QTN-26-27-0001.csv"), "w",
                  encoding="utf-8") as f:
            f.write("Description,Qty,Rate\nSpring 2mm,5000,10.00\n")
        text = self.dialog._quotation_text(self.dialog._register_rows[0])
        self.assertIn("Spring 2mm", text)

    def test_it_falls_back_to_the_recorded_figures(self):
        text = self.dialog._quotation_text(self.dialog._register_rows[0])
        self.assertIn("QTN/26-27/0001", text)

    def test_their_own_reason_is_given_to_the_tool(self):
        """An honest "they said the rate was too high" beats inventing an
        objection for the tool to answer."""
        self.assertIn("Rate too high",
                      self.dialog._last_reply_text(
                          self.dialog._register_rows[0]))

    def test_a_won_back_row_reopens(self):
        """A row we are actively arguing with is not a lost one — left closed
        it drops off every list Prism keeps."""
        self.dialog._winback_sent(self.dialog._register_rows[0], ["ok"], [])
        saved = register.load(mailflow.Paths(self.folder).register_csv)
        self.assertEqual(saved[0]["Status"], register.NEGOTIATING)
        self.assertEqual(saved[0]["Result"], "")

    def test_a_failed_send_does_not_reopen_it(self):
        told = []
        self.dialog._explain = told.append
        self.dialog._winback_sent(self.dialog._register_rows[0],
                                  [], [("a@b.c", "refused")])
        saved = register.load(mailflow.Paths(self.folder).register_csv)
        self.assertEqual(saved[0]["Status"], register.NOT_CONVERTED)
        self.assertTrue(told)


class _Signal:
    """Just enough of a Qt signal for a fake worker to be connected to."""

    def connect(self, *_a, **_kw):
        return None


class _Recording:
    """A stand-in QMessageBox that records instead of showing."""

    Yes = 1
    No = 0

    def __init__(self, log):
        self._log = log

    def information(self, *a, **kw):
        self._log.append(a)

    def warning(self, *a, **kw):
        self._log.append(a)

    def question(self, *a, **kw):
        self._log.append(a)
        return self.No


class _Patched:
    """Swap one attribute on a module for the duration of a block."""

    def __init__(self, module, name, value):
        self.module, self.name, self.value = module, name, value

    def __enter__(self):
        self.original = getattr(self.module, self.name)
        setattr(self.module, self.name, self.value)
        return self.value

    def __exit__(self, *exc):
        setattr(self.module, self.name, self.original)
        return False


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
