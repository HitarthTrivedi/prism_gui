# Prism

A native desktop app (PySide6/Qt — no browser, no local server) that takes a
task in plain language, works out which AI tools it needs, and drives them in
**your own Chrome, signed in as you**. On top of that sits a shelf of
purpose-built add-ons for small manufacturers: read the inbox and keep an
inquiry register, take quantities off a CAD drawing, send email from your own
account.

> **Working on Prism? Read [CONTRIBUTING.md](CONTRIBUTING.md) first.** It is
> short, and following it is not optional — it is what keeps four people able
> to ship at the same time.
>
> | | |
> |---|---|
> | [CONTRIBUTING.md](CONTRIBUTING.md) | How we work: the rules, and how to land your work |
> | [docs/architecture/10-adding-an-add-on.md](docs/architecture/10-adding-an-add-on.md) | Building an add-on, end to end |
> | [docs/architecture/09-boundaries.md](docs/architecture/09-boundaries.md) | Every rule, and the test that enforces it |
> | [docs/ADDONS_MOVE_MAP.md](docs/ADDONS_MOVE_MAP.md) | Where a file went, and how to rebase across the move |
> | [OWNERS.md](OWNERS.md) | Who is looking after what, this sprint |

It has **no engine of its own**: `core_bridge.py` imports `prism_terminal`'s
`core/` package directly, so routing, browser automation, voice and
file-finding are the exact same code the CLI uses. Both apps read and write the
same `~/.prism/config.json` — set your API key or agents in either one and the
other sees it immediately.

