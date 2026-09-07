# Adding an add-on

End to end, using Gerber as the worked example, because Gerber is real and
in the tree and you can read every file this page mentions.

Before this restructure, adding an add-on meant editing seven hand-maintained
tables in four shared files. Three of those tables were lists of the same
add-ons and they had **already diverged** — different memberships, different
icons, and one add-on described on the Home screen as "Coming soon" for
months after it shipped.

Now it is one folder and one line.

---

## The shape

```
addons/gerber/
    __init__.py     a docstring; a regular package, not a namespace package
    addon.py        MANIFEST = Addon(...)      ← STDLIB ONLY
    contract.py     what this add-on will do for another one
    panel.py        the front-door screen
    dialog.py       the working window
```

Plus **one line** in `addons/registry.py`. That is the only shared file you
touch, it is append-only, and its merge conflicts are one line.

Your tests go in `tests/`, not in `addons/<key>/tests/`. `tests/conftest.py`
has autouse fixtures — a fingerprint of the developer's real `~/.prism` (a
past incident destroyed 52 real runs) and a straggler-thread drain — that
apply to that subtree and would not reach a test living inside your add-on.

---

## 1. Write the manifest

`addons/gerber/addon.py`:

```python
from addons.manifest import ACCENT, RAIL, HOME, Addon, Offer

MANIFEST = Addon(
    key="gerber",
    label="Gerber",
    feature="boq",                 # a REFERENCE into plans.FEATURES
    tip="PCB size, track width & spacing, drill size and count — …",
    blurb="Measured off the Gerber files",
    icon="file",
    tone=ACCENT,                   # a TOKEN, never a colour
    order=30,
    shelves=(RAIL, HOME),
    screen="gerber",
    panel="addons.gerber.panel:GerberPanel",
    dialog="addons.gerber.dialog:GerberDialog",
    probe="core_bridge:gerber_available",
    kind="gerber",
    run_prefixes=("Gerber — ", "/gerber "),
    engine=("gerber",),
)
```

**Stdlib only in this file.** `packaging/prism.spec` imports the registry in
a bare interpreter to compute `hiddenimports`; a Qt import here would need a
display on the build box, and an engine import would break the build the day
the submodule moves. Everything else is named by dotted string and resolved
lazily. `tests/test_addon_contract.py` checks this two ways — an AST walk and
a real subprocess.

### Four fields that are easy to get wrong

**`feature` is a reference, not a name.** It must exist in `plans.FEATURES`,
and it is not always the same word as `key`. Gerber rides `"boq"` because the
licence server has no `gerber` key and gating on one nobody can be granted
would deny everyone — including the single account testing it. Changing it
later is a one-word diff, which is what `plans.py`'s job-not-screen naming
was built for.

**`tone` is a token** (`"accent"`, `"ok"`, `"warn"`, `"muted"`), resolved by
`theme.tone()` when the widget is built. Putting `theme.ACCENT` in a table
freezes it at import time, before `theme.apply_role()` runs — and because
`apply_role` rebinds `ACCENT` but not `OK` or `WARN`, the staleness affects
only some rows and is correspondingly hard to see.

**`run_prefixes` must never be translated.** They match f-strings your dialog
writes into run titles. A translated prefix matches nothing and History
silently empties in Hindi — no error, an empty list. Every display prefix
ends in a space, which is what makes
`devtools/extract_strings.py::_is_copy()` reject it as copy.

**`engine` is a declaration.** It is what tells the build to bundle those
modules, and it stops an add-on quietly growing a dependency `prism.spec`
has never heard of.

---

## 2. Register it

`addons/registry.py`, one line, alphabetical:

```python
from addons.gerber.addon import MANIFEST as _gerber
```

…and add it to the `REGISTRY` tuple.

**Static, never `importlib`.** A dynamic registry is shorter and invisible to
PyInstaller's analyser: dev perfect, frozen build ships an empty shelf,
windowed, no console. See `09-boundaries.md` §2.

---

## 3. Build the front door and the dialog

Subclass `AddonFrontDoor` from `shell/widgets/panel_base.py` for the panel. It is
already a declarative manifest in all but name — `ICON`, `HUE`, `HEADLINE`,
`DETAIL`, `ACTION`, `STEPS`, `PLACEHOLDERS`, `KIND` as class attributes, plus
`opened`/`open_run`/`navigate` signals. Read `addons/gerber/panel.py`; it is
64 lines and most of them are copy.

For the dialog, subclass `PrismDialog` from `shell/dialogs/base.py`.

**Any background work subclasses `shell.workers._Worker`.** Never `QThread`
directly — see `09-boundaries.md` §3 for what that costs.

**Reach the engine through `core_bridge` only.** `CB.get_gerber()`,
`CB.gerber_available()`. Never `from core import gerber`.

---

## 4. Add the licence gate

You do not write one. The shell reads `feature` off your manifest and routes
through the same `_authorized_then()` gate every other add-on uses.

What you **must** do is check `tests/test_addon_gates.py` covers your key.
Its last test fails if you add an add-on to the rail without adding it there,
because a gate test nobody remembers to write is the same as no gate test.

The gate is a separate line of code from the thing it guards. Lose it in a
refactor and the suite stays green, the app keeps working, and the add-on is
free — for everybody, including the customers who did not buy it. The only
signal is revenue.

---

## 5. If another add-on needs your work

**Never import it, and never let it import you.** Declare an intent.

In `addons/names.py`:

```python
MEASURE_PCB = "measure.pcb"
```

In your manifest:

```python
offers=(Offer(names.MEASURE_PCB,
              "addons.gerber.contract:open_with_files",
              "Measure this board"),),
```

In `addons/gerber/contract.py`, do the work — **and do your own shaping**:

```python
def open_with_files(parent, cfg, paths):
    files = CB.get_files()
    attachments = [...]        # what an attachment IS, is your business
    from addons.gerber.dialog import GerberDialog
    GerberDialog(cfg, attachments, parent).exec()
```

The consumer side is three lines and knows nothing about you:

```python
owner, handler = registry.offering(names.MEASURE_PCB)
if owner is None:
    return                     # nothing offers it — draw no button
registry.resolve(handler)(self, self.cfg, paths)
```

Four rules keep this honest:

1. **The payload is plain data.** Paths and strings — never a Qt object, never
   an engine object. Otherwise the caller has to import both to talk to you.
2. **The intent name lives in `names.py`**, and is named after the JOB, not
   after you. `MEASURE_DRAWING` survives BOQ being renamed or replaced;
   `OPEN_BOQ_DIALOG` would not.
3. **The offering side shapes the data.** Inquiry hands paths; BOQ decides
   what an attachment is. That one rule removed four of the five things
   Inquiry used to know about BOQ.
4. **The consumer degrades to a hidden button, never an error** — strictly
   better than the old behaviour, where the button was drawn and then
   paywalled after the click.

---

## 6. Before you push

```bash
python -m pytest
QT_QPA_PLATFORM=offscreen PRISM_SELFTEST=1 python main.py    # census must pass
```

The selftest resolves every panel, dialog and probe every manifest names. It
is what proves your modules actually reached the frozen archive rather than
merely importing on your machine — which is the difference between a red
`smoke_test.py` in CI and a customer opening an empty shelf.

---

## What you do NOT have to touch

`shell/widgets/sidebar.py`, `shell/widgets/home_panel.py`, `shell/main_window.py`,
`shell/widgets/panel_base.py`'s tables, `packaging/prism.spec`.

The rail, the Home shelf, History's run attribution, the routed-agent gate
and the build's module list all read the registry. That is the whole point:
**four people in four folders, and the only shared file is one append-only
line each.**
