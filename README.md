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

The window auto-sizes to whatever screen it's actually on (92%/88% of
available width/height, capped at 1400×900, floor 760×480) instead of a
fixed size that can overflow a smaller display.

- **Sidebar** — every CLI `/` command as a click target (Status, AI
  Directory, Agents, Profile, Key, Chrome, Login tabs, full Setup, Email,
  Run history), plus a wake-word toggle and a **Favorites** shelf (star a
  file/folder once, click it later instead of re-describing it).
- **Task panel** (top, always visible) — type or speak your task. Speaking
  runs through the same Wispr-Flow-style interpreter as the CLI: it cleans
  the transcript and splits out any file/folder mention from the actual task.
- **Files & Folders**, **Prompt Engineering**, **Agents**, and **Pipeline
  Output** are `QDockWidget`s, not fixed panes — drag any one by its title
  bar to pop it into its own floating window, resize it independently, or
  hit its **✕** to close it. Closed one by accident? **View menu** in the
  menu bar lists all four and reopens whichever you check.
  - **Files & Folders** — every file/folder Prism thinks you mentioned (from
    speech), with **Keep this** / **Change…** per mention — the GUI
    equivalent of the CLI's confirm-before-attach flow. Typed queries don't
    auto-scan for file mentions in prose — use the **Attach file/folder**
    buttons instead, since a GUI has a real file picker.
  - **Prompt Engineering** — the full chain: what you said → the expanded
    task brief → each stage's engineered prompt.
  - **Agents** — one row per stage the router marked needed: a checkbox
    (run/skip) and a dropdown of every tool in that category. The router's
    suggested alternative is starred; a tool you explicitly NAMED in your
    query ("using NotebookLM…") is pre-selected and flagged. Click **Run
    Pipeline** when you're happy with the picks.
  - **Pipeline Output** — live per-stage cards as the pipeline runs, each
    with a **Copy output** button — if a later stage fails, grab the last
    good stage's text and paste it into the next tool by hand.
- **Completion popup** — once the run finishes (or fails partway), a dialog
  lists every stage that completed with a one-line description of what it
  produced, and an **Open** button per stage that pops that ONE stage's
  full text into its own window — so you only open the ones you actually
  need instead of scrolling through everything.
- **Email** (sidebar → ✉️ Email) — mirrors the CLI's `/email`: recipients
  from an attached CSV and/or addresses typed in the goal text, a **Search
  for their public email** fallback (via your research/brains agent) when
  none are given, a draft generated through a normal pipeline stage
  (editable before sending), then a confirm-and-send step. First use opens
  the one-time SMTP setup dialog (Gmail needs an app password, not your
  real one) automatically if it isn't configured yet.

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
main.py                entry point
main_window.py         the only file that makes decisions; owns all workers & docks
core_bridge.py          puts prism_terminal/core on sys.path, re-exports it
workers.py              QThread wrappers (routing, automation, voice, find)
wakeword.py             best-effort "Prism" wake-word listener
favorites.py            starred file/folder persistence (~/.prism/gui_favorites.json)
style.qss               dark theme matching the CLI's brand palette
widgets/                dumb display widgets — sidebar, and the 4 dockable panels
dialogs/                Setup wizard, AI Directory, Email compose/setup, Completion popup
```
