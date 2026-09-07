# Where everything went

Every file the add-ons restructure moved, old path → new path. Generated
from `git diff -M`, not from memory.

**If you have a branch open, read "Rebasing your branch" at the bottom
first.** It is four commands and it is the difference between a mechanical
rebase and a wall of modify/delete conflicts.

---

## Moved

| Was | Is now | Similarity |
| --- | --- | --- |
| `dialogs/gerber_dialog.py` | `addons/gerber/dialog.py` | 100% |
| `widgets/gerber_panel.py` | `addons/gerber/panel.py` | 100% |
| `dialogs/boq_dialog.py` | `addons/boq/dialog.py` | 100% |
| `widgets/boq_panel.py` | `addons/boq/panel.py` + `addons/bom/panel.py` | split |
| `dialogs/email_dialog.py` | `addons/email/dialog.py` | 99% |
| `widgets/email_panel.py` | `addons/email/panel.py` | 99% |
| `sent_log.py` | `addons/email/sent_log.py` | 100% |
| `dialogs/reel_dialog.py` | `addons/reel/dialog.py` | 100% |
| `dialogs/motion_dialog.py` | `addons/motion/dialog.py` | 99% |
| `dialogs/inquiry_dialog.py` | `addons/inquiry/dialog.py` | 78% (see below) |
| `dialogs/inquiry_setup_dialog.py` | `addons/inquiry/setup.py` | 97% |
| `widgets/inquiry_panel.py` | `addons/inquiry/panel.py` | 97% |
| `widgets/register_table.py` | `addons/inquiry/register_table.py` | 100% |

`inquiry_dialog.py` is 78% because ~900 lines came out of it first: the
quotation surface (`QuotationDialog`, `_CompareDialog`, `_POReviewDialog`)
now lives in **`addons/inquiry/quotation.py`**. It is re-exported from
`addons/inquiry/dialog.py`, so `UI.QuotationDialog` still resolves.

## The shell moved too

Everything that is Prism itself, rather than one of its features, is now
under `shell/`. **Whole directories moved, so this is one rule, not a list:**

| Was | Is now |
| --- | --- |
| `widgets/…` | `shell/widgets/…` |
| `dialogs/…` | `shell/dialogs/…` |
| `main_window.py` | `shell/main_window.py` |
| `workers.py` | `shell/workers.py` |

So `from widgets.controls import button` → `from shell.widgets.controls import
button`, and `import main_window` → `from shell import main_window`. Nothing
inside any of those files changed except its own imports.

The top level now states the architecture rather than burying it:

```
addons/          the features
shell/           the app itself
licensing/       entitlements
packaging/       how it ships
prism_terminal/  the engine (submodule)
```

## Split

`widgets/simple_panels.py` (1,581 lines, six screens) is **gone**:

| Now in | What |
| --- | --- |
| `shell/widgets/panel_base.py` | `Page`, `AddonFrontDoor`, `bucket_for`, `_RunRow`, the copy tables and shared helpers |
| `shell/widgets/guide_panel.py` | `GuidePanel` |
| `shell/widgets/catalog_panel.py` | `CatalogPanel` |
| `shell/widgets/history_panel.py` | `HistoryPanel`, `_AbortedRow` |
| `addons/boq/panel.py` | `BoqPanel` |
| `addons/bom/panel.py` | `BomPanel` |
| `addons/gerber/panel.py` | `GerberPanel` |

Three names lost a leading underscore, because a private name imported from
four other modules is a public name nobody renamed:

    _Page  ->  Page          _bucket  ->  bucket_for
    _AddonFrontDoor  ->  AddonFrontDoor

**The `EmailPanel` re-export shim at the bottom of `simple_panels.py` is
gone.** If you imported `EmailPanel` from `simple_panels`, import it from
`addons.email.panel` instead.

## New

| File | What it is |
| --- | --- |
| `addons/manifest.py` | The `Addon` dataclass. What an add-on IS, as data |
| `addons/registry.py` | Every add-on, statically imported. **The one shared file an add-on touches** |
| `addons/names.py` | The intent vocabulary add-ons use to ask each other for work |
| `addons/<key>/addon.py` | One manifest per add-on |
| `addons/<key>/contract.py` | What that add-on will do for another one |
| `inquiry_config.py` | Email automation's settings, as plain functions over a dict — no Qt |
| `docs/architecture/09-boundaries.md` | The rules, each paired with the test that enforces it |
| `docs/architecture/10-adding-an-add-on.md` | The recipe, end to end |

## Deleted

| File | Why |
| --- | --- |
| `widgets/blueprint.py` | 72 lines, imported by nothing at all |
| `widgets/simple_panels.py` | Split, see above |

## Did NOT move, deliberately

| File | Why |
| --- | --- |
| `main.py`, `app_meta.py`, `updater.py`, `apply_update.py`, `update_manifest.py`, `paths.py`, `licensing/`, `packaging/` | The **build contract surface**. The things that depend on these are not Python imports — a PyInstaller spec, a Nuitka command line, a few lines of YAML. Move one and nothing fails until a release. `tests/test_repo_layout.py` pins them |
| `inquiry_config.py` | Home reads it through `dashboard_data`. Putting it inside the Inquiry add-on would make Home depend on that add-on, which is the coupling the whole restructure removes |
| `shell/workers.py` | It moved into `shell/`, but was **not split**: 20 worker classes are patched by name in four test files, and separating them is its own piece of work |
| `integrations/gdrive.py`, `shell/dialogs/drive_dialog.py` | Drive is the only add-on with a `datas` coupling to `prism.spec`, and its `google_client.json` is gitignored — so it exists on some build machines and not others, and a mismatch is invisible on any machine lacking it |
| `prism_terminal/` | The engine. Untouched by this migration, entirely |

---

## Rebasing your branch

```bash
git config merge.renameLimit 999999   # the default cap misses renames on a diff this size
git fetch origin
git rebase origin/main                # REBASE, not merge
```

**Rebase, not merge.** A rebase replays your commits onto the moved tree one
at a time, so git's rename detection maps each small change onto the new
path. A merge reconciles the whole relocation against your whole branch at
once and gives you a wall of modify/delete conflicts.

When a rebase stops on a file that moved:

```bash
git show REBASE_HEAD -- dialogs/gerber_dialog.py > /tmp/mine.patch
git rm dialogs/gerber_dialog.py
# apply the same hunk by hand to addons/gerber/dialog.py
git add addons/gerber/dialog.py && git rebase --continue
```

`git log --follow <newpath>` works, and `git blame` survives — the moves
were made with `git mv` and every one recorded at 78–100% similarity, so
history is intact.

**Do not run a formatter over anything before rebasing.** A reformat near a
move destroys rename detection and turns a mechanical rebase into a manual
merge.

## If you had >200 uncommitted lines in a moved file

`git stash pop` after a rename is a modify/delete conflict with no rename
information at all. Commit to a WIP branch first, then rebase that.
