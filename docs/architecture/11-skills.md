# Skills — the doctrine layer

**Answers:** where Prism keeps what it knows about *what a good result looks
like*, how that reaches a tool, and how an answer is checked against it.

---

## The problem this solves

Prism knew a great deal about its trade. A bill of materials needs a grade
and a recognised section designation. A cold email is under 120 words. A
slide title is a claim, not a topic. A mushroom-head emergency stop is about
40 mm across, not 250.

All of it lived inside Python f-strings — roughly 1,300 lines of expert
instruction spread across eighteen modules, plus another 700 in Motion and
Studio. Three consequences followed:

1. **Changing a rule of thumb meant a release.** A customer who knew better
   than the shipped doctrine had nowhere to put that.
2. **Almost none of it was enforced.** `bom.py` asked, in prose, for
   dimensionally plausible sizes. Nothing looked at the answer.
3. **Prism had no standards of its own to add.** Until 1.5.7 the planner
   improvised a role, a spec and a quality bar for every step. From 1.5.7 it
   writes a short brief and Prism adds the rest, but for most kinds of work
   there was nothing written down for Prism to add.

A skill is that knowledge as a file: shipped with the app, overridable by the
customer, listed to the router so it can choose rather than invent, and
paired with a check the run can act on.

---

## The shape

```
prism_terminal/skills/<key>/
    SKILL.md      frontmatter (what it is for) + the doctrine
    checks.py     optional  faults(text, context) -> list[str]
    examples/     optional  golden outputs the doctrine points at
    references/   optional  long material for people; never typed
```

`core/skills.py` is the only module that knows this format. The frontmatter
fields and how to write a body are documented in
`prism_terminal/skills/README.md`, beside the skills themselves, because
that is what a person adding one has open.

---

## The two ways in

### Routed — a pipeline stage

1. `router._stage_lines` names each stage's skills, by key only, in the
   stage table the planner reads. Each skill's one-line description is
   printed once, inside the SKILLS rule, however many stages share it.
2. `router._schema_stub` adds a `"skills": []` key to that stage's slot —
   only for stages that have any.
3. `router._skills_rule`, a bullet under WHAT TO WRITE FOR EACH STEP, asks
   the planner to *name* at most two and not to restate them in the brief,
   because Prism types the skill's own standards after it.
4. `router.route` calls `skills.assign`, which validates the picks against
   what actually exists for that stage, and — where the planner chose none
   and the stage is running — falls back to `triggers:` matched against the
   **person's own words**. Same backstop shape as the make-stage guardrail,
   for the same reason: a planner paraphrasing a brief must not be the only
   thing deciding.

   The fallback attaches **one** skill, where an explicit pick may name two.
   A planner naming two has reasoned about whether they sit together; a
   trigger match has not, and "a pitch deck, and a one-pager pdf brochure"
   hits both the deck and the document skill. Typing both at one stage asks
   for a deck laid out in pages, then faults it for not being one — the
   stage's single re-ask spent on a contradiction Prism created itself.

   Which one: **earliest mention wins**, then the number of matching words.
   Ranking on the count first rewards whichever skill happens to list more
   synonyms, which is an accident of how its triggers were written rather
   than a signal about this request. At the same position the longer
   phrase wins, so the documentation skill's "document the" beats the
   document skill's bare "document".
5. `automation.run` reads the settled keys with `skills.keys_for`, and types
   `skills.block(keys)` after the task, next to the stage suffix — with two
   exceptions. A **maker** (Canva, Gamma, v0, the video tools), or any tool on the
   presentation stage, is given the
   standards without the `Shape`, `Non-goals` and `Example` sections: those
   lay out a text answer and tell a text stage to leave the building to a
   later step, so typed to a maker they say "do not build it". A
   **machine-read stage** (the Studio script, the design turn, a Motion
   storyboard) is given nothing, because it must reply with only a JSON
   object and a second author of format rules makes the model drop the JSON.

