# What changed

Written for the person who has to pick this up later — each entry says what it
was, what it is now, and why the change was made, because the "why" is the
part that gets lost.

Tests: **813 passing**, plus 148 scenario checks (`devtools/scenarios.py`).

---

# Round 9 — the help screen learns to talk, and the way to a person is real

Round 7 shipped Help & support with tiers two and three as placeholders, on
instruction. The instruction changed after a day of real use, and so did a
verdict on the first version's feel: a chat screen that posted every menu
into the thread and left it there read as a form that kept growing.

## The transcript behaves like a conversation now

**Was:** ten full-width topic cards in the thread, then ten question rows,
then ten more topic cards when somebody went back — all of them still
pressable for ever, which is both a wall to scroll and a fork waiting to be
clicked.

**Is:** three rules. Topics are CHIPS — their names are two words, so ten of
them take three short rows and the whole opening fits above the fold
(questions stay full-width rows, because a truncated question cannot be
chosen). A menu is RETIRED the moment the conversation moves past it — the
pick already survives as the customer's own bubble, so nothing readable is
lost. And Prism's messages carry its mark, because two voices in one column
need telling apart faster than reading them. Plus a Start over button — the
screen keeps its thread across visits by design, which made "begin again"
impossible without one.

## The assistant is real — the customer's own Groq key, on a leash

The button now starts a conversation with a model, and everything about the
wiring is about keeping it honest:

* It answers **from the written help, not from its imagination**: every
  question heading (so it knows the true shape of the product), the full
  text of the answers matching this question, and the ones already read —
  marked *do not repeat these*. The first rule of its instructions is to say
  "I don't have that one, press Contact the team" rather than guess, because
  a made-up menu item costs the customer more than an admitted unknown.
* It starts knowing the four facts half of every support call is spent
  establishing: version, whether a key is saved, the platform, the licence
  state.
* Temperature 0.15 — support answers are quotations from the manual, and a
  model feeling creative about which menu an option lives in is the one
  failure this tier cannot afford. A test pins it.
* Its failures go through `friendly.explain()`, so the assistant breaking
  reads exactly like the rest of the app breaking — a sentence and steps,
  never a code. No key saved: it says so and offers the Settings button,
  because the customer least likely to have a key is the one who has not
  finished setting up.
* An animated Thinking bubble while it works, and the window's own shutdown
  now winds the assistant's thread up — a running QThread destroyed with its
  owner aborts the process, and Prism vanishing mid-question is a memorably
  bad way to end a support session.

## Contact the team hands the whole story to a person

The sheet arrives pre-filled with what a support thread spends its first
three replies asking for: version, platform, licence state, the device code
(seat problems are unanswerable without it), and the full conversation —
editable, with the promise printed on it that keys and passwords are never
included (true by construction, and tested). Three ways out, because
`mailto:` silently does nothing on a machine with no mail client: open the
email app (with the full text put on the clipboard FIRST, so a truncating
mail client cannot lose it), copy it all, or save it as a file that also
carries the redacted diagnostics report.

## Tests

52 in `tests/test_support.py` now: the retire-the-menus rules, Start over
forgetting everything including the gate, the assistant's grounding (whole
product shape, full answers for the question at hand, already-read marked),
the refuse-don't-guess instruction pinned by string, the no-key path, the
cautious temperature, failure-through-friendly, and the contact draft's
contents and its no-secrets guarantee.

---

# Round 8 — Email automation: every inbox, one register, and the order's own screen

A second firm described their whole operation in one sentence: everything —
inquiries, quotations, follow-ups, purchase orders — arrives by email, on
several addresses, and several people retype it all into one shared Excel
sheet. That is the workflow the engine has run since Round 3, asked for at
the scale of an office instead of a desk. `docs/EMAIL_AUTOMATION.md` is the
full design and the business case, with sources; this is what changed.

## The mailbox step takes a list now

**Was:** one account under `cfg["inquiry"]["account"]`, one read bookmark
beside it.

**Is:** `cfg["inquiry"]["accounts"]` — each entry with its own bookmark,
because two mailboxes sharing one last-UID would skip or re-import each
other's mail, and either failure is indistinguishable from a quiet week.
The old keys are still written, mirroring the first entry, so a config saved
by this version opens in the previous one; `accounts_of()` is the one reader
that understands both, and an existing customer's first check after updating
carries on from exactly where their last one stopped.

