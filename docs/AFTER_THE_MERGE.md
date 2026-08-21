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

## Sales questions open

- **Agencies or their clients?** Undecided — see the reasoning in the
  conversation of 2026-08-20 and `docs/FUTURE_INDUSTRY_TARGETS.md` §5.
- **Ask Fine Circuits for the values behind the ticks.** Their check list
  records "Verify drill detail information — ok" without recording *what* the
  detail was. Min track width and min track spacing have no witness on either
  sample. One job with their CAM operator's own figures closes that for good.
