# Owners

Who is looking after what, this sprint.

**This file is deliberately separate from the architecture.** Ownership
rotates; the boundaries do not. Reassigning a module should be a one-line
edit here and nothing else — if changing an owner ever requires touching
code or `docs/architecture/`, that is a bug in the structure, not in this
table.

No names appear anywhere else in the repository, on purpose.

---

## Add-ons

Each row is two globs and nothing shared. That is the property the
restructure was for: the owner of an add-on can work, test, review and ship
without waiting on anybody else's file.

| Add-on | Code | Tests | Owner |
| --- | --- | --- | --- |
| Email automation | `addons/inquiry/**` | `test_inquiry_ui.py`, `test_inquiry_screen.py`, `test_email_automation.py`, `test_register_table.py` | _unassigned_ |
| BOQ | `addons/boq/**` | **none of its own** — see below | _unassigned_ |
| BOM | `addons/bom/**` | **none of its own** — see below | _unassigned_ |
| Gerber | `addons/gerber/**` | `test_gerber.py`, `test_gerber_clean.py`, `test_gerber_dialog.py`, `test_gerber_form.py` | _unassigned_ |
| Email | `addons/email/**` | `test_email_panel.py`, `test_email_compose.py` | _unassigned_ |
| Reel / Studio | `addons/reel/**` | `test_reel_capture.py`, `test_reel_dialog.py`, `test_reel_edit.py` | _unassigned_ |
| Motion Graphics | `addons/motion/**` | **none of its own** — disabled at source, see below | _unassigned_ |

### Two gaps worth knowing before you assign anything

**BOQ and BOM have no test file.** Not a thin one — none. `addons/boq/dialog.py`
is 601 lines and is only ever exercised incidentally, by `test_addon_gates.py`
(does the paywall hold), `test_gates.py` (is it patched out), and
`test_cross_platform_browser.py` (one guidance string). BOQ is a paid feature
that measures a customer's drawing and produces the quantities they price
from, and Gerber — one prospective customer, not in daily use — has four test
files to its name. Whoever takes BOQ should expect writing its first test to
be the first job.

**Motion has none because it does not run.** `core/motion/render.py` sets
`_DISABLED_PENDING_ASSET_FIX = True` and `is_available()` returns `False`
unconditionally, so the add-on is declared `status=SOON` and its tile is a
caption. Its nine engine modules were also absent from every frozen build
until the packaging walk was made recursive — so the day that switch is
turned off, build it before believing it.

**BOM and BOQ cannot be owned independently yet.** BOM's dialog *is* BOQ's,
in `mode="bom"` — declared as `provided_by="boq"` in its manifest and
enforced by `tests/test_addon_contract.py`. Assign them to the same person
until BOM owns a dialog, or accept that a BOM change may need a BOQ review.

---

## The shell

Nobody owns these as a feature; they are shared surface, and a change to one
affects every add-on. **Review by someone other than the author.**

| Area | Code | Steward |
| --- | --- | --- |
| The add-on contract | `addons/manifest.py`, `addons/registry.py`, `addons/names.py` | _unassigned_ |
| The window and the rail | `main_window.py`, `widgets/sidebar.py`, `widgets/home_panel.py` | _unassigned_ |
| Shared panel furniture | `widgets/panel_base.py` | _unassigned_ |
| Workers | `workers.py` | _unassigned_ |
| The engine façade | `core_bridge.py` | _unassigned_ |
| Licensing | `licensing/**` | _unassigned_ |
| Build and release | `packaging/**`, `.github/workflows/**`, `devtools/**` | _unassigned_ |
| The engine | `prism_terminal/` (separate repo) | _unassigned_ |

---

## Rules that outlive any assignment

1. **The build contract surface never moves.** `main.py`, `app_meta.py`,
   `updater.py`, `apply_update.py`, `update_manifest.py`, `paths.py`,
   `core_bridge.py`, `licensing/`, `packaging/`. Things depend on those
   *paths* that are not Python imports, so moving one fails at release time
   rather than at desk time. `tests/test_repo_layout.py` says so.

2. **Update-manifest signing stays offline and human-only.** The signing key
   never enters a CI secret, a repo variable, or Render. A CI compromise must
   not become a supply-chain compromise.

3. **Nobody renames a `plans.FEATURES` key or an `AGENT_REGISTRY` display
   name without the licence server changing too.** The server is
   authoritative for what those words mean, and a rename breaks entitlements
   or a published payload row silently. Moving files is free; renaming these
   is not.

4. **A boundary change needs a boundary test.** See
   `docs/architecture/09-boundaries.md`. If you relax a rule, delete the test
   that enforced it in the same commit, so the change is visible in review
   rather than discovered later.

---

## Adding a person

Give them `docs/architecture/10-adding-an-add-on.md` and one add-on folder.
That document is written to be readable cold, with no prior context about
this codebase, and it uses a real add-on in the tree as its worked example —
so the first thing they do can be to open the file it describes and check
that it says what actually happened.
