"""The customer's credit screens — Apollo's, in Prism's shape (24-Sep-2026).

The balance pill opens a small "Team credit usage" card (Upgrade plan / View
usage); View usage is the Credit usage page (Overview with a donut, Usage details
as the activity list, About credits); Upgrade is Select plan → Add-ons → Payment →
Review, and ends in a REQUEST to Alphakore because nothing here takes a card.

A fake licence server answers /v1/credits/*, and the workers that would call it
on a thread are swapped for ones that run inline — a test never starts a thread,
never spins an event loop and never touches the network or ~/.prism.
"""
from __future__ import annotations

import csv
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QObject, Signal                       # noqa: E402
from PySide6.QtWidgets import QApplication                       # noqa: E402

import core_bridge  # noqa: F401,E402  (puts prism_terminal/core on sys.path)
from addons.leads import credits_page as CP                      # noqa: E402
from addons.leads import workbench as WB                         # noqa: E402
from addons.leads.workers import CreditsCallWorker as RealWorker  # noqa: E402
from prospector import gateway as G                              # noqa: E402

from test_leads_credit_pool import RATES, _PooledScreen          # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

NOW = int(time.time())
DAY = 86400


def usage_payload(**over) -> dict:
    """What /v1/credits/usage answers for a licence on a plan, four features used."""
    out = {
        "balance": 1904, "allowance": 2000, "rollover": False,
        "plan": "growth", "plan_name": "Growth",
        "cycle": {"start": NOW - 5 * DAY, "end": NOW + 25 * DAY, "days": 30},
        "window": {"min_at": NOW - 5 * DAY, "max_at": NOW}, "used": 96,
        "by_action": [
            {"action": "people_search", "name": "Find people", "credits": 42, "calls": 14},
            {"action": "email_find", "name": "Find e-mails", "credits": 24, "calls": 12},
            {"action": "ai_qualify", "name": "Qualify with AI", "credits": 18, "calls": 18},
            {"action": "email_verify", "name": "Verify e-mails", "credits": 12, "calls": 12}],
        "by_member": [{"id": 1, "name": "Harsh's laptop", "credits": 70, "you": True},
                      {"id": 2, "name": "Seat 2", "credits": 26, "you": False}],
        "members": [{"id": 1, "name": "Harsh's laptop", "you": True},
                    {"id": 2, "name": "Seat 2", "you": False}],
        "actions": [{"action": "people_search", "name": "Find people"},
                    {"action": "email_find", "name": "Find e-mails"},
                    {"action": "ai_qualify", "name": "Qualify with AI"}],
        "activity": [
            {"id": 9, "at": NOW - 3600, "kind": "spend", "action": "people_search",
             "name": "Find people", "member": "Harsh's laptop", "delta": -3,
             "balance_after": 1904, "note": ""},
            {"id": 1, "at": NOW - 5 * DAY, "kind": "allowance", "action": "", "name": "",
             "member": "", "delta": 2000, "balance_after": 2000, "note": "Plan started"}],
    }
    out.update(over)
    return out


def offers_payload(**over) -> dict:
    out = {"offers": [
        {"key": "starter", "kind": "plan", "name": "Starter", "blurb": "A few searches a month.",
         "credits": 500, "cycle_days": 30, "price_inr": None},
        {"key": "growth", "kind": "plan", "name": "Growth", "blurb": "Weekly prospecting.",
         "credits": 2000, "cycle_days": 30, "price_inr": 4999},
        {"key": "scale", "kind": "plan", "name": "Scale", "blurb": "Every day.",
         "credits": 6000, "cycle_days": 30, "price_inr": 1234567},
        {"key": "pack-500", "kind": "pack", "name": "500 credits", "blurb": "One-off.",
         "credits": 500, "cycle_days": 0, "price_inr": 999}],
        "balance": 1904, "plan": "growth", "allowance": 2000, "requests": []}
    out.update(over)
    return out


