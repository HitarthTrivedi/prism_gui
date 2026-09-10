"""Every background thread subclasses `workers._Worker`, never `QThread`.

This is the most expensive rule in the codebase to have broken, and until
now it was enforced only by remembering it.

What goes wrong
───────────────
A QThread garbage-collected while its underlying thread is still running
makes Qt call qFatal(): "QThread: Destroyed while thread is still running".
That is a process abort, not an exception -- 0xC0000409 on Windows, with no
Python traceback, no `except` that can catch it, and nothing in the log
after it. CHANGES.md records why it kept being rediscovered rather than
recognised: "the crash happens after the last thing anyone logs."

The trap is that `Signal.connect()` does NOT keep the emitter alive. A
worker held only through its `done`/`failed` connections has an effective
refcount of zero the moment the caller's own reference goes -- a dialog
closing, an attribute reassigned to the next run's worker, a local going
out of scope. The next collection destroys it mid-run and Prism dies.

Why a test and not a note
─────────────────────────
This exact defect was fixed SIX times by THREE people across four weeks.
Five of those were per-call-site patches, and each one found a site the
previous had missed. Only the sixth was structural: `_Worker`, which
anchors every running worker in a module-level set from start() until its
finished signal fires, so no call site can drop a running worker by
accident.

BUGS.md's entry ends with an instruction -- "any new background thread must
subclass workers._Worker, never QThread directly". A rule that must be
obeyed at twenty-odd call sites by five people is a bug with a delay on it.
This file is that instruction, executable.

It also matters for the add-ons restructure specifically: workers move
between packages, and a copy-paste of an existing worker into a new add-on
is exactly how `class Foo(QThread)` gets written again.

Scope
─────
`prism_terminal/` is the engine, shared with the unlicensed CLI, and has no
Qt at all. `tests/` may construct whatever it needs to test threading, and
`devtools/` is never packaged.
"""
from __future__ import annotations

import ast
import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication              # noqa: E402

import workers                                          # noqa: E402

_app = QApplication.instance() or QApplication([])

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", "__pycache__", "build", "dist", "release", "videos",
             "prism_terminal", ".venv", "venv", "node_modules", "tests",
             "devtools", ".claude"}

# The one place a bare QThread subclass is correct: the anchor itself.
ANCHOR_FILE = "workers.py"
ANCHOR_CLASS = "_Worker"


def _is_qthread(base: ast.expr) -> bool:
    """`QThread` or `QtCore.QThread` — both spellings appear in Qt code."""
    if isinstance(base, ast.Name):
        return base.id == "QThread"
    if isinstance(base, ast.Attribute):
        return base.attr == "QThread"
    return False


def _sources():
    for folder, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if name.endswith(".py"):
                path = os.path.join(folder, name)
                yield os.path.relpath(path, ROOT).replace(os.sep, "/"), path


def _bare_qthread_subclasses(rel: str, path: str) -> list[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            tree = ast.parse(f.read(), filename=path)
    except (OSError, SyntaxError):
        return []

    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if not any(_is_qthread(b) for b in node.bases):
            continue
        if rel == ANCHOR_FILE and node.name == ANCHOR_CLASS:
            continue          # the anchor is allowed to be the thing it wraps
        found.append("%s:%d  class %s(QThread)" % (rel, node.lineno, node.name))
    return found


class NoBackgroundThreadSubclassesQThreadDirectly(unittest.TestCase):

    def test_every_worker_goes_through_the_anchor(self):
        offenders = []
        for rel, path in _sources():
            offenders.extend(_bare_qthread_subclasses(rel, path))
        self.assertEqual(
            offenders, [],
            "These classes subclass QThread directly:\n  "
            + "\n  ".join(offenders)
            + "\n\nSubclass workers._Worker instead. A bare QThread that is "
              "garbage-collected while still running aborts the whole "
              "process with no Python traceback -- and connecting its "
              "signals does NOT keep it alive, so this breaks the first "
              "time a caller's reference goes out of scope rather than the "
              "first time the code runs. See BUGS.md entry 0a.")

    def test_the_anchor_is_still_where_this_test_thinks_it_is(self):
        """If _Worker is renamed or moved, the exemption above silently starts
        excusing nothing -- or worse, excusing the wrong class."""
        self.assertTrue(hasattr(workers, ANCHOR_CLASS),
                        "workers._Worker is gone; every worker in this repo "
                        "depends on it and so does the test above")


class TheAnchorActuallyAnchors(unittest.TestCase):
    """The inheritance check above passes just as happily if somebody guts
    _Worker.start(). These two assertions are what make it mean something."""

    def test_a_running_worker_is_held_by_the_anchor(self):
        class _Trivial(workers._Worker):
            def run(self):
                pass

        w = _Trivial()
        self.addCleanup(workers._running.discard, w)
        self.assertNotIn(w, workers._running,
                         "a worker that has not been started must not be held")

        w.start()
        # Held immediately, and deterministically so: _forget is a QUEUED
        # connection onto this thread, so it cannot have run before we get
        # back here -- nothing has processed events yet.
        self.assertIn(w, workers._running,
                      "workers._Worker.start() no longer anchors the worker, "
                      "so a running worker can once again be garbage-collected "
                      "mid-run and abort the process")
        self.assertTrue(w.wait(5000), "the trivial worker never finished")

    def test_the_anchor_set_drains(self):
        """A set that only ever grows leaks every worker for the life of the
        process, and the inheritance test above would not notice.

        _forget is called DIRECTLY rather than by pumping the event queue.
        Pumping is what the queued `finished` connection would do in the real
        app, but in a shared-process test suite QApplication.processEvents()
        also runs every OTHER test's deferred callbacks -- and this suite
        leaves singleShot lambdas queued against dialogs whose C++ side is
        already gone. Doing that here corrupted the heap and killed the whole
        run (Windows 0xc0000374), several hundred tests after the one that
        posted the callback. The connection itself is asserted separately
        below, which is the half that pumping was supposed to prove.
        """
        class _Trivial(workers._Worker):
            def run(self):
                pass

        w = _Trivial()
        workers._running.add(w)
        w._forget()
        self.assertNotIn(
            w, workers._running,
            "workers._Worker._forget() no longer releases the worker, so the "
            "anchor set grows without bound")

    def test_start_wires_finished_to_forget(self):
        """The other half of the drain: that _forget is actually connected to
        something. Read from the source because PySide6 offers no way to
        enumerate a signal's receivers."""
        source = inspect.getsource(workers._Worker.start)
        self.assertIn("_running.add", source,
                      "start() no longer anchors the worker")
        self.assertIn("finished.connect", source,
                      "start() no longer arranges for the worker to be "
                      "released when it finishes")


if __name__ == "__main__":
    unittest.main()
