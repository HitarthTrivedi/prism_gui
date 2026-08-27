"""The Inquiry Automation *screen* — the redesign's read-only surface.

tests/test_inquiry_ui.py covers the working dialog: setting up a mailbox,
sorting what arrived, correcting a mis-sort. This file covers the screen the
rail now lands on, and the dashboard_data layer underneath it.

Four things it defends:

  · **Every figure comes out of the register.** The design's screen is full of
    invented spring-manufacturer numbers. If any of them survives into the
    product as a hardcoded value, the first customer to notice stops believing
    the other three.
  · **Empty and zero are different.** No register configured must show the way
    in, not a wall of zeroes — those mean opposite things to somebody deciding
    whether the add-on is working.
  · **A real CSV is hostile.** It is edited in Excel by hand, so it arrives
    with unparseable dates, money with words in it, and statuses nobody
    defined. None of that may take the screen down.
  · **The licence gate still holds.** The screen reads a register the customer
    may not own, so it must sit behind the same `inbox` check the dialog did.

Nothing here writes to the developer's own ~/.prism — every register lives in
a tempdir, and the config is built by hand rather than loaded.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

from datetime import date, timedelta
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# No PRISM_LICENSE_OFFLINE_DEV here. Nothing in this file needs it — every
# licence answer it depends on is mocked — and setting it at module scope set
# it for the whole process, because pytest imports every test module during
# collection. That opened licensing's offline-dev bypass underneath the
# revoked-licence test in test_authorization.py. See tests/conftest.py.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

import core_bridge as CB  # noqa: E402
import dashboard_data as DATA  # noqa: E402
import licensing  # noqa: E402
from licensing.status import LicenseState  # noqa: E402
from widgets.inquiry_panel import TABS, InquiryPanel  # noqa: E402

_app = QApplication.instance() or QApplication([])

REG = CB.get_register()
MAILFLOW = CB.get_mailflow()

# The docstring above promises the config is built by hand rather than loaded.
# It was not quite true: MainWindow() calls config.load(), so the tests that
# build one were reading whoever is running them. On a machine where Prism has
# actually been used — which is every machine that matters — the inquiry panel
# came up holding that person's real register, and the test asserting a fresh
# screen starts empty failed for a reason that had nothing to do with the code.
#
# Pointing CONFIG_PATH at a file that does not exist makes load() return its
# defaults, which is what "built by hand" was always meant to mean.
_REAL_CONFIG_PATH = CB.config.CONFIG_PATH
_SCRATCH = tempfile.mkdtemp(prefix="prism-test-screen-")


def setUpModule():
    CB.config.CONFIG_PATH = os.path.join(_SCRATCH, "config.json")


def tearDownModule():
    CB.config.CONFIG_PATH = _REAL_CONFIG_PATH


def blank(**values) -> dict:
    """An empty register row with only the named columns filled."""
    row = dict.fromkeys(REG.COLUMNS, "")
    row.update(values)
    return row


def written(rows, folder: str) -> dict:
    """Save `rows` as a real register under `folder`; return a matching cfg."""
    paths = MAILFLOW.Paths(folder)
    paths.ensure()
    REG.save(rows, paths.register_csv)
    return {"inquiry": {"folder": folder}}


def sample_rows(today: date | None = None) -> list[dict]:
    """One row in each state that renders differently."""
    today = today or date.today()
    fmt = "%Y-%m-%d"
    return [
        blank(**{"Inquiry no": "INQ/1", "Customer": "Everest Auto",
                 "Product asked": "Compression springs", "Quantity": "5000",
                 "Status": REG.QUOTED, "Quotation no": "Q1",
                 "Quotation value": "186000",
                 "Date received": today.strftime(fmt),
                 "Quotation date": (today - timedelta(days=9)).strftime(fmt),
                 "Reminders sent": "1"}),
        blank(**{"Inquiry no": "INQ/2", "Customer": "Konkan Precision",
                 "Product asked": "Torsion springs", "Status": REG.NEW,
                 "Date received": today.strftime(fmt)}),
        blank(**{"Inquiry no": "INQ/3", "Customer": "Shreeji Auto",
                 "Status": REG.CONVERTED, "Quotation no": "Q3",
                 "Quotation value": "210000", "Order value": "210000",
                 "Date received": (today - timedelta(days=20)).strftime(fmt)}),
        blank(**{"Inquiry no": "INQ/4", "Customer": "Vadodara Wire",
                 "Status": REG.NOT_CONVERTED, "Quotation no": "Q4",
                 "Quotation value": "38200", "Reason if lost": "Price",
                 "Date received": (today - timedelta(days=30)).strftime(fmt)}),
    ]


class NoRegisterYet(unittest.TestCase):
    """Zero inquiries and no register at all are different facts."""

    def test_stats_are_none_when_unconfigured(self):
        self.assertIsNone(DATA.inquiry_stats({}))

    def test_stats_are_none_when_the_file_is_missing(self):
        """A configured folder that has never been written to. Common: setup
        finished, no mail checked yet."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"inquiry": {"folder": os.path.join(tmp, "not-created")}}
            self.assertIsNone(DATA.inquiry_stats(cfg))
            self.assertEqual(DATA.register_rows(cfg), [])

    def test_the_screen_builds_and_offers_the_way_in(self):
        panel = InquiryPanel({})
        self.assertIsNotNone(panel)
        # set_up is what the empty state's button fires. If it ever stops
        # existing the empty state becomes a dead end.
        self.assertTrue(hasattr(panel, "set_up"))

    def test_a_configured_mailbox_offers_check_not_setup_again(self):
        """The real bug this class exists to describe, finally covered: a
        mailbox that connects and saves still has an empty register until
        somebody actually checks it. Offering only "Set up Email automation"
        here sent a working setup back into the setup sheet forever — Setup
        saves, returns to this same empty screen, nothing has read the
        inbox, the screen greets it again. The way out of THIS empty state
        is Check, not Setup."""
        cfg = {"inquiry": {"accounts": [{"address": "het@example.com",
                                        "password": "x"}]}}
        panel = InquiryPanel(cfg)
        card = panel._not_set_up()
        buttons = [w for w in card.findChildren(QPushButton)]
        labels = [b.text() for b in buttons]
        self.assertIn("Check my mail now", labels)
        self.assertNotIn("Set up Email automation", labels)
        check_btn = next(b for b in buttons if b.text() == "Check my mail now")
        fired = []
        panel.open_dialog.connect(lambda: fired.append(True))
        check_btn.click()
        self.assertEqual(fired, [True])

    def test_an_unconfigured_mailbox_still_offers_setup(self):
        panel = InquiryPanel({})
        card = panel._not_set_up()
        labels = [b.text() for b in card.findChildren(QPushButton)]
        self.assertIn("Set up Email automation", labels)
        self.assertNotIn("Check my mail now", labels)


