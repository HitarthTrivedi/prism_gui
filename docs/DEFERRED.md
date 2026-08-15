# Deferred work

Things deliberately not built yet, and **what has to happen before they are
worth building.**

A list of "nice to have someday" rots — nobody reads it, and six months later
nobody remembers whether an entry was a plan or a passing thought. So every
entry here carries a **trigger**: the observable thing that turns it from an
idea into a job. If the trigger has not happened, the entry is doing its job by
sitting here.

Add an entry when you consciously choose the smaller version of something. The
comment in the code should point here; this file should point back at the code.

---

## Reel motion — check the seams, don't only ask

**Where:** `prism_terminal/core/reel_web.py`, `design_instructions()`

**Done so far:** the art-director prompt now carries the motion laws — one
current, seams cut mid-motion, no idle wobble, stillness before the climax.
Adapted from HyperFrames' motion doctrine (Apache 2.0).

**Not done:** any check that the model followed them. It is advice, and advice
is not a guarantee.

**What it would be:** a `seams` array in the design JSON, one row per cut
declaring the exit and entry vector. `parse_spec()` verifies the rows agree and
sends mismatches back — exactly the loop that already exists for layout faults
("this text falls outside the frame, fix it"). Roughly 2–3 days.

**DONE — the trigger fired.** A reel obeyed every law in the prompt (one
current, leftward, no wobble anywhere) and still came back looking like
PowerPoint, because the slide-ness was not in the seams. `motion_faults()` now
checks the two faults that were: the scene wrapper animated as one slab, and
one animation used by 70%+ of everything that moves.

**Still not checked:** one axis at a time, and keeping a recurring object. Both
are stated in the prompt but too subjective to measure — flag them if a reel
ever obeys the two checked rules and still reads as slides.

---

## Reel motion — carriers across the cut

**Where:** same place.

**What it would be:** one object travelling *through* the seam at matched
position and velocity, so two scenes read as a single camera move rather than
two scenes. This is the strongest idea in the doctrine.

**Why it is possible here:** both scenes are on screen during a cut — the
outgoing one carries `--x` 0→1 and the incoming one `--e` 0→1. A carrier would
be the same element authored into both, animated to meet.

**Trigger:** the seam check above working reliably. Asking a model to author a
matched element into two separate scene blocks is a lot to ask while the
simpler laws are still being missed. A week or more, and worth it only for
customers who care about the difference.

---

## Agent failover — retry inside the pipeline, not after it

**Where:** `prism_terminal/core/automation.py`, `_retry_failed_stages()`

**Done so far:** a stage that produces nothing is handed to a different tool
from the same category and retried.

**Not done:** the retry runs AFTER the pipeline. A stage that failed in the
middle has already handed nothing to the stages behind it, and those are not
re-run — so a mid-pipeline failure is only partly recovered. The last stage,
which is where quotas actually run out, is fully recovered.

**What it would be:** retrying in place, inside the stage loop.

**Trigger:** a customer losing real work to a MIDDLE stage failing. Doing it
means restructuring a 500-line loop whose index-keyed maps (`machine_stages`,
`spec_feeder`, `design_feeder`) all shift if the stage list changes underneath
it — genuine surgery on the riskiest function in the codebase, and it cannot be
tested without a browser.

---

## Gerber reading — its own add-on

**Where:** not built. Design captured in `docs/FUTURE_INDUSTRY_TARGETS.md`.

**Done so far:** proven against a real 4-layer board — size, layers, holes by
size and type, track widths, stackup. Under a second, offline.

**Not done:** the add-on itself — its own window beside BOQ, reusing BOQ's
file-drop shape, with room to attach company details and a sample of the wanted
output.

**Trigger:** two or three real customer zips from Fine Circuits, ideally from
different design tools and ideally one with no `.gbrjob`. The reader has been
tested on exactly one file, a clean KiCad export, and the fallback path — the
one that matters — has never run.

---

## The test that hangs

**Where:** `tests/test_gates.py::TaskQueue::test_each_task_is_planned_in_turn`

**What is wrong:** it builds a real `MainWindow`, which reaches for the licence
server, and it HANGS rather than failing. A plain `pytest tests/` appears to
freeze. Every test command in this repo's docs carries a `--deselect` for it.

**Trigger:** it is already overdue. Left in place rather than deleted because
deleting a hanging test hides the hang; the fix is to stub the licence call the
way the other window tests do.

---

## Translation catalogue

**Where:** `plans.py`

**What is wrong:** feature names and blurbs are not in the translation
catalogue, so the paywall and plan descriptions stay English no matter what
language the customer picked.

**Trigger:** the first customer running Prism in Gujarati or Hindi who reaches
a paywall. Pre-existing and unchanged since Round 3.
