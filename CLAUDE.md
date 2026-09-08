# Working on Prism with Claude

The owner's standing instruction (8 Sep 2026): every pull, merge, push and
every change to the codebase's structure follows the architecture rules,
so that modules stay independent and are easy to add, edit, update and
delete. Those rules are the repository's, not this file's — read them:

- `CONTRIBUTING.md` — the eight rules and how work lands.
- `docs/architecture/10-adding-an-add-on.md` — the shape of an add-on.
- `docs/architecture/09-boundaries.md` — why each rule exists and which
  test enforces it.

The short form, so nothing is done from memory:

1. An add-on is one folder, `addons/<key>/`, with a stdlib-only `addon.py`
   manifest, `contract.py`, `panel.py`, `dialog.py` and its own workers.
   The only shared file it touches is `addons/registry.py`, one line.
2. No add-on imports another add-on. Ask by intent (`addons/names.py`).
3. Only `core_bridge.py` imports the engine (`prism_terminal/`).
4. Every background thread subclasses `workers._Worker`.
5. Manifest, names and registry stay stdlib-only; registry imports are
   static, never `importlib`.
6. Licence feature keys and agent display names are frozen.
7. The build-contract files at the repo root never move.
8. A guard test is never deleted or skipped to make a change pass; if a
   rule must change, change it and its test in the same commit and say why.

Landing work:

- Pull, merge or push only when the owner asks in that message.
- `git config merge.renameLimit 999999`, `git fetch`, then **rebase** onto
  `origin/main`. Never merge, never force-push a shared branch.
- Push `prism_terminal` before `prism_gui` and bump the gitlink.
- Before every push: `python3 -m pytest` and
  `QT_QPA_PLATFORM=offscreen PRISM_SELFTEST=1 python3 main.py`.
- After adding UI copy: `python3 devtools/extract_strings.py`, and read
  what it removed, not only what it added.
- Update the golden lists in the guard tests (`GOLDEN_RAIL`, `GOLDEN_HOME`,
  `PANELS`, `ADDON_FEATURES`) in the same commit as the add-on.

Testing traps: never call `processEvents()`, `exec()` or a `QEventLoop`
in a test; never write to the real `~/.prism` (conftest fails the run).