class CreditsServer:
    """The licence server's /v1/credits/*, as a transport for prospector.gateway."""

    def __init__(self):
        self.calls: list = []                   # (op, body)
        self.usage = usage_payload()
        self.offers = offers_payload()
        self.fail: dict = {}                    # op -> GatewayError

    def __call__(self, path: str, body: dict) -> dict:
        op = path.rsplit("/", 1)[-1]
        self.calls.append((op, body))
        if op in self.fail:
            raise self.fail[op]
        if op == "status":
            return {"balance": self.usage["balance"], "rates": RATES, "ready": {}}
        if op == "usage":
            return self.usage
        if op == "offers":
            return self.offers
        if op == "request":
            return {"request": {"id": len(self.calls), "offer_key": body["offer_key"],
                                "status": "new"}, "created": True}
        raise AssertionError(path)

    def ops(self) -> list:
        return [op for op, _ in self.calls]

    def bodies(self, op: str) -> list:
        return [b for o, b in self.calls if o == op]


class SyncCall(QObject):
    """CreditsCallWorker without the thread: start() makes the call inline and
    emits, so signals reach their slots directly."""
    done = Signal(str, dict)
    failed = Signal(str, str)

    def __init__(self, what: str, **params):
        super().__init__()
        assert what in RealWorker.WHAT, what
        self.what, self.params = what, params

    def start(self):
        call = {"usage": G.credit_usage, "offers": G.credit_offers,
                "request": G.request_offer}[self.what]
        try:
            out = call(**self.params)
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(self.what, getattr(e, "message", "") or str(e))
            return
        self.done.emit(self.what, out)


class _Screens(unittest.TestCase):
    """A fake server, inline workers, and no real licence state."""

    def setUp(self):
        self.server = CreditsServer()
        G.set_transport(self.server)
        for patch in (
                mock.patch.object(G, "_auth_body", lambda **extra: {
                    "license_id": "L-TEST", "device_fp": "D-TEST", "app_version": "0", **extra}),
                mock.patch.object(CP, "CreditsCallWorker", SyncCall),
                mock.patch.object(WB, "CreditsCallWorker", SyncCall)):
            patch.start()
            self.addCleanup(patch.stop)

    def tearDown(self):
        G.forget()

    def usage_dialog(self, **kw):
        dlg = CP.CreditUsageDialog(kw.pop("rates", RATES))
        self.addCleanup(dlg.close)
        return dlg

    def upgrade_dialog(self):
        dlg = CP.UpgradeDialog()
        self.addCleanup(dlg.close)
        return dlg


# ── the calls to the server ──────────────────────────────────────────────────

@pytest.mark.pooled
class TheCreditAccountCalls(_Screens):

    def test_only_the_filters_that_were_set_are_sent(self):
        G.credit_usage()
        G.credit_usage(min_at=100, device_id=3, action="email_find", limit=50)
        first, second = self.server.bodies("usage")
        self.assertEqual({k for k in first} & {"min_at", "max_at", "device_id", "action", "limit"},
                         {"limit"})                               # the limit always goes
        self.assertEqual((second["min_at"], second["device_id"], second["action"], second["limit"]),
                         (100, 3, "email_find", 50))
        self.assertEqual(second["license_id"], "L-TEST")

    def test_min_at_of_zero_is_sent_because_it_means_all_time(self):
        G.credit_usage(min_at=0)
        self.assertIn("min_at", self.server.bodies("usage")[0])
        self.assertEqual(self.server.bodies("usage")[0]["min_at"], 0)

    def test_a_read_keeps_the_balance_the_pill_and_the_run_line_use(self):
        self.assertIsNone(G.known_balance())
        G.credit_offers()
        self.assertEqual(G.known_balance(), 1904)

    def test_a_request_carries_the_offer_and_the_note(self):
        G.request_offer("growth", "start from the 1st")
        self.assertEqual(self.server.bodies("request")[0]["offer_key"], "growth")
        self.assertEqual(self.server.bodies("request")[0]["note"], "start from the 1st")

    def test_a_server_refusal_is_raised_with_its_own_sentence(self):
        self.server.fail["offers"] = G.GatewayError("DEVICE_NOT_ACTIVATED", "This machine isn't set up.")
        with self.assertRaises(G.GatewayError) as caught:
            G.credit_offers()
        self.assertEqual(caught.exception.message, "This machine isn't set up.")

    def test_the_worker_only_makes_the_three_calls_it_knows(self):
        with self.assertRaises(ValueError):
            RealWorker("buy")
        for what in ("usage", "offers", "request"):
            self.assertEqual(RealWorker(what).what, what)


