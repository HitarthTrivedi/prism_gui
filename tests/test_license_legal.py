"""Activation must make the local legal notice a real customer decision."""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

import licensing  # noqa: E402
from dialogs import license_dialog as LD  # noqa: E402

_app = QApplication.instance() or QApplication([])
KEY = "PRSM-TZQ57-XJ8VA-9R60N-ZJZCG"


class LegalAcknowledgement(unittest.TestCase):
    def _dialog(self):
        state = mock.Mock(license_id="", features=[], usable=False,
                          message="", kind="", license_ends=0)
        with mock.patch.object(licensing, "state", return_value=state):
            return LD.LicenseDialog(mode="activate")

    def test_key_cannot_activate_until_both_documents_are_read_and_accepted(self):
        dialog = self._dialog()
        dialog.key_edit.setText(KEY)
        self.assertFalse(dialog.activate_btn.isEnabled())
        self.assertFalse(dialog.terms_check.isEnabled())
        self.assertFalse(dialog.privacy_check.isEnabled())

        # Exercise the acknowledgement state without opening a modal document
        # viewer in the test; _read_terms/_read_privacy are the UI paths that
        # set these flags after showing the bundled documents.
        dialog._terms_opened = True
        dialog.terms_check.setEnabled(True)
        dialog.terms_check.setChecked(True)
        self.assertFalse(dialog.activate_btn.isEnabled())

        dialog._privacy_opened = True
        dialog.privacy_check.setEnabled(True)
        dialog.privacy_check.setChecked(True)
        self.assertTrue(dialog.activate_btn.isEnabled())

    def test_each_document_has_a_clear_local_open_action(self):
        dialog = self._dialog()
        self.assertEqual(dialog.terms_btn.text(), "Read Terms of Use")
        self.assertEqual(dialog.privacy_btn.text(), "Read Privacy Policy")
        self.assertFalse(dialog._legal_acknowledged())

        with mock.patch.object(dialog, "_open_legal") as open_legal:
            dialog._read_terms()
            dialog._read_privacy()
        self.assertEqual(open_legal.call_count, 2)
        self.assertTrue(dialog.terms_check.isEnabled())
        self.assertTrue(dialog.privacy_check.isEnabled())


if __name__ == "__main__":
    unittest.main(verbosity=2)
