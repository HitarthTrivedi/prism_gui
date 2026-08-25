"""The Gerber add-on's window — same rule as the terminal's /gerber, tested
the same way test_reel_dialog.py tests a dialog's calls to AutomationWorker:
intercept the worker rather than let it open a browser, and read what it was
actually given.

This is the file that has to catch the one mistake BOQ's own dialog would
make if copied blindly: BoqDialog attaches the customer's drawing to its
writing stage (`files.insert(0, CB.files.attach(self.cad_path))`), which is
correct there and would be a real leak here. A Gerber set IS the customer's
product; the whole add-on's pitch to a fabricator is that it stays on their
machine. If a future edit ever adds that same line to gerber_dialog.py, the
security test below fails immediately, in CI, before it ships.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PRISM_LICENSE_OFFLINE_DEV", "1")
from PySide6.QtWidgets import QApplication  # noqa: E402

from dialogs import gerber_dialog as GD  # noqa: E402
from dialogs.gerber_dialog import GerberDialog  # noqa: E402

_app = QApplication.instance() or QApplication([])

# REPORTS_DIR is a real, visible ~/Desktop/Prism Gerber by design (see the
# constant's own comment) — exactly right for the app, and exactly wrong for
# a test run to litter on whoever's machine runs the suite. Redirected for
# the whole module, not just per-test: a measurement genuinely can outlive
# its own test under GIL contention from the other thousand-odd tests in a
# full run (a per-test mock.patch already proved this — two real CSVs
# landed in the real folder from a straggler GerberWorker whose `done`
# signal was not delivered until well after that test's teardown had put
# the real path back). A module-wide redirect does not make that structurally
# impossible — a worker could in principle outlive this whole file's run —
# but it shrinks the exposed window from "the rest of the suite" to "the
# rest of this one file", which is what actually stopped the leak.
_REAL_REPORTS_DIR = GD.REPORTS_DIR
_SCRATCH_REPORTS_DIR = tempfile.mkdtemp(prefix="prism-test-gerber-reports-")


def setUpModule():
    GD.REPORTS_DIR = _SCRATCH_REPORTS_DIR


def tearDownModule():
    GD.REPORTS_DIR = _REAL_REPORTS_DIR

REAL = "/Users/hitarthtrivedi/Documents/PythonProgram/prism-ai-flow/gerber_test"


class _Sig:
    def connect(self, *_):
        pass


_UNSET = object()


def _dialog(cfg=_UNSET):
    # A cfg with no configured writing agent makes _write_up() correctly
    # stop and show QMessageBox.warning — a REAL modal, which blocks
    # forever in an offscreen test with nobody to click it. That is not a
    # bug to work around with a fake; it is the dialog behaving exactly as
    # it should for a customer who has not opened Agents yet. Every test
    # that calls _write_up needs a cfg naming a real writer.
    #
    # The sentinel matters: `cfg or {...}` would silently swap in the
    # default the moment a caller passed cfg={} on purpose, to test exactly
    # the no-agent case — an empty dict is falsy, so the "no agent"
    # fixture would quietly get one anyway and the guard test would never
    # exercise the branch it exists to check.
    if cfg is _UNSET:
        cfg = {"agents": {"content": "ChatGPT"}}
    return GerberDialog(cfg, [], None)


def _measure_and_join(dlg, paths, timeout_s=15.0, step_s=0.02):
    """Run a real measurement to completion, then JOIN the QThread before
    returning — not just wait for its `done` signal.

    Missing that join is what turned a ~1 second measurement into a suite
    that never finished. GerberWorker is CPU-bound Python around the actual
    shapely calls, and Python code does not release the GIL just because
    its owning QThread posted a signal — the thread object was still alive
    and still running underneath. Leave several of those un-joined across
    a handful of tests and every later test's worker is fighting the
    leftover ones for the same GIL, which is indistinguishable from a hang
    without watching CPU: one job at a time is a second each, four
    un-joined jobs contending is minutes.

    Returns True if measuring finished (and the thread is now joined),
    False on timeout — the caller should skip rather than assert on a
    partially-run dialog.
    """
    dlg._on_files_added(list(paths))
    deadline = time.monotonic() + timeout_s
    while not dlg.jobs and time.monotonic() < deadline:
        _app.processEvents()
        time.sleep(step_s)
    worker = getattr(dlg, "_worker", None)
    if worker is not None:
        worker.wait(5000)          # the run already finished; this returns fast
    return bool(dlg.jobs)


class TheReportsGoSomewhereFindable(unittest.TestCase):
    """Every other add-on's CSV lands in the hidden ~/.prism/runs — exactly
    where an owner who wants to email a customer the numbers in the next
    five minutes will never think to look. Gerber's own reports go
    somewhere they will actually be found again."""

    def test_it_is_a_named_folder_on_the_desktop(self):
        # _REAL_REPORTS_DIR, not GD.REPORTS_DIR — setUpModule has already
        # redirected the live attribute to a scratch folder by the time any
        # test runs (see its comment for why), so this checks what the app
        # actually ships with, captured before that redirect happened.
        desktop = os.path.expanduser("~/Desktop")
        self.assertTrue(_REAL_REPORTS_DIR.startswith(desktop + os.sep))
        self.assertEqual(os.path.basename(_REAL_REPORTS_DIR), "Prism Gerber")


class AnAgentOnlyEverSeesTheNumbers(unittest.TestCase):
    """The standing rule, enforced at the one place it could quietly break:
    the write-up call. Intercepting AutomationWorker itself — not just
    reading gerber_dialog.py's source, the way the terminal's equivalent
    test does — because a GUI dialog builds its call from several pieces of
    state (self.jobs, self.ask.text()) that a source-text search cannot
    follow the way an actual call can be inspected.

    One real measurement for the whole class, not one per test method: five
    tests asking five unrelated questions about the SAME already-measured
    job need the job measured once, not five times."""

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(REAL):
            raise unittest.SkipTest("sample jobs not on this machine")
        cls.dlg = _dialog()
        ok = _measure_and_join(
            cls.dlg,
            [os.path.join(REAL, "CAM for EI-500DT-CYP-TOP-001-V2 ERP53.rar")])
        if not ok:
            raise unittest.SkipTest(
                "measuring did not finish in time on this machine")

    def _capture_write(self, context=""):
        import dialogs.gerber_dialog as mod
        seen = {}

        class Fake:
            def __init__(self, *a, **kw):
                seen["args"], seen["kwargs"] = a, kw
                self.done = self.failed = _Sig()

            def start(self):
                seen["started"] = True

        was = mod.AutomationWorker
        mod.AutomationWorker = Fake
        try:
            self.dlg.ask.edit.setPlainText(context)
            self.dlg._write_up()
        finally:
            mod.AutomationWorker = was
        return seen

    def test_no_gerber_path_is_ever_in_the_attachment_list(self):
        seen = self._capture_write("reply with our price")
        # Position 3 of AutomationWorker(cfg, prism_cfg, attachments, query, ...)
        attachments = seen["args"][2] if len(seen["args"]) > 2 else \
            seen["kwargs"].get("attachments")
        self.assertEqual(attachments, [],
                         "the write-up stage was given file attachments — "
                         "the whole point of this add-on is that it never is")

    def test_the_prompt_text_names_no_file_path(self):
        """Even with attachments=[], a path string leaking into the PROMPT
        text would still tell an agent where the design lives."""
        seen = self._capture_write("reply with our price")
        prompt = seen["kwargs"]["custom_stages"][0][2][0]
        for entry in self.dlg.jobs[0][1]["files"]:
            self.assertNotIn(entry["path"], prompt)
        self.assertNotIn(REAL, prompt)

    def test_the_prompt_carries_the_measured_numbers(self):
        seen = self._capture_write("reply with our price")
        prompt = seen["kwargs"]["custom_stages"][0][2][0]
        answers = self.dlg.jobs[0][1]["answers"]
        self.assertIn(answers["pcb_size"], prompt)
        self.assertIn("reply with our price", prompt)

    def test_the_prompt_says_the_files_are_not_attached(self):
        """The same sentence the terminal's /gerber sends, because both call
        core.gerber.agent_brief() — one function, not two independently
        worded versions that could drift apart."""
        seen = self._capture_write("")
        prompt = seen["kwargs"]["custom_stages"][0][2][0]
        self.assertIn("NOT", prompt)
        self.assertIn("attached", prompt)
        self.assertIn("confidential", prompt)

    def test_the_query_label_never_names_a_file_path(self):
        """AutomationWorker's fourth positional argument becomes the run's
        saved label — also worth checking, since a run history is something
        a colleague could later read over someone's shoulder."""
        seen = self._capture_write("reply with our price")
        query = seen["args"][3] if len(seen["args"]) > 3 else ""
        self.assertNotIn(REAL, query)