# ── the formatting ───────────────────────────────────────────────────────────

class TheNumbers(unittest.TestCase):

    def test_rupees_use_indian_grouping(self):
        self.assertEqual([CP.rupees(n) for n in (0, 999, 4999, 12999, 100000, 1234567)],
                         ["₹0", "₹999", "₹4,999", "₹12,999", "₹100,000".replace("100,000", "1,00,000"),
                          "₹12,34,567"])

    def test_a_price_says_ask_until_one_is_set(self):
        self.assertEqual(CP.price_text({"kind": "plan", "price_inr": None}), "Ask Alphakore")
        self.assertEqual(CP.price_text({"kind": "plan", "price_inr": 4999, "cycle_days": 30}), "₹4,999 / month")
        self.assertEqual(CP.price_text({"kind": "plan", "price_inr": 49999, "cycle_days": 365}), "₹49,999 / year")
        self.assertEqual(CP.price_text({"kind": "plan", "price_inr": 900, "cycle_days": 7}), "₹900 / 7 days")
        self.assertEqual(CP.price_text({"kind": "pack", "price_inr": 999}), "₹999 once")

    def test_credits_read_as_one_credit_or_many(self):
        self.assertEqual((CP.credits_text(1), CP.credits_text(1240)), ("1 credit", "1,240 credits"))

    def test_a_date_reads_the_way_apollo_prints_it(self):
        self.assertRegex(CP.when(NOW), r"^[A-Z][a-z]{2} \d{1,2}, \d{4}, \d{1,2}:\d{2} [AP]M$")
        self.assertRegex(CP.when(NOW, with_time=False), r"^[A-Z][a-z]{2} \d{1,2}, \d{4}$")
        self.assertEqual(CP.when("nonsense"), "")


# ── the card behind the pill ─────────────────────────────────────────────────

@pytest.mark.pooled
class TheTeamCreditUsageCard(_Screens):

    def test_a_plan_shows_used_of_allowance_a_bar_and_the_renewal(self):
        card = CP.CreditCard()
        self.addCleanup(card.close)
        card.set_usage(usage_payload())
        self.assertEqual(card.headline.text(), "96 of 2,000 credits")
        self.assertEqual(card.left.text(), "1,904 credits left")
        self.assertFalse(card.bar.isHidden())
        self.assertTrue(card.note.text().startswith("Renews "))
        self.assertEqual((card.upgrade.text(), card.view.text()), ("Upgrade plan", "View usage"))

    def test_a_plain_pool_shows_what_is_left_and_no_bar(self):
        card = CP.CreditCard()
        self.addCleanup(card.close)
        card.set_usage(usage_payload(allowance=0, cycle=None, plan="", balance=1240, used=96))
        self.assertEqual(card.headline.text(), "1,240 credits left")
        self.assertTrue(card.bar.isHidden())
        self.assertEqual(card.note.text(), "96 credits used in the last 30 days")

    def test_it_says_when_the_credits_could_not_be_read(self):
        card = CP.CreditCard()
        self.addCleanup(card.close)
        card.set_error("Couldn't reach Prism's licence server.")
        self.assertEqual(card.headline.text(), "Your credits couldn't be read")
        self.assertIn("licence server", card.note.text())

    def test_the_buttons_say_what_they_were_pressed_for(self):
        card = CP.CreditCard()
        self.addCleanup(card.close)
        seen = []
        card.upgradeRequested.connect(lambda: seen.append("upgrade"))
        card.usageRequested.connect(lambda: seen.append("usage"))
        card.upgrade.click()
        card.view.click()
        self.assertEqual(seen, ["upgrade", "usage"])