### Feature — an add-on's own prompt

An add-on builds its own prompt and appends `skills.addendum("<feature>")`.
Wired today:

| Feature key | Builder |
|---|---|
| `boq.standards`, `boq.interpret`, `boq.format` | `core/boq.py` |
| `bom.standards`, `bom.format` | `core/bom.py` |
| `inquiry.negotiation`, `inquiry.followup` | `core/drafting.py` |
| `gerber.writeup` | `core/gerber.py` |
| `gerber.form` | `core/gerber_form.py` |
| `step.ask`, `step.plan`, `step.auto` | `core/stepfile.py` |
| `email.blast` | `core/mailer.py` — the hook only. No shipped skill claims it: a blast is as often a price update to existing customers as a first email to a stranger, and cold-outreach doctrine would cut the update to 120 words |
| `leads.reach` | `prospector/reach.py`, through `core_bridge.skills` |

A caller that builds its own stages passes `stage_skills={label: [key]}` to
`automation.run` (through `AutomationWorker` from the GUI) so the check runs
for those stages too. Two do today: the BOQ and BOM **format** stage, and the
inquiry **negotiation** draft through `drafting.draft`.

**`addendum` returns `""` when no skill claims the feature.** That is the
rule the whole design rests on: a prompt with no skill is byte-identical to
what it was before skills existed. Doctrine is added by a file appearing,
never by the mechanism being present.

---

## The check

`skills.check(keys, text, context)` runs every claimed skill's `faults()`
over the stage's captured answer.

When it finds anything, `automation.run` sends the faults back in the same
chat — one re-ask, via `_reask` — and keeps the second answer **only if it
has fewer faults**. That is the same shape as the reel spec lint, and the
reason is the same: a "fix" that trades six faults for seven is not a fix.

Rules the checkers hold to:

- A checker returns plain sentences. It may find nothing. It may never
  raise — one that does is reported and skipped, never costing a run.
- It runs on prose scraped from a browser, so it tolerates junk and returns
  `[]` for an empty answer.
- It is never run on a machine-read stage (`machine_shaped`). A JSON scene
  spec has its own lint, and a prose checker over it would report a fault on
  every line and burn the one re-ask.
- It is never run on a maker, or on the presentation stage whichever tool
  runs it. What it built is the deliverable; what comes
  back in the chat is "done", and faulting that line would spend the re-ask
  telling Canva to type the deck out.
- It is handed the prompt the tool was shown, minus the skill's own text, as
  `context["prompt"]`. A figure counts as invented only when it appears
  nowhere in there, so a price from the quotation passes and a discount from
  nowhere does not.
- It is never run on a reply that shows a built file: a file card, or only
  Claude's sandbox log ("Read 11 files, ran 11 commands"). On the owner's own
  document run Claude built the DOCX itself and the chat showed its card;
  judged as text, that card would have spent the re-ask asking Claude to
  paste the document instead.

Nine of the twelve shipped skills have one. Each has a known-good and a
known-bad sample in `tests/skill_samples/`, in two shapes: as a model writes
it, and as Prism captures it after the chat renders it. The good one must
pass clean and the bad one must be caught in both, so a rule that is too
tight fails the suite rather than quietly costing every run a re-ask. Where
the owner's own runs hold a real reply of that kind, it is kept there too,
with client names removed.

---

## What a checker reads

Not markdown. `automation._capture` takes Selenium's element text of the chat
page, so a checker reads the answer as displayed. Across the owner's 93 saved
replies there were no table pipes and no bold markers. Headings arrive as
bare short lines, list items lose their bullets and numbers, table cells are
joined by single spaces, and a citation is a bare site name on the line under
the claim.

The first checkers were written for markdown. Replayed over those runs, the
research checker called 121 sourced figures unsourced and missed a heading
named "Executive Summary", and the parts-list checker rejected every real
parts list as "not a table". They were rewritten against the captured shape,
using helpers in `core/skills.py` that read both shapes, and
`devtools/capture_skill_samples.py` renders the test samples in real Chrome so
the tests see what the engine sees.

