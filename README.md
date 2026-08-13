# Prism

A native desktop app (PySide6/Qt — no browser, no local server) that takes a
task in plain language, works out which AI tools it needs, and drives them in
**your own Chrome, signed in as you**. On top of that sits a shelf of
purpose-built add-ons for small manufacturers: read the inbox and keep an
inquiry register, take quantities off a CAD drawing, send email from your own
account.

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

- **Rail** (left) — brand, then the primary destinations (Home, How to use
  Prism, AI tools, History, Settings), the wake-word switch, and three grouped
  shelves:
  - **ADD-ONS** — Inquiry Automation, BOQ, Email, and BOM & Stock (visibly
    *coming soon*, disabled on purpose: a shelf that looks like a product line
    is worth more in a demo than an empty gap). Anything not in your licence
    shows a padlock and opens the pitch rather than failing.
  - **WORKSPACE** — Status, Login tabs.
  - **CONFIGURE** — Licence, Agents, Language, Your role, Profile, API key,
    Chrome.

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

### Inquiry Automation (`inbox`)

The one used every day, and the reason the app gets opened at all. Built with a
spring manufacturer at GIDC, Vadodara.

Four tabs, in the order the work happens: **What arrived → Inquiries → What
they said back → Waiting on a reply.**

- **Reads the mailbox, never writes to it.** `readonly=True` select and
  `BODY.PEEK[]`, so nothing is marked read, moved or deleted and the owner
  keeps using Outlook on the same account.
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
- **Wins back a no**: drafts the reply through the AI tools in your own Chrome,
  using bargaining limits you supply in a file. With no such file it is
  instructed to offer nothing on price at all.

It stops twice on purpose — before a price goes to a customer, and before a
purchase order is accepted.

### BOQ, Email, Reel

- **BOQ** — quantities off a CAD drawing (DXF via `ezdxf`) or from a written
  spec. Counts and measures; **you** price it. The Rate and Amount columns are
  deliberately left blank.
- **Email** — recipients from an attached CSV and/or addresses in the goal
  text, a **Search for their public email** fallback, a draft generated through
  a normal pipeline stage (editable), then confirm-and-send from *your own*
  account. First use opens the one-time SMTP setup (Gmail needs an app
  password).
- **Reel / Studio** — short videos, drawn with Pillow and encoded with FFmpeg.
  **FFmpeg ships inside the build** (`imageio-ffmpeg`); if it is ever missing,
  Prism downloads the same wheel and verifies it against the SHA-256 PyPI
  publishes for that exact file before unpacking it.

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
- **Inquiry Automation's send path and the PO → BOQ hand-off** are written and
  unit-tested but have never run against a real mailbox. Reading is the
  well-covered half.
- `plans.py` feature names and blurbs are not in the translation catalogue.

## Tests

```bash
python3 -m pytest tests/ -q --deselect \
  "tests/test_gates.py::TaskQueue::test_each_task_is_planned_in_turn"

python3 -m devtools.scenarios        # 148 end-to-end scenario checks
python3 devtools/inbox_demo.py       # the inbox pipeline on sample mail
```

588 tests, plus the 148 scenarios. Nothing in either suite touches the network:
IMAP and Groq are both faked, because a test that needs a mail server is a test
nobody runs.

**That one deselect is not decoration.** `test_each_task_is_planned_in_turn`
builds a real `MainWindow`, which reaches for the licence server, and it hangs
rather than failing — so a plain `pytest tests/` appears to freeze. It is
pre-existing and unrelated to any recent work; it hangs on a clean tree at
older commits too. Left in place rather than quietly deleted, because a hanging
test is a real problem and deleting it would only hide it.

## Files

```
main.py                 entry point; fonts, stylesheet, licence gate, self-test
main_window.py          the only file that makes decisions; owns all workers & columns
core_bridge.py          puts prism_terminal/core on sys.path, re-exports it
workers.py              QThread wrappers (routing, automation, voice, find, inbox, send, draft, ffmpeg)
plans.py                what each plan includes — the single source for the paywall
theme.py                Industry design tokens, and the per-role accent hue
i18n.py                 interface translation; patches Qt before any widget exists
identity.py roles.py    who is signed in, and what colour their copy is
workspace.py            per-member folders on a shared drive
friendly.py             any error -> title, plain English, numbered next steps
diagnostics.py          crash logs to ~/.prism/logs
paths.py                resource resolution, frozen and from source
app_meta.py             name, version, bundle id, support details
favorites.py            starred file/folder persistence
wakeword.py             best-effort "Prism" wake-word listener
awake.py cloud.py       keep-awake during long runs; cloud file attach
style.qss               the Industry theme — everything QSS can express
assets/fonts/           Barlow + Barlow Condensed (OFL), vendored
lang/                   language packs

licensing/
  client.py             HTTP to the licence server; timeouts sized for a cold host
  token.py store.py     verify offline, cache locally
  device.py             machine fingerprint (seat counting)
  keys.py               Ed25519 public keys; DEVELOPMENT ones trusted from source only
  status.py meter.py    state machine; Groq token metering
widgets/
  icons.py              24x24 stroked line icons, tinted & cached
  blueprint.py          the hairline frame + registration marks QSS can't draw
  controls.py           the square switch, tool chip, step mark, chips
  sidebar.py            the left rail, its shelves and their padlocks
  input_panel.py        the task card
  agents_panel.py       the plan (owns the stage -> plain-English copy map)
  files_panel.py        "Files you mentioned"
  prompt_panel.py       "Behind the scenes"
  output_panel.py       live per-step results
  ask_panel.py          the "what do you want?" box, shared by every add-on screen
  markdown.py           markdown -> Qt rich text
dialogs/
  setup_dialog.py       Setup, with per-section deep links from the rail
  license_dialog.py     activation, expiry, licence problems
  paywall.py            what a locked add-on is, and what it costs
  inquiry_setup_dialog.py  mailbox, files, terms, who's who — asked once
  inquiry_dialog.py     the four-tab Inquiry Automation screen
  boq_dialog.py reel_dialog.py email_dialog.py
  history_dialog.py     past runs, re-rendered out of their stored JSON
  completion_dialog.py  what each step produced, once a run ends
  problem_dialog.py     friendly.py's output, with a diagnostics-file offer
  guide_dialog.py       "How to use Prism", for someone who has never used AI
  drive_dialog.py       pick a file out of Google Drive like one off the disk
  ai_directory_dialog.py  the tool catalogue
devtools/               mint.py (licence keys), scenarios.py, inbox_demo.py — never shipped
packaging/              prism.spec, build.py, smoke_test.py
tests/                  588 tests; nothing here reaches the network
```
