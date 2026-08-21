# After the merge

**Work that is decided, understood, and blocked only on pulling the GUI
changes.** Not a wish list — everything here has been argued through and is
waiting on one thing: a colleague is editing `prism_gui`, so the engine moves
and the window does not.

This is different from `DEFERRED.md`, which holds work that is *not worth
building yet* and carries a trigger. Everything here is worth building now.

**Rules for this file**
- An entry leaves only when it is done or deliberately killed — say which.
- Every entry names the file it touches, so the work starts without a hunt.
- Record the *reasoning*, not just the task. In six weeks the task will be
  obvious and the reasoning will not.
- Update it in the conversation where the decision is made, not later.

**Last updated:** 2026-08-20

---

## 1. The Gerber add-on needs its window

**Engine: DONE** — `prism_terminal/core/gerber.py`, `/gerber` in `prism.py`,
commit `7cef5c4`. 26 tests in `prism_gui/tests/test_gerber.py`, commit
`d3263e1`. Neither pushed at time of writing.

**GUI: not started.** Today the only way in is the terminal.

**What it should be:** its own item beside BOQ, reusing BOQ's drop-a-file
shape. Drop a folder, `.zip` or `.rar` — never individual files, because a job
arrives as one archive of 9 to 17 files and asking a customer to pick the right
four is the whole problem restated. It shows four panels, exactly as the
terminal does: what is in the job, the five numbers, the workings, and the
cross-check.

**The five numbers Fine Circuits asked for**, and nothing else:
pcb size · min track width · min track spacing · min drill size · number of
drills.

**The rule that must not be broken:** the Gerber files never reach an AI.
`cmd_gerber` passes `attachments=[]` and a test asserts that literal string.
The GUI must do the same. See `docs/FUTURE_INDUSTRY_TARGETS.md` §"The rule that
must not be broken".

**Needs `pip install shapely`** — without it four of five numbers still work,
and the missing one says so.

---

## 2. The Gerber verification ladder

Four ways to check the numbers, cheapest first. Steps 1 and 2 exist; 3 and 4
are the plan for when a job defeats us.

1. **The job's own CAM report** — `crosscheck()` already parses `.DRR`/`.REP`
   and compares hole counts and tool tables. Free, exact, no AI. The 2018
   sample reproduces all ten tools and 218 holes.
2. **A second independent implementation** — `gerbonara` (pip, pure Python,
   test-only, not a runtime dependency). Comparing per-layer object counts is
   what found both parser bugs on 2026-08-19; all 19 layers of both samples now
   match exactly. Pinned by a skipping test. **Reach for this before any AI.**
3. **AI sanity-check on a RENDERED IMAGE plus the numbers** — not built. A PNG
   of the copper is not a manufacturable design, so this does not break the
   rule above the way attaching the Gerber would. It cannot see 0.132 mm, but
   it can catch a wrong layer, a size out by 10x, missing holes.
4. **The raw Gerber to an AI — only with the customer's written permission.**
   This is where Gerber differs from BOQ, which *does* attach the drawing
   (`write_files = ([cad_file] if cad_file else []) + templates + note_files`).
   A building drawing is a description of a job. A Gerber set **is** the
   customer's product. Do not copy the BOQ pattern across without asking.

**Why this is written down:** on 2026-08-19 an independent measurement found
two real defects — modal D-codes and sequential polarity — that code review and
900 passing tests had missed. Both produced *plausible* wrong numbers with no
error and no crash. One meant Prism had read 158 of a layer's 470 objects and
reported a clearance anyway.

---

## 3. Untested Gerber constructs

Neither sample contains these, so nothing proves they work. Prism warns when it
meets them; a warning is not a guarantee.

- **Arcs** (`G02`/`G03`) — zero in both jobs. Implemented, never exercised on
  real data.
- **Aperture macros** (`%AM`) on a copper layer — present only on the 2018
  job's drawing layers. Macro flashes are counted but given no geometry, so
  they take no part in spacing.
- **Step-and-repeat** (`%SR`) panelisation — detected and reported, not
  expanded.
- **Negative inner planes**, where the plane layer is drawn inverted.

**The contact has said the two samples are deliberately simple and that complex
files will follow.** Run steps 1 and 2 of the ladder on every one of them.

---

## 4. The reel look is now the house style

