"""A run file that disappears mid-walk must not take the window with it.

`recent_runs` is called from `HomePanel.build`, which runs inside
`MainWindow.__init__`. So an exception raised here does not blank a panel —
the main window never comes into existence, and a frozen build has no console
to say why. It is a real situation on a synced or shared team folder, where
another machine can delete a run between the directory listing and the read.

The guard was written once, with a comment explaining exactly this, and then
quietly defeated: a second `os.path.getmtime(path)` was called further down
the same function, outside the try, and the guarded value it duplicated was
left unused. This pins the property rather than the line, so a third
reintroduction fails here instead of on a customer's machine.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dashboard_data as DATA  # noqa: E402


class RunFileVanishesMidWalk(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.cfg = {"runs_dir": self.dir.name}
        self.paths = []
        for i in range(3):
            path = os.path.join(self.dir.name, f"run{i}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"query": f"task {i}",
                           "agents": {"research": "Perplexity"}}, f)
            self.paths.append(path)

    def tearDown(self):
        self.dir.cleanup()

    def test_a_file_deleted_after_listing_does_not_raise(self):
        """The whole point: survive it, do not propagate it.

        `_run_files` is stubbed to return THIS TEST'S temp files and nothing
        else. That is not tidiness — the first version of this test called the
        real `_run_files(self.cfg)` and deleted `listed[0]`, on the assumption
        that passing `cfg["runs_dir"]` pointed it at the temp directory. It
        does not: `_run_files` ignores that key entirely and resolves through
        `workspace.runs_dir(identity.viewing()["mid"], cfg)`, i.e. the real
        ~/.prism/runs. So every run of the suite deleted one of the user's
        actual saved runs, and the `skipTest` guard meant to catch that never
        fired — it only checked that the list was non-empty, and it was
        non-empty precisely because it was full of real data.

        A test that reaches outside its own tempdir is a bug even when it
        passes. Nothing below touches a path this test did not create.
        """
        doomed = self.paths[0]
        real = DATA._run_files

        def listing_then_delete(cfg, *a, **k):
            # Only ever this test's own files.
            out = list(self.paths)
            if os.path.exists(doomed):
                os.remove(doomed)     # the race: gone between list and read
            return out

        DATA._run_files = listing_then_delete
        try:
            runs = DATA.recent_runs(self.cfg, 10)     # must not raise
        finally:
            DATA._run_files = real

        self.assertNotIn(doomed, [r["path"] for r in runs],
                         "the deleted run should be skipped, not reported")
        self.assertEqual(len(runs), 2, "the surviving two should still load")

    def test_the_suite_never_reads_the_real_run_folder(self):
        """Belt and braces on the mistake above.

        `_run_files` ignoring `cfg["runs_dir"]` is the trap: any test that
        passes a temp cfg and assumes isolation is actually operating on the
        user's home directory. Assert the shape of that so the next person
        writing a dashboard_data test finds out from a failure here rather
        than from missing history.
        """
        import inspect
        src = inspect.getsource(DATA._run_files)
        self.assertNotIn("runs_dir\"]", src.replace("'", '"'),
                         "if _run_files starts honouring cfg['runs_dir'], "
                         "update the tests that stub it out")
        self.assertIn("workspace.runs_dir", src,
                      "_run_files resolves through workspace, so a temp cfg "
                      "does NOT isolate it — stub it, never call it for real")

    def test_every_getmtime_in_recent_runs_is_guarded(self):
        """Structural, because the runtime race is timing-dependent.

        Reintroducing the bug means adding a getmtime outside the try, which
        this catches deterministically on every run.
        """
        import ast
        import inspect
        import textwrap

        src = textwrap.dedent(inspect.getsource(DATA.recent_runs))
        tree = ast.parse(src)

        all_calls = {n.lineno for n in ast.walk(tree)
                     if isinstance(n, ast.Call)
                     and getattr(n.func, "attr", "") == "getmtime"}
        guarded = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                guarded |= {n.lineno for n in ast.walk(node)
                            if isinstance(n, ast.Call)
                            and getattr(n.func, "attr", "") == "getmtime"}

        self.assertEqual(
            all_calls - guarded, set(),
            "recent_runs() calls os.path.getmtime outside a try/except. "
            "Home is built during MainWindow.__init__, so this does not blank "
            "a panel — it stops the window existing at all.")


class FilterActiveArtifactsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _touch(self, name: str, mtime_offset: int = 0) -> str:
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write("test")
        t = 1700000000 + mtime_offset
        os.utime(path, (t, t))
        return path

    def test_filters_superseded_reels_and_specs(self):
        # 3 runs/follow-ups of a reel task
        v1_mp4 = self._touch("Titan Fast Track Watch Belt Reel - Reel.mp4", 10)
        v1_json = self._touch("Titan Fast Track Watch Belt Reel - Reel.json", 10)
        v2_mp4 = self._touch("fix the formatting issue in text - Reel.mp4", 20)
        v2_json = self._touch("fix the formatting issue in text - Reel.json", 20)
        v3_audio = self._touch("generate a voice for this reel - Audio - voiceover.mp3", 30)
        v3_mp4 = self._touch("generate a voice for this reel - Reel.mp4", 30)
        v3_json = self._touch("generate a voice for this reel - Reel.json", 30)

        # 5 distinct artwork scene images
        art1 = self._touch("Titan Fast Track Watch Belt Reel - Artwork.png", 5)
        art2 = self._touch("Titan Fast Track Watch Belt Reel - Artwork 2.png", 5)
        art3 = self._touch("Titan Fast Track Watch Belt Reel - Artwork 3.png", 5)
        art4 = self._touch("Titan Fast Track Watch Belt Reel - Artwork 4.png", 5)
        art5 = self._touch("Titan Fast Track Watch Belt Reel - Artwork 5.png", 5)

        all_paths = [
            v1_mp4, v1_json, v2_mp4, v2_json, v3_audio, v3_mp4, v3_json,
            art1, art2, art3, art4, art5,
        ]

        active = DATA.filter_active_artifacts(all_paths)

        # Must pick ONLY the newest reel MP4 (v3_mp4)
        self.assertIn(v3_mp4, active)
        self.assertNotIn(v1_mp4, active)
        self.assertNotIn(v2_mp4, active)

        # Must pick ONLY the newest reel spec JSON (v3_json)
        self.assertIn(v3_json, active)
        self.assertNotIn(v1_json, active)
        self.assertNotIn(v2_json, active)

        # Must keep the newest audio voiceover
        self.assertIn(v3_audio, active)

        # Must keep all 5 distinct scene images
        for a in (art1, art2, art3, art4, art5):
            self.assertIn(a, active)


if __name__ == "__main__":
    unittest.main()