@pytest.mark.pooled
class ThePillOpensIt(_PooledScreen, _Screens):

    def setUp(self):
        _PooledScreen.setUp(self)
        _Screens.setUp(self)

    def tearDown(self):
        _Screens.tearDown(self)
        _PooledScreen.tearDown(self)

    def test_clicking_the_pill_drops_the_card_with_this_licences_numbers(self):
        wb = self._bench()
        wb._show_credits()
        pop = wb._credit_popover
        self.addCleanup(pop.close)
        self.assertEqual(pop.card.headline.text(), "96 of 2,000 credits")
        self.assertIn("usage", self.server.ops())
        first = pop
        wb._show_credits()
        self.assertIs(wb._credit_popover, first)                # one card, re-read each click

    def test_a_server_that_cannot_be_reached_says_so_on_the_card(self):
        wb = self._bench()
        self.server.fail["usage"] = G.GatewayError("UNREACHABLE", "Couldn't reach Prism's licence server.")
        wb._show_credits()
        self.addCleanup(wb._credit_popover.close)
        self.assertEqual(wb._credit_popover.card.headline.text(), "Your credits couldn't be read")

    def test_view_usage_opens_the_credit_usage_page_and_upgrade_the_flow(self):
        wb = self._bench()
        wb._show_credits()
        self.addCleanup(wb._credit_popover.close)
        wb._credit_popover.card.view.click()
        self.assertIsInstance(wb._credit_dlg, CP.CreditUsageDialog)
        self.addCleanup(wb._credit_dlg.close)
        self.assertEqual(wb._credit_dlg.windowTitle(), "Credit usage")
        wb._credit_popover.card.upgrade.click()
        self.assertIsInstance(wb._upgrade_dlg, CP.UpgradeDialog)
        self.addCleanup(wb._upgrade_dlg.close)

    def test_the_usage_page_hands_its_own_upgrade_button_on(self):
        wb = self._bench()
        wb._open_credit_usage()
        self.addCleanup(wb._credit_dlg.close)
        wb._credit_dlg.add_credits.click()
        self.assertIsInstance(wb._upgrade_dlg, CP.UpgradeDialog)
        self.addCleanup(wb._upgrade_dlg.close)

    def test_the_price_list_the_page_shows_is_the_one_the_server_sent(self):
        wb = self._bench()
        wb._open_credit_usage()
        self.addCleanup(wb._credit_dlg.close)
        wb._credit_dlg._tabs.set_current(2)
        text = " ".join(lab.text() for lab in wb._credit_dlg._about_grid.parentWidget().findChildren(
            CP.QLabel))
        self.assertIn("3 credits", text)
        self.assertIn("1 credit", text)


# ── Credit usage ─────────────────────────────────────────────────────────────

