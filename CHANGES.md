# What changed in this round

Everything below is in this commit. Tests: **263 passing**.

Written for the person who has to pick this up later — each entry says what it
was, what it is now, and why the change was made, because the "why" is the
part that gets lost.

---

## Bugs fixed

### Apollo was being sent a paragraph and refusing it
A live run failed with `Value too long: 'Context from the previous pipeline
stage (RESEA…' exceeds 200 characters`. Apollo is a filter screen, not a chat
box, and its API rejects any single value over 200 characters — the pipeline
was handing it the whole inter-stage brief.

Two halves. The stage before Apollo is now told to emit a fixed filter block
(`TITLES / INDUSTRIES / LOCATIONS / HEADCOUNT / KEYWORDS`) instead of prose,
and Apollo is driven by **its own search URL** rather than by typing into the
page — Apollo mirrors its whole search state into the address bar, so this
sets the same filters without touching the left rail's class names. Values are
hard-capped in code, not just asked for in the prompt.

*Files:* `core/agents.py`, `core/automation.py`, `tests/test_apollo.py`

### Canva took over every image
With the Canva app connected to ChatGPT, every visual and presentation turn
came back as a flat template — including jobs that needed a rendered
illustration. Canva composes a stock layout; DALL·E renders the scene actually
described.

Canva is now **opt-in**: it engages only when the user's own words ask for
something editable (`canva`, `editable`, `template`, `edit later`…). And when
they have not asked, the prompt says so explicitly — silence is not enough,
because a connected Canva app gets reached for unless told otherwise.

*Files:* `core/agents.py`, `core/automation.py`, `tests/test_canva.py`

### Add file stopped working
Caused by the i18n work below. To translate a window caption, `QFileDialog`'s
**static** methods were wrapped — but those are the entry point to a *native
OS panel*, not a Qt widget, and every attachment in the app goes through them.
macOS does not even draw a title on an open panel, so the patch bought nothing
and cost the most load-bearing path in the UI.

Statics are stock again; captions are translated at the call sites instead. A
test now fails the build if they are ever wrapped again, and a second test
greps every call site for a bare literal caption.

*Files:* `i18n.py`, `main_window.py`, `widgets/*.py`, `tests/test_i18n.py`

### LAZYCOOK was being talked down to
It runs its own Generate → Analyze → Optimize → Validate loop and scrapes the
web itself — which is the entire reason to route to it over Perplexity. Prism's
house style (`Your ONLY task is:`, a fixed section list, `STRICT PIPELINE
RULES: 1. Perform ONLY the task above — nothing more`) reads to it as "stop
after the first pass", so it answered in one shot and came back weaker than
the tool it was chosen over.

Agents can now declare `prompt_style="natural"` and get asked the way a person
asks. The handoff is still requested — the pipeline cannot work without it —
but as a request at the end rather than as rule 3 of 4. The router also gets a
carve-out rule, **only when such a tool is actually in the plan**.

*Files:* `core/agents.py`, `core/automation.py`, `core/router.py`

---

## New features

### Multilingual — Hindi and Gujarati, 100%
Prism translates **by value**, not by call site: `t()` takes the English string
and returns the local one, and `install()` patches the Qt methods that put text
on screen so no widget code changed.

The safety property: a string is only swapped if it is in
`lang/_catalogue.json`. The same `setText()` also draws customer names, file
paths and whole paragraphs written by Claude — none of those are in the
catalogue, so none can be touched. Run `devtools/extract_strings.py` after
adding UI copy.

Also handles: script-appropriate font fallbacks (Barlow has no Devanagari),
right-to-left layout, and a **separate** setting for what language the AI
tools write back in — plenty of people want the app in Gujarati and the client
deliverable in English.

*Files:* `i18n.py`, `lang/`, `devtools/extract_strings.py`, `core/lang.py`

### Roles, per-member folders and a manager view
A company activates with one **company key**; each person then pastes a
**designation key** (`PRSD1.…`) that we mint. The role is Ed25519-signed, so it
cannot be forged by editing a settings file — tests cover self-promotion,
another company's key, and replay as a licence token.

Eight roles (Owner, Manager, Sales, Marketing, Operations, Engineering,
Accounts, HR), each with its own workspace folder, default tools and **accent
colour** — the hue rotates while every swatch keeps its exact lightness, so
contrast is identical in all nine (measured drift: 0.000000).

