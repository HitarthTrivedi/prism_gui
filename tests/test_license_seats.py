"""SEAT_LIMIT_REACHED is a choice, not a dead end.

The reimaged-laptop case: a one-seat licence, the old machine gone, the
customer sitting at the new one looking at "every seat is in use". The server
lists the machines holding seats; the dialog shows them and one click frees
the chosen seat and activates here. Before this the only way out was an
email to us — device.py predicted it as the most common ticket.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

import licensing  # noqa: E402
from dialogs import license_dialog as LD  # noqa: E402

_app = QApplication.instance() or QApplication([])

KEY = "PRSM-TZQ57-XJ8VA-9R60N-ZJZCG"
DEVICES = [{"id": 41, "label": "Kiran's old MacBook", "platform": "darwin",
            "last_seen": 1_700_000_000}]


def _seat_error():
    return licensing.ServerError(
        "SEAT_LIMIT_REACHED", "Every seat on this licence is already in use.",
        {"seats": 1, "in_use": 1, "devices": DEVICES})


class ReleaseFlow(unittest.TestCase):
    def _dialog(self):
        with mock.patch.object(licensing, "state") as st:
            st.return_value = mock.Mock(license_id="", features=[], usable=False,
                                        message="", kind="", license_ends=0)
            return LD.LicenseDialog(mode="activate")

    def _run_worker(self, worker):
        # Synchronously, on this thread: the worker's run() is plain Python and
        # the signals connect direct in-thread, which is exactly what the
        # dialog's slots see once the real thread finishes.
        worker.run()

    def test_seat_limit_shows_the_machines_and_frees_the_chosen_one(self):
        dlg = self._dialog()
        dlg.key_edit.setText(KEY)
        calls = []

        def activate(key):
            calls.append(("activate", key))
            if len([c for c in calls if c[0] == "release"]) == 0:
                raise _seat_error()
            return mock.Mock(features=["core"], customer="Kiran", days_left=9)

        def release(key, device_id):
            calls.append(("release", key, device_id))

        with mock.patch.object(licensing, "activate", side_effect=activate), \
                mock.patch.object(licensing, "release_device", side_effect=release), \
                mock.patch.object(LD._ActivateWorker, "start",
                                  lambda w: self._run_worker(w)), \
                mock.patch.object(dlg, "accept") as accept:
            dlg._activate()
            self.assertTrue(dlg.seats_box.isVisibleTo(dlg))
            self.assertTrue(dlg.message.isVisibleTo(dlg))
            buttons = [b for b in dlg.seats_box.findChildren(QPushButton)]
            self.assertEqual(len(buttons), 1)
            self.assertTrue(buttons[0].isEnabled())
            texts = " ".join(l.text() for l in
                             dlg.seats_box.findChildren(type(dlg.message)))
            self.assertIn("old MacBook", texts)
            self.assertIn("last used", texts)

            buttons[0].click()
            self.assertEqual(calls, [("activate", KEY), ("release", KEY, 41),
                                     ("activate", KEY)])
            accept.assert_called_once()

    def test_a_server_without_ids_still_shows_the_list_but_cannot_release(self):
        dlg = self._dialog()
        dlg.key_edit.setText(KEY)
        error = licensing.ServerError(
            "SEAT_LIMIT_REACHED", "Every seat is in use.",
            {"devices": [{"label": "Office PC", "last_seen": 1}]})
        with mock.patch.object(licensing, "activate", side_effect=error), \
                mock.patch.object(LD._ActivateWorker, "start",
                                  lambda w: self._run_worker(w)):
            dlg._activate()
        buttons = dlg.seats_box.findChildren(QPushButton)
        self.assertEqual(len(buttons), 1)
        self.assertFalse(buttons[0].isEnabled())

    def test_retyping_the_key_hides_the_old_list(self):
        dlg = self._dialog()
        dlg.key_edit.setText(KEY)
        with mock.patch.object(licensing, "activate", side_effect=_seat_error()), \
                mock.patch.object(LD._ActivateWorker, "start",
                                  lambda w: self._run_worker(w)):
            dlg._activate()
        self.assertTrue(dlg.seats_box.isVisibleTo(dlg))
        dlg.key_edit.setText(KEY[:-1] + "A")
        self.assertFalse(dlg.seats_box.isVisibleTo(dlg))


class ClientCall(unittest.TestCase):
    def test_release_device_posts_the_key_and_the_id(self):
        seen = {}

        def fake_post(endpoint, body, **kw):
            seen.update(endpoint=endpoint, body=body, kw=kw)
            return {"released": True}

        with mock.patch.object(licensing.client, "_post", side_effect=fake_post):
            licensing.release_device("prsm tzq57 xj8va 9r60n zjzcg", 41)
        self.assertEqual(seen["endpoint"], "/v1/release")
        self.assertEqual(seen["body"], {"key": KEY.replace("-", ""), "device_id": 41})
        self.assertEqual(seen["kw"]["retries"], 0)


if __name__ == "__main__":
    unittest.main()
