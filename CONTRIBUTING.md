# How we work on Prism

Read this once, properly. It is short, and following it is not optional.

---

## The one thing this document is for

> **A fix should be able to land on `main` the day it is written.**

That is the measure. Not tidiness, not file counts, not architecture for its
own sake. Everything below exists to protect that one property.

Here is what it was like before, and it is worth knowing because the rules
only make sense against it. Over ninety days **every one of us edited the
same four files**: `main_window.py`, `workers.py`, `sidebar.py`,
`simple_panels.py`. Every feature had to be wired through them. So every
branch collided there, merging became something you put off, branches sat
unmerged for weeks — and the fixes on them never reached `main`.

Which everyone experienced as *"the same bugs keep coming back."* They had
not come back. They had never landed.

The clearest case: one process-killing crash was **fixed six times by three
people over four weeks.** Five of those fixes were patches at individual call
sites, and each one found a site the previous had missed. The sixth was
structural — and it sat unmerged on a branch while the other five were being
written.

The restructure removes the collisions. These rules stop them coming back.

---

## Where everything is

```
addons/<key>/          ONE ADD-ON. Yours. Nobody else edits it.
    addon.py               the manifest — what this add-on IS, as data
    contract.py            what it will do for another add-on
    panel.py  dialog.py    its screens

addons/registry.py     every add-on, one static import each.
                       THE ONLY SHARED FILE AN ADD-ON TOUCHES.

widgets/  dialogs/     the shell and the shared kit. Not yours alone.
core_bridge.py         the ONLY door to the engine
prism_terminal/        the engine (separate repo, separate migration)

main.py  app_meta.py  updater.py  apply_update.py  update_manifest.py
paths.py  licensing/  packaging/
                       THE BUILD CONTRACT SURFACE. These never move.
```

Where a specific file went in the migration: **`docs/ADDONS_MOVE_MAP.md`**.

---

## The rules

Each one is enforced by a test. If you break it, the suite tells you at your
desk instead of a customer telling you in three weeks. **Do not delete a
guard test to make your change pass** — if a rule genuinely needs to change,
change it deliberately and delete its test in the same commit, so the
decision is visible in review.

### 1. No add-on imports another add-on

Ever. This is the one the whole product rests on: it is what lets four people
work in four folders.

If you need work another add-on does, **ask by intent**:

```python
owner, handler = registry.offering(names.MEASURE_DRAWING)
if owner is None:
    return                       # nothing offers it — draw no button
registry.resolve(handler)(self, self.cfg, paths)
```

Full recipe: **`docs/architecture/10-adding-an-add-on.md`** §5.

### 2. Only `core_bridge.py` touches the engine

Never `from core import …` anywhere else. Use `CB.get_gerber()`,
`CB.boq_available()`. The bridge is what puts the engine on `sys.path` in the
first place, so a direct import also depends on something else having
imported the bridge — it works until the import order changes.

### 3. Every background thread subclasses `workers._Worker`

Never `QThread` directly. A `QThread` collected while running aborts the
process — no traceback, no log line, nothing catchable. **Connecting a signal
does not keep the object alive**, so this breaks on a timing change rather
than on a code path.

This is the bug that was fixed six times.

### 4. Data modules import no UI; widgets do not need a dialog to load

A panel opening a modal on a click is fine — import it *inside the method*.
What is banned is a widget or a data module that cannot be **imported**
without a dialog. That is a load-order dependency, and it is what stopped
Email automation being extractable for months.

### 5. The manifest layer is stdlib-only

`addons/manifest.py`, `names.py`, `registry.py` and every `addon.py`: no Qt,
no engine, no theme. The build imports them in a bare interpreter. Name
things with dotted strings and let the registry resolve them.

### 6. `registry.py`'s imports are static — never `importlib`

A dynamic registry is shorter, prettier, and **invisible to PyInstaller**.
Development would be perfect and the shipped build would open with an empty
shelf, in a windowed app with no console. There is no test for this one; it
is on you and on review.

### 7. Names the licence server shares are frozen

`plans.FEATURES` keys and `AGENT_REGISTRY` display names. **Moving files is
free. Renaming these is not** — the server is authoritative, and a rename
breaks entitlements or silently unmatches a published payload row.

### 8. The build contract surface never moves

The files listed in the map above. Things depend on those *paths* that are
not Python imports — a PyInstaller spec, a Nuitka command line, a few lines
of YAML — so moving one fails at release time, not at desk time.

Why each rule exists, and which test enforces it:
**`docs/architecture/09-boundaries.md`**.

---

## Landing your work

This half matters as much as the code. The mess was never only a layout
problem.

**Branch small, land fast.** If your branch touches only `addons/<yours>/`
it has nothing to collide with. Use that. A branch that lives a week is a
branch that will hurt to merge.

**Rebase, never merge, when `main` has moved.**

```bash
git config merge.renameLimit 999999
git fetch origin && git rebase origin/main
```

**Push the submodule before the parent.** If you bumped `prism_terminal`,
push the engine first. A superproject pinned to an unpushed engine commit
fails CI checkout for everybody with `not our ref <sha>` — and it leaves a
hole in history that a `git bisect` walks into months later.

**Never force-push a shared branch.** Never `git reset --hard` something you
have pushed.

**Run the suite before you push.**

```bash
python -m pytest
QT_QPA_PLATFORM=offscreen PRISM_SELFTEST=1 python main.py
```

The selftest resolves every add-on's panels and dialogs. It is what proves
your modules will actually be in the frozen build rather than merely
importing on your machine.

---

## When you fix a bug

> **A fix is not finished when it works. It is finished when it cannot come
> back.**

Either the mistake becomes structurally impossible, or it gets a test.

An entry in `BUGS.md` ending *"any new X must remember to Y"* is not a fixed
bug. It is a bug with a delay on it, and we have the receipts: that exact
sentence is why one crash was fixed six times.

And **an entry leaves `BUGS.md` when the fix is on `main`** — not when it is
written, not when it is on your branch. Two entries in that file sat titled
"FIXED, uncommitted" while the fix existed and nobody could use it.

---

## Things that will bite you

Learned the hard way, each one during the migration:

- **Do not call `processEvents()`, `exec()` or `QEventLoop` in a test.** The
  suite leaves callbacks queued against destroyed widgets; pumping the loop
  runs them against freed memory and kills the run *hundreds of tests later*.
  See `BUGS.md` #11.
- **Do not assert wiring by reading source text.** A test that greps
  `main_window.py` for a line passes when the line is connected to nothing,
  and fails on a refactor that changes no behaviour. Build the window and
  assert the signal arrives.
- **Do not run a formatter across files somebody is rebasing over.** It
  destroys git's rename detection and turns a mechanical rebase into a manual
  merge.
- **Do not translate a run prefix.** They match f-strings the dialogs write;
  a translated one matches nothing and History silently empties.
- **Regenerate `lang/_catalogue.json` when you add UI copy**
  (`python devtools/extract_strings.py`) — and check what it says it
  *removed*, not just what it added.

---

## If a guard test fails

Read the message. They are written to tell you what breaks and why, not just
that something is unequal.

Then ask which of these it is:

1. **You broke a rule** → fix the code.
2. **The rule should change** → change it deliberately, update its test in
   the same commit, and say why in the commit message. Review will see it.
3. **The test is wrong** → say so out loud. Two tests in this repository were
   passing for the wrong reason and one had become tautological; they are not
   sacred. But prove it, do not assume it.

What is not on the list: deleting the test, or adding your file to a skip
list, so the suite goes quiet.
