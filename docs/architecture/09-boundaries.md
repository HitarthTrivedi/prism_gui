# Boundaries

The rules about what may depend on what, and — for every one of them — the
test that fails when it is broken.

That pairing is the point of this document. Prism has had good rules before.
They lived in comments, in `BUGS.md` entries ending "any new X must remember
to Y", and in people's heads, and each of them was eventually broken by
somebody who had not read the comment. **A rule enforced by memory, across
five people and twenty call sites, is a bug with a delay on it.**

So: if a rule below has no test beside it, it is not a rule yet. Say so
rather than trusting it.

---

## 1. Dependencies point one way

```
    addons/  ──▶  the shell (widgets/, dialogs/, root modules)  ──▶  core_bridge  ──▶  the engine
```

Nothing points back up the chain.

| Rule | Enforced by |
| --- | --- |
| **Only `core_bridge.py` imports the engine.** Nothing else may `from core import …` | `tests/test_engine_facade.py` |
| **No add-on imports another add-on** | `tests/test_addon_contract.py::NoAddOnKnowsAnotherAddOn` |
| **A data module imports no dialogs and no widgets** | `tests/test_layering.py` |
| **A widget may not import a dialog at module scope** | `tests/test_layering.py` |

### Why the engine rule matters more than it looks

`core_bridge.py` puts `prism_terminal` on `sys.path`, decides which of three
possible checkouts wins, installs the Groq meter from the GUI side so the
submodule stays licence-free, and wraps every heavy module in a lazy getter
with an availability probe. A direct `from core import gerber` skips all of
it — and it *also* depends on something else having imported the bridge
first, so it works until the import order changes.

The test is AST-based, not grep: several docstrings in this repo quote
`from core import …` while explaining this very rule.

### Why the widget rule is "at module scope", not "never"

A panel opening a modal on a click is normal, and four panels do it
(artifacts → preview, settings → licence, settings → legal, support →
contact). Those are navigational and are written as deferred imports.

What is banned is needing a dialog in order to **load**. That is a
load-order dependency and a barrier to moving either file — which is exactly
what stopped Email automation being extractable until `inquiry_config.py`
existed.

---

## 2. Add-ons

| Rule | Enforced by |
| --- | --- |
| **The manifest layer is stdlib-only** — no Qt, no engine, no theme | `tests/test_addon_contract.py::TheManifestLayerIsStdlibOnly` (AST **and** a real bare-interpreter subprocess) |
| **`registry.py`'s imports are static.** Never `importlib` | review — see below |
| **Every add-on package is in the registry** | `tests/test_addon_contract.py` |
| **Every `feature` key exists in `plans.FEATURES`** | `tests/test_addon_contract.py` |
| **Every dotted reference resolves** | `tests/test_addon_contract.py::TheDottedReferencesResolve` |
| **An add-on answers for its own offers, from its own package** | `tests/test_addon_contract.py` |
| **A reference into another add-on's package must be declared `provided_by`** | `tests/test_addon_contract.py` |
| **Run prefixes are unique and never translatable** | `tests/test_addon_contract.py` |
| **Every add-on's licence gate holds** | `tests/test_addon_gates.py` |

### The static-import rule, which has no test and needs one

`addons/registry.py` imports each manifest by name, one line each. A dynamic
registry —

```python
for name in os.listdir("addons"):
    importlib.import_module("addons.%s.addon" % name)
```

— is shorter, prettier, needs no edit per add-on, and is **completely
invisible to PyInstaller's analyser.** Development would be perfect. The
frozen build would ship an empty shelf, in a windowed app with no console,
and the first person to find out would be a customer.

`packaging/prism.spec` already records this class of accident happening
once. Until somebody writes the test, this is enforced at review.

The backstops that *are* tested: `registry.addon_modules()` walks `addons/`
recursively for `hiddenimports`, `packaging/build.py` passes
`--include-package=addons` for the Nuitka path
(`tests/test_packaging_enumerates.py`), and `main.py`'s selftest resolves
every entry point at startup so `packaging/smoke_test.py` goes red rather
than a customer.

