# Prism GUI (v0)

A native desktop app (PySide6/Qt — no browser, no local server) for Prism.
It has **no engine of its own**: `core_bridge.py` imports `prism_terminal`'s
`core/` package directly, so routing, browser automation, voice, and
file-finding are the exact same code the CLI uses. Both apps read/write the
same `~/.prism/config.json` — set your API key or agents in either one and
the other sees it immediately.

`prism_terminal` is a **git submodule** (see `.gitmodules`), pinned to
[github.com/HitarthTrivedi/prism_terminal](https://github.com/HitarthTrivedi/prism_terminal).
Clone with `--recurse-submodules` and everything needed is there — no
separate setup step.

## Run it

```bash
git clone --recurse-submodules https://github.com/HitarthTrivedi/prism_gui.git
cd prism_gui
pip install -r requirements.txt
python3 main.py
```

Already cloned without `--recurse-submodules`? Run `git submodule update
--init` once to fetch it.

If you're developing `prism_terminal` and `prism_gui` side by side (this
repo's own setup), `core_bridge.py` prefers a sibling `../prism_terminal`
folder over the submodule automatically, so local edits are picked up
immediately without touching the submodule pin.

First launch opens the Setup dialog (API key, profile, one agent per
category, premium plans, Chrome version) if `~/.prism/config.json` isn't
already configured from the CLI.

## Layout

The window follows **direction 1b ("Workbench")** of the *Prism Directions*
design canvas — everything in view, nothing to drag — rendered in the
**Industry** design system: a light `#f2f2f3` canvas, slate-blue `#5980a6`
accent, Barlow / Barlow Condensed, square corners throughout, and hairline
borders with blueprint registration marks on the primary containers.

It auto-sizes to whatever screen it's actually on (92%/88% of available
width/height, capped at 1360×880, floor 1060×640).

Three fixed columns. The old `QDockWidget`s are gone: nothing can be dragged
out, closed, or lost behind a tab, so there's no View menu either.

- **Rail** (left) — brand, the four primary destinations (Home, AI tools,
  History, Settings), the wake-word switch, then the rest of the CLI's `/`
  commands one size down (Status, Login tabs, Email, Agents, Profile, API
  key, Chrome) and a **Favorites** shelf (star a file/folder once, click it
  later instead of re-describing it).
- **Work** (centre) — a two-page stack, because composing and running are the
  only two things you can be doing and they never want to share the screen:
  - **Composing** — the **task card** (a blueprint frame: kicker, live state
    chip, the task as editable 16px text, and Speak / Add file / Add folder /
    **Make a plan**), then **Your plan**: one row per stage the router marked
    needed, each with a square include-marker, a line icon, a plain-English
    name ("Look things up", "Write it up", "Build the slides"), one line of
    what it means, and the tool as a clickable **chip**. Click a row to drop
    that step; click its chip to run the step somewhere else. The router's
    suggestion is starred in the chip's menu; a tool you explicitly NAMED
    ("using NotebookLM…") is pre-selected and tagged *You picked this*.
    **Start the work** runs whatever is still switched on.
  - **Running** — live per-step cards, each with **Copy output** and **Open in
    tool**, so if a later step fails you can grab the last good text and carry
    on by hand. **Back to the plan** returns.
- **Context** (right) — **Files you mentioned**: every file/folder Prism
  thinks you meant (from speech), with **Keep** / **Change** per mention — the
  GUI equivalent of the CLI's confirm-before-attach flow. Typed queries don't
  auto-scan prose for file mentions; use **Add file/folder**, since a GUI has
  a real file picker. Below it, **Behind the scenes** — collapsed by default —
  opens the full chain: what you said → the expanded task brief → each stage's
  engineered prompt.
- **Setup** (rail → Settings, or any of API key / Profile / Agents / Chrome) —
  one scrolling page with a sticky header and footer. The rail links land on
  the section you asked for, scrolled into view with its field focused and its
  heading briefly marked, rather than dropping you at the top of the wizard.
- **Run history** (rail → History) — every finished *or failed* run is saved
  to `~/.prism/runs/` in the same shape the CLI writes, plus a record of which
  tool ran each step. Rendered as prose, not as the raw JSON it's stored in: what you asked and when, then one section per
  step with its plain-English name, the tool that ran it, the prompt it was
  given, and what it answered as formatted markdown.
- **Completion popup** — once the run finishes (or fails partway), a dialog
  lists every step that completed with a one-line description of what it
  produced, and an **Open** button per step that pops that ONE step's full
  text into its own window — so you only open the ones you actually need.
- **Email** (rail → Email) — mirrors the CLI's `/email`: recipients from an
  attached CSV and/or addresses typed in the goal text, a **Search for their
  public email** fallback (via your research/brains agent) when none are
  given, a draft generated through a normal pipeline stage (editable before
  sending), then a confirm-and-send step. First use opens the one-time SMTP
  setup dialog (Gmail needs an app password, not your real one) automatically.

## Known v0 limitations (be aware before relying on these)

- **Wake word ("Prism")** — `wakeword.py` is a best-effort polling loop
  (record ~2s, check for silence, transcribe if not silent, look for
  "prism"), **not** a real local wake-word engine. Expect a couple of
  seconds of lag and occasional missed/false triggers. Swap in
  Porcupine/OpenWakeWord if this needs to be production-grade.
- **NotebookLM automation** (`core/automation.py`'s `_run_notebooklm`) is
  itself best-effort/unverified against a live session — see its docstring.
- File-mention resolution on a **typed** query is intentionally NOT
  automatic (only spoken input runs the interpreter) — a GUI has real
  Attach buttons, prose-scanning a typed sentence adds risk for no benefit.

## Files

```
main.py                 entry point; registers the vendored fonts, loads the stylesheet
main_window.py          the only file that makes decisions; owns all workers & the columns
theme.py                Industry design tokens for the custom-painted widgets
core_bridge.py          puts prism_terminal/core on sys.path, re-exports it
workers.py              QThread wrappers (routing, automation, voice, find)
wakeword.py             best-effort "Prism" wake-word listener
favorites.py            starred file/folder persistence (~/.prism/gui_favorites.json)
style.qss               the Industry theme — everything QSS can express
assets/fonts/           Barlow + Barlow Condensed (OFL), vendored so headings never fall back
widgets/
  icons.py              the system's 24x24 stroked line icons, tinted & cached
  blueprint.py          the hairline frame + registration marks QSS can't draw
  controls.py           the square switch, tool chip, step mark, chips & type helpers
  sidebar.py            the left rail
  input_panel.py        the task card
  agents_panel.py       the plan (also owns the stage -> plain-English copy map)
  files_panel.py        "Files you mentioned"
  prompt_panel.py       "Behind the scenes"
  output_panel.py       live per-step results
  markdown.py           markdown -> Qt rich text, for AI responses
dialogs/
  setup_dialog.py       Setup, with per-section deep links from the rail
  history_dialog.py     past runs, re-rendered out of their stored JSON
  completion_dialog.py  what each step produced, once a run ends
  ai_directory_dialog.py, email_dialog.py
```

