# What changed

Written for the person who has to pick this up later — each entry says what it
was, what it is now, and why the change was made, because the "why" is the
part that gets lost.

Tests: **396 passing**.

---

# Round 3 — Inbox to Order

Asked for in person by a spring manufacturer at GIDC: *let Prism read my mail,
sort it, keep my inquiries in one file, quote from my own rate list, track
whether the customer said yes or no, and when the PO comes, make the production
sheet.* They also asked for SOPs to be sent to customers automatically.

The engine for all of it is built and tested. **The screens are not** — see the
end of this section.

Two documents cover it: [`docs/EMAIL_WORKFLOW.md`](docs/EMAIL_WORKFLOW.md) is
what happens, in plain language, with the flowcharts;
[`docs/EMAIL_WORKFLOW_RUNTIME.md`](docs/EMAIL_WORKFLOW_RUNTIME.md) is how —
which AI does which job, his day hour by hour, and every point a person is
needed.

### Reading the inbox — `core/inbox.py`
The other half of `mailer.py`, which could already send. IMAP over the standard
library, no new dependency. Works with any company-domain mailbox; `discover()`
tries `imap.`, `mail.` and the bare domain so nobody has to know what their
server is called.

**Two rules it will not break.** The folder is opened read-only and every fetch
uses `BODY.PEEK`, so Prism never marks anything read, moved or deleted — the
owner still uses Outlook on the same account, and a tool that silently cleared
unread flags would make them miss a real order. And nothing in the file talks
to an AI; fetching is plumbing.

Handles the things that bite in year two: a server that renumbers the mailbox
(UIDVALIDITY), the `UID n:*` search that always returns the newest message even
when it is older than asked for, attachment filenames containing `../`, and
four customers all attaching `drawing.pdf`.

### Sorting it — `core/triage.py`
Local rules first, AI only for what is left. A newsletter is caught by its own
`List-Unsubscribe` header, an out-of-office by `Auto-Submitted`, a known
customer or supplier by a list the company already has. Only genuinely new
correspondents are ever put in a prompt, and only a 1,200-character snippet of
them.

That ordering is what makes "most of your mail never leaves this computer" a
testable claim rather than a hopeful one — and it is tested: a suite check
fails the build if locally-sorted mail ever reaches a prompt. `local_only`
turns off the AI pass entirely and the feature still works.

Corrections are learned per exact address, so a sender is never asked about
twice. They outrank every rule except machine post — one mistaken tap must not
put a robot's auto-reply in the register for ever.

### The register — `core/register.py`
One growing CSV, one row per inquiry, opens in Excel. Financial-year numbering
(`INQ/25-26/0087`, April to March, like every quotation book in the country).
Written atomically, because a crash mid-write must not truncate somebody's
order book. Columns they add by hand survive. When the file is open in Excel it
says *"close the inquiry register in Excel"* rather than failing silently.

Replies find their own row by Message-Id, falling back to an open inquiry from
the same address — which catches the customer who replies from their phone and
breaks the thread. A closed row never swallows new business.

Also here: `awaiting_followup()`, the most valuable list in the file, and the
month-end figures. Conversion is counted against quotations sent, not inquiries
received — an inquiry nobody quoted was never a chance, and counting it makes
the number flattering and useless.

### Pricing — `core/quoting.py`
Reads their rate list (CSV, or Excel via openpyxl) and finds the header row
rather than assuming row 1, because real price lists open with a letterhead.
Understands quantity slabs from `Rate @ 1000` columns. Matches free text to a
row by rare-word weighting with the digits weighted up again, because in this
trade the numbers are the specification — and returns *candidates with reasons*,
never a decision.

For made-to-drawing work there is no rate to look up, so there is a cost sheet:
their own lines, their own rates, charged per kg, per piece, per lot or as a
percentage. Plus wire and coil weight from a drawing's dimensions — geometry,
checkable against a scale.

**No AI touches a number in this file, and a test enforces it.** Every figure
is Decimal, rounded half-up the way Indian accounting does — Python's default
turns ₹0.125 into ₹0.12 where Tally says ₹0.13, and "the software rounds
differently" is not a conversation worth having. The AI is handed formatted
figures and told, twice, to write the sentences around them.

### Purchase orders — `core/po.py`
Pulls the fields out of a PDF or Word PO, then puts it next to the quotation
and points at every difference. Scans are detected and say *"type these four
things in"* instead of returning a confidently empty order.

### SOPs — `core/sop.py`
The easiest thing in the whole workflow to automate, because there is no money
in the message. Library from a folder — revisions read from filenames like
`SOP-07_Heat-Treatment_rev3.pdf`, or from an index file if they keep one — and
only the newest revision is ever offered.

Four triggers, and the third is the one worth building for: **revise a
document and everyone holding the old revision is chased automatically.** The
log records who received which revision on which date, which is the answer to
*"prove your customers were notified"* — the question an ISO auditor asks, and
which today means somebody searching Sent Items for an afternoon.

### The daily loop — `core/mailflow.py`
One `check()` call does everything that cannot cost money if it goes wrong, and
hands back a worklist of what needs a person. **It never sends anything** — a
test greps the file to keep it that way. It never raises either: this runs on a
ten-minute timer next to somebody running a factory, so a mail server having a
bad afternoon belongs in a status line.

### Two bugs found by the tests, both real
- **A rate cut was measured against the wrong thing.** The PO comparison
  ignored differences under ₹1. Ninety paise off a unit rate is under ₹1 — and
  on 5,000 pieces it is ₹4,500, walking straight past the check that exists to
  catch it. The tolerance now multiplies out by the quantity first.
- **The inquiry folder was not created when nothing was attached.** The
  register printed a path that opened onto nothing.

### Also
- `plans.py` gains the `inbox` feature. Inclusive in **Works** — it is the
  piece they use every day, and it is what makes them open Prism at all.
  An add-on for **Studio**.
- **The BOQ paywall copy was lying.** It promised "a priced BOQ"; the engine
  deliberately leaves Rate and Amount blank. Now it says the customer's rates
  go in the blank columns — Prism counts, you price. Same correction already
  made in the business documents.
- `openpyxl` added to `requirements.txt`. Optional at runtime, bundled in every
  build.

### Not done — the screens
The engine runs the whole loop. The window he clicks in does not exist yet:
mail-account setup, the worklist, the quotation review with its Hold button,
and the PO confirmation. That is the next piece of work, and it is what he will
judge the product by.

Also still English-only: `plans.py` feature names and blurbs are not in the
translation catalogue — the new `inbox` feature is in exactly the same state as
every existing one, so this is a pre-existing gap rather than a new one.

---

# Round 2 — roles, languages, cloud attach, plain-English errors

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