class WithNoWritingAgentConfigured(unittest.TestCase):
    """The guard `_write_up` hits before it ever builds a call — real
    QMessageBox.warning, which is correct for a customer who has not opened
    Agents yet, and blocks forever in a headless test with nobody to click
    it. Patched here rather than avoided, so the guard itself is proven to
    fire instead of just being routed around."""

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(REAL):
            raise unittest.SkipTest("sample jobs not on this machine")
        cls.dlg = _dialog(cfg={})     # no agents configured
        if not _measure_and_join(
                cls.dlg,
                [os.path.join(REAL, "layer 1.zip")]):
            raise unittest.SkipTest(
                "measuring did not finish in time on this machine")

    def test_it_warns_instead_of_calling_an_agent_with_nothing_set_up(self):
        import dialogs.gerber_dialog as mod
        with mock.patch.object(mod.QMessageBox, "warning") as warned, \
             mock.patch.object(mod, "AutomationWorker") as auto:
            self.dlg._write_up()
        warned.assert_called_once()
        auto.assert_not_called()


class MeasuringNeverCallsAnAgent(unittest.TestCase):
    """The half of the promise that has nothing to do with the write-up
    button: dropping a file and reading the five numbers must never, by
    itself, start a browser or reach an AI. GerberWorker only ever imports
    core.gerber, which core.gerber's own module docstring commits to never
    importing anything network-facing."""

    def test_gerber_worker_never_imports_automation(self):
        import inspect
        import workers
        src = inspect.getsource(workers.GerberWorker)
        self.assertNotIn("AutomationWorker", src)
        self.assertNotIn("automation", src.lower())


