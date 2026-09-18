"""Deleting past runs from the History screen.

The first test this panel has ever had, and it exists because the feature it
covers is the first thing in the GUI that deletes a piece of the user's work.

Two things are pinned here above all others:

  · **the run folder is a junk drawer.** Alongside `run_*.json` it holds the
    artefacts runs produced -- reel scene specs and their .mp4, BOQ and
    Gerber CSVs -- none of them named after the run that made them, and
    `main_window` globs `reel_*.json` there to find the latest spec. A
    delete that tidied those away would break the reel editor and throw away
    finished work. `test_a_produced_file_beside_the_records_is_never_touched`
    is what catches that being "simplified" later.

  · **the isolation.** `cfg["runs_dir"]` isolates nothing -- `_run_files`
    ignores it and resolves through `workspace.runs_dir()`. A test that
    assumed otherwise deleted fifty-two of a developer's real saved runs
    before anybody noticed (see tests/conftest.py). Both doors are shut
    below, for the module, the way tests/test_gates.py:60-75 does it.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication                 # noqa: E402

import core_bridge as _CB                                  # noqa: E402
import dashboard_data as DATA                              # noqa: E402
import workspace as _WS                                    # noqa: E402

_app = QApplication.instance() or QApplication([])

_SCRATCH_RUNS = tempfile.mkdtemp(prefix="prism-test-history-")


class RunFolderTest(unittest.TestCase):
    """Isolation is re-established for EVERY test, and then proved.

    Module-level patching is not enough and this file is the proof. Both
    this module and tests/test_gates.py redirect the same global,
    `workspace.runs_dir`, in setUpModule and restore it in tearDownModule.
    pytest-randomly interleaves items from different modules, so one
    module's teardown fires while the other is still running and hands the
    REAL function back mid-suite.

    test_gates only ever WRITES runs, so that flaw sat there harmlessly. This
    module deletes, and the first full-suite run with it removed thirteen of
    a developer's real saved runs -- the same accident conftest.py records
    happening once before, at fifty-two.

    So: patched per test rather than per module, and then CHECKED. A
    destructive test proves its isolation before it is allowed to destroy
    anything; it does not assume it.
    """

    def setUp(self):
        for target, name in ((_WS, "runs_dir"),):
            patch = mock.patch.object(target, name,
                                      lambda *a, **kw: _SCRATCH_RUNS)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(_CB.config, "RUNS_DIR", _SCRATCH_RUNS)
        patch.start()
        self.addCleanup(patch.stop)

        # The safety net. If anything ever hands the real resolver back
        # again, every test in this file fails here -- loudly, before a
        # single os.remove runs -- instead of deleting somebody's history.
        resolved = os.path.realpath(_WS.runs_dir("personal", {}))
        real_home = os.path.realpath(
            os.path.join(os.path.expanduser("~"), ".prism"))
        self.assertEqual(resolved, os.path.realpath(_SCRATCH_RUNS),
                         "run folder is not the scratch one -- refusing to "
                         "run a destructive test")
        self.assertFalse(resolved.startswith(real_home),
                         "run folder resolves inside the real ~/.prism -- "
                         "refusing to run a destructive test")

        for name in os.listdir(_SCRATCH_RUNS):
            os.remove(os.path.join(_SCRATCH_RUNS, name))

    def write_run(self, stamp: int, **extra) -> str:
        path = os.path.join(_SCRATCH_RUNS, "run_%d.json" % stamp)
        record = {"query": "task %d" % stamp, "title": "Task %d" % stamp,
                  "agents": {"plan": "ChatGPT"}}
        record.update(extra)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f)
        return path

    def names(self) -> list[str]:
        return sorted(os.listdir(_SCRATCH_RUNS))


class DeletingRunRecords(RunFolderTest):

    def test_one_goes_and_the_others_stay(self):
        a, b, c = (self.write_run(n) for n in (1, 2, 3))
        self.assertEqual(DATA.delete_runs({}, [b]), (1, []))
        self.assertEqual(self.names(), ["run_1.json", "run_3.json"])

    def test_several_at_once(self):
        paths = [self.write_run(n) for n in (1, 2, 3)]
        gone, refused = DATA.delete_runs({}, paths[:2])
        self.assertEqual((gone, refused), (2, []))
        self.assertEqual(self.names(), ["run_3.json"])

    def test_a_record_that_vanished_first_is_not_an_error(self):
        """recent_runs() lists, then a person clicks. The gap is real."""
        path = self.write_run(1)
        os.remove(path)
        self.assertEqual(DATA.delete_runs({}, [path]), (1, []))

    def test_an_empty_list_does_nothing(self):
        self.write_run(1)
        self.assertEqual(DATA.delete_runs({}, []), (0, []))
        self.assertEqual(self.names(), ["run_1.json"])


class TheJunkDrawerIsLeftAlone(RunFolderTest):
    """The run folder holds produced work as well as records."""

    def test_a_produced_file_beside_the_records_is_never_touched(self):
        self.write_run(1)
        for junk in ("gerber_123.csv", "gerber_summary_123.csv",
                     "boq_quantities_9.csv", "discovered_4.csv"):
            open(os.path.join(_SCRATCH_RUNS, junk), "w").write("x")
        DATA.delete_runs({}, [os.path.join(_SCRATCH_RUNS, "gerber_123.csv")])
        self.assertIn("gerber_123.csv", self.names())

    def test_a_reel_spec_is_never_touched(self):
        """main_window globs reel_*.json to find the latest spec, and the
        reel editor needs the .mp4 and its .json side by side."""
        spec = os.path.join(_SCRATCH_RUNS, "reel_77.json")
        open(spec, "w").write("{}")
        open(os.path.join(_SCRATCH_RUNS, "reel_77.mp4"), "w").write("x")
        gone, refused = DATA.delete_runs({}, [spec])
        self.assertEqual(gone, 0)
        self.assertEqual(refused, [spec])
        self.assertIn("reel_77.json", self.names())
        self.assertIn("reel_77.mp4", self.names())

    def test_clearing_everything_leaves_the_produced_files(self):
        runs = [self.write_run(n) for n in (1, 2, 3)]
        open(os.path.join(_SCRATCH_RUNS, "gerber_5.csv"), "w").write("x")
        DATA.delete_runs({}, runs)
        self.assertEqual(self.names(), ["gerber_5.csv"])


class APathFromAWidgetIsNotTrusted(RunFolderTest):
    """The caller hands back paths it was given. Check them anyway."""

    def test_a_file_outside_the_run_folder_is_refused(self):
        other = tempfile.mkdtemp()
        stray = os.path.join(other, "run_666.json")
        open(stray, "w").write("{}")
        gone, refused = DATA.delete_runs({}, [stray])
        self.assertEqual((gone, refused), (0, [stray]))
        self.assertTrue(os.path.exists(stray))

    def test_a_path_that_climbs_out_is_refused(self):
        other = tempfile.mkdtemp()
        stray = os.path.join(other, "run_666.json")
        open(stray, "w").write("{}")
        climb = os.path.join(_SCRATCH_RUNS, "..",
                             os.path.basename(other), "run_666.json")
        gone, _refused = DATA.delete_runs({}, [climb])
        self.assertEqual(gone, 0)
        self.assertTrue(os.path.exists(stray))

    def test_something_that_is_not_a_run_record_is_refused(self):
        for name in ("notes.txt", "run_1.txt", "myrun_1.json"):
            path = os.path.join(_SCRATCH_RUNS, name)
            open(path, "w").write("x")
            self.assertEqual(DATA.delete_runs({}, [path]), (0, [path]), name)
            self.assertTrue(os.path.exists(path), name)


class TheScreen(RunFolderTest):
    """Against the real HistoryPanel, with the confirmation stubbed.

    `_confirm_delete` is a seam for exactly this reason -- a test must never
    have to press a button inside a modal.
    """

    def panel(self, confirm: bool = True):
        from widgets.history_panel import HistoryPanel
        screen = HistoryPanel({})
        # build() directly, not refresh(): the panel is LAZY, so refresh()
        # deliberately does nothing while it is off-screen.
        screen.build()
        screen._confirm_delete = lambda *a, **kw: confirm
        return screen

    def test_a_row_delete_removes_that_run(self):
        self.write_run(1)
        self.write_run(2)
        screen = self.panel()
        target = [r for r in screen._runs if r["path"].endswith("run_1.json")]
        screen._delete(target)
        self.assertEqual(self.names(), ["run_2.json"])

    def test_saying_no_deletes_nothing(self):
        self.write_run(1)
        screen = self.panel(confirm=False)
        screen._delete(list(screen._runs))
        self.assertEqual(self.names(), ["run_1.json"])

    def test_clear_all_empties_the_records(self):
        for n in (1, 2, 3):
            self.write_run(n)
        open(os.path.join(_SCRATCH_RUNS, "gerber_1.csv"), "w").write("x")
        screen = self.panel()
        screen._clear_all()
        self.assertEqual(self.names(), ["gerber_1.csv"])

    def test_clear_all_on_an_empty_history_asks_nothing(self):
        screen = self.panel()
        asked = []
        screen._confirm_delete = lambda *a, **kw: asked.append(1) or True
        screen._clear_all()
        self.assertEqual(asked, [])

    def test_ticking_rows_drives_the_bulk_bar(self):
        a = self.write_run(1)
        self.write_run(2)
        screen = self.panel()
        self.assertFalse(screen._bulk.isVisible())
        screen._pick(a, True)
        self.assertEqual(screen._picked, {a})
        screen._pick(a, False)
        self.assertEqual(screen._picked, set())

    def test_deleting_the_selection_removes_exactly_those(self):
        a = self.write_run(1)
        self.write_run(2)
        c = self.write_run(3)
        screen = self.panel()
        screen._pick(a, True)
        screen._pick(c, True)
        screen._delete_picked()
        self.assertEqual(self.names(), ["run_2.json"])

    def test_the_selection_is_cleared_after_a_reload(self):
        a = self.write_run(1)
        screen = self.panel()
        screen._pick(a, True)
        screen._delete_picked()
        screen._reload()
        self.assertEqual(screen._picked, set())

    def test_the_folded_row_deletes_every_run_it_stands_for(self):
        """The aborts are the bulk of a real history and are all the same
        failure, so clearing the fold is the common wish."""
        for n in (1, 2, 3, 4):
            self.write_run(n, error="Chrome would not launch", agents={})
        screen = self.panel()
        aborted = [r for r in screen._runs if not r["ok"]]
        self.assertEqual(len(aborted), 4)
        screen._delete(aborted)
        self.assertEqual(self.names(), [])

    def test_home_is_told_the_list_moved(self):
        """Home shows the same records in its activity list and counters."""
        self.write_run(1)
        screen = self.panel()
        told = []
        screen.runs_changed.connect(lambda: told.append(1))
        screen._delete(list(screen._runs))
        screen._reload()
        self.assertEqual(told, [1])

    def test_the_artifact_folder_a_run_points_at_survives(self):
        kept = tempfile.mkdtemp()
        self.write_run(1, artifacts=kept)
        screen = self.panel()
        screen._delete(list(screen._runs))
        self.assertEqual(self.names(), [])
        self.assertTrue(os.path.isdir(kept),
                        "deleting a run must not shred the work it produced")


if __name__ == "__main__":
    unittest.main()