### `provided_by`, and why it exists

BOM has its own rail row, its own screen and its own front door, but the
thing it opens is **BOQ's dialog with `mode="bom"`**. Moving BOQ therefore
left BOM's manifest naming a module inside another add-on's package — the
import ban, laundered through a string, silently passing every test.

`provided_by="boq"` declares it. The test requires the declaration. That
makes the coupling visible and tested; it does not make it good. The fix is
for BOM to own a dialog, or for the two to be one add-on with two front
doors.

---

## 3. Threads

| Rule | Enforced by |
| --- | --- |
| **Every background thread subclasses `workers._Worker`, never `QThread`** | `tests/test_worker_mandate.py` |

A `QThread` garbage-collected while its OS thread is still running makes Qt
call `qFatal()`. That is a process abort — `0xC0000409` on Windows, no
Python traceback, no `except` that can catch it, nothing in the log after
it. `CHANGES.md` records why it kept being rediscovered rather than
recognised: *"the crash happens after the last thing anyone logs."*

The trap is that **`Signal.connect()` does not keep the emitter alive**, so
a worker held only through its `done`/`failed` connections dies the moment
the caller's reference goes. It breaks on a timing change, not a code path.

This defect was fixed **six times by three people across four weeks**. Five
were per-call-site patches and each found a site the last had missed. The
sixth — `_Worker`, which anchors every running worker in a module-level set
from `start()` until `finished` — is the structural one. When the test was
first written it immediately found two threads still outside it, including
the wake-word listener that was the *original* instance of the bug.

The test asserts two things, not one: that nothing subclasses `QThread`
directly, **and** that `_Worker` still actually anchors and releases. The
first alone passes just as happily if somebody guts `start()`.

---

## 4. The build contract surface

These files are reached **by path**, not by import — a PyInstaller spec, a
Nuitka command line, a few lines of YAML. Move one and nothing fails until a
release.

```
main.py  app_meta.py  updater.py  apply_update.py  update_manifest.py
paths.py  core_bridge.py  licensing/  packaging/
```

| Rule | Enforced by |
| --- | --- |
| **Those paths do not move** | `tests/test_repo_layout.py` |
| **CI's inline `python -c` imports still resolve** | `tests/test_ci_entrypoints.py` |
| **The engine walk is recursive; `addons/` is enumerated** | `tests/test_packaging_enumerates.py` |
| **The body stack's `addWidget` order matches `main_window.SCREENS`** | `tests/test_screen_registry.py` |

The subtle one is `paths.py`. `bundle_dir()` falls back to its own
`__file__`, so moving it one directory deeper makes every asset resolve one
directory too high **in source checkouts only** — frozen builds use
`sys._MEIPASS` and stay perfectly fine. CI green, developers broken, which
is backwards.

---

## 5. Names the licence server also knows

The server is structurally blind to file layout — every request carries IDs,
a device fingerprint, a version string and feature keys, never a path. But
three vocabularies are shared, and **all three break on renames, never on
moves**:

| Vocabulary | Shared via | Breaks when |
| --- | --- | --- |
| `plans.FEATURES` keys | the token's `feat` claim, the lease's `scope` | a key is renamed. Hardcoded both sides; **the server wins** |
| `AGENT_REGISTRY` display names (`"ChatGPT"`) | published payload override rows | an entry is renamed — the row silently stops matching |
| `core/agents.py`, `core/router.py`, `pros_cons.txt` | a hand-copied snapshot in `/v1/payload` | they are edited — nothing detects the drift |

Moving files is free. Renaming these is not. There is no test for this one
because the other half lives in a different repository; it is written down
here instead, which is the honest state of it.

---

## 6. The rule about rules

> When a bug is fixed, the fix either becomes structurally impossible to
> undo, or it gets a test.

A `BUGS.md` entry ending *"any new X must remember to Y"* is not finished.
It is a bug scheduled for later.
