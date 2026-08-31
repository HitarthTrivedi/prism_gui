# Prism GUI — Production-Grade Improvement Log

**Purpose.** A living diagnostic + decision log for turning the Prism GUI from a
working prototype into a production-grade product. Each feature is treated
branch-and-bound: state what a real product needs, check what already exists,
build the gap, verify it works, then move on. Diagnostic data (what we found,
what we decided, what we measured) is recorded here as we go.

Started 2026-08-26. Owner: Harsh. Notify Parth on each feature start.

---

## 1. The plan lives in PRODUCTION_READINESS.md

The catalogue of production-grade capabilities — what a real product must have,
and in what order — is the **master plan** in `docs/PRODUCTION_READINESS.md`.
Single source of truth for the *plan*.

This file is the **log**: what we actually did, found, decided, verified and
broke while working down that plan. Single source of truth for the *history*.
Pick a feature from the roadmap → build it (at a full Signals-depth spec) →
record the journey here.

---

## 2. Today's build — Follow-up after completion, auto-routed (capability #1) — DONE

**Plan change (mid-build).** The first cut was a per-stage "Review each step"
checkpoint. Replaced, on request, by a **post-completion follow-up**: the run
stays autonomous, and only when the WHOLE task is done does Prism offer a
refinement. The refinement is auto-routed — Prism reads the note and sends it to
the assigned agent of the step it is about (Prism's "assign it automatically"
principle), folding in any new attachments. It loops (a follow-up run can offer
another follow-up).

**How it's built (files touched):**
- **Dialog** `dialogs/followup_dialog.py` (`FollowupDialog`): recap of the
  result, a refinement box, an "Add files" picker, Send / No-I'm-done. X closes
  as "done" (never starts a run by accident).
- **Classify** `workers.py` (`FollowupRouteWorker`): a Groq JSON-mode call that,
  given the follow-up + the steps that ran (key, agent, snippet), returns the
  target step key — this is the auto-routing.
- **GUI** `main_window.py`: `_on_run_done`'s completion path calls
  `_offer_followup()` → shows the dialog → classifies → `_on_followup_routed()`
  resolves the step's assigned agent (`self._stage_agents`) and calls
  `_start_followup_run()`, which re-runs just that one stage via the engine's
  existing `custom_stages` path, with the prior output as context + the new
  attachments. No new engine surgery — the per-stage review's engine hook was
  reverted.

**Verified (headless):** compiles; dialog submit + empty-guard; MainWindow
builds with the wiring. **Not yet verified:** the live end-to-end (needs a real
run + a working Groq key for the classify).

--- older per-stage notes kept for history below ---

## 2b. (superseded) per-stage "Review each step"

**What it is.** A human-in-the-loop checkpoint *between AI handoffs*. When the
"Review each step" toggle is on, the run pauses after each AI answers and,
BEFORE that answer is handed to the next tool, shows it to the owner. They can
**accept** it (moves on unchanged), **send a follow-up** that refines it in the
same chat (loops until they accept), or **stop** the run. Off by default — an
unattended run behaves exactly as before.

**How it's built (files touched):**
- **Engine** `prism_terminal/core/automation.py`: `run()` gained a `review=None`
  callback; after each stage's answer is captured and before it is committed to
  `all_responses`, if `review` is set the loop calls it and acts on the
  decision — `refine` re-asks the same tab via `_reask()` and loops, `continue`
  proceeds, `stop` ends. `review is None` ⇒ old behaviour, untouched. Refine is
  gated to chat-box tools (needs a textarea); Apollo/NotebookLM can be accepted
  but not re-asked.
- **Bridge** `workers.py` `AutomationWorker`: new `review_requested` signal +
  `submit_review()` + a `_review()` callback that emits to the GUI and blocks
  on a `threading.Event` in the worker thread until the user answers. `stop()`
  wakes a pending review with `{"action":"stop"}` so closing mid-review can't
  deadlock teardown. Passed to the engine only when `review_each_step=True`.
