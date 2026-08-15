# What changed

Written for the person who has to pick this up later — each entry says what it
was, what it is now, and why the change was made, because the "why" is the
part that gets lost.

Tests: **727 passing**, plus 148 scenario checks (`devtools/scenarios.py`).

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
