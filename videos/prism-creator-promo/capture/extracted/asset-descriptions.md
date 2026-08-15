# Asset inventory

No website was captured — Prism is a native desktop app (PySide6/Qt), so the
no-capture path applies and the brief supplied the material. Three real assets
are available, all staged in `capture/assets/`.

## capture/assets/prism-logo.svg

The Prism mark: a faceted prism drawn as five flat polygons in a teal ramp
(`#86EBD3`, `#4CD9B4`, `#35C7A4`, `#1DA487`, `#128066`) inside a `#4CD9B4`
9px-stroke outline that reads as a tall glass wedge. 260×340, transparent
background. Vector — safe to scale to any size. **Use:** the closing sting, and
optionally as the small brand lockup in the first frame.

## capture/assets/app-plan-rows.png

A real 1470×984 macOS screenshot of Prism mid-task, the single strongest piece
of evidence in the project. Light `#f2f2f3` canvas, slate-blue accent, Barlow
type. What it shows, left to right:

- **Left rail** — brand lockup "PRISM", Home / AI tools / History / Settings,
  a `Listen for "Prism"` switch, then ADD-ONS (BOQ, Email, BOM Stock (soon)),
  WORKSPACE (Status, Login tabs), CONFIGURE (Licence, Agents, Profile, API key,
  Chrome).
- **Centre, top** — the action row: `Speak`, `Add file`, `Add folder`,
  `Add task`, and a filled slate-blue `→ Make a plan` button.
- **Centre, main — "Your plan", "3 steps of 7".** Seven rows, each a square
  include-checkbox, a line icon, a plain-English name, one line of what it
  means, and the tool as a clickable chip on the right:
  1. **Look things up** — "Find the facts and sources this needs" — chip
     `Perplexity` — carries a **Suggested** tag. *Checked.*
  2. **Think it through** — "Work out the angle and the argument" — chip
     `ChatGPT`. *Checked.*
  3. **Write it up** — "Turn the thinking into clear words" — chip `Claude`.
     *Checked.*
  4. **Make the images** — "Generate the artwork to go with it" — chip
     `ChatGPT`. *Unchecked.*
  5. **Make the video** — "Produce the video or audio piece" — chip
     `Claude Design`. *Unchecked.*
  6. **Build the tool** — "Stand up the app or page itself" — chip `Kimi 2.6`.
     *Unchecked.*
  7. **Build the slides** — "A clean deck, ready to present" — chip
     `Claude Design`. *Unchecked.*
- **Centre, bottom** — a full-width slate-blue `▶ Start the work` button and a
  `Discard` button.
- **Right column** — "FILES YOU MENTIONED", an `ATTACHED` group holding one
  file card, `Delta_Investor_Deck.pptx`, with a `Detach selected` button below;
  then "BEHIND THE SCENES ›" with the line "See exactly what Prism will ask
  each tool, in plain English. Optional — only if you're curious."; and at the
  bottom a tip: "Click any step to leave it out, or click its tool chip to run
  that step somewhere else."

**Constraint:** landscape (1470×984) against a 1080×1920 canvas. Never show the
whole window — crop into the region that carries the beat (the plan-rows stack;
the attached-file card; a single row with its tool chip) and stage that crop as
a lit inset panel.

## capture/assets/app-task-card.png

A real 1248×762 screenshot of Prism at rest, before a task exists. The task card
is empty and reads "Describe what you want done — name any file or folder in
plain words and Prism will go find it", with `Speak` / `Add file` / `Add folder`
buttons and a **disabled** `Make a plan`. A "Waiting on you" state chip sits top
right. "Your plan" below is an empty placeholder: "Describe a task above and
press Make a plan — Prism will lay out the steps here, and you can drop any of
them before it runs." The right column reads "Nothing attached yet. Mention a
file out loud, or use Add file." Same landscape constraint — crop, don't shrink.
**Use:** the before state, if a before/after beat needs it.