@pytest.mark.pooled
class TheCreditUsagePage(_Screens):

    def test_the_overview_says_what_is_available_and_when_it_renews(self):
        dlg = self.usage_dialog()
        self.assertEqual(dlg.available.text(), "1,904 / 2,000")
        self.assertTrue(dlg.renews.text().startswith("Credits will renew on "))
        self.assertIn("Plan: Growth.", dlg.plan_line.text())
        self.assertIn("don't roll over", dlg.plan_line.text())

    def test_a_pool_with_no_plan_says_its_credits_do_not_expire(self):
        self.server.usage = usage_payload(allowance=0, cycle=None, plan="", plan_name="", balance=1240)
        dlg = self.usage_dialog()
        self.assertEqual(dlg.available.text(), "1,240")
        self.assertIn("don't expire", dlg.renews.text())
        self.assertEqual(dlg.plan_line.text(), "")

    def test_the_donut_is_cut_by_feature_and_the_legend_names_each_share(self):
        dlg = self.usage_dialog()
        self.assertEqual([v for v, _ in dlg.donut.slices()], [42, 24, 18, 12])
        self.assertEqual(dlg.donut._top, "96 of 2,000")
        self.assertEqual(dlg.donut._bottom, "credits used")
        text = " ".join(lab.text() for lab in dlg._legend.parentWidget().findChildren(CP.QLabel))
        self.assertIn("Find people", text)
        self.assertIn("44%", text)

    def test_team_members_regroups_it_and_marks_you(self):
        dlg = self.usage_dialog()
        dlg._group.set_current(1)
        self.assertEqual([v for v, _ in dlg.donut.slices()], [70, 26])
        text = " ".join(lab.text() for lab in dlg._legend.parentWidget().findChildren(CP.QLabel))
        self.assertIn("Harsh's laptop (you)", text)
        self.assertIn("Seat 2", text)

    def test_nothing_used_is_a_plain_grey_ring_and_says_so(self):
        self.server.usage = usage_payload(used=0, by_action=[], by_member=[], activity=[])
        dlg = self.usage_dialog()
        self.assertEqual(dlg.donut.slices(), [])
        self.assertEqual(dlg.donut._top, "0 of 2,000")
        self.assertTrue(dlg.table.isHidden())
        self.assertFalse(dlg.empty.isHidden())

    def test_the_activity_list_is_every_movement_newest_first(self):
        dlg = self.usage_dialog()
        self.assertEqual(dlg.table.rowCount(), 2)
        self.assertEqual([dlg.table.item(0, c).text() for c in (1, 2, 3, 4, 5)],
                         ["Spent", "Find people", "Harsh's laptop", "-3", "1,904"])
        self.assertEqual([dlg.table.item(1, c).text() for c in (1, 4, 5)],
                         ["Plan credits", "+2,000", "2,000"])

    def test_tabs_switch_pages_and_the_filters_hide_on_about_credits(self):
        dlg = self.usage_dialog()
        dlg._tabs.set_current(1)
        self.assertEqual(dlg._pages.currentIndex(), 1)
        self.assertFalse(dlg._filters.isHidden())
        dlg._tabs.set_current(2)
        self.assertEqual(dlg._pages.currentIndex(), 2)
        self.assertTrue(dlg._filters.isHidden())

    def test_the_default_window_is_the_cycle_and_asks_the_server_for_nothing_more(self):
        self.usage_dialog()
        body = self.server.bodies("usage")[0]
        for absent in ("min_at", "max_at", "device_id", "action"):
            self.assertNotIn(absent, body)

    def test_picking_a_date_a_member_and_a_feature_asks_the_server_again(self):
        dlg = self.usage_dialog()
        before = len(self.server.bodies("usage"))
        dlg.date_box.setCurrentIndex(dlg.date_box.findData(7))
        dlg.member_box.setCurrentIndex(dlg.member_box.findData(2))
        dlg.feature_box.setCurrentIndex(dlg.feature_box.findData("email_find"))
        bodies = self.server.bodies("usage")[before:]
        self.assertEqual(len(bodies), 3)
        last = bodies[-1]
        self.assertAlmostEqual(last["min_at"], int(time.time()) - 7 * DAY, delta=5)
        self.assertEqual((last["device_id"], last["action"]), (2, "email_find"))

    def test_all_time_asks_from_the_beginning(self):
        dlg = self.usage_dialog()
        dlg.date_box.setCurrentIndex(dlg.date_box.findData(0))
        self.assertEqual(self.server.bodies("usage")[-1]["min_at"], 0)

    def test_a_licence_without_a_plan_offers_thirty_days_first(self):
        self.server.usage = usage_payload(allowance=0, cycle=None, plan="")
        dlg = self.usage_dialog()
        self.assertEqual(dlg.date_box.itemText(0), "Last 30 days")
        self.assertEqual([dlg.date_box.itemText(i) for i in range(dlg.date_box.count())].count("Last 30 days"), 1)

    def test_a_plan_offers_the_current_cycle_first(self):
        dlg = self.usage_dialog()
        self.assertEqual(dlg.date_box.itemText(0), "Current billing cycle")

    def test_the_member_and_feature_choices_come_from_the_server_and_survive_a_refresh(self):
        dlg = self.usage_dialog()
        self.assertEqual([dlg.member_box.itemText(i) for i in range(dlg.member_box.count())],
                         ["All members", "Harsh's laptop (you)", "Seat 2"])
        dlg.member_box.setCurrentIndex(2)
        dlg.reload()
        self.assertEqual(dlg.member_box.currentData(), 2)

    def test_a_failed_read_says_why_on_the_page(self):
        self.server.fail["usage"] = G.GatewayError("UNREACHABLE", "Couldn't reach Prism's licence server.")
        dlg = self.usage_dialog()
        self.assertIn("licence server", dlg._status.text())

    def test_the_activity_exports_as_a_csv_excel_opens(self):
        dlg = self.usage_dialog()
        path = os.path.join(tempfile.mkdtemp(), "credit-activity.csv")
        self.assertEqual(dlg.write_csv(path), 2)
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
        self.assertEqual(rows[0], ["When", "What", "Feature", "Team member", "Credits", "Balance", "Note"])
        self.assertEqual(rows[1][1:6], ["Spent", "Find people", "Harsh's laptop", "-3", "1904"])
        with open(path, "rb") as f:
            self.assertEqual(f.read(3), b"\xef\xbb\xbf")               # a BOM, so Excel reads UTF-8

    def test_about_credits_lists_what_each_lookup_costs(self):
        dlg = self.usage_dialog()
        text = " ".join(lab.text() for lab in dlg._about_grid.parentWidget().findChildren(CP.QLabel))
        for cost in ("3 credits", "2 credits", "1 credit"):
            self.assertIn(cost, text)
        self.assertIn("Find people", text)                            # the short name, from the server

    def test_about_credits_does_not_repeat_a_title_as_its_own_detail(self):
        dlg = self.usage_dialog(rates={"email_find": {"credits": 2, "label": "E-mail address found"}})
        self.server.usage = usage_payload(actions=[])                  # no short name: the label is the title
        dlg.reload()
        labels = [lab.text() for lab in dlg._about_grid.parentWidget().findChildren(CP.QLabel)]
        self.assertEqual(labels.count("E-mail address found"), 1)


