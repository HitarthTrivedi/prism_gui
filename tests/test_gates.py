"""Do the locks actually lock?

The unit tests in test_licensing.py prove the licence *state* is computed
correctly. These prove the app acts on it — that a locked add-on does not open,
that an expired licence stops new work, and that a routed paid agent cannot
sneak past the rail.

That distinction matters: every one of these would still pass its state test
while the dialog opened anyway, because the gate is a separate line of code
from the thing it guards.

Qt runs offscreen; no window is ever shown.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "devtools"))

from cryptography.hazmat.primitives import serialization as _ser  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: E402
    Ed25519PrivateKey)
from PySide6.QtWidgets import QApplication  # noqa: E402

import licensing  # noqa: E402
import mint  # noqa: E402
from licensing import device, keys, store  # noqa: E402

DAY = 86400
_app = QApplication.instance() or QApplication([])


class GateTest(unittest.TestCase):
    """Shared harness: a temp ~/.prism and a throwaway signing key."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prism-gate-")
        self.private = Ed25519PrivateKey.generate()
        public = self.private.public_key().public_bytes(
            _ser.Encoding.Raw, _ser.PublicFormat.Raw).hex()
        device.reset_cache()
        self.patches = [
            mock.patch.object(licensing, "user_dir", return_value=self.tmp),
            mock.patch.object(keys, "public_keys", return_value={"t": public}),
        ]
        for p in self.patches:
            p.start()
        self.paywalled: list[str] = []
        licensing.set_paywall_handler(
            lambda feature, parent, state: self.paywalled.append(feature))

    def tearDown(self):
        licensing.set_paywall_handler(None)
        for p in self.patches:
            p.stop()
        device.reset_cache()
        licensing.reload()

    def grant(self, features, *, days=10, kind="trial"):
        now = int(time.time())
        claims = {
            "kid": "t", "sub": "lic_t", "cust": "RS Infotech", "plan": kind,
            "kind": kind, "feat": list(features), "seats": 1,
            "dev": device.fingerprint(self.tmp)[0],
            "iat": now, "nbf": now, "exp": now + days * DAY,
            "lend": now + days * DAY, "grace": 0,
        }
        store.save(self.tmp, {"token": mint.sign(claims, self.private),
                              "license_id": "lic_t", "last_seen_utc": now})
        return licensing.reload()

    def _window(self):
        """A real MainWindow, with Setup stubbed — it would otherwise pop on a
        window that has no Groq key configured."""
        import main_window
        with mock.patch.object(main_window.MainWindow, "_open_setup"):
            return main_window.MainWindow()

    def _instant_authorize(self, allowed=True, message=""):
        """Replace AuthorizeWorker with something synchronous.

        The real one is a QThread doing a network round trip. Left running,
        a test finishes while it is still alive and Qt tears the thread down
        underneath it — which segfaults the interpreter at exit rather than
        failing a test, and is miserable to trace back here.
        """
        import licensing

        class _Instant:
            def __init__(self, feature="core", action="run", parent=None):
                self._cb = None

            @property
            def done(self):
                outer = self

                class _Sig:
                    def connect(self, fn):
                        outer._cb = fn
                return _Sig()

            def start(self):
                if self._cb:
                    self._cb(licensing.Authorization(allowed, run_id="run_test",
                                                     message=message))
        return _Instant


class Entitlements(GateTest):
    def test_require_passes_what_is_owned(self):
        self.grant(["core", "boq"])
        self.assertTrue(licensing.require("boq"))
        self.assertEqual(self.paywalled, [])

    def test_require_blocks_and_pitches_what_is_not(self):
        self.grant(["core"])
        self.assertFalse(licensing.require("boq"))
        self.assertEqual(self.paywalled, ["boq"])

    def test_expired_licence_blocks_everything(self):
        self.grant(["core", "boq"], days=-1)
        self.assertFalse(licensing.require("core"))
        self.assertFalse(licensing.require("boq"))