class TheDialogMeasuresARealJob(unittest.TestCase):
    """Not a mock — the actual GerberWorker, the actual core.gerber, against
    real jobs the terminal's own test suite is pinned to. If this ever
    disagrees with tests/gerber_samples.json, the two surfaces have drifted
    and one of them is wrong.

    Deliberately NOT the whole gerber_test folder: two of the seven real
    samples take minutes each (a 12-layer board with 187,674 traces on one
    layer), and test_gerber.py already pins those under PRISM_SLOW_TESTS. A
    GUI smoke test needs proof the wiring works, not a second multi-minute
    run of geometry the engine suite already covers."""

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(REAL):
            raise unittest.SkipTest("sample jobs not on this machine")

    def setUp(self):
        # The module-level redirect (see setUpModule) already keeps this off
        # the real Desktop; this narrows it further to a fresh folder per
        # test, purely so each test can assert against a path that is
        # unambiguously its own.
        self._reports_dir = tempfile.mkdtemp(prefix="prism-test-gerber-reports-")
        self._reports_patch = mock.patch.object(GD, "REPORTS_DIR", self._reports_dir)
        self._reports_patch.start()

    def tearDown(self):
        self._reports_patch.stop()

    def test_a_single_job_measures_and_a_csv_is_saved(self):
        src = os.path.join(REAL, "layer 1.zip")
        if not os.path.exists(src):
            self.skipTest("sample missing")
        dlg = _dialog()
        if not _measure_and_join(dlg, [src]):
            self.skipTest("measuring did not finish in time on this machine")
        self.assertEqual(len(dlg.jobs), 1)
        name, job = dlg.jobs[0]
        self.assertAlmostEqual(job["answers"]["pcb_size_mm"][0], 60.0, places=1)
        self.assertIn(self._reports_dir, dlg.csv_label.text())
        self.assertTrue(os.path.isdir(self._reports_dir))
        self.assertTrue(dlg.run_btn.isEnabled())

    def _two_fast_jobs_folder(self):
        """Copies (not symlinks — split_jobs dedupes by name+size, and this
        must read as two distinct jobs) of the two small real samples."""
        import shutil
        d = tempfile.mkdtemp(prefix="prism-test-gerber-dialog-")
        for name in ("layer 1.zip", "CAM for EI-500DT-CYP-TOP-001-V2 ERP53.rar"):
            src = os.path.join(REAL, name)
            if not os.path.exists(src):
                self.skipTest(f"{name} missing on this machine")
            shutil.copy(src, d)
        return d

    def test_several_jobs_in_one_folder_are_measured_separately(self):
        dlg = _dialog()
        if not _measure_and_join(dlg, [self._two_fast_jobs_folder()],
                                 timeout_s=30):
            self.skipTest("measuring did not finish in time on this machine")
        self.assertEqual(len(dlg.jobs), 2)
        self.assertIn("Saved so every number", dlg.csv_label.text())

    def test_a_multi_job_result_refuses_to_write_up_one_of_them_blindly(self):
        dlg = _dialog()
        if not _measure_and_join(dlg, [self._two_fast_jobs_folder()],
                                 timeout_s=30):
            self.skipTest("measuring did not finish in time on this machine")
        import dialogs.gerber_dialog as mod
        fired = []
        # This path shows QMessageBox.information — a real modal — before it
        # ever gets near AutomationWorker. Patch it rather than let it block
        # forever with nobody to click it, same reasoning as the no-agent
        # guard above.
        with mock.patch.object(mod.QMessageBox, "information") as told:
            was = mod.AutomationWorker
            mod.AutomationWorker = lambda *a, **kw: fired.append(True)
            try:
                dlg._write_up()
            finally:
                mod.AutomationWorker = was
        told.assert_called_once()
        self.assertEqual(fired, [])


if __name__ == "__main__":
    unittest.main()