class TheFiguresComeFromTheRegister(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cfg = written(sample_rows(), self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_open_counts_only_open_statuses(self):
        """Quoted and New are open; Converted and Not converted are done. A
        count that includes closed rows makes the number meaningless."""
        self.assertEqual(DATA.inquiry_stats(self.cfg)["open"], 2)

    def test_quoted_value_is_compact_rupees(self):
        value = DATA.inquiry_stats(self.cfg)["quoted_value"]
        self.assertTrue(value.startswith("₹"), value)

    def test_win_rate_is_a_number(self):
        self.assertIsInstance(DATA.inquiry_stats(self.cfg)["win_rate"],
                              (int, float))

    def test_every_row_reaches_the_table(self):
        self.assertEqual(len(DATA.register_view(self.cfg)), 4)

    def test_status_tones_are_semantic(self):
        """Won green, lost red, in-flight accent, untouched neutral. These
        must not drift onto the accent ramp — the whole point is that they
        stay put when the role hue rotates."""
        tones = {r["num"]: r["tone"] for r in DATA.register_view(self.cfg)}
        self.assertEqual(tones["INQ/3"], "ok")        # Converted
        self.assertEqual(tones["INQ/4"], "err")       # Not converted
        self.assertEqual(tones["INQ/2"], "neutral")   # New
        self.assertEqual(tones["INQ/1"], "accent")    # Quoted

    def test_money_is_grouped_in_lakhs_without_paise(self):
        amounts = {r["num"]: r["amount"] for r in DATA.register_view(self.cfg)}
        self.assertEqual(amounts["INQ/1"], "₹1,86,000")

    def test_an_unquoted_row_shows_a_dash_not_zero(self):
        """₹0.00 reads as a quote for nothing rather than as no quote yet."""
        amounts = {r["num"]: r["amount"] for r in DATA.register_view(self.cfg)}
        self.assertEqual(amounts["INQ/2"], "—")

    def test_waiting_rows_carry_days_and_reminders(self):
        for row in DATA.waiting_view(self.cfg):
            self.assertIsInstance(row["sent_days"], int)
            self.assertTrue(row["reminders"])

    def test_inquiries_per_day_buckets_today_last(self):
        series = DATA.inquiries_per_day(self.cfg)
        self.assertEqual(len(series), 7)
        self.assertEqual(series[-1], 2)   # two rows dated today

    def test_every_tab_builds(self):
        for tab in ("arrived", "register", "replies", "waiting"):
            with self.subTest(tab=tab):
                panel = InquiryPanel(self.cfg)
                panel._pick(tab)


class ThePopulatedScreenAlwaysOffersTheWorkingDialog(unittest.TestCase):
    """Reading a mail, editing a register field, and preparing a quotation
    all happen in the working dialog behind this screen — this screen is a
    report. The only place that ever fired open_dialog was "Chase again",
    which exists solely on the "gone quiet" tab, and only once something is
    actually overdue for a follow-up.

    Two brand-new inquiries — Status New, received today, nothing quoted
    yet — is a real customer's first day using this, and awaiting_followup()
    only ever considers QUOTED / FOLLOWING_UP / NEGOTIATING rows. A New row
    is never overdue, so "Chase again" never renders, and the whole screen
    was left with no door into the dialog at all."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        today = date.today().strftime("%Y-%m-%d")
        rows = [
            blank(**{"Inquiry no": "INQ/1", "Customer": "Shreeji Auto",
                     "Status": REG.NEW, "Date received": today}),
            blank(**{"Inquiry no": "INQ/2", "Customer": "Konkan Precision",
                     "Status": REG.NEW, "Date received": today}),
        ]
        self.cfg = written(rows, self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_the_fixture_actually_has_nothing_overdue(self):
        """If this fails, the rest of the class proves nothing — it would
        mean the fixture drifted and stopped matching the real bug."""
        self.assertEqual(DATA.inquiry_stats(self.cfg)["waiting"], 0)

    def test_the_working_dialog_is_still_reachable(self):
        panel = InquiryPanel(self.cfg)
        fired = []
        panel.open_dialog.connect(lambda: fired.append(True))
        opener = next((b for b in panel.findChildren(QPushButton)
                      if b.text() == "Check my mail now"), None)
        self.assertIsNotNone(
            opener,
            "no button anywhere on the populated screen opens the working "
            "dialog — reading mail, editing the register and preparing a "
            "quotation are all unreachable")
        opener.click()
        self.assertEqual(fired, [True])

    def test_it_is_still_there_on_every_tab(self):
        for _key, label in TABS:
            with self.subTest(tab=label):
                panel = InquiryPanel(self.cfg)
                panel._pick(_key)
                labels = [b.text() for b in panel.findChildren(QPushButton)]
                self.assertIn("Check my mail now", labels)


class AHostileRegister(unittest.TestCase):
    """The register is a CSV people edit in Excel. It arrives damaged."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cfg = written([
            blank(**{"Inquiry no": "BAD/1", "Customer": "",
                     "Status": "", "Quotation value": "not a number",
                     "Date received": "garbage", "Reminders sent": "many"}),
            blank(**{"Inquiry no": "BAD/2", "Customer": "Zero Co",
                     "Status": "Some Unknown Status",
                     "Quotation value": "-500",
                     "Date received": "31-02-2026"}),   # not a real date
        ], self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_stats_survive(self):
        self.assertIsNotNone(DATA.inquiry_stats(self.cfg))

    def test_no_row_is_silently_dropped(self):
        """Losing somebody's inquiry because its date would not parse is worse
        than showing it with a blank date."""
        self.assertEqual(len(DATA.register_view(self.cfg)), 2)

    def test_an_unknown_status_still_gets_a_tone(self):
        tone = DATA.register_view(self.cfg)[1]["tone"]
        self.assertIn(tone, ("accent", "neutral"))

    def test_money_with_words_in_it_does_not_raise(self):
        self.assertIsInstance(DATA.register_view(self.cfg)[0]["amount"], str)

    def test_every_tab_still_builds(self):
        for tab in ("arrived", "register", "replies", "waiting"):
            with self.subTest(tab=tab):
                panel = InquiryPanel(self.cfg)
                panel._pick(tab)


def _licence(features) -> LicenseState:
    return LicenseState(status=licensing.VALID, plan="Growth",
                        customer="Test", kind="team",
                        features=frozenset(features), seats=3,
                        license_id="7F3A", license_ends=2 ** 31 - 1,
                        token_expires=2 ** 31 - 1, grace_days=7)


class TheLicenceGateStillHolds(unittest.TestCase):
    """The screen reads a register the customer may not have bought."""

    def setUp(self):
        self._real_state, self._real_reload = licensing.state, licensing.reload

    def tearDown(self):
        licensing.state, licensing.reload = self._real_state, self._real_reload

    def _grant(self, features):
        licensing.state = lambda: _licence(features)
        licensing.reload = lambda: _licence(features)

    def test_without_the_feature_it_goes_through_the_gate(self):
        import main_window
        self._grant({"core"})
        asked = []
        with mock.patch.object(main_window.MainWindow, "_authorized_then",
                               lambda self, feat, act, then: asked.append(feat)):
            win = main_window.MainWindow()
            win._handle_command("inquiry")
            self.assertEqual(asked, ["inbox"])
            self.assertNotEqual(win.screens.currentIndex(), main_window.INQUIRY)

    def test_with_the_feature_it_reaches_the_screen(self):
        import main_window
        self._grant({"core", "inbox"})
        with mock.patch.object(main_window.MainWindow, "_authorized_then",
                               lambda self, feat, act, then: then()):
            win = main_window.MainWindow()
            win._handle_command("inquiry")
            self.assertEqual(win.screens.currentIndex(), main_window.INQUIRY)

    def test_a_locked_row_stays_clickable(self):
        """A padlocked add-on opens its pitch. A disabled one sells nothing
        and is indistinguishable from something broken."""
        import main_window
        self._grant({"core"})
        win = main_window.MainWindow()
        win.refresh_licence_ui()
        row, _label, _icon, _feature = win.sidebar._gated["inquiry"]
        self.assertTrue(row.property("locked"))
        self.assertTrue(row.isEnabled())

    def test_the_banner_recovers_once_a_background_refresh_lands(self):
        """The window is built from the cached token while _licence_gate's
        refresh is still in flight. If that token is past its offline window
        the banner correctly says so — and then the refresh lands a second
        later and the banner has to stop saying it.

        It did not. The only repaint was on a TEN MINUTE timer, so a customer
        whose licence had already fixed itself sat looking at "Prism hasn't
        been able to reach the licence server" and an "Enter a licence key"
        button, which reads as being asked to buy what they have paid for.
        """
        import main_window

        stale = LicenseState(status=licensing.STALE, plan="Growth",
                             customer="Test", kind="team",
                             features=frozenset({"core", "inbox"}), seats=3,
                             license_id="7F3A", license_ends=2 ** 31 - 1,
                             token_expires=0, grace_days=7)
        licensing.state = lambda: stale
        licensing.reload = lambda: stale
        win = main_window.MainWindow()
        win.refresh_licence_ui()
        # isVisibleTo, not isVisible: the window is never shown in tests, so
        # isVisible() is False regardless and would pass either way.
        self.assertTrue(win.banner.isVisibleTo(win),
                        "a stale licence must show the banner")
        self.assertIn("reach the licence server", win._banner_text.text())

        # ...the background refresh lands, exactly as it did on the machine
        # that reported this.
        self._grant({"core", "inbox"})
        win._repaint_licence()
        self.assertFalse(win.banner.isVisibleTo(win),
                         "banner must go once the licence is valid again")

    def test_the_repaint_is_actually_scheduled_soon_after_launch(self):
        """The method above is only half of it. The bug was that nothing
        CALLED it for ten minutes, so this pins the schedule rather than the
        repaint — without it, disabling the singleShot calls leaves the other
        test passing and the customer still staring at a stale banner."""
        import main_window
        from PySide6.QtCore import QTimer

        self._grant({"core", "inbox"})
        scheduled = []
        real = QTimer.singleShot

        def capture(ms, target):
            scheduled.append((ms, getattr(target, "__name__", str(target))))

        with mock.patch.object(QTimer, "singleShot", staticmethod(capture)):
            main_window.MainWindow()

        repaints = [ms for ms, name in scheduled if name == "_repaint_licence"]
        self.assertTrue(repaints, "nothing repaints the licence after launch")
        self.assertLessEqual(
            min(repaints), 5_000,
            f"first repaint is {min(repaints)}ms away — a customer whose "
            f"licence fixes itself must not wait that long to be told")

    def test_an_owned_add_on_is_not_marked_locked(self):
        import main_window
        self._grant({"core", "inbox"})
        win = main_window.MainWindow()
        win.refresh_licence_ui()
        row, _label, _icon, _feature = win.sidebar._gated["inquiry"]
        self.assertFalse(row.property("locked"))


class TheScreenStaysInStepWithTheStore(unittest.TestCase):

    def setUp(self):
        self._real_state, self._real_reload = licensing.state, licensing.reload
        licensing.state = lambda: _licence({"core", "inbox"})
        licensing.reload = lambda: _licence({"core", "inbox"})
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        licensing.state, licensing.reload = self._real_state, self._real_reload
        self._tmp.cleanup()

    def test_refresh_picks_up_a_register_written_after_load(self):
        """The dialog works the register while the screen is behind it, so the
        screen is stale the moment the dialog closes."""
        import main_window
        win = main_window.MainWindow()
        self.assertFalse(win.inquiry_panel._rows)

        cfg = written(sample_rows(), self._tmp.name)
        win.inquiry_panel.cfg = cfg
        win.inquiry_panel.refresh()
        self.assertEqual(len(win.inquiry_panel._rows), 4)

    def test_set_up_opens_setup_not_the_working_dialog(self):
        """It used to route through the working dialog, which opened setup
        itself — three stacked windows for one click."""
        import main_window
        opened = []
        with mock.patch.object(main_window.MainWindow, "_open_inquiry_setup",
                               lambda self: opened.append("setup")), \
             mock.patch.object(main_window.MainWindow, "_open_inquiry_dialog",
                               lambda self: opened.append("dialog")):
            win = main_window.MainWindow()
            win.inquiry_panel.set_up.emit()
            self.assertEqual(opened, ["setup"])

    def test_chase_again_opens_the_working_dialog(self):
        import main_window
        opened = []
        with mock.patch.object(main_window.MainWindow, "_open_inquiry_dialog",
                               lambda self: opened.append("dialog")):
            win = main_window.MainWindow()
            win.inquiry_panel.open_dialog.emit()
            self.assertEqual(opened, ["dialog"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