`~/Desktop/studio_pcb.mp4` (18 Aug 03:31, 26.7 s, 1080x1920) is the standard to
hold every future reel against. Dark, terminal-styled, and built from the
customer's own material: a real file listing, 238 holes drawn as 238 dots, the
board drawn with dimension lines, a two-column panel contrasting what stays on
the machine with what the AI ever sees.

**Wanted:** that adaptiveness for *any* sector, not just PCB. The scene-at-a-
time pipeline in `reel_web.py` already asks for it — "build it from the
customer's own material, not from adjectives" — but nothing verifies it
happened.

**Also wanted: hooks.** A reel without one is never watched to the end, so the
opening ~1.5 seconds is not a title card — it is the whole bet. Nothing in
`design_instructions()` or `scene_instructions()` currently treats scene 1
differently from scene 4. That is the gap.

**Fix the invented numbers first.** `studio_pcb.mp4` claims 238 holes,
125.93 x 76.40 mm and 0.152 mm — the AI made all three up, because the reader
did not exist when the script was written. The real board reads 218 holes,
90.17 x 90.17 mm, 0.203 mm, 4 layers, confirmed against the customer's own CAM
report. Re-render those scenes; the spec is saved beside the video.

---

## 5. Two copies of prism_terminal on the dev machine

`prism-ai-flow/prism_terminal` (standalone, on `main`, **36 commits behind**)
and `prism-ai-flow/prism_gui/prism_terminal` (the submodule, current). Same
GitHub repo, two checkouts.

This already cost an afternoon: `/gerber` was run in the stale copy and
reported "Unknown command". **Decide one way or the other** — delete the outer
one, or pull it after every push. Two checkouts of one repo is a trap, not a
convenience.

---

## 6. Validated by the customer — and what they said next

**2026-08-20.** Fine Circuits sent back their own filled-in check sheet for
both sample jobs and Prism reconciles with it: size, track width, min drill
and hole count exact on both boards, spacing within a mil. Asked about the
one-mil difference their reply was *"if its 9 or 10 it means its working"* —
so the reader is confirmed against a real customer's own figures.

Two things that reply told us, both worth acting on:

- **The sheet was filled in by someone else** while the contact was busy. It
  is a good witness, not a precise one. Prism's figure is arguably tighter
  than theirs, and the one-mil gap is design rule versus measured worst case
  (102 places on the 2018 board sit at 9 mil).

- **"We just do DRC."** They run a Design Rule Check, which means a tool
  already produces these numbers and the hand measuring is a side task. ASK
  FOR A DRC OUTPUT: it is machine-generated, free, and a far better witness
  than a spreadsheet — the same role the `.DRR` played. It may also mean the
  five numbers are not the product and the DRC is. Worth finding out before
  building the window.

---

## 7. Where the Gerber add-on actually goes — the whole enquiry

**The gap, stated plainly.** Genesis 2000, InCAM, CAM350 and UcamX are real,
mature, and our contact almost certainly runs one — his DRC comes from
somewhere. They do more than Prism does and always will. What they do NOT do
is anything either side of the measurement, and they need a trained CAM
engineer sitting at them. Asked what takes longest, he said "actually whole
process".

**An incoming job, end to end:**

```
1. Email/WhatsApp lands with a zip        Prism — Inquiry Automation (built)
2. Identify layers, measure the board     Prism — core/gerber.py    (built)
3. Can we make it? What is at our limit?  NOT BUILT
4. How many boards fit our panel?         NOT BUILT
5. Cost it — laminate, layers, finish     NOT BUILT
6. Write the quote                        Prism — drafting          (built)
7. Send it                                Prism — mailer            (built)
8. Chase it at 2 days                     Prism — mailflow          (built)
```

**CAM software owns step 2 alone.** We now own 1, 2, 6, 7, 8. Steps 3-5 are
the whole remaining product, and none of them need to touch a Gerber.

**Each step goes to the tool that is best at it — that is the Prism part.**

- **3 — the thinking tool.** Measured numbers plus the fab's own capability
  sheet: "you quote to 4 mil, this needs 5, fine; the 0.15 mm drill is at
  your limit, flag it." It sees numbers, never the design.
- **4 — code, not an AI.** Panel utilisation is geometry, the same argument
  as measuring. An LLM estimating how many boards fit a 18x24 panel is the
  BOQ mistake again.
- **5 — the research tool.** Laminate and finish prices THIS WEEK, from the
  web, not a rate card from two years ago.
- **6 — the writing tool**, in his format and his voice.

One tool doing all four would be worse at all four, and that is exactly what
every competing automation is.