# ── Upgrade ──────────────────────────────────────────────────────────────────

@pytest.mark.pooled
class TheUpgradeFlow(_Screens):

    def test_plans_and_packs_are_listed_with_their_prices_or_ask(self):
        dlg = self.upgrade_dialog()
        self.assertEqual(set(dlg._cards), {"starter", "growth", "scale", "pack-500"})
        texts = {k: " ".join(lab.text() for lab in c.findChildren(CP.QLabel)) for k, c in dlg._cards.items()}
        self.assertIn("Ask Alphakore", texts["starter"])
        self.assertIn("₹4,999 / month", texts["growth"])
        self.assertIn("₹12,34,567 / month", texts["scale"])
        self.assertIn("500 credits, one time", texts["pack-500"])
        self.assertIn("₹999 once", texts["pack-500"])

    def test_the_current_plan_cannot_be_asked_for_again(self):
        dlg = self.upgrade_dialog()
        self.assertEqual(dlg._cards["growth"].button.text(), "Current plan")
        self.assertFalse(dlg._cards["growth"].button.isEnabled())
        dlg._choose("growth")                                          # even by code
        self.assertEqual(dlg._plan, "")                                # never picked
        for _ in range(3):
            dlg._go_next()
        self.assertFalse(dlg._next.isEnabled())                        # so nothing to send
        self.assertEqual(dlg._cards["growth"].state, "current")

    def test_a_request_already_open_is_shown_and_cannot_be_repeated(self):
        self.server.offers = offers_payload(requests=[{"offer_key": "scale", "status": "new"}])
        dlg = self.upgrade_dialog()
        self.assertEqual(dlg._cards["scale"].button.text(), "Requested")
        self.assertFalse(dlg._cards["scale"].button.isEnabled())
        self.assertIn("already asked for Scale", dlg._banner.text())
        self.assertFalse(dlg._banner.isHidden())
        dlg._choose("scale")                                           # even by code
        self.assertEqual(dlg._plan, "")

    def test_choosing_selects_one_plan_and_one_pack_and_choosing_again_unselects(self):
        dlg = self.upgrade_dialog()
        dlg._choose("starter")
        dlg._choose("scale")                                           # a second plan replaces the first
        self.assertEqual(dlg._plan, "scale")
        self.assertEqual(dlg._cards["scale"].button.text(), "Selected")
        self.assertEqual(dlg._cards["starter"].button.text(), "Select")
        dlg._choose("scale")
        self.assertEqual(dlg._plan, "")
        dlg._choose("pack-500")
        self.assertEqual(dlg._pack, "pack-500")

    def test_the_steps_run_select_addons_payment_review(self):
        dlg = self.upgrade_dialog()
        seen = []
        for _ in range(4):
            seen.append(dlg._pages.currentIndex())
            dlg._go_next()
        self.assertEqual(seen, [0, 1, 2, 3])
        dlg._go_back()
        self.assertEqual(dlg._pages.currentIndex(), 2)
        self.assertEqual(dlg._back.isHidden(), False)

    def test_payment_says_no_card_is_taken(self):
        dlg = self.upgrade_dialog()
        dlg._go_next(); dlg._go_next()
        text = " ".join(lab.text() for lab in dlg._pages.currentWidget().findChildren(CP.QLabel))
        self.assertIn("No card is taken here", text)
        self.assertIn("nothing is charged", text)

    def test_the_review_says_what_will_be_sent_and_send_needs_a_pick(self):
        dlg = self.upgrade_dialog()
        for _ in range(3):
            dlg._go_next()
        self.assertEqual(dlg._next.text(), "Send request")
        self.assertFalse(dlg._next.isEnabled())                        # nothing picked
        self.assertIn("haven't picked anything", dlg._review.text())
        dlg._go_back(); dlg._go_back(); dlg._go_back()
        dlg._choose("scale"); dlg._choose("pack-500")
        dlg._note.setPlainText("Start from the 1st")
        for _ in range(3):
            dlg._go_next()
        self.assertTrue(dlg._next.isEnabled())
        for expect in ("Scale — 6,000 credits every 30 days — ₹12,34,567 / month",
                       "500 credits, one time — ₹999 once", "Your note: Start from the 1st"):
            self.assertIn(expect, dlg._review.text())

    def test_send_asks_for_each_pick_in_turn_with_the_note_and_ends_on_the_done_page(self):
        dlg = self.upgrade_dialog()
        dlg._choose("scale"); dlg._choose("pack-500")
        dlg._note.setPlainText("Start from the 1st")
        for _ in range(4):
            dlg._go_next()                                             # the fourth press sends
        sent = self.server.bodies("request")
        self.assertEqual([b["offer_key"] for b in sent], ["scale", "pack-500"])
        self.assertTrue(all(b["note"] == "Start from the 1st" for b in sent))
        self.assertEqual(dlg._pages.currentIndex(), 4)
        self.assertIn("Alphakore has your request", dlg._done_text.text())
        self.assertEqual(dlg._next.text(), "Done")
        self.assertTrue(dlg._back.isHidden())

    def test_a_refused_request_says_why_stops_and_lets_them_try_again(self):
        self.server.fail["request"] = G.GatewayError("NOT_FOUND", "That plan isn't on offer any more.")
        dlg = self.upgrade_dialog()
        dlg._choose("scale"); dlg._choose("pack-500")
        for _ in range(4):
            dlg._go_next()
        self.assertEqual(len(self.server.bodies("request")), 1)        # the pack was not attempted
        self.assertFalse(dlg._error.isHidden())
        self.assertIn("isn't on offer", dlg._error.text())
        self.assertTrue(dlg._next.isEnabled())
        self.assertEqual(dlg._pages.currentIndex(), 3)

    def test_plans_that_could_not_be_loaded_say_so(self):
        self.server.fail["offers"] = G.GatewayError("UNREACHABLE", "Couldn't reach Prism's licence server.")
        dlg = self.upgrade_dialog()
        self.assertIn("licence server", dlg._banner.text())
        self.assertEqual(dlg._cards, {})

    def test_an_empty_shelf_says_to_ask_alphakore(self):
        self.server.offers = offers_payload(offers=[])
        dlg = self.upgrade_dialog()
        self.assertIn("ask Alphakore", dlg._plans_host[2].text())
        self.assertIn("ask Alphakore", dlg._packs_host[2].text())

    def test_the_stepper_marks_where_you_are(self):
        dlg = self.upgrade_dialog()
        self.assertEqual([lab.text() for lab in dlg._step_labels],
                         ["1  Select plan", "2  Add-ons", "3  Payment", "4  Review"])
        dlg._go_next()
        self.assertIn("700", dlg._step_labels[1].styleSheet())        # bold: the step you are on
        self.assertNotIn("700", dlg._step_labels[0].styleSheet())


if __name__ == "__main__":
    unittest.main()