`workspace.readable_members()` is the single access rule: a working role sees
one folder, an admin sees all. Every screen goes through it.

> Enforced by Prism, not by the OS. On a shared drive a member can open Finder
> and read another folder. The signed role is the part that is solid.

*Files:* `roles.py`, `identity.py`, `workspace.py`, `plans.py`,
`licensing/designation.py`, `theme.py`

### Cloud file attach — no OAuth
Add file now lists every cloud folder mounted on the machine — Google Drive
(named by account), Shared drives, OneDrive, Dropbox, iCloud — and opens the
chooser inside it.

Google Drive for Desktop mounts Drive as an ordinary folder, so there is no
token, no consent screen, and nothing that expires. The OAuth path in
`integrations/gdrive.py` still exists for anyone without Drive for Desktop,
but it is no longer the way in.

*Files:* `cloud.py`, `integrations/`, `dialogs/drive_dialog.py`

### Plain-English errors
Every failure goes through one translator and comes out as **what happened**,
**what to do** as numbered steps, and where possible a button that does it.

`session not created: This version of ChromeDriver only supports Chrome 131`
becomes *"Prism couldn't open Chrome"* with three steps and a button to the
Chrome setting.

Tests fail the build if "webdriver", "selector", "traceback", "HTTP" or
"OAuth" reaches the screen, or if any message lacks a next action — a message
without one is a phone call.

*Files:* `friendly.py`, `dialogs/problem_dialog.py`

### A guide, and a welcome
"How to use Prism" is second in the sidebar: 13 topics in plain language with
copyable examples. Locked add-ons appear greyed with what they do — it is the
only place a customer discovers what else we sell. First-timers get a welcome
offering the tour before Setup.

*Files:* `dialogs/guide_dialog.py`, `main_window.py`

### Attachments
Folders now show as one row with their files indented, so a whole "Add folder"
can be removed in one go. Plus **Detach all**, a duplicate guard, and a status
message for every outcome — so a button that appears to do nothing is
impossible.

*Files:* `widgets/files_panel.py`, `main_window.py`

---

## Reliability

Audited the whole path a daily user walks. See `KNOWN_ISSUES.md` for the
plain-language version sorted into *fixed / code / needs money / nobody can
fix*.

| | |
|---|---|
| **Groq retires a model** | `MODEL_FALLBACKS` is a list. A dead model falls through, the working one is saved, the customer sees nothing. This one would have taken every install down on the same day. |
| **Rate limits** | Waits the `retry-after`, retries once, then says what to do. |
| **Cold-start refusals** | Authorize timeout 15s → **45s** plus one retry — transport failures only, never on a real answer, so a metered run cannot be double-counted. |
| **No way to debug** | Rolling log in `~/.prism/logs` + **Export diagnostics**. Credentials and email addresses are stripped, and that is tested. |
| **Sleeping mid-run** | Wake lock held for the run, released even if the window closes mid-run. |
| **Silent truncation** | Long attachments show "(first part only)". |
| **Workspace offline** | Banner saying today's work will not reach the manager. |

*Files:* `diagnostics.py`, `awake.py`, `core/router.py`, `licensing/client.py`

---

## Things deliberately NOT done

- **Licence server hosting.** The 45s timeout absorbs most cold starts, but a
  host that sleeps needs a paid plan. Free interim: point an uptime monitor at
  `/health` every 10 minutes.
- **Publishing the Google OAuth consent screen.** Only matters if we ever use
  the API route instead of Drive for Desktop. While it is in Testing, refresh
  tokens expire every 7 days.
- **The guide's own text is English only.** The UI is 373/373 in Hindi and
  Gujarati; the 13 guide topics are not in the catalogue yet.
- **Rate cards.** The BOQ engine leaves Rate/Amount blank on purpose. Letting
  a customer attach their own price list is the single feature that would open
  the dealer and manufacturer markets — see `docs/BUSINESS_NOTES.docx`.

---

## If something here breaks

1. `Settings → Export diagnostics` — one file, credentials stripped.
2. `~/.prism/logs/prism.log` — the rolling log.
3. `python3 -m unittest discover -s tests` — 263 tests.
4. `QT_QPA_PLATFORM=offscreen PRISM_SELFTEST=1 python3 main.py` — proves a
   build is whole.