---

## What has no skill, on purpose

**Reels.** The Studio script step and the design turn already carry their own
rules and a strict JSON format, and the script rules say "say nothing about
how it should look". The scene skill is about exactly that, so typed there it
would be a second, contradicting rulebook. Reel quality is a matter for those
built-in prompts, which the prompt audit of 2026-09-11 covers.

---

## What it costs

Measured on the owner's own configuration on 2026-09-11, with the 1.5.8 planner:

| | characters |
|---|---|
| Planner prompt without skills | 13,095 |
| Planner prompt with skills | 14,959 |
| One skill typed to a text tool | 2,900 – 3,600 |
| One skill typed to a maker | 2,100 – 2,700 |
| One trade skill appended to an add-on prompt | 3,300 – 4,000 |

The prompt audit of the same day
(`prism+gui/artifacts/prompt-pipeline-and-deliverables-2026-09-11.html`)
proposes a planner prompt of about 4,000 characters and a whole chat message
under 2,500. A skill's own text is longer than that second target by itself.
That is a deliberate trade — standards written once and checked, in place of
rules the planner improvises and nothing checks — but it is a trade, and the
levers are each skill's `budget:` and the length of its body.

---

## Beside the deliverable contract

Every step has a kind — text, file, image, video, data or links — and
`core/contract.py` checks that the deliverable exists, re-asking once when it
does not. A skill sits beside that, and between them a step is asked again
at most once:

- a **text** step gets the whole skill, and its checker;
- a **file, image or video** step, a maker, or the presentation stage gets
  the standards without the text layout, and no checker: the contract judges
  it by whether the thing exists;
- a **data** or **links** step, and any step a program reads, gets nothing;
- the checker runs only when the contract found nothing missing.

---

## Overriding, and the one thing an override may not do

```
~/.prism/skills/<key>/SKILL.md    replaces the shipped doctrine
~/.prism/skills/<key>/notes.md    appended to it as FIELD NOTES
~/.prism/skills/<new-key>/        a skill of the customer's own
```

An override may leave the frontmatter out and just write doctrine; the
shipped routing stays in force.

**`checks.py` is loaded only from the shipped folder.** A skill file may
change what a tool is told. It may not run code on the customer's machine.
The same reasoning that keeps engine sources out of a build applies here,
and it is what makes serving skills from the licence server safe later.

---

## Budgets

Browser tools take one blob of text, and a long prompt types slowly and
crowds out the person's own request. Over `browser` transport a body is cut
at its `budget:`, at a paragraph boundary, with headings counted against a
`TOTAL_BUDGET` of 6,000 characters for the stage. Direct API calls
(`transport: [api]`) get the whole body.

A guard test asserts every shipped body fits its own budget, because what
gets cut first is the quality checklist at the end — the half the typed
preamble promises the tool it will be judged against.

---

## Packaging

`packaging/prism.spec` excludes `skills/` from the generic engine-data walk
and ships the tree with its own entry, **including the `.py` files**. That
loop drops every `.py` as code, which is right for engine sources — shipping
them was a licence bypass — and wrong for a `checks.py`, which nothing
imports and `core/skills.py` reads from its path. Without the exception the
app ships doctrine with nothing enforcing it, and only a customer would ever
find out.

---

## Boundaries

- `core/skills.py` imports `config` and `ui` and nothing else from the
  engine. Every feature module imports *it*, never the reverse.
- The GUI reaches it through `core_bridge.skills`, like every other engine
  module (rule 3 in `CONTRIBUTING.md`).
- A skill folder is data. Adding one touches no shared file — the same
  property that makes an add-on one folder and one line.

---

## Seeing what applies

`/skills` in the terminal lists every skill, where it applies, whether it is
checked, whether it is overridden, and the two folders. A planned run prints
the skills attached to each stage before it starts, and again as each stage
types them.
