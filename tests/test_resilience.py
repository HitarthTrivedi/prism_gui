"""The fallbacks a customer only meets on a bad day.

Every test here corresponds to a numbered entry in the failure register. They
exist because none of this is reachable in normal use: you cannot notice that
the model fallback works, and you cannot notice that the diagnostics file has
your API key in it until it is in somebody's inbox.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402
import cloud  # noqa: E402
import diagnostics  # noqa: E402
import workspace as W  # noqa: E402
from core import router as R  # noqa: E402


class _Resp:
    def __init__(self, code, body, headers=None):
        self.status_code, self._body = code, body
        self.headers = headers or {}

    def json(self):
        return self._body


def _ok(model):
    return _Resp(200, {"choices": [{"message": {"content": f"ok:{model}"}}]})


class GroqSurvival(unittest.TestCase):
    """F-07 and F-08. A retired model or a rate limit must not end the day."""

    def test_a_retired_model_falls_through_to_the_next(self):
        tried = []

        def answer(url, headers=None, json=None, timeout=None):
            tried.append(json["model"])
            if json["model"] == "llama-3.3-70b-versatile":
                return _Resp(400, {"error": {"message":
                             "model `llama-3.3-70b-versatile` decommissioned"}})
            return _ok(json["model"])

        with mock.patch.object(R.requests, "post", answer), \
             mock.patch.object(R, "_remember_model"):
            out = R.groq_chat("k", "llama-3.3-70b-versatile", "hi")
        self.assertEqual(out, "ok:llama-3.1-8b-instant")
        self.assertEqual(len(tried), 2)

    def test_the_working_model_is_saved_so_it_costs_one_request_once(self):
        def answer(url, headers=None, json=None, timeout=None):
            if json["model"] == "gone-model":
                return _Resp(404, {"error": {"message": "model not found"}})
            return _ok(json["model"])

        with mock.patch.object(R.requests, "post", answer), \
             mock.patch.object(R, "_remember_model") as remembered:
            R.groq_chat("k", "gone-model", "hi")
        self.assertTrue(remembered.called)

    def test_a_rate_limit_waits_and_retries(self):
        calls = []

        def answer(url, headers=None, json=None, timeout=None):
            calls.append(1)
            if len(calls) == 1:
                return _Resp(429, {"error": {}}, {"retry-after": "1"})
            return _ok(json["model"])

        with mock.patch.object(R.requests, "post", answer), \
             mock.patch("time.sleep") as slept:
            out = R.groq_chat("k", "m", "hi")
        self.assertEqual(out, "ok:m")
        self.assertTrue(slept.called)

    def test_a_persistent_rate_limit_says_what_to_do(self):
        with mock.patch.object(R.requests, "post",
                               lambda *a, **k: _Resp(429, {}, {"retry-after": "1"})), \
             mock.patch("time.sleep"):
            with self.assertRaises(RuntimeError) as caught:
                R.groq_chat("k", "m", "hi")
        self.assertIn("rate-limiting", str(caught.exception))

    def test_a_bad_key_names_the_setting_that_fixes_it(self):
        with mock.patch.object(R.requests, "post",
                               lambda *a, **k: _Resp(401, {"error": {}})):
            with self.assertRaises(RuntimeError) as caught:
                R.groq_chat("k", "m", "hi")
        self.assertIn("Setup", str(caught.exception))

    def test_no_network_is_not_reported_as_a_groq_fault(self):
        import requests as rq
        with mock.patch.object(R.requests, "post",
                               mock.Mock(side_effect=rq.ConnectionError("x"))):
            with self.assertRaises(RuntimeError) as caught:
                R.groq_chat("k", "m", "hi")
        self.assertIn("internet", str(caught.exception).lower())

    def test_a_metered_request_is_never_repeated_on_a_real_answer(self):
        """Only transport failures retry. A server that answered has said
        something, and repeating the call would double-count the run."""
        calls = []

        def answer(url, headers=None, json=None, timeout=None):
            calls.append(1)
            return _Resp(403, {"error": {"message": "forbidden"}})

        with mock.patch.object(R.requests, "post", answer):
            with self.assertRaises(RuntimeError):
                R.groq_chat("k", "m", "hi")
        self.assertEqual(len(calls), 1)

    def test_the_chain_never_repeats_a_model(self):
        chain = R.model_chain("llama-3.1-8b-instant")
        self.assertEqual(chain[0], "llama-3.1-8b-instant")
        self.assertEqual(len(chain), len(set(chain)))


class LicenceColdStart(unittest.TestCase):
    """F-01. The server sleeps; that must not read as a refusal."""

    def test_the_authorize_timeout_survives_a_cold_start(self):
        from licensing import client
        self.assertGreaterEqual(
            client.AUTHORIZE_TIMEOUT, 30,
            "a host that sleeps takes 30-60s to wake; a shorter timeout "
            "refuses the first run of every morning")

    def test_a_transport_failure_retries_once(self):
        from licensing import client
        calls = []

        def boom(*args, **kwargs):
            calls.append(1)
            raise OSError("connection reset")

        with mock.patch("requests.post", boom), mock.patch("time.sleep"):
            with self.assertRaises(client.Unreachable):
                client._post("/v1/authorize", {}, app_version="1",
                             retries=1)
        self.assertEqual(len(calls), 2)

    def test_a_background_call_does_not_retry(self):
        """Refresh and usage failing is harmless — the cached token covers
        them — so they must not spend the customer's time on a retry."""
        from licensing import client
        calls = []

        def boom(*args, **kwargs):
            calls.append(1)
            raise OSError("nope")

        with mock.patch("requests.post", boom):
            with self.assertRaises(client.Unreachable):
                client._post("/v1/usage", {}, app_version="1")
        self.assertEqual(len(calls), 1)


