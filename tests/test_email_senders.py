"""Several addresses to send from, and which one a message actually left by.

Reading has taken a list of mailboxes since the multi-mailbox round; sending
had not. Everything Prism sent -- the quotation, the reminder, the win-back,
the blast -- went out from whichever single address had been typed into the
Email add-on first, because `core/mailer.py` resolves the From header from
one key, `cfg["email"]["address"]`, and every call site handed it the whole
config.

So the load-bearing test in this file is not any of the new behaviour. It is
`ALegacyConfigStillSends`: a customer who has one account set up must have a
config that reads as exactly one account, an overlay that is byte-for-byte
the dict the engine already receives, and a screen with no chooser on it.
The feature is only safe because that case did not move.

The rest pins the parts that are easy to get subtly wrong:

  · the legacy mirror follows the DEFAULT account, not merely the first one,
    because `mailer.is_configured()` reads the mirror and is the gate in
    front of all five send sites -- a mirror pointing at a parked account
    would offer a Send button for an account that will never send
  · a parked account keeps its password, so parking is not deleting
  · the readers hand back copies, so a dialog editing them cannot change
    what is saved until Save says so

Nothing here runs the event loop against a modal, and nothing writes to the
real ~/.prism -- see setUpModule.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PRISM_LICENSE_OFFLINE_DEV", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Signal, QObject                     # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox        # noqa: E402

import core_bridge as CB                                       # noqa: E402
import email_config                                            # noqa: E402
from addons.email import dialog as ED                          # noqa: E402
from addons.email.dialog import EmailComposeDialog, EmailSetupDialog  # noqa: E402

_app = QApplication.instance() or QApplication([])


# ── never write the developer's own config ───────────────────────────────
_REAL_SAVE = CB.config.save
_REAL_CONFIG_PATH = CB.config.CONFIG_PATH
_SCRATCH = tempfile.mkdtemp(prefix="prism-test-senders-")


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


def legacy_cfg(folder: str = "") -> dict:
    """A config written by a Prism from before sending took a list."""
    return {"email": {"address": "sales@shakti.one", "password": "x",
                      "host": "smtp.gmail.com", "port": 465,
                      "folder": folder or tempfile.mkdtemp(prefix="prism-s-")},
            "agents": {"content": "ChatGPT"}}


def two_sender_cfg(folder: str = "") -> dict:
    base = legacy_cfg(folder)
    base["email"] = email_config.account_block(base, [
        {"address": "sales@shakti.one", "password": "x",
         "host": "smtp.gmail.com", "port": 465, "active": True},
        {"address": "accounts@shakti.one", "password": "y",
         "host": "smtp.gmail.com", "port": 587, "active": True},
    ])
    return base


class _FakeSendWorker(QObject):
    """Emits done at once — a send that never touches a mail server, and
    remembers the config it was handed so a test can ask who it would have
    signed in as."""
    progress = Signal(int, int, str, bool, str)
    done = Signal(list, list)
    failed = Signal(str)
    stopped = False

    def __init__(self, cfg, recipients, subject, body, files):
        super().__init__()
        self.cfg, self.recipients = cfg, recipients
        _FakeSendWorker.last = self

    def start(self):
        self.done.emit([r["email"] for r in self.recipients], [])

    def isRunning(self):
        return False


# ── the guarantee that makes the rest safe ───────────────────────────────
class ALegacyConfigStillSends(unittest.TestCase):
    """One account, saved by the previous version, behaves as it always did."""

    def setUp(self):
        self.cfg = legacy_cfg()

    def test_it_reads_as_exactly_one_account(self):
        accounts = email_config.sending_accounts_of(self.cfg)
        self.assertEqual([a["address"] for a in accounts],
                         ["sales@shakti.one"])

    def test_it_is_active_although_nothing_ever_said_so(self):
        # A missing `active` key must read as "in use". Read the other way,
        # every existing customer's mail silently stops going out.
        self.assertTrue(email_config.can_send(self.cfg))
        self.assertEqual(email_config.default_sender(self.cfg)["address"],
                         "sales@shakti.one")

    def test_the_overlay_is_the_dict_the_engine_already_receives(self):
        # The whole safety argument in one assertion: with one account, what
        # SendWorker is handed is what it was handed before this change.
        overlay = email_config.cfg_for_sender(
            self.cfg, email_config.default_sender(self.cfg))
        self.assertEqual(overlay["email"], self.cfg["email"])

    def test_the_engines_own_gate_still_passes(self):
        self.assertTrue(CB.mailer.is_configured(self.cfg))

    def test_the_compose_window_offers_no_choice_there_is_not(self):
        d = EmailComposeDialog(self.cfg, [], None)
        d.show()
        d.layout().activate()
        self.assertFalse(d.from_box.isVisibleTo(d),
                         "a chooser with one entry is a decision the "
                         "customer does not have")
        self.assertEqual(d._sender()["address"], "sales@shakti.one")


class TheSendingAccountsList(unittest.TestCase):

    def test_the_list_wins_over_the_legacy_mirror(self):
        cfg = two_sender_cfg()
        cfg["email"]["address"] = "stale@shakti.one"
        self.assertEqual(
            [a["address"] for a in email_config.sending_accounts_of(cfg)],
            ["sales@shakti.one", "accounts@shakti.one"])

    def test_copies_come_back_not_references(self):
        cfg = two_sender_cfg()
        got = email_config.sending_accounts_of(cfg)
        got[0]["address"] = "scribbled@shakti.one"
        self.assertEqual(cfg["email"]["accounts"][0]["address"],
                         "sales@shakti.one")

    def test_the_mirror_is_the_default_so_the_engines_gate_agrees(self):
        cfg = two_sender_cfg()
        self.assertEqual(cfg["email"]["address"], "sales@shakti.one")
        self.assertEqual(cfg["email"]["host"], "smtp.gmail.com")
        self.assertEqual(cfg["email"]["port"], 465)
        self.assertTrue(CB.mailer.is_configured(cfg))

    def test_a_parked_account_never_sends_but_keeps_its_password(self):
        cfg = two_sender_cfg()
        accounts = email_config.sending_accounts_of(cfg)
        accounts[0]["active"] = False
        cfg["email"] = email_config.account_block(cfg, accounts)
        self.assertEqual(
            [a["address"] for a in email_config.active_senders(cfg)],
            ["accounts@shakti.one"])
        self.assertEqual(email_config.default_sender(cfg)["address"],
                         "accounts@shakti.one")
        # Parked, not deleted: the password is still there to switch back on.
        self.assertEqual(cfg["email"]["accounts"][0]["password"], "x")

    def test_the_mirror_follows_the_default_past_a_parked_account(self):
        # The gate in front of all five send sites reads the mirror. A mirror
        # left pointing at a parked account would offer a Send button for an
        # account that will never send.
        cfg = two_sender_cfg()
        accounts = email_config.sending_accounts_of(cfg)
        accounts[0]["active"] = False
        cfg["email"] = email_config.account_block(cfg, accounts)
        self.assertEqual(cfg["email"]["address"], "accounts@shakti.one")
        self.assertEqual(cfg["email"]["port"], 587)

    def test_the_sent_log_folder_survives_a_rewrite(self):
        cfg = two_sender_cfg()
        self.assertTrue(cfg["email"]["folder"])
        self.assertNotIn("folder", cfg["email"]["accounts"][0],
                         "the sent-log folder is an install setting, not an "
                         "account's")

    def test_the_overlay_does_not_mutate_what_it_copies(self):
        cfg = two_sender_cfg()
        before = dict(cfg["email"])
        email_config.cfg_for_sender(
            cfg, email_config.sending_accounts_of(cfg)[1])
        self.assertEqual(cfg["email"], before)

    def test_the_overlay_hides_prisms_own_keys_from_the_engine(self):
        # core/mailer.py reads this dict straight through to smtplib.
        overlay = email_config.cfg_for_sender(
            two_sender_cfg(), {"address": "a@b.com", "password": "p",
                               "host": "h", "port": 465,
                               "label": "Sales", "active": True})
        self.assertNotIn("label", overlay["email"])
        self.assertNotIn("active", overlay["email"])

    def test_nothing_configured_cannot_send(self):
        self.assertFalse(email_config.can_send({}))
        self.assertEqual(email_config.sending_accounts_of({}), [])


class SetupKeepsSeveralSendingAddresses(unittest.TestCase):

    def _dialog(self, cfg):
        dlg = EmailSetupDialog(cfg, None)
        dlg.show()
        dlg.layout().activate()
        self.addCleanup(dlg.deleteLater)
        return dlg

    def test_a_list_of_one_hides_itself(self):
        # One address above a form asking for that same address reads as two
        # steps where there is only one thing to do.
        d = self._dialog(legacy_cfg())
        self.assertFalse(d.senders.isVisibleTo(d))
        self.assertFalse(d.remove_sender_btn.isVisibleTo(d))
        self.assertFalse(d.active_box.isVisibleTo(d))

    def test_a_second_address_brings_the_list_out(self):
        d = self._dialog(legacy_cfg())
        d._add_sender()
        d.addr_edit.setText("accounts@shakti.one")
        self.assertTrue(d.senders.isVisibleTo(d))
        self.assertEqual(d.senders.count(), 2)

    def test_each_address_keeps_its_own_saved_password(self):
        d = self._dialog(two_sender_cfg())
        d._sender_picked(1)
        self.assertEqual(d._saved_password, "y")
        self.assertEqual(d.pass_edit.text(), "",
                         "a saved password is kept by leaving the box blank, "
                         "never by showing it")
        d._sender_picked(0)
        self.assertEqual(d._saved_password, "x")

    def test_saving_writes_the_list_and_the_mirror(self):
        d = self._dialog(legacy_cfg())
        d._add_sender()
        d.addr_edit.setText("accounts@shakti.one")
        d.pass_edit.setText("y")
        d.host_edit.setText("smtp.gmail.com")
        d.port_edit.setText("587")
        with _NoSave() as save:
            d._save()
        self.assertEqual(len(save.saved), 1)
        block = save.saved[0]["email"]
        self.assertEqual([a["address"] for a in block["accounts"]],
                         ["sales@shakti.one", "accounts@shakti.one"])
        self.assertEqual(block["address"], "sales@shakti.one")
        self.assertTrue(CB.mailer.is_configured(save.saved[0]))

    def test_making_one_the_default_moves_it_to_the_top(self):
        d = self._dialog(two_sender_cfg())
        d._sender_picked(1)
        d._make_default()
        with _NoSave() as save:
            d._save()
        block = save.saved[0]["email"]
        self.assertEqual([a["address"] for a in block["accounts"]],
                         ["accounts@shakti.one", "sales@shakti.one"])
        self.assertEqual(block["address"], "accounts@shakti.one",
                         "the mirror has to follow the new default, or the "
                         "engine's gate answers about the old one")

    def test_it_refuses_to_leave_nothing_able_to_send(self):
        d = self._dialog(two_sender_cfg())
        for index in (0, 1):
            d._sender_picked(index)
            d.active_box.setChecked(False)
        with mock.patch.object(QMessageBox, "warning") as warned:
            with _NoSave() as save:
                d._save()
        self.assertTrue(warned.called)
        self.assertEqual(save.saved, [], "nothing should have been written")

    def test_the_address_on_screen_complains_the_way_it_always_did(self):
        # The account being edited is checked by _account(), unchanged, so a
        # customer who has only ever had one account sees the same sentence
        # this dialog has always shown them.
        d = self._dialog(legacy_cfg())
        d._add_sender()
        d.addr_edit.setText("accounts@shakti.one")
        d.host_edit.setText("smtp.gmail.com")
        with mock.patch.object(QMessageBox, "warning") as warned:
            with _NoSave() as save:
                d._save()
        self.assertTrue(warned.called)
        self.assertIn("Enter your app password", str(warned.call_args))
        self.assertEqual(save.saved, [])

    def test_an_address_left_behind_is_named_not_silently_dropped(self):
        # The half-filled account is NOT the one on screen -- the case the
        # old single-account dialog could not have. Naming it is the whole
        # point: "something is wrong somewhere" is not a fixable message.
        d = self._dialog(legacy_cfg())
        d._add_sender()
        d.addr_edit.setText("accounts@shakti.one")
        d.host_edit.setText("smtp.gmail.com")
        d._sender_picked(0)                 # back to the complete one
        with mock.patch.object(QMessageBox, "warning") as warned:
            with _NoSave() as save:
                d._save()
        self.assertTrue(warned.called)
        self.assertIn("accounts@shakti.one", str(warned.call_args))
        self.assertEqual(save.saved, [])
        self.assertEqual(d._current, 1,
                         "the dialog should move to the account it is "
                         "complaining about")


class TheMessageLeavesFromTheChosenAddress(unittest.TestCase):

    def test_the_compose_window_offers_every_active_address(self):
        d = EmailComposeDialog(two_sender_cfg(), [], None)
        d.show()
        d.layout().activate()
        self.assertTrue(d.from_box.isVisibleTo(d))
        self.assertEqual([d.from_box.itemText(i)
                          for i in range(d.from_box.count())],
                         ["sales@shakti.one", "accounts@shakti.one"])

    def test_the_worker_signs_in_as_the_address_that_was_picked(self):
        cfg = two_sender_cfg()
        d = EmailComposeDialog(cfg, [], None)
        d.show()
        d.to_edit.setText("rajesh@acme.in")
        d.subject_edit.setText("Quotation for springs")
        d.body_edit.setPlainText("Rates attached.")
        d.from_box.setCurrentIndex(1)
        with mock.patch.object(ED, "SendWorker", _FakeSendWorker), \
                mock.patch.object(QMessageBox, "question",
                                  return_value=QMessageBox.Yes), \
                mock.patch.object(QMessageBox, "information"), \
                mock.patch.object(ED.CB.config, "save_run"):
            d._send()
        handed = _FakeSendWorker.last.cfg["email"]
        self.assertEqual(handed["address"], "accounts@shakti.one")
        self.assertEqual(handed["port"], 587,
                         "the chosen account's own server settings have to "
                         "travel with it, not just its address")

    def test_the_confirmation_names_the_address_it_will_send_from(self):
        cfg = two_sender_cfg()
        d = EmailComposeDialog(cfg, [], None)
        d.show()
        d.to_edit.setText("rajesh@acme.in")
        d.subject_edit.setText("Quotation")
        d.body_edit.setPlainText("Rates attached.")
        d.from_box.setCurrentIndex(1)
        with mock.patch.object(ED, "SendWorker", _FakeSendWorker), \
                mock.patch.object(QMessageBox, "question",
                                  return_value=QMessageBox.No) as asked, \
                mock.patch.object(ED.CB.config, "save_run"):
            d._send()
        # What the customer was asked to confirm must be the account the mail
        # would actually have left from.
        self.assertIn("accounts@shakti.one", str(asked.call_args))

    def test_the_default_sends_when_nobody_picks(self):
        cfg = two_sender_cfg()
        d = EmailComposeDialog(cfg, [], None)
        d.show()
        d.to_edit.setText("rajesh@acme.in")
        d.subject_edit.setText("Quotation")
        d.body_edit.setPlainText("Rates attached.")
        with mock.patch.object(ED, "SendWorker", _FakeSendWorker), \
                mock.patch.object(QMessageBox, "question",
                                  return_value=QMessageBox.Yes), \
                mock.patch.object(QMessageBox, "information"), \
                mock.patch.object(ED.CB.config, "save_run"):
            d._send()
        self.assertEqual(_FakeSendWorker.last.cfg["email"]["address"],
                         "sales@shakti.one")


if __name__ == "__main__":
    unittest.main()
