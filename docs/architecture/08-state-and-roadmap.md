# 8 · System State & Roadmap Map

[← Operations](07-operations.md) · [Index](README.md)

---

**This document is the PM's control panel.** It says what exists, how well it is
proven, what is decided-but-blocked, and what is deliberately not built and why.

It does not *replace* `docs/DEFERRED.md` and `docs/AFTER_THE_MERGE.md` — those
are the working files where decisions get made. **This is the index across
them**, so you can see the whole board at once.

**Snapshot:** 2026-08-26 · commit `20292f4` · version `1.3.0` · 74,259 lines of
Python · 1,203 tests + 148 scenarios.

---

## 8.1 The maturity board

Rated on two independent axes, because they fail differently:

- **Built** — does the code exist and pass tests?
- **Proven** — has it run against real customer data, and did a customer confirm the output?

| Capability | Built | Proven | Notes |
|---|:---:|:---:|---|
| **Main task pipeline** (route → plan → run) | ✅ | ✅ | The general-purpose product |
| **Licensing & authorisation** | ✅ | ✅ | Committed test vector, 777-line auth test file |
| **Email automation — reading** | ✅ | ✅ | Fetch, sort, register, file attachments. The well-covered half |
| **Email automation — sending** | ✅ | ❌ | **Never run against a real mailbox** |
| **Email automation — PO screen** | ✅ | ❌ | **Never run against a real mailbox** |
| **Multi-mailbox walk** | ✅ | ⚠️ | Built and tested; office-scale customer had not yet run it at time of writing |
| **Quotation from rate list / cost sheet** | ✅ | ⚠️ | Arithmetic is exact and tested; not yet validated against a customer's own sent quotes |
| **Gerber engine** | ✅ | ✅ | **Reconciled against Fine Circuits' own filled-in check sheet** on both sample jobs |
| **Gerber GUI** | ✅ | ⚠️ | Window built; needs real customer archives |
| **BOQ** | ✅ | ⚠️ | Geometry sound; `.dwg` needs a local converter |
| **Email blast** | ✅ | ✅ | |
| **Reel** | ✅ | ✅ | |
| **Studio** | ✅ | ⚠️ | House style set; **invented numbers in the reference reel still to fix** |
| **Voice / push-to-talk** | ✅ | ✅ | |
| **Wake word** | ⚠️ | ❌ | Best-effort polling loop, **not** a real engine |
| **NotebookLM automation** | ⚠️ | ❌ | Best-effort, unverified against a live session |
| **Teams / shared workspace** | ✅ | ⚠️ | One-writer rule holds |
| **Localisation (hi, gu)** | ✅ | ⚠️ | `plans.py` strings not in the catalogue |
| **BOM & Stock** | ❌ | ❌ | Shelf placeholder, disabled on purpose |
| **PCB capability check (step 3)** | ❌ | ❌ | **The recommended next build** |
| **Panel utilisation (step 4)** | ❌ | ❌ | Wait until asked |
| **PCB costing (step 5)** | ❌ | ❌ | Wait until stage 1 has earned it |

---

## 8.2 The three lists, and the difference between them

This is the discipline the repo already runs on. Keep it.

| File | Holds | An entry leaves when |
|---|---|---|
| `docs/AFTER_THE_MERGE.md` | **Decided, understood, blocked only on a merge.** Everything here is worth building *now* | It is done, or deliberately killed — **say which** |
| `docs/DEFERRED.md` | **Deliberately not built yet.** Every entry carries a **trigger**: the observable thing that turns it from an idea into a job | Its trigger fires |
| `docs/FUTURE_INDUSTRY_TARGETS.md` | Which industries next, and the hard rules per industry | A target is entered or abandoned |

### The rules that make these files work

From `AFTER_THE_MERGE.md`, and worth restating because they are the reason the
files are still readable:

- **An entry leaves only when it is done or deliberately killed — say which.**
- **Every entry names the file it touches**, so the work starts without a hunt.
- **Record the *reasoning*, not just the task.** In six weeks the task will be
  obvious and the reasoning will not.
- **Update it in the conversation where the decision is made, not later.**

And from `DEFERRED.md`:

> A list of "nice to have someday" rots — nobody reads it, and six months later
> nobody remembers whether an entry was a plan or a passing thought. **So every
> entry carries a trigger. If the trigger has not happened, the entry is doing
> its job by sitting here.**

> **Add an entry when you consciously choose the smaller version of something.**
> The comment in the code should point here; this file should point back at the
> code.

---

## 8.3 Deferred work — the trigger board

Every open entry in `docs/DEFERRED.md`, with the observable event that would
start it. **This is the table to review at a regular interval.**