- **Dialog** `dialogs/review_dialog.py`: `ReviewDialog` — shows the answer
  read-only, an optional refine box, and Continue / Send-follow-up / Stop.
  Closing with the X defaults to Continue (never lose an answer or stop a run
  by accident).
- **GUI** `widgets/input_panel.py`: a "Review each step" checkbox in the
  composer action row + `review_each_step()` getter. `main_window._start_run`
  passes the flag and connects `review_requested` → `_on_review_requested`,
  which shows the dialog (on the GUI thread) and calls `submit_review()`.

**Verified (headless):** dialog decisions (continue/refine/stop/empty-guard);
the thread bridge — `review()` blocks until `submit_review()`, and `stop()`
wakes a blocked review (no teardown deadlock); MainWindow constructs with the
toggle. **Not yet verified:** the full pause during a live browser run — needs a
recorded run (toggle on → run a 2-stage task → dialog appears after stage 1 →
Continue → stage 2 → Refine → same tab re-asks).

---

## 3. Diagnostic data log

_(dated entries — findings, measurements, decisions)_

- **2026-08-26** — Pulled latest: 52 files / +4,488 lines from the team.
  New since our last state: `widgets/artifacts_panel.py`, `widgets/email_panel.py`,
  `dialogs/motion_dialog.py`, `sent_log.py`, and tests. Email dialog was rebuilt
  by the team (To/Subject/Message form) — supersedes our earlier `goal_edit`
  crash fix cleanly.
- **2026-08-26** — Confirmed artifact *display* already exists (`ARTIFACTS_DIR`
  + panel); the missing half is engine-side *capture* of browser artifacts.
- **2026-08-26** — Flow-mapped input→plan→run. Seam for the review checkpoint is
  the per-stage commit point in `automation.run` (after `_make_editable`, before
  `all_responses[stage] = …`, ~line 2755). Reused `_reask()` for the refine path
  and the `on_event`/`should_stop` callback convention for the new `review` hook.
- **2026-08-26** — Built + verified "Review each step" (see §2). Engine change is
  on the `prism_terminal` submodule (branch `groq-json-fallback`, unpushed — no
  write access yet); GUI changes on `prism_gui` main (pushable).
- **2026-08-26** — Plan change: replaced per-stage review with a **post-completion
  follow-up, auto-routed** to the relevant step's assigned agent (see §2). Reverted
  the engine review hook (no engine change needed — reuses `custom_stages`). All
  GUI-only now, so this whole feature is pushable to `prism_gui`.
- **2026-08-27** — Follow-up feature confirmed working live (dialog fires after a
  real run). Fixed `_result_summary`: it showed the first-non-empty step (surfaced
  the research step); now walks execution order and leads with the FINAL result,
  showing every step's output labelled (a task with multiple outputs shows all).
- **2026-08-27** — Live repro of the artifact bug (C2 / BUGS.md #3): a Claude DOCX
  artifact was captured as its one-line preamble → premature settle, broken
  handoff, lost deliverable. Confirmed NO existing engine capture (only image-canvas
  harvesting + display-only `artifacts_panel`). Shipped Layer-A mitigation (prose
  stages told to answer in chat, not artifacts). Real detection (Layer B/C) needs
  live DOM of Claude's artifact pane / ChatGPT canvas — spec in `docs/ARTIFACT_CAPTURE.md`.
- **2026-08-26** — Field bugs from testing: (#1) first-run wizard nagged until
  `onboarded=True` was actually saved — now resolved (config complete). (#3) Stop
  is cooperative and only polled at some points, so a browser mid-page-load/upload/
  render ignores it — OPEN, needs more stop-checks in the engine + a Force-stop.

---

## 4. Open questions / to verify

- Exact seam for the follow-up step (awaiting flow map).
- Whether to generate questions via browser or Groq API (leaning API for the
  real completion signal — same reasoning as the Reel scene-spec fallback).
- How the task text is represented at the seam (string vs dict) so answers
  merge cleanly.