`prism_terminal` is a **git submodule** (see `.gitmodules`), pinned to
[github.com/HitarthTrivedi/prism_terminal](https://github.com/HitarthTrivedi/prism_terminal).
Clone with `--recurse-submodules` and everything needed is there.

## Install it (no Python needed)

**→ [GETTING_STARTED.md](GETTING_STARTED.md)** — the full walkthrough: which
file to grab, the first-launch unsigned-app step, and first-run setup. This is
the doc to hand a non-technical user or client.

Short version: grab the build for your OS from
[Releases](https://github.com/HitarthTrivedi/prism_gui/releases) — portable, no
installer, nothing written outside the folder and `~/.prism`. You will also
need **Google Chrome**, since Prism drives it directly.

You need a **licence key** to get past the first screen. See
[LICENSING.md](LICENSING.md); [SHIPPING.md](SHIPPING.md) covers issuing them
and [BUILD.md](BUILD.md) covers building the apps yourself.

## Run it from source

```bash
git clone --recurse-submodules https://github.com/HitarthTrivedi/prism_gui.git
cd prism_gui
pip install -r requirements.txt
python3 main.py
```

Already cloned without `--recurse-submodules`? Run `git submodule update
--init` once to fetch it.

**The submodule always wins.** If you have a sibling `../prism_terminal`
checkout as well, it is *ignored* — `paths.resource()` resolves to
`./prism_terminal` and that is checked first. This README used to claim the
opposite, and the cost of believing it is an afternoon spent editing a copy
that is never loaded. `core_bridge.py` prints a note naming both paths when it
finds two, so you are told rather than left guessing.

First launch opens the licence screen, then Setup (API key, profile, one agent
per category, Chrome version) if `~/.prism/config.json` isn't already
configured from the CLI.

### Working on it without a licence server

```bash
PRISM_LICENSE_OFFLINE_DEV=1 PRISM_LICENSE_SERVER=http://127.0.0.1:9 python3 main.py
```

Both are honoured **only from source** — a frozen build ignores them, or they
would be a total bypass. `PRISM_LICENSE_OFFLINE_DEV` alone is not enough when a
real server is reachable: it fires on a connection *failure*, and a server that
answers "no" has not failed. Pointing at a dead port is what makes it apply.
Mint a local licence with `python3 devtools/mint.py install --features ...`.

## Layout

The window follows **direction 1b ("Workbench")** of the *Prism Directions*
design canvas — everything in view, nothing to drag — rendered in the
**Industry** design system: a light `#f2f2f3` canvas, slate-blue `#5980a6`
accent, Barlow / Barlow Condensed, square corners throughout, and hairline
borders with blueprint registration marks on the primary containers.

The accent hue shifts with the signed-in member's **role**, so a glance says
whose copy this is. Only the hue moves — every swatch keeps its lightness, so
contrast is identical in every role and nothing needs re-checking for
legibility.

It auto-sizes to whatever screen it is on (92%/88% of available width/height,
capped at 1360×880, floor 1060×640).

Three fixed columns. The old `QDockWidget`s are gone: nothing can be dragged
out, closed, or lost behind a tab, so there is no View menu either.

- **Rail** (left) — brand, then two named groups, Settings, and the pinned
  foot (wake word, profile). **The budget is twelve controls and two
  headings**, fitting at 768px with no scroll; anything new has to displace
  something.
  - **WORK** — New task, Home, History, Artifacts: the destinations that
    bracket a run.
  - **ADD-ONS** — Email automation, BOQ, Gerber, Email, BOM & Stock. This
    shelf is **generated from `addons/registry.py`**, not hand-listed, so it
    cannot drift from the Home screen the way it used to. Anything not in
    your licence shows a padlock and opens the pitch rather than failing.
  - **Settings** — one row under a hairline. It owns everything that
    configures Prism; the old WORKSPACE and CONFIGURE shelves are sections of
    that screen now, so every field is editable where you land rather than
    behind a second dialog.

  Reel / Studio and Motion Graphics are reachable from Home and by command
  but have no rail row — Reel's slot went to Artifacts, and Motion cannot run
  yet. That is a decision, recorded in their manifests and pinned by
  `tests/test_addon_contract.py`.

  Below that, a **Favorites** shelf — star a file or folder once, click it
  later instead of re-describing it.
- **Work** (centre) — a two-page stack, because composing and running are the
  only two things you can be doing and they never want to share the screen:
  - **Composing** — the **task card** (a blueprint frame: kicker, live state
    chip, the task as editable 16px text, and Speak / Add file / Add folder /
    **Make a plan**), then **Your plan**: one row per stage the router marked
    needed, each with a square include-marker, a line icon, a plain-English
    name ("Look things up", "Write it up", "Build the slides"), one line of what
    it means, and the tool as a clickable **chip**. Click a row to drop that
    step; click its chip to run it somewhere else. The router's suggestion is
    starred in the chip's menu; a tool you explicitly NAMED ("using
    NotebookLM…") is pre-selected and tagged *You picked this*. **Start the
    work** runs whatever is still switched on.
  - **Running** — live per-step cards, each with **Copy output** and **Open in
    tool**, so if a later step fails you can grab the last good text and carry
    on by hand. **Back to the plan** returns.
- **Context** (right) — **Files you mentioned**: every file or folder Prism
  thinks you meant (from speech), with **Keep** / **Change** per mention — the
  GUI equivalent of the CLI's confirm-before-attach flow. Typed queries don't
  auto-scan prose for file mentions; use **Add file/folder**, since a GUI has a
  real file picker. Below it, **Behind the scenes** — collapsed by default —
  opens the full chain: what you said → the expanded task brief → each stage's
  engineered prompt.

## The add-ons

### Email automation (`inbox`)

The one used every day, and the reason the app gets opened at all. Built with
a spring manufacturer at GIDC, Vadodara; grown to office scale — several
mailboxes, one shared register — after a second firm described exactly that
(`docs/EMAIL_AUTOMATION.md`).

Five tabs, in the order the work happens: **What arrived → Inquiries → What
they said back → Waiting on a reply → The order came.**

- **Reads the mailboxes, never writes to them.** `readonly=True` select and
  `BODY.PEEK[]`, so nothing is marked read, moved or deleted and the owner
  keeps using Outlook on the same account. Any number of accounts, walked one
  at a time, each with its own read bookmark; a **Mailbox** column in the
  register says which address each inquiry came to.
- **Sorts on local rules first.** `List-Unsubscribe`, auto-replies, known
  senders and a few narrow keyword rules settle most mail without any AI call
  at all. Only genuinely unknown senders reach the model, in one batched call.
  A **Keep everything on this computer** switch removes even that.
- **Keeps an inquiry register** — an ordinary CSV that opens in Excel and stays
  theirs whatever happens to Prism. Written atomically; hand-added columns
  survive; a register open in Excel produces "close it in Excel", not a lost
  row. An existing register can be imported, numbering carrying on from theirs.
- **Prices from their own rate list or their own cost sheet**, showing every
  line of the working. Decimal arithmetic with `ROUND_HALF_UP`, Indian lakh
  grouping, financial-year numbering (`INQ/25-26/0087`). No AI ever touches a
  figure.
- **Reads the reply** — accepted, declined, haggling, or a question — and
  proposes the register change. It never applies itself.
- **Chases the quiet ones** every two days, three times, then stops. Each
  reminder is worded differently.
- **Puts the PO against the quotation actually sent** — read back from the
  CSV written at send time, refused on any mismatch — and lists every
  difference with rate gaps multiplied out by quantity. Accepting is a
  button; scanned POs get typed-in boxes and an honest sentence.
- **Wins back a no**: drafts the reply through the AI tools in your own Chrome,
  using bargaining limits you supply in a file. With no such file it is
  instructed to offer nothing on price at all.

It stops twice on purpose — before a price goes to a customer, and before a
purchase order is accepted.

### BOQ, BOM, Gerber, Email, Reel, Motion

Each lives in `addons/<key>/` and is declared by one manifest. The
authoritative list is `addons/registry.py`; this is the plain-English version.

- **BOQ** — quantities off a CAD drawing (DXF via `ezdxf`) or from a written
  spec. Counts and measures; **you** price it. The Rate and Amount columns are
  deliberately left blank.
- **BOM & Stock** — the parts list to fabricate an assembly, off the same
  drawing or spec. It is BOQ's dialog in a different mode, which is why its
  manifest declares `provided_by="boq"` rather than pretending to own a
  window it does not. **Gated on the `boq` key**, not `bom`: a `bom` feature
  exists in `plans.py` but the licence server has never been told about it,
  so buying `bom` alone gets you nothing and buying `boq` gets you this free.
- **Gerber** — PCB size, track width and spacing, drill sizes and counts,
  measured out of the Gerber files by Prism itself. **The design files are
  never attached to anything** — only the measured numbers reach the AI
  stage. Also rides the `boq` key, because there is no `gerber` key on the
  licence server yet and gating on one nobody can be granted would deny
  everyone, including the account testing it.
- **Email** — recipients from an attached CSV and/or addresses in the goal
  text, a **Search for their public email** fallback, a draft generated through
  a normal pipeline stage (editable), then confirm-and-send from *your own*
  account. First use opens the one-time SMTP setup (Gmail needs an app
  password).
- **Reel** — short videos, drawn with Pillow and encoded with FFmpeg.
  **FFmpeg ships inside the build** (`imageio-ffmpeg`); if it is ever missing,
  Prism downloads the same wheel and verifies it against the SHA-256 PyPI
  publishes for that exact file before unpacking it.
- **Studio** — the same encode, but the frames are a real web page filmed in a
  paused Chromium rather than drawn in Python, so no two clients get the same
  film. The design stage is a **conversation**: one turn for the look and a
  storyboard, then **one turn per scene**, each laid out at 1080×1920 and
  corrected before the next is asked for. Asking for the whole reel in one
  reply was what made the old output look like a slide deck — a scene got
  about 278 characters, which is a headline and a subhead. See
  `CHANGES.md` → Round 6.
- **Motion Graphics** — a scene-graph video with camera, charts and diagrams.
  **Not available in this release**: `core/motion/render.py` sets
  `_DISABLED_PENDING_ASSET_FIX`, so `is_available()` returns `False` and the
  tile is a caption rather than a button. Declared `status=SOON` in its
  manifest, which is what makes that a fact about the add-on instead of a
  hardcoded pair of keys in a render method.

Reel, Studio and Motion share the `reel` key — one media capability tier, not
three purchases. Reel and Motion have no rail row and are reached from Home or
by command, which is why their licence gate carries the whole weight: the
router can put Prism Reel into a plan without anybody clicking a shelf.

## Licensing

Every launch and every add-on goes through `licensing/`. The server signs a
compact claims blob; the app verifies it offline against an Ed25519 public key
baked into the bundle. **There is no offline fallback** — if the licence server
cannot be reached, the answer is no. See [LICENSING.md](LICENSING.md) for the
reasoning and the trade that comes with it.

An expired licence still opens the app read-only: History and everything
already produced stay reachable, because locking someone out of their own past
output is how a lapsed trial becomes a complaint instead of a sale.

## When something goes wrong

`friendly.py` turns every error a customer can see into three things: what
happened in five words, one or two sentences of plain English, and the numbered
things to try. **Never show someone a problem without showing them the next
action** — a message with no action is a phone call.

Crashes land in `~/.prism/logs` via `diagnostics.py`, because a windowed build
has no console to print to.

## Languages and roles

`i18n.py` patches Qt before the first widget exists, so nothing is built
untranslated. Prism's own interface language and the language the AI tools
answer in are set separately — a Gujarati-speaking owner may well want the
output in English. Language packs live in `lang/`.

`identity.py` and `roles.py` carry the signed-in member; `workspace.py` gives
each their own folders on a shared drive.

## Known limitations

- **Wake word ("Prism")** — `wakeword.py` is a best-effort polling loop
  (record ~2s, check for silence, transcribe if not silent, look for "prism"),
  **not** a real local wake-word engine. Expect a couple of seconds of lag and
  occasional missed or false triggers. Swap in Porcupine/OpenWakeWord if this
  needs to be production-grade.
- **NotebookLM automation** (`core/automation.py`'s `_run_notebooklm`) is
  best-effort and unverified against a live session — see its docstring.
- File-mention resolution on a **typed** query is intentionally not automatic
  (only spoken input runs the interpreter) — a GUI has real Attach buttons, and
  prose-scanning a typed sentence adds risk for no benefit.
- **Email automation's send path and the PO screen** are written and
  unit-tested but have never run against a real mailbox. Reading is the
  well-covered half.
- `plans.py` feature names and blurbs are not in the translation catalogue.

## Tests

```bash
python3 -m pytest tests/ -q

python3 -m devtools.scenarios        # 148 end-to-end scenario checks
python3 devtools/inbox_demo.py       # the inbox pipeline on sample mail
```

1,465 tests, plus the 148 scenarios. Nothing in either suite touches the network:
IMAP and Groq are both faked, because a test that needs a mail server is a test
nobody runs.

**Do NOT export `PRISM_LICENSE_OFFLINE_DEV=1` to run the suite.** This file
used to tell you to, on the grounds that the GUI suites would otherwise "wait
on the network". That is not what the variable does: `licensing._offline_dev()`
is read only inside `_unreachable_answer()`, i.e. *after* the HTTP call has
already raised `Unreachable`. It changes the ANSWER, never the round trip, so
it cannot make a hanging test finish.

What it does do is open a production bypass underneath the revocation test:
with the hatch open, a revoked licence's offline fallback is granted and
`test_h_a_revoked_licence_gets_no_lease_and_loses_its_cache` fails on
`True is not false`. That failure was read as known contamination for months.
`tests/conftest.py` now strips the variable per test, so the suite is
insulated either way — but do not put it back in the invocation.

**The deselect this file used to demand is gone, and so is the hang.**
`test_each_task_is_planned_in_turn` builds a real `MainWindow` and used to
hang rather than fail, so a plain `pytest tests/` appeared to freeze. The
cause was never that test: `InquiryDialog.__init__` ends with `enter()`,
which arms a zero-delay `_first_look()`, and `MainWindow` builds that panel
at startup — so the first test to drive the event loop with an unconfigured
mailbox blocked on a modal `QMessageBox.question` nothing headless could
answer. `_first_look()` now asks only on the screen the user actually has
open (see `_is_the_open_screen`), which fixed the same bug in the product:
Prism was opening that question over the dashboard on every launch.

Also gone: `test_a_quiet_quotation_appears_on_the_chase_list` dated its
quotation `today.replace(day=1)` against a `followup_days=3` fixture, so it
failed on the 1st, 2nd and 3rd of every month and passed the other 28 days.

## Files

Where a file went in the add-ons restructure: **`docs/ADDONS_MOVE_MAP.md`**.

```
main.py                 entry point; fonts, stylesheet, licence gate, self-test
main_window.py          the shell: navigation, the licence gate, the pipeline.
                        It no longer knows WHICH add-ons exist — it reads the
                        registry. See docs/architecture/01-system-overview.md
core_bridge.py          the ONLY door to prism_terminal/core. Nothing else
                        may import the engine (tests/test_engine_facade.py)
workers.py              background threads. Every one subclasses _Worker,
                        which is what stops a running thread being collected
                        and aborting the process (tests/test_worker_mandate.py)
plans.py                what each plan includes — the single source for the
                        paywall, and shared with the licence server
inquiry_config.py       Email automation's settings as plain functions over a
                        dict — no Qt, so Home can read them without importing
                        an add-on
theme.py                Industry design tokens, the per-role accent hue, and
                        tone() — which resolves an add-on's colour LATE
i18n.py                 interface translation; patches Qt before any widget exists
identity.py roles.py    who is signed in, and what colour their copy is
workspace.py            per-member folders on a shared drive
friendly.py             any error -> title, plain English, numbered next steps
diagnostics.py          crash logs to ~/.prism/logs
paths.py                resource resolution, frozen and from source
app_meta.py             name, version, bundle id, support details
updater.py              in-app updates. UPDATE_REPO is compiled into every
                        shipped binary and cannot be overridden at runtime
favorites.py            starred file/folder persistence
wakeword.py             best-effort "Prism" wake-word listener
awake.py cloud.py       keep-awake during long runs; cloud file attach
style.qss               the Industry theme — everything QSS can express
assets/fonts/           Barlow + Barlow Condensed (OFL), vendored
lang/                   language packs + _catalogue.json (the translatable set)

addons/                 ONE FOLDER PER ADD-ON. This is where feature work goes.
  manifest.py           the Addon dataclass — what an add-on IS, as data
  registry.py           every add-on, one STATIC import each. The only shared
                        file an add-on touches, and it is append-only
  names.py              the intent vocabulary add-ons use to ask each other
                        for work without importing each other
  inquiry/              Email automation: dialog, quotation, setup, panel,
                        register_table
  boq/  bom/  gerber/   measured off a drawing or a Gerber job
  email/                compose and send, plus sent_log
  reel/  motion/        video. Motion is status=SOON — it cannot run yet

  ...and inside every one of those add-on folders, the same four things:
      <key>/addon.py        the manifest — stdlib only
      <key>/contract.py     what this add-on does for another one
      <key>/panel.py        its front-door screen
      <key>/dialog.py       its working window

licensing/              never imports Qt; the paywall is injected
  client.py             HTTP to the licence server
  token.py store.py     verify offline, cache locally
  device.py             machine fingerprint — OS identifiers only, so moving
                        files cannot orphan a customer's activation
  keys.py               Ed25519 public keys; DEVELOPMENT ones from source only
  status.py meter.py    state machine; Groq token metering
widgets/                the shell and the shared kit — NOT feature code
  panel_base.py         Page, AddonFrontDoor, the run-row, the copy tables
  guide_panel.py catalog_panel.py history_panel.py
  sidebar.py            the left rail — its shelf is DERIVED from the registry
  home_panel.py         same shelf, same source
  icons.py controls.py  the icon set; the square switch, chips, step marks
  input_panel.py        the task card
  agents_panel.py       the plan (owns the stage -> plain-English copy map)
  files_panel.py output_panel.py prompt_panel.py ask_panel.py markdown.py
dialogs/                the shell's own windows only
  base.py               PrismDialog — every dialog's frame
  license_dialog.py paywall.py legal_dialog.py contact_dialog.py
  history_dialog.py completion_dialog.py followup_dialog.py problem_dialog.py
  guide_dialog.py preview_dialog.py ai_directory_dialog.py
  drive_dialog.py       Google Drive — deliberately NOT an add-on package yet:
                        it is the only one with a datas coupling to prism.spec
devtools/               mint.py (licence keys), extract_strings.py — never shipped
packaging/              prism.spec, build.py, smoke_test.py
tests/                  the suite, including the boundary guards that make
                        docs/architecture/09-boundaries.md executable
```