| # | Deferred | Trigger | Size |
|---|---|---|---|
| 1 | **Several machines writing one register** | A customer whose salespeople refuse to put mailbox passwords on the shared office PC — **heard from two firms, not one** | Days. Per-machine append journals, merged by whichever Prism reads next. **The migration must be invisible** |
| 2 | **OCR for scanned POs** | Scanned POs above ~half a real customer's **measured** volume — counted from their own register, not guessed in a meeting — **AND** the customer saying the typing is what stops them using the tab | — |
| 3 | **Storyboard is advice, not a contract** | A reel where every scene lays out clean and the film **still reads as a deck**. That is now the only failure mode left in this stage, so watch for it specifically | Same shape as the layout check that already works |
| 4 | **Design stage takes minutes** | A customer complaining about the wait, **or** a reel long enough (10+ scenes) that the sequence outlives the model's context | — |
| 5 | **Reel motion — carriers across the cut** | The seam check working reliably first. Asking a model to author a matched element into two separate scene blocks is a lot while the simpler laws are still missed | A week or more, and worth it only for customers who care |
| 6 | **Agent failover inside the pipeline** | A customer **losing real work to a MIDDLE stage failing** | Genuine surgery on the riskiest function in the codebase — a 500-line loop whose index-keyed maps (`machine_stages`, `spec_feeder`, `design_feeder`) all shift if the stage list changes underneath it |
| 7 | **Gerber reading — its own add-on** | Two or three real customer zips from Fine Circuits, ideally from different design tools and **ideally one with no `.gbrjob`**. The reader has been tested on exactly one clean KiCad export, and **the fallback path — the one that matters — has never run** | — |
| 8 | **The test that hangs** | **Already overdue.** The fix is to stub the licence call the way the other window tests do | Small |
| 9 | **Translation catalogue** (`plans.py` strings) | — | Small |

**Marked closed, but unverified:** *Reel motion — check the seams* is recorded
in `docs/DEFERRED.md` as **DONE**, via a `motion_faults()` that checks the two
measurable faults.

> ⚠️ **Discrepancy found while writing these docs.** `motion_faults` does not
> exist anywhere in `prism_terminal/core/` at the currently pinned submodule
> commit — the nearest real function is `brand_faults()` (`reel_web.py:373`).
> Either the work landed in `prism_terminal` upstream and the submodule pin here
> is behind it, or the entry was written ahead of the code. **This is the exact
> failure mode `AFTER_THE_MERGE.md` exists to catch** (the engine moves and the
> window does not). See §8.7 debt #10.

---

## 8.4 Decided and waiting — `docs/AFTER_THE_MERGE.md`

| # | Item | State |
|---|---|---|
| 1 | Gerber add-on needs its window | Engine **done**; window built since |
| 2 | The Gerber verification ladder | Steps 1–2 built; 3–4 are the plan for when a job defeats us |
| 3 | Untested Gerber constructs | Arcs, aperture macros, step-and-repeat, negative planes — **warned about, not guaranteed** |
| 4 | The reel look is the house style | Standard set; **invented numbers to re-render first** |
| 5 | Two copies of `prism_terminal` on the dev machine | **Decide one way or the other.** Two checkouts of one repo is a trap, not a convenience |
| 6 | Validated by the customer | Done — and it produced the DRC question below |
| 7 | Where the Gerber add-on actually goes | The eight-step map. **Steps 3–5 are the whole remaining product** |
| 8 | What the customer must hand over | The three-stage ask, each stage worth something on its own |
| 9 | The realistic first build | **Build the capability check. Do not build panel utilisation, costing or sending yet** |

---

## 8.5 The open questions worth answering next

These are not tasks. They are things you do not know, where the answer changes
what gets built.

| # | Question | Why it matters | Who can answer |
|---|---|---|---|
| 1 | **Is the DRC the product, not the five numbers?** | The contact said *"we just do DRC"* — a tool already produces these numbers and the hand measuring is a side task. If the DRC is the product, the measurement add-on is a feature of something else | Fine Circuits — **ask for a DRC output**. Machine-generated, free, a far better witness than a spreadsheet |
| 2 | **What does his capability sheet look like?** | It is the entire input to the recommended next build (step 3) | Fine Circuits |
| 3 | **What panel sizes does he run, and what does he cost a job on?** | Inputs to steps 4 and 5 — **do not guess any of them** | Fine Circuits, later stages |
| 4 | **Does the email send path survive a real mailbox?** | The largest verification gap in the product | Any willing existing customer |
| 5 | **How does the office-scale customer actually run the walk?** | The one-writer rule is a design decision that has not met its stress case | The second firm |
| 6 | **What proportion of real POs are scans?** | Trigger #2 needs a measured number from a real register, not an estimate | Existing customer's own register |

---

## 8.6 How to decide what is next — the rules already in play

The repo has an implicit decision doctrine. Written down, it is:

### 1. Each move must be finishable, checkable against a real job, and useful on its own

> *"One step at a time, in the order he will actually say yes."*

### 2. Do not ask for more than the customer will give at that stage

A fabricator will type in one page. He will not type in eight, and he will not
hand over his mail password on day one to a supplier he met last month. So the
setup is staged, and **each stage has to be worth something on its own** — if he
stops after stage one he must still have got value.

### 3. Send each step to the tool that is best at it — that *is* the Prism part

