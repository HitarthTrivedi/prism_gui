"""The Email add-on's front door — widgets/simple_panels.py::EmailPanel.

Before this, EmailSetupDialog only ever opened itself the first time, from
MainWindow._open_email_dialog(), which is guarded by
`not CB.mailer.is_configured(self.cfg)`. Once an account was configured there
was no button, menu, or gesture anywhere on screen that reopened it — a wrong
password or a mailbox change had no way in short of hand-editing the config
file. This defends the fix: a standing "Change account" action that opens the
same dialog regardless of whether one is already set up.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest

from PySide6.QtWidgets import QApplication  # noqa: E402

from dialogs.email_dialog import EmailSetupDialog  # noqa: E402
from widgets.simple_panels import EmailPanel  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _labels(panel: EmailPanel) -> list[str]:
    return [action.text() for action in panel.header_actions()]


class TheChangeAccountDoor(unittest.TestCase):

    def test_it_is_offered_with_no_account_configured(self):
        panel = EmailPanel({})
        self.assertIn("Change account", _labels(panel))

    def test_it_is_still_offered_once_an_account_is_configured(self):
        panel = EmailPanel({"email": {"address": "sales@acme.co.in"}})
        self.assertIn("Change account", _labels(panel))

    def test_clicking_it_asks_to_open_setup_rather_than_start_a_draft(self):
        """It must be its own action, not a relabelled "Start a draft" —
        otherwise pressing it drops the owner into composing mail instead of
        into the account form they actually asked for."""
        panel = EmailPanel({})
        seen = []
        panel.change_account.connect(lambda: seen.append("setup"))
        panel.opened.connect(lambda: seen.append("draft"))
        actions = panel.header_actions()
        change = next(a for a in actions if a.text() == "Change account")
        change.click()
        self.assertEqual(seen, ["setup"])

    def test_main_window_wires_it_to_the_setup_dialog(self):
        """A source check, in keeping with how this app already proves the
        inquiry screen is routed (tests/test_inquiry_ui.py::ItIsOnTheShelf) —
        constructing a real MainWindow pulls in the licence client for a test
        that is really about one signal connection."""
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "main_window.py")
        with open(path, encoding="utf-8") as f:
            source = f.read()
        self.assertIn("email_panel.change_account.connect(self._open_email_setup)",
                      source)
        self.assertIn("def _open_email_setup(self):", source)
        setup_body = source.split("def _open_email_setup(self):", 1)[1]
        setup_body = setup_body.split("\n    def ", 1)[0]
        self.assertNotIn("is_configured", setup_body,
                         "must open unconditionally, not only when unset")
        self.assertIn("EmailSetupDialog(self.cfg, self)", setup_body)


class ThePasswordNeverReadsAsLost(unittest.TestCase):
    """EmailSetupDialog is now reachable at any time via "Change account", so
    the same fix made on the Inquiry Automation side — a loud, standing
    confirmation that a blank box means "kept", not "deleted" — belongs here
    too, or the very door just added recreates the report that started this:
    opening setup makes the saved app password look like it vanished."""

    def test_a_saved_password_says_so_loudly(self):
        dialog = EmailSetupDialog({"email": {"address": "sales@acme.co.in",
                                              "password": "p"}})
        self.assertEqual(dialog.pass_edit.text(), "")
        self.assertTrue(dialog.password_status.isVisibleTo(dialog))
        self.assertIn("already saved", dialog.password_status.text())

    def test_the_notice_goes_quiet_once_a_new_password_is_typed(self):
        dialog = EmailSetupDialog({"email": {"address": "sales@acme.co.in",
                                              "password": "p"}})
        dialog.pass_edit.setText("a-new-app-password")
        self.assertFalse(dialog.password_status.isVisibleTo(dialog))

    def test_no_notice_when_nothing_has_ever_been_saved(self):
        dialog = EmailSetupDialog({})
        self.assertNotIn("already saved", dialog.password_status.text())


if __name__ == "__main__":
    unittest.main()