**Why a fabricator can say yes at all:** it runs on his own logged-in
accounts — his ChatGPT, his Claude, his Chrome — so no API bills and no new
subscriptions, and the customer's design never leaves his machine. That is
not a feature bolted on; it is the precondition for letting any of this near
his clients' work. See [[gerber-addon-security-constraint]].

**The sentence:** *CAM tells you what the board is. Prism tells you what to
charge for it, writes the quote, sends it, and chases it — using the AI
subscriptions you already pay for, without your customer's design ever
leaving your computer.*

**Ask him before building 3-5:** what does his capability sheet look like,
what panel sizes does he run, and what does he actually cost a job on. All
three are inputs we do not have.

---

## 8. What the customer has to hand over before any of this runs

Everything past the measurement needs something only the fab can give us, and
the amount asked for is the thing most likely to kill the sale. A fabricator
will type in one page. He will not type in eight, and he will not hand over
his mail password on day one to a supplier he met last month.

So the setup is staged, and **each stage has to be worth something on its
own** — if he stops after stage one he must still have got value.

### Stage 1 — one page, and the product works

| What | Why | Risk |
|---|---|---|
| **Capability sheet** — thinnest track, tightest gap, smallest drill, layer count, finishes, panel sizes | Turns five measured numbers into "yes we can make this, and the 0.15 mm drill is at our limit" | Low. He has this already; it is what he quotes against. |

That is the whole of stage 1. One document, and the output goes from a
measurement to a decision.

### Stage 2 — the quote, once stage 1 has earned trust

| What | Why | Risk |
|---|---|---|
| **How he prices** — per layer, per area, per hole, per finish, setup charge, minimum order | Nothing can cost a job without it | Medium. This is his margin. He will not share it until stage 1 has proved useful. |
| **A sample quote he has sent** | Format, wording, terms, his own voice | Low, and it is worth more than any template we could write |
| **Company details** — letterhead, GST, bank, terms | Goes on the document | Low |

### Stage 3 — sending, only if he wants it

| What | Why | Risk |
|---|---|---|
| **Sending account** (SMTP or whatever he uses) | To send and to chase | **High.** Credentials. Last thing asked for, never the first. |

### The assumption to NOT make

**Not every job arrives by email.** The window fabricators showed this: WhatsApp
photos, a phone call, a worker's notebook. A PCB fab may take jobs through a
customer portal, a shared drive, a WhatsApp group, or an ERP nobody outside
the company has heard of.

So the add-on must work from **a folder on his machine**, full stop. If a zip
lands there by any means, it is measured. Email ingestion is one route in, not
the route in — Inquiry Automation already reads mail for the fabs that use it,
and everyone else drops a folder.

---

## 9. The realistic first build — and what NOT to build

Trying for the whole eight-step pipeline gets none of it right. The three
unbuilt steps are not equal, and only one of them is safe to do now.

### Build: the capability check (step 3)

**Input:** the measured numbers + his one-page capability sheet.
**Output:** can we make it, what is at our limit, what needs a decision.
**Why it is the right first move:** one document from him, no pricing, no
credentials, no assumption about how the job arrived. And it is the step that
turns Prism from "a thing that reads Gerbers" into "a thing that answers the
question I actually have".

### Do NOT build yet: panel utilisation (step 4)

Needs his panel sizes, his edge rails, his scoring rules and his tooling
margins. It is real geometry — CODE, not an AI, the same argument as
measuring — but it is a week of work and it is wrong in a way he will spot
instantly if any of those inputs are guessed. **Wait until he asks for it.**

### Do NOT build yet: costing (step 5)

Needs his entire rate structure, which is his margin. Asking for it early
reads as asking for his books. **Wait until stage 1 has earned it.**

### Do NOT build yet: sending

He has not said he wants Prism touching his mail, and credentials are the
highest-friction thing on the list.

**The rule:** each move must be finishable, checkable against a real job, and
useful on its own. One step at a time, in the order he will actually say yes
to.

---

## Sales questions open

- **Agencies or their clients?** Undecided — see the reasoning in the
  conversation of 2026-08-20 and `docs/FUTURE_INDUSTRY_TARGETS.md` §5.
- **Ask Fine Circuits for the values behind the ticks.** Their check list
  records "Verify drill detail information — ok" without recording *what* the
  detail was. Min track width and min track spacing have no witness on either
  sample. One job with their CAM operator's own figures closes that for good.