class Diagnostics(unittest.TestCase):
    """F-19. The export is emailed by a customer who cannot check it."""

    def test_a_groq_key_never_reaches_the_log(self):
        self.assertNotIn("gsk_", diagnostics._scrub(
            "using key gsk_abcdefghijklmnopqrstuvwxyz012345"))

    def test_a_licence_key_and_token_are_redacted(self):
        for secret in ("PRSM-4K2XA-9WQ7M-3TYRB-8HNVE",
                       "PRSD1.eyJhbGciOiJF.c2lnbmF0dXJl",
                       "PRSMv1.eyJzdWIiOiJs.c2ln"):
            self.assertNotIn(secret, diagnostics._scrub(f"key={secret}"))

    def test_an_email_address_is_redacted(self):
        self.assertNotIn("ravi@firm.com",
                         diagnostics._scrub("sent to ravi@firm.com"))

    def test_a_password_is_redacted(self):
        self.assertNotIn("hunter2",
                         diagnostics._scrub('password: hunter2'))

    def test_writing_the_log_never_raises(self):
        with mock.patch.object(diagnostics, "log_path",
                               return_value="/nope/cannot/write.log"):
            diagnostics.write("INFO", "should not raise")   # no assertion needed

    def test_the_report_scrubs_what_it_prints(self):
        with mock.patch.object(diagnostics, "_cfg", return_value={
                "api_key": "gsk_realkeyvalue0123456789", "profile": "x"}):
            text = diagnostics.report()
        self.assertNotIn("gsk_realkeyvalue", text)
        self.assertIn("api_key", text)     # the KEY is useful, the value isn't

    def test_the_report_names_the_device_so_a_seat_can_be_released(self):
        text = diagnostics.report()
        self.assertIn("Device id", text)


class CloudSources(unittest.TestCase):
    """The Drive feature: mounted folders, no OAuth."""

    def test_a_google_drive_mount_is_found_and_labelled_by_account(self):
        home = tempfile.mkdtemp(prefix="prism-home-")
        mount = os.path.join(home, "Library", "CloudStorage",
                             "GoogleDrive-ravi@firm.com", "My Drive")
        os.makedirs(mount)
        with mock.patch("os.path.expanduser", return_value=home):
            sources = cloud.sources()
        self.assertTrue(sources)
        self.assertIn("ravi@firm.com", sources[0]["label"])
        self.assertEqual(sources[0]["kind"], "google")
        self.assertEqual(sources[0]["path"], mount)

    def test_shared_drives_are_offered_as_well_as_my_drive(self):
        home = tempfile.mkdtemp(prefix="prism-home-")
        base = os.path.join(home, "Library", "CloudStorage",
                            "GoogleDrive-ravi@firm.com")
        os.makedirs(os.path.join(base, "My Drive"))
        os.makedirs(os.path.join(base, "Shared drives"))
        with mock.patch("os.path.expanduser", return_value=home):
            labels = [s["label"] for s in cloud.sources()]
        self.assertTrue(any("Shared drives" in l for l in labels), labels)

    def test_the_same_folder_is_never_offered_twice(self):
        home = tempfile.mkdtemp(prefix="prism-home-")
        real = os.path.join(home, "Library", "CloudStorage",
                            "GoogleDrive-a@b.com", "My Drive")
        os.makedirs(real)
        os.symlink(real, os.path.join(home, "Google Drive"))
        with mock.patch("os.path.expanduser", return_value=home):
            paths_seen = [os.path.realpath(s["path"]) for s in cloud.sources()]
        self.assertEqual(len(paths_seen), len(set(paths_seen)))

    def test_nothing_mounted_is_not_an_error(self):
        home = tempfile.mkdtemp(prefix="prism-home-")
        with mock.patch("os.path.expanduser", return_value=home):
            self.assertEqual(cloud.sources(), [])
            self.assertFalse(cloud.has_google())
        self.assertIn("Drive for Desktop", cloud.install_hint())


class WorkspaceReachability(unittest.TestCase):
    """F-22. Falling back silently is worse than falling back loudly."""

    def test_an_unreachable_share_is_reported(self):
        note = W.unreachable({"workspace_root": "/Volumes/NoSuchNAS/Prism"})
        self.assertIn("can't be reached", note)
        self.assertIn("manager", note)

    def test_a_reachable_share_says_nothing(self):
        tmp = tempfile.mkdtemp(prefix="prism-ws-")
        self.assertEqual(W.unreachable({"workspace_root": tmp}), "")

    def test_a_local_only_copy_says_nothing(self):
        self.assertEqual(W.unreachable({}), "")


class SleepInhibitor(unittest.TestCase):
    """F-11. A run is tens of minutes and the user walks away."""

    def setUp(self):
        import awake
        awake.release_all()

    def test_nested_runs_release_once_at_the_end(self):
        import awake
        with mock.patch.object(awake, "_start") as start, \
             mock.patch.object(awake, "_stop") as stop:
            awake.acquire()
            awake.acquire()
            awake.release()
            self.assertFalse(stop.called, "a queue still running must stay awake")
            awake.release()
            self.assertTrue(stop.called)
            self.assertEqual(start.call_count, 1)

    def test_release_all_cleans_up_an_unbalanced_acquire(self):
        """A window closed mid-run would otherwise leave caffeinate alive and
        the machine would never sleep again until reboot."""
        import awake
        with mock.patch.object(awake, "_start"), \
             mock.patch.object(awake, "_stop") as stop:
            awake.acquire()
            awake.acquire()
            awake.release_all()
        self.assertTrue(stop.called)
        self.assertFalse(awake.held())


if __name__ == "__main__":
    unittest.main(verbosity=2)