**The walk is one account at a time, never parallel.** The engine's own rule
— two fetches racing on one bookmark registers the same inquiry twice — is
"N fetches racing on one order book" the moment there are N accounts. One
dead mail server is skipped and named ("sales@… — the mail server didn't
answer" is a whole sentence; without the address it is half of one); one
locked register stops the walk, because the same lock would refuse every
account after it and none of their bookmarks have moved. A password being
refused three times sidelines that mailbox — the provider would throttle and
then lock it, and "Prism locked me out of my email" is the support call that
ends a deployment — while the healthy ones keep being read.

**The register says where each inquiry arrived.** One new column, `Mailbox`,
stamped when the row is born and never rewritten — a PO landing on a
different address later is not the inquiry moving. With sales@, info@ and
the owner's own address feeding one file, "who is this customer talking to"
is the first question the sheet gets asked.

**The centralised sheet was always one file; Setup now says so.** The
register lives in one folder, so the folder picker now carries the sentence
("choose a folder on your shared drive and everyone opens the same
register") and a one-click **Use the team folder** when the Prism workspace
is set up. One machine does the writing — the office PC that stays on;
everyone else reads. Several machines writing one register is deliberately
deferred, with its trigger, in `docs/DEFERRED.md`.

## The purchase order finally has its screen

`core/po.py` — read the PO, compare it to the quotation, flag every
difference — has been built and tested since Round 3, and no screen ever
called it. The runtime doc has named "the PO confirmation" as the missing
screen the whole time. Tab **5 · The order came** is that screen:

* The comparison is against the quotation **actually sent**, read back from
  the CSV written at send time — today's rate list could quote something the
  customer never saw. The reader mirrors `quoting.write_csv` and is checked
  against the file's own Total row to the paisa; a file that does not add up
  produces NO comparison rather than a wrong one.
* Accepting is a button, and it only writes the register — `Converted`, the
  PO number, the order value. The second of the two money stops, exactly
  where every doc has always promised it.
* The typed-in boxes are not a failure mode, they are the design: half of
  real POs are scans with no text in them, and the privacy switch means a PO
  — which is mail content — is never sent out to be read when *Keep
  everything on this computer* is on. Reading by machine is the convenience;
  the person holding the printed order is never blocked. (OCR: deferred,
  with a measured trigger, in `docs/DEFERRED.md`.)

## The shelf says "Email automation" now

Both prospect firms said "email", not "inquiries", when they described what
they wanted — so the shelf item, the screen and the setup say **Email
automation**. The rail key (`inquiry`), the licence feature (`inbox`), the
register format and every file on disk are unchanged: the SKU and the wiring
did not move, only the name on the shelf. The support screen's answers grew
three questions to match (several mailboxes, the shared register, what
happens when the PO arrives).

## Tests

27 new (`tests/test_email_automation.py`): per-mailbox bookmarks banked
against the right account, the dead-server skip and the locked-register
stop, learned senders chaining from one mailbox's check to the next, the
Mailbox stamp (and that it never rewrites), per-address password back-off,
the quotation round-trip to the paisa with the tampered-file refusal, the
₹4,500-on-ninety-paise comparison catch, the privacy switch keeping a PO's
text on the machine, and the review sheet refusing an empty accept. The
five-tab order test in `test_inquiry_ui.py` was updated deliberately: the
tab order is still the explanation of the feature, and the fifth tab is the
end the workflow was sold on.

---

# Round 7 — Help & support: the written answer first, then us

`friendly.py` speaks when Prism itself notices a problem. Nobody was there
for the larger half — the customer who is not looking at an error at all:
does one licence cover two computers, will the inbox add-on touch my real
mail, what do I type in the box. Nothing is broken, so no dialog ever
appears, and every one of those questions was a phone call.

## A new rail destination, and the shape of it

**Help & support** sits in the rail next to How to use Prism — they are not
the same thing: the guide is for somebody who does not yet know what Prism
does, this is for somebody who knew exactly what they wanted and did not get
it. It is a screen, not a dialog, like every other destination the rail
switches to, and it keeps its conversation for the life of the window — you
can follow an answer's button to Settings and come back to the thread.

Three tiers, in an order that is the whole design:

1. **The written answers** (`support_kb.py`) — 61 questions in 10 topics,
   the ones actually asked down a phone, phrased the way the customer says
   them. Same writing rules `friendly.py` is held to: plain English, then
   numbered steps that start with a verb, never a problem without a next
   action. Every button and menu an answer names was checked against this
   build — the redesign moved several (Login tabs sits behind More settings
   now; "Back to the plan" became "Back to the steps"; Export diagnostics
   lives on the sheet Settings' Change buttons open) and an instruction that
   names a control that is not there sends the customer hunting.
   A typed box searches them; the scoring deliberately returns NOTHING
   rather than a weak guess, because the empty result is what opens the
   route to a person.
2. **The assistant** and 3. **Contact the team** — placeholders, by
   decision, not omission. The plan is an assistant that talks the problem
   through, and a direct line that has us call the customer; both are their
   own change. The buttons are already in place so the screen's shape does
   not shift under people later, and each one, pressed today, answers
   honestly in the transcript — the contact one hands over the address that
   is read today. A placeholder may postpone the feature, never the person.

**The gate.** Tiers 2 and 3 stay shut until a written answer has actually
been tried — the pattern every government service site uses, because a
button marked contact-us gets pressed instead of the four-line answer that
was faster. But it opens on the FIRST honest miss: one answer marked "No,
still stuck", or one typed question with no match. Nobody is made to read
six irrelevant answers to earn a person, and the shut buttons carry the
sentence that says what opens them.

**The ways in.** friendly's catch-all — the one entry where we genuinely do
not know what went wrong — now carries an "Open Help & support" button, and
the guide's "when something goes wrong" topic points the same way.

## What it took elsewhere

* `devtools/extract_strings.py` had not learned the redesign's copy tables
  (`sidebar.MORE`, `settings_panel.SECTIONS`, `GuidePanel.CARDS`, …), so the
  new screens' labels were quietly untranslatable; registered them, and
  normalised catalogue paths to forward slashes so a regeneration on Windows
  stops rewriting every entry. Catalogue regenerated: 373 → 768 strings.
  Sixteen keys whose English no longer exists anywhere were pruned from the
  Hindi and Gujarati packs.
* Two transcript bugs found by measuring rather than looking: the scroll
  range ran hundreds of pixels past the last message (a word-wrapped label's
  *minimum* size is its height when wrapped at its widest word, and the
  layout sums those width-blind), and the scroll-to-newest landed one layout
  pass short every time. The column now sizes by height-for-width and rides
  the range while a message settles.
* 36 tests (`tests/test_support.py`): the jargon and verbs-first rules the
  answers are held to, every action key against the window's dispatcher,
  the search phrasings, both halves of the gate, and that the placeholders
  answer honestly and end somewhere real.

---

# Round 6 — the reels were slides, and it was arithmetic

One change, and it came from a measurement rather than an opinion.

A reel built by hand with a coding agent was compared against a reel Prism
generated. Same renderer, same CSS, same browser. The difference was not taste:

|                        | Built by hand | Prism |
| ---------------------- | ------------- | ----- |
| markup + motion per scene | **20,300 chars** | **278 chars** |
| elements per scene     | 25–77         | 3–5   |
| animations inside scenes | 150         | 0     |
| planning written first | ~50,000 chars | none  |

**278 characters is a headline and a subhead.** That is a slide. There is
nothing in it to move, so no instruction about motion could ever have fixed it
— which is exactly why the previous attempt, which added motion rules to the
prompt, made the output worse rather than better.

The cause was structural. The art director was asked for the whole reel in one
JSON object, and a model writing one JSON object budgets a few thousand
characters and divides them by seven.

## The design stage is a conversation now

**Was:** one prompt, one reply, the whole reel.

**Is:** turn one is the LOOK and a STORYBOARD — the palette, the type, the
shared stylesheet, and one row per scene giving it a distinct job, composition
and motion. Then one turn per scene, in the same tab, each with a whole reply
to spend on one scene. Each is laid out in the real browser and corrected
before the next is asked for.

Measured on the same four-scene script, rendered both ways:

```
OLD   4 scenes |   271 chars/scene |  7 elements/scene |  0 animations
NEW   4 scenes | 2,339 chars/scene | 34 elements/scene | 30 animations
```

**Why the correction loop is better too.** A layout fault used to come back as
"scene 3's headline is off the frame" against a reply the model had long since
moved past. Now it is simply "this one", while the scene is still the subject.

**Why more turns cost the customer nothing.** Prism drives the customer's own
browser on their own subscription. Ten prompts in a chat window instead of two
is slower, not more expensive — which is the opposite of the economics a
coding agent faces, and the reason this approach was available to us and not
to them. The design stage now takes minutes rather than seconds, and says
which scene it is on while it works.

## Per-scene CSS is confined to its scene

`scope_css()` in `core/reel_web.py`. A model naming things in reply four
cannot see what it called them in reply two — everybody writes `.title`,
everybody writes `@keyframes rise`. Left alone they collide and whichever
scene loses the cascade silently inherits another scene's type size and
another scene's motion.

Every selector is rewritten to that scene's layer and every `@keyframes`
renamed, with the `animation:` declarations that point at them following the
rename. Three details that took real care:

- **`.leaving` is the scene element itself**, not something inside it.
  Prefixed as a descendant, every hand-written cut would have silently
  stopped working.
- **A class may share a keyframes name.** `.rise` and `@keyframes rise` are
  both idiomatic; only the animation references are rewritten, never the
  class.
- **`url()` contents are not CSS.** A brace in a path or a data: URI used to
  be read as structure and cut the stylesheet in half.

It is worth more than the collisions it prevents: because a scene *cannot*
reach outside itself, the prompt never has to ask it to be careful. It is told
so, in as many words — a scene free to name things clearly writes better CSS
than one hedging against a collision it cannot see.

## A failed turn costs one scene, not the reel

More turns means more chances to fail. A reply that is prose rather than JSON
is asked again, more bluntly. A scene that still will not come back is
replaced by a plain one built from the script's own words — modest, legible by
construction, in the design's own colours. One dull scene ships; a hole does
not.

---

# Round 5 — a week of real runs, and what they broke

Nothing in this round came from planning. Every entry is something that went
wrong while the product was being used to make an actual reel for an actual
prospect, and several of them had been quietly wrong for a long time.

The theme, if there is one: **Prism was losing information at the seams.** Not
crashing — losing. The customer's own words on the way into a prompt, the
customer's CSS on the way out of a browser, the evidence on the way into an
error message. Every one of those failures reads as "the AI did a bad job".

## The customer's own words now reach the tool doing the work

The most expensive bug here, and the hardest to see.

Prism expands a request into a professional task brief, and the router writes
each stage prompt FROM that brief. The router is handed the raw request and
told it wins on scope — but the stage prompts it produces were only as good as
what it chose to carry across, and **the agents never saw the original at
all.**

A customer asked for a reel about *"Consiz, a mouse with a middle button that
summarises whatever you have selected and lets you ask questions about it"*.
The brief came back as *"showcase the mouse, demonstrate its features, explain
its benefits"*. The button, the selecting, the summarising, the asking — every
mechanical fact, gone. Claude then wrote a genuinely good script about a
generic productivity mouse, because a generic productivity mouse was all it
had ever been told about.

Nothing downstream can catch that. A summary that drops the one fact the whole
video is about still reads perfectly well, so every later stage compounds it
confidently — and the handoff chain means stage four works from stage three's
summary of stage two's summary.

The raw request now rides at the top of every stage prompt, verbatim, before
the attachments and before the previous stage's handoff. It is labelled as the
human speaking, and says outright that what follows is a summary, that
summaries lose things, and that specific facts above must survive even if the
brief below does not repeat them. Capped at 2500 characters and marked when
truncated — generous on purpose, because the Consiz mechanism sat in the last
third of that sentence.

*Suggested by the customer, who diagnosed it from the two briefs side by side.*

## The chat window was corrupting the design on its way out

Two bugs, one saved file, and the model was innocent of both.

A reel's art direction is a JSON document containing a full stylesheet.
Repeatedly it came back as **"No JSON found in the agent's reply"** while the
customer could see JSON sitting on the ChatGPT page. Unanswerable — until the
failed reply started being kept (below). One look at it settled both:

- **A soft-wrapped URL became a real newline inside a JSON string.** The chat
  window wrapped a very long Google Fonts `@import`, and the scrape turned that
  visual wrap into an actual line break inside the value. JSON forbids an
  unescaped control character in a string, so an entire design was thrown away
  over a line break that only ever existed on screen. `_escape_control_chars()`
  now escapes exactly those, tracking string state so ordinary
  pretty-printing between members is untouched. Run against the real saved
  failure, the design comes back whole — 6 scenes, both fonts, 3550 characters
  of CSS.

- **Markdown ate every asterisk, and that was our own instruction's fault.**
  Both prompts said "no fences". Outside a code block the reply renders as
  prose, prose is markdown, and markdown treats `*` as an emphasis marker — so
  `*{box-sizing:border-box}` arrived as ` {box-sizing:border-box}` and the
  whole CSS reset was silently dropped. The saved file contained **zero
  asterisks in 17KB**. Fences are now required, and the prompt says why so a
  model does not helpfully strip them again. The parser has always skipped
  fences — its own docstring says scrapes carry them — so forbidding them
  bought nothing and cost entire designs.

## Evidence is kept instead of discarded

The reason the above took three attempts to diagnose: the scraped text lived in
a local variable, the run moved on, and the error said only "No JSON found".

A design that will not parse is now written to
`~/.prism/logs/design-that-would-not-parse-<ts>.txt`, and the error names the
file. It answered a fortnight-old mystery on its first use.

The same failure of nerve appeared elsewhere: **a planning failure discarded
the customer's prompt entirely.** Planning is where runs fail most often — a
rate limit, a dead connection, an expired key — and it fails before anything is
written down, so their own words were the only casualty. Somebody who spent
five minutes describing a job had to remember it and type it again. Saved now,
error and all.

## A reel with no pictures is designed on purpose

Image generation fails for ordinary reasons — a quota, a content refusal, a
render that never finished. On one run ChatGPT thought for 185 seconds and
produced nothing.

Prism noticed. The design stage did not, and **silence is not neutral**: an
empty asset list produced an empty listing, so the prompt simply did not
mention pictures, and a model asked for a premium product reel assumed the
usual ones existed and wrote `src='asset:art1'`.

The renderer already strips unresolved assets, so nothing showed a broken-image
glyph. But a layout DESIGNED around pictures that never arrive is worse than
that: the holes are stripped and what remains is a composition with gaps in it,
which reads as broken rather than as spare.

`assets.manifest({})` now says there are no images, that this is not an
oversight, that nothing is coming later, and — the part that matters — what to
do instead: carry it on typography, hierarchy, negative space, rules, colour
fields and CSS shapes. A prohibition alone produces a timid design, so it also
says outright that a spare type-led reel is a legitimate and often superior
one.

## Canva: make the picture first, then make it editable

Asking for an editable Canva design and a good image in the same prompt made
the customer choose between them. Canva COMPOSES a template — stock layouts,
its own type — where DALL·E renders the scene described. For "da Vinci sipping
Wagh Bakri chai" the render is the whole job.

Now the two asks stop competing. The first prompt asks only for the best
picture the tool can draw; once it exists, a second prompt goes into the same
conversation — `@canva can you make this design editable` — pointing at the
artwork directly above it. Best picture *and* an editable file, which was not
previously on offer. *The customer's idea.*

Four failure modes have defined answers rather than surprises: nothing
generated → skip it entirely; Canva not connected → the fixed reply is dropped
rather than appended; Canva silent → keep the image; wrong kind of stage →
never asked.

That last one shipped wrong and was caught on the first real run: `artwork` and
`design` were included, and the Studio pipeline's design stage emits JSON for
Prism's own renderer — so the follow-up asked Canva to "import the image above"
when the message above was a CSS blob. The editable stages are now exactly the
registry's Canva-configured ones, with a test asserting the two lists match,
because they drifted apart once and **that drift was the bug**.

## Closing the browser no longer kills Prism

Reported as *"python stopped working and prism ended"*, with a real macOS crash
report behind it: SIGABRT, `QThread::~QThread`, `_Py_Finalize`.

Qt calls `qFatal()` when a thread object is destroyed while still running, and
PySide destroys every QThread during interpreter shutdown. So closing Prism
mid-run did not leak quietly — it killed the process. The app's own log signed
off with an ordinary "Prism closed" and no traceback, which is why it looked
like a mystery: the crash happens after the last thing anyone logs.

Every live worker is now stopped and joined on close. Stop-all before wait-all,
so three stuck workers cost ten seconds between them rather than thirty.
Inquiry Automation had the same hole and more workers than anywhere else.

Separately: **a closed browser window was diagnosed as a Chrome version
problem.** Every frame of a Selenium stack trace says
`undetected_chromedriver`, which matched the version-mismatch rule, so a closed
tab sent the customer off to update a browser that was working perfectly. A
confident wrong answer is worse than the generic one it replaced, because they
act on it. And the run kept going against the dead session — every later stage
opening it, timing out, and reporting the same error. It stops on the first one
now and says so once.

## When a tool runs out, another one finishes the job

A run is twenty to forty minutes and the heaviest stage is usually the last, so
the free tier that runs out runs out at the END — leaving a pipeline that did
nine tenths of the work and produced nothing usable.

Prism now reads the page for "you've reached your limit", "out of free
messages", "upgrade to continue" and the rest, kept deliberately apart from the
signed-out check because the two need opposite responses: an exhausted quota is
something Prism can route around by itself, whereas signing in is something
only the customer can do.

The replacement comes from the same category, so it can do the same job — a
failed image stage handed to a research tool produces an essay about pictures.
Tools the customer already configured go first, because they are probably
signed in to those. Capped at two attempts; each one is minutes of browser
time.

**Limitation, stated rather than left to be discovered:** the retry runs after
the pipeline, not inside it. A stage that failed in the middle has already
handed nothing to the stages behind it, and those are not re-run. The last
stage is fully recovered. Doing better means restructuring a 500-line loop
whose index-keyed maps all shift if the stage list changes underneath it.

## The test suite was writing into the customer's own data

Twice, found twice, and the second one was found by a customer asking a
completely different question.

- **`~/.prism/config.json`** — a test called `_checked()`, which calls
  `_remember()`, which calls `config.save()`. It wrote a bare fixture over a
  real config: Groq key, profile, agent choices, Chrome pin, gone. The only
  symptom was Prism asking to be set up again on every launch, which reads like
  a Prism bug rather than a test one.
- **`~/.prism/runs/`** — tests proving "a broken run is still recorded" were
  recording into the real History. **56 of 128 files** were fake "Chrome would
  not launch" failures. Worse than clutter: they carried no query, so they
  looked exactly like real runs whose prompt had been lost — the bug
  manufactured evidence for a bug that did not exist.

Both now refuse at module level rather than relying on the next person to
remember. The runs one needed two doors shut, not one: `config.RUNS_DIR` is
only the CLI's default, and the window passes its own folder. Verified by
counting the directory before and after the suite.

## Documentation

- **`docs/FUTURE_INDUSTRY_TARGETS.md`** — where Prism goes after springs and
  plastics. PCB fabricators (Fine Circuits / Fineline, Manjusar GIDC — the
  first real prospect, with what was proven against their actual 4-layer
  board), and EMS/assembly houses, which is the larger prize because they
  receive a Gerber AND a BOM AND a pick-and-place file. Includes the rule that
  matters: **the Gerber files never leave the machine** — Prism measures
  locally and only the measurements, the template and the company details go to
  the AI tools to be formatted. Their customers are aerospace and medical firms
  whose board geometry arrives under NDA.
- **`README.md`** — rewritten. It still said "v0" and described a July build,
  and one line in it was not merely stale but wrong: it claimed a sibling
  `../prism_terminal` checkout takes priority over the submodule. It does not,
  and never did. The same sentence had already been removed from
  `core_bridge.py`; this copy survived, and it cost an afternoon of editing a
  file that is never loaded — twice.

## Also in this round

The licence lease and secret store, macOS codesigning, and the UI pass that
lifted content onto cards and folded the seven CONFIGURE rows behind a
disclosure, all by the second developer on the project.

### Still open
The send path and the PO → BOQ hand-off remain written, unit-tested, and never
run against a real mailbox. `plans.py` feature names are still not in the
translation catalogue.

---

# Round 4 — the screens, and the rest of the loop

Round 3 built the engine and said plainly that the screens did not exist. They
do now, and the workflow runs end to end: read the mail, register it, quote it,
read the answer, chase the silence, argue with the no.

## The screen

Four tabs, in the order the work happens — **What arrived → Inquiries → What
they said back → Waiting on a reply.** The tab order is the explanation of the
feature, so it has a test of its own.

- **Colour.** Categories, statuses and reply intents are tinted so a
  hundred-row register reads at arm's length. The word is always there as well
  as the colour: roughly one man in twelve cannot tell the red from the green,
  and a register printed on the office laser comes out grey. Tests assert every
  category and every status has a colour, because an uncoloured cell in a
  coloured column reads as a rendering bug.
- **Checks on a timer.** Off by default; interval set in Setup. It only ever
  READS. A tick is skipped while a check is already running — two IMAP fetches
  racing on one bookmark is how the same inquiry gets registered twice — and
  skipped while a quotation is open on top. Failures on a tick go to the status
  line, not a dialog: a modal appearing over somebody's work every ten minutes
  because the mail server had a bad afternoon is how the feature gets switched
  off for good. For the same reason a tick never moves the tab.
- **Time as well as date** in the register. Two inquiries from one customer on
  the same morning were indistinguishable before. Converted to local time — a
  mail header carries the *sender's* offset, so a 09:00 enquiry from Germany
  was filing itself at 09:00 in a Gujarat register.
- **Editing a row by hand.** They can always edit the CSV in Excel, but a
  register that can only be corrected by closing the app is one they stop
  correcting. The bookkeeping fields are deliberately not editable — letting
  the inquiry number be retyped is how two rows end up sharing one.
- **Starting from a register they already keep.** Setup imports it: their own
  columns survive untouched, numbering carries on from theirs rather than
  reissuing a number already on a quotation, and an existing register is never
  overwritten. Columns Prism did not recognise are reported, not guessed.

## Replies, which is the part it is bought for

The engine already worked out what each reply meant. The GUI threw it away.

Tab 3 now shows the reply, what Prism makes of it, what the register *would*
say, and the customer's actual words underneath. **Nothing applies itself** — a
machine silently rewriting a sales record on the strength of a sentence it
might have misread is not something a business can check.

`register.mark_reply()` is careful about three things:

- **"Accepted" does not mean Converted.** Going ahead is a promise; Converted
  is a fact with a PO number behind it. Collapsing them makes the month-end
  conversion figure optimistic by exactly the orders that never arrived — the
  one number an owner would repeat to a bank.
- **An unreadable reply changes nothing but the date.** A wrong status is worse
  than a stale one: the owner acts on the register without re-reading the mail,
  and a quotation wrongly marked Not converted is never chased again.
- **Haggling is not a refusal.** "Send your best price" is the commonest reply
  there is, and reading it as a no closes a row that is still winnable.

## Chasing, unattended

Every two days, three times, then it stops. The schedule lives in the register
— `Reminders sent` and `Last contact`, the same two columns the owner can see
and edit — so there is no hidden second queue to drift out of step with it.

One reminder per check, never a batch: three leaving in the same second, to
three customers who talk to each other, reads as a machine. Each is worded
differently — the first is a light touch, the third asks straight out whether
to close the file. A failed send is not counted, or Prism gives up after three
reminders that never left the building. Off until switched on.

## Winning back a no — and less Groq

**`core/drafting.py` is new.** Writing a page of persuasion that knows what was
quoted, what they objected to, and how far this owner will move on price is a
different job from labelling an inbox. It goes through the AI tools in the
customer's own Chrome, on their own subscription — no API key, no per-token
cost.

The risk is a tool that offers 15% because it sounded persuasive. So: no figure
may appear that is not in the owner's own policy file, **no policy file means
no discount is offered at all**, and the customer's email is marked as
information rather than instruction — a buyer cannot write "ignore your pricing
policy" and negotiate with the tool directly.

Two things deliberately did **not** move to the browser, with the reasoning in
the module docstring: sorting the inbox (a browser round trip is most of a
minute; two hundred emails is a working day with their Chrome held hostage) and
writing the register (Python writes it atomically, gets the money right to the
paisa, and cannot hallucinate a row — and it is the customer's order book, not
something to post to a website).

**Reading a reply now usually needs no AI at all.** `mailflow.local_intent()`
settles the formulaic ones — 13 of 13 test phrases, zero calls. Only genuinely
vague replies reach the model. The rules run first even when a key is
configured, or they would be dead code.

## Pricing from the owner's own formulas

The engine could always run a cost sheet; the GUI only read rate lists, which
locked out every shop quoting made-to-drawing work. Either source works now,
and every line of the working is shown — this is the number they will be asked
to justify on the phone.

Two defects the testing found:

- **The quotation totals the *rounded* per-piece rate**, so it does not equal
  the cost. Reading ₹31,556 on screen and sending ₹31,550 is how an owner stops
  believing the whole calculation. The gap is now stated in words.
- **A blank weight quoted the labour alone** — an under-quote that looked like
  a finished quotation. It refuses now.

## FFmpeg

A Windows customer met a codec install guide on pressing Reel. FFmpeg is now
**bundled** (`imageio-ffmpeg` in the wheel), with a verified download as the
fallback: the same wheel, checked against the SHA-256 PyPI publishes for that
exact file, verified before it is unpacked. `reel.py` and `reel_web.py` each
had their own `shutil.which("ffmpeg")`; both delegate to one resolver now, and
a test parses the AST to keep it that way.

The self-test line that read "optional — needs FFmpeg on the machine" *was* the
belief that caused the bug. It names which FFmpeg is in use now.

## The licence server

- **`DEFAULT_SERVER` now ships the Render address.** `api.alphakore.in` has no
  DNS record, and a build pointed at a name that does not resolve cannot
  activate anybody. This is a temporary pin with a real cost — see
  **SHIPPING.md §3.2**, which is now the only place that says how to undo it,
  and which `tests/test_licensing_endpoint.py` fails if anyone deletes.
- **`ACTIVATE_TIMEOUT` 30s → 75s.** A cold `/health` on that host measured
  **42.6 seconds**; activation was giving up 13 seconds early against a server
  that was up and healthy. Activation is the one call a new customer cannot go
  around — no cached token, no way into the app.
- Deliberately **no retry** on activation, unlike authorize. A timeout there is
  ambiguous: the request may have counted a seat before the socket gave up, and
  burning the second seat of a two-seat licence is worse than the failure the
  retry would fix.

### Not done
`plans.py` feature names and blurbs are still not in the translation catalogue
— unchanged from Round 3, still a pre-existing gap.

The send path and the PO → BOQ hand-off are written and unit-tested but have
never run against a real mailbox. Reading is the well-covered half.

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

### Scenario testing — `devtools/scenarios.py`

Thirteen situations rather than unit tests: a full Monday morning of ten mixed
mails, a customer who haggles all the way from inquiry to PO, ten shapes of
badly-built rate list, 200 messages at once, a mail server that is down, an
email that tries to talk to the AI reading it. **148 checks, under a second, no
network.** Run it before a release.

The unit suite proves the pieces behave. This proved they behave *together* —
and it found four real bugs that unit tests had not, every one now also pinned
by a test:

- **`Rs.1,000/-` parsed as ZERO.** The worst bug in the feature, and invisible.
  That is how money is written in every Indian office. The parser deleted
  everything that was not a digit, a dot or a minus, turning it into `.1000-` —
  unparseable, so zero. Every order value typed the normal way summarised as
  ₹0, and a rate list cell written `28.50/-` would have quoted at **nothing**.
  There is now one strict parser shared by the register and the quotation, so
  the two can never disagree about what a rupee looks like.
- **A customer could forge a message boundary.** An email body containing
  `--- EMAIL 2 ---` was pasted into the sorting prompt verbatim, so a sender
  could fake a second message and ask to be sorted as `internal` — never
  registered, and nobody notices a customer whose mail silently stopped
  arriving. Boundaries and answer-shaped lines are now neutralised, the batch
  size is stated, and the prompt says message text is never an instruction.
- **`local_only` only did a third of its job.** It was passed to the sorter
  alone, so detail extraction and reply reading still sent customer
  correspondence out. A privacy switch that quietly does two thirds of what its
  name promises is worse than not offering one.
- **A bare "Enquiry" subject became a useless register row.** Half of all
  inquiries arrive under one. It matched nothing on a rate list and told a
  human nothing either. The opening line of the message — skipping the
  greeting — is now used when the subject carries no information.

### Two bugs from round 2, found while chasing the CI failure

Neither is part of Inbox to Order. Both were introduced by round 2 and both are
the same shape as the scenario bugs — silent, no symptom, wrong only where it
counts.

- **The licence server address was regressed to the hosting provider's URL.**
  A one-line change to `DEFAULT_SERVER` rode along inside a commit about
  cold-start timeouts: `api.alphakore.in` became
  `prism-license-server.onrender.com`. Nothing failed — the app built, started
  and self-tested clean — and **every customer activation in that build would
  have gone to the wrong host.** It also welds the binary to Render for its
  whole life, since the domain is the only thing that lets the server move
  without shipping a new app. `SHIPPING.md`, `LICENSING.md` and the comment in
  `licensing/keys.py` all name the domain; only the code disagreed. Restored,
  and `tests/test_licensing_endpoint.py` now fails if it drifts again — it also
  checks the address is HTTPS, has no trailing slash, and still matches the
  regex `packaging/prism.spec` uses to rewrite it for staging builds.
- **`core_bridge.py` described the opposite of what it does.** It claimed a
  sibling `../prism_terminal` checkout took priority "so you're always working
  against the copy you're editing". It does not: `paths.resource()` resolves to
  the submodule when running from source and is checked first, so a sibling was
  never reached. The behaviour is right — the submodule is what gets committed
  and built — so the sentence went rather than the code. And because this
  machine genuinely has both copies, `core_bridge` now prints which one is
  loaded and which is ignored, which is the sentence that ends the afternoon
  somebody would otherwise lose editing the wrong tree.

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