| Step | Tool | Why |
|---|---|---|
| Capability check | The **thinking** tool | Measured numbers + his capability sheet. It sees numbers, never the design |
| Panel utilisation | **Code, not an AI** | Geometry. An LLM estimating how many boards fit an 18×24 panel is the BOQ mistake again |
| Costing | The **research** tool | Laminate and finish prices *this week*, from the web, not a rate card from two years ago |
| Writing the quote | The **writing** tool | In his format and his voice |

> **One tool doing all four would be worse at all four, and that is exactly what
> every competing automation is.**

### 4. Anything that can cost the customer money stops on a click

Not because the software cannot do it — because if Prism mails a wrong rate to a
customer, that is a real loss and it is our fault. **Everything that cannot cost
money if it goes wrong should run by itself.**

### 5. Prefer the honest refusal to the confident guess

`po.looks_scanned()` says "this is a photograph, type four fields" rather than
OCR-ing a rate. Gerber warns about untested constructs rather than reporting a
number it cannot stand behind. **An answer that arrives with confidence and is
wrong costs more than no answer.**

### 6. Measure before you build

Trigger #2 requires a **counted** proportion from a real register, not a figure
from a meeting. This is the pattern: turn "customers want X" into "N of M
measured cases show X".

---

## 8.7 Technical debt register

Ranked by what it will cost if left.

| # | Debt | Cost if left | Fix size |
|---|---|---|---|
| 1 | **`test_each_task_is_planned_in_turn` hangs** | `pytest tests/` appears to freeze — every new contributor loses time to it, and the deselect has to be remembered | Small: stub the licence call the way other window tests do |
| 2 | **Send path + PO screen unverified against a real mailbox** | The riskiest thing to sell. A first real customer finds the bug | Medium: one willing customer, one supervised run |
| 3 | **Two `prism_terminal` checkouts on the dev machine** | Already cost an afternoon once (`/gerber` "Unknown command") | Trivial: delete one |
| 4 | **README test counts are stale** (says 705 and 588; actual 1,203) | Erodes trust in the rest of the README | Trivial |
| 5 | **`plans.py` strings not translated** | Hindi/Gujarati users see English on the paywall — the screen where you are asking for money | Small |
| 6 | **Wake word is a polling loop** | Lag and misses; unsellable as a feature | Medium: swap in Porcupine / OpenWakeWord |
| 7 | **NotebookLM automation unverified** | A stage that silently returns nothing | Medium |
| 8 | **Agent failover only after the pipeline, not inside it** | A middle-stage failure loses downstream work | **Large** — surgery on the riskiest function in the codebase. Do not start without trigger #6 |
| 9 | **Gerber fallback path never exercised** | The reader has been tested on exactly one clean KiCad export | Blocked on trigger #7 — real customer zips |
| 10 | **`DEFERRED.md` marks reel-motion seam checking DONE, but `motion_faults` is not in the pinned submodule** | A doc claiming a guarantee the code does not provide is worse than no doc. It also suggests the submodule pin may be behind the engine generally | Trivial to diagnose: `cd prism_terminal && git log --oneline -20` and compare with upstream. Then either bump the pin or reopen the entry |

---

## 8.8 Metrics worth tracking

The product currently produces these but does not aggregate them. Each is
cheaply derivable from data that already exists on disk.

| Metric | Source | Tells you |
|---|---|---|
| Inquiries per day | `dashboard_data.inquiries_per_day()` | Whether the register is being fed |
| Conversion rate | Register `Status` column | Whether quoting works |
| Time from inquiry to quotation | `Date received` vs `Quotation date` | The number the customer actually feels |
| Reminders sent vs. replies | `Reminders sent`, `Last contact` | Whether chasing works |
| Triage source split (`rule` / `learned` / `ai`) | `Verdict.source` | **How much AI you are actually buying** — and how well `Knowledge` is growing |
| `unsorted_by_failure` count | `Result.unsorted_by_failure` | Messages nothing managed to read — the only figure that means something may have been missed |
| Run success/failure | `dashboard_data.run_counts()` | Pipeline reliability |
| Per-stage durations | `run_<ts>.json` `durations` | Which stage is slow — newly answerable |

> **The triage source split is the most under-used number in the product.** It
> is the direct evidence for the privacy claim *and* the cost claim, and it is
> already recorded on every verdict.

**The number to quote a customer**, from `EMAIL_WORKFLOW_RUNTIME.md`:
*about six minutes a day, in four taps.* Not "automation" — **six minutes**.

---

## 8.9 A suggested cadence

For running this as a PM rather than as a developer.

| Rhythm | Do |
|---|---|
| **Per change** | Update the architecture doc the change touches, in the same commit |
| **Weekly** | Walk §8.3's trigger board. Has any trigger fired? |
| **Weekly** | Check the failure catalogue in [07-operations.md §7.7](07-operations.md#77-diagnostics-and-failure-modes) against what support actually saw |
| **Per customer conversation** | Record the *reasoning* in `DEFERRED.md` / `AFTER_THE_MERGE.md` **in that conversation, not later** |
| **Per release** | Refresh the maturity board (§8.1) and the snapshot line at the top |
| **Per quarter** | Re-read §8.5's open questions. Which are still open, and why? |

---

[← Operations](07-operations.md) · [Index](README.md)