class WindowGates(GateTest):
    """The real MainWindow methods, with the dialogs stubbed out so a failure
    to gate shows up as an attempted open rather than a hung modal."""

    def test_locked_addon_does_not_open_its_dialog(self):
        import main_window
        self.grant(["core"])            # no boq
        win = self._window()
        with mock.patch.object(main_window, "BoqDialog") as dialog:
            win._open_boq()
        dialog.assert_not_called()
        self.assertEqual(self.paywalled, ["boq"])

    def test_owned_addon_gets_past_the_gate(self):
        import main_window
        self.grant(["core", "boq"])
        win = self._window()
        # boq_available() is the dependency probe that runs *after* the gate;
        # stubbing it False stops the real dialog while still proving the
        # licence check let us through.
        with mock.patch.object(main_window, "AuthorizeWorker",
                               self._instant_authorize(allowed=True)), \
             mock.patch.object(main_window.CB, "boq_available",
                               return_value=(False, "no ezdxf")), \
             mock.patch.object(main_window.QMessageBox, "information"):
            win._open_boq()
        self.assertEqual(self.paywalled, [])

    def test_owned_addon_still_blocked_when_the_server_is_unreachable(self):
        """No offline fallback: owning BOQ is not enough, the server has to
        say yes at the moment it is opened."""
        import main_window
        self.grant(["core", "boq"])
        win = self._window()
        with mock.patch.object(
                main_window, "AuthorizeWorker",
                self._instant_authorize(
                    allowed=False,
                    message="Prism couldn't reach the licence server.")), \
             mock.patch.object(main_window, "BoqDialog") as dialog, \
             mock.patch.object(main_window.QMessageBox, "warning") as warned:
            win._open_boq()
        dialog.assert_not_called()
        warned.assert_called_once()

    def test_email_gate(self):
        import main_window
        self.grant(["core"])
        win = self._window()
        with mock.patch.object(main_window, "EmailComposeDialog") as dialog:
            win._open_email()
        dialog.assert_not_called()
        self.assertEqual(self.paywalled, ["email"])

    def test_expired_licence_blocks_planning(self):
        self.grant(["core"], days=-1)
        win = self._window()
        started = []
        with mock.patch.object(win, "_workers", started):
            win._route("build me a bill of quantities")
        self.assertEqual(started, [])       # no RouteWorker ever queued
        self.assertEqual(self.paywalled, ["core"])

    def test_banner_hidden_when_licence_is_healthy(self):
        self.grant(["core", "boq"])
        win = self._window()
        self.assertFalse(win.banner.isVisible())

    def test_banner_shown_when_licence_has_ended(self):
        self.grant(["core"], days=-1)
        win = self._window()
        self.assertTrue(win.banner.isVisibleTo(win))

    def test_sidebar_padlocks_what_is_not_owned(self):
        self.grant(["core", "boq"])
        win = self._window()
        gated = win.sidebar._gated
        self.assertTrue(gated["boq"][0].property("locked") in (False, None))
        self.assertTrue(gated["email"][0].property("locked"))
        # Locked, but still clickable — the click is the customer telling us
        # what they want, and it opens the pitch.
        self.assertTrue(gated["email"][0].isEnabled())


class GettingOut(GateTest):
    """A customer must be able to abandon work they no longer want.

    A run is tens of minutes of browser automation; before this the only exit
    was force-quitting the app, which threw away every step that had already
    finished.
    """

    def test_stop_asks_the_engine_to_wind_up(self):
        """Not a thread kill: the engine polls a flag and stops at a safe
        point, keeping finished steps and closing Chrome properly."""
        self.grant(["core"])
        win = self._window()

        stopped = []
        win._active_run = mock.Mock(
            isRunning=mock.Mock(return_value=True),
            stop=mock.Mock(side_effect=lambda: stopped.append(True)))
        win._stop_run()
        self.assertEqual(stopped, [True])

    def test_stop_is_harmless_when_nothing_is_running(self):
        self.grant(["core"])
        win = self._window()
        win._active_run = None
        win._stop_run()             # must not raise

    def test_stop_button_only_shows_while_running(self):
        self.grant(["core"])
        win = self._window()
        win.output_panel.set_running(True)
        self.assertTrue(win.output_panel.stop_btn.isVisibleTo(win.output_panel))
        win.output_panel.set_running(False)
        self.assertFalse(win.output_panel.stop_btn.isVisibleTo(win.output_panel))

    def test_stop_latches_so_a_second_click_does_nothing(self):
        self.grant(["core"])
        win = self._window()
        win.output_panel.set_running(True)
        win.output_panel._on_stop()
        self.assertFalse(win.output_panel.stop_btn.isEnabled())
        self.assertIn("Stopping", win.output_panel.stop_btn.text())

    def test_a_cancelled_run_keeps_what_finished(self):
        import main_window
        self.grant(["core"])
        win = self._window()
        win._stage_results = [{"stage": "brains", "agent": "Claude",
                               "text": "done", "url": "", "snippet": "s",
                               "ok": True}]
        win._active_run = mock.Mock(stopping=mock.Mock(return_value=True))
        with mock.patch.object(main_window, "CompletionDialog") as dialog, \
             mock.patch.object(win, "_save_run"):
            win._on_run_done({}, {})
        dialog.assert_called_once()          # the finished work is still shown

    def test_discard_clears_the_plan_but_keeps_attachments(self):
        import main_window
        self.grant(["core"])
        win = self._window()
        win.routing = {"stages": {}}
        win.attachments = [{"path": "/tmp/x.dwg", "name": "x.dwg"}]
        with mock.patch.object(main_window.QMessageBox, "question",
                               return_value=main_window.QMessageBox.Yes):
            win._discard_plan()
        self.assertIsNone(win.routing)
        self.assertEqual(len(win.attachments), 1)   # explicit choices survive

    def test_discard_can_be_backed_out_of(self):
        import main_window
        self.grant(["core"])
        win = self._window()
        win.routing = {"stages": {}}
        with mock.patch.object(main_window.QMessageBox, "question",
                               return_value=main_window.QMessageBox.Cancel):
            win._discard_plan()
        self.assertIsNotNone(win.routing)


class PlanningIsAuthorised(GateTest):
    """Planning is a Groq call — it costs tokens and every run starts with it,
    so it goes through the server like a run does."""

    def test_planning_asks_the_server(self):
        import main_window
        self.grant(["core"])
        win = self._window()
        with mock.patch.object(main_window, "AuthorizeWorker",
                               self._instant_authorize(allowed=True)), \
             mock.patch.object(main_window, "RouteWorker") as router, \
             mock.patch.object(main_window.CB.config, "is_configured",
                               return_value=True):
            win._route("draw me a bill of quantities")
        router.assert_called_once()

    def test_planning_stops_when_the_server_says_no(self):
        import main_window
        self.grant(["core"])
        win = self._window()
        with mock.patch.object(main_window, "AuthorizeWorker",
                               self._instant_authorize(
                                   allowed=False, message="Licence ended.")), \
             mock.patch.object(main_window, "RouteWorker") as router, \
             mock.patch.object(main_window.QMessageBox, "warning") as warned, \
             mock.patch.object(main_window.CB.config, "is_configured",
                               return_value=True):
            win._route("draw me a bill of quantities")
        router.assert_not_called()
        warned.assert_called_once()


class RoutedAgentGate(GateTest):
    """Prism Reel can enter a plan through the router without the customer
    ever touching the rail, so the sidebar gate alone would leak it."""

    def test_locked_routed_agent_is_offered_as_a_drop(self):
        import main_window
        from PySide6.QtWidgets import QMessageBox
        self.grant(["core"])            # no reel
        win = self._window()
        win.routing = {"stages": {}}
        win._last_query = "make me a reel"

        with mock.patch.object(win.agents_panel, "selected_agents",
                               return_value={"brains": "Claude",
                                             "media": "Prism Reel"}), \
             mock.patch.object(main_window.QMessageBox, "question",
                               return_value=QMessageBox.Yes), \
             mock.patch.object(main_window, "AuthorizeWorker",
                               self._instant_authorize()), \
             mock.patch.object(main_window, "AutomationWorker") as worker:
            win._run_pipeline()

        self.assertTrue(worker.called, "the rest of the plan should still run")
        ran = worker.call_args[0][1]["agents"]
        self.assertNotIn("Prism Reel", ran.values())
        self.assertIn("Claude", ran.values())

    def test_declining_the_drop_shows_the_pitch(self):
        import main_window
        from PySide6.QtWidgets import QMessageBox
        self.grant(["core"])
        win = self._window()
        win.routing = {"stages": {}}
        win._last_query = "make me a reel"

        with mock.patch.object(win.agents_panel, "selected_agents",
                               return_value={"media": "Prism Studio"}), \
             mock.patch.object(main_window.QMessageBox, "question",
                               return_value=QMessageBox.Cancel), \
             mock.patch.object(main_window, "AutomationWorker") as worker:
            win._run_pipeline()

        worker.assert_not_called()
        self.assertEqual(self.paywalled, ["reel"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
