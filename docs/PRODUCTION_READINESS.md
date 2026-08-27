# Prism GUI — Production-Readiness Roadmap

**What this is.** The standardized catalogue of every capability the Prism GUI
must have to be a *production-grade product*, not a working prototype. It is the
master plan. Each capability is listed with its current state, the gap, the
intended approach, and a priority — and each one, when we build it, gets its own
**full spec at the depth of `docs/Prism Signals`** (rationale → principles →
architecture → API → hook sites → schema → failure semantics → rollout →
objections). This file is the map; the per-feature specs are the territory.

**How we work — branch-and-bound.** Pick the next capability by priority →
study it to that depth → build it → prove it works → log it in `improvement.md`
→ move on. Nothing ships as a hack; everything is a properly-studied,
production-quality feature. We are missing most of these today and will land
them one at a time.

**Legend.** ✅ done · ◑ partial · ○ missing · 📄 spec exists.
**Priority.** P0 blocks the September cohort · P1 soon after · P2 later.

---

## Pillar A — Input & Intent
*Getting the task right before spending a run.*

| Capability | State | Gap / Approach | Pri |
|---|---|---|---|
| **A1 Task queue** (run several in order) | ✅ | Present (`input_panel.tasks()`) | — |
| **A2 Post-completion follow-up, auto-routed** | ✅ | Built this session — refine + add attachments after a task, auto-sent to the right step's assigned agent | — |
| **A3 Clarify-before-run** | ○ | Optional: for a vague prompt, ask 2–4 questions before planning (Groq JSON). Deferred in favour of A2 | P2 |
| **A4 Prompt/task templates** | ○ | Saved, parameterised task starters per add-on (e.g. "BOQ for a <type> building") so a non-expert isn't facing a blank box | P1 |
| **A5 Attachment management** | ◑ | Attach file/folder works; needs preview, per-file remove, and size/type validation before a run | P1 |

## Pillar B — Execution Control
*Staying in command of a run in flight.*

| Capability | State | Gap / Approach | Pri |
|---|---|---|---|
| **B1 Plan review & edit** | ✅ | 7 edit capabilities in `agents_panel` | — |
| **B2 Cancel / Stop** | ◑ | **Cooperative stop has gaps** — a browser mid-page-load/upload/render ignores it. Add stop-checks around the unguarded ops + a **Force-stop** (close the browser). *(field bug #3)* | **P0** |
| **B3 Live progress / status** | ✅ | Stage cards, timeline, step counter | — |
| **B4 Cost & time transparency** | ✅ | Plan rows show cost band + typical time | — |
| **B5 Pause / resume a run** | ○ | Beyond stop: hold a run and continue later (harder; needs engine state) | P2 |

## Pillar C — Output & Artifacts
*Everything the run produces, captured and reusable.*

| Capability | State | Gap / Approach | Pri |
|---|---|---|---|
| **C1 Artifact display** | ✅ | `ARTIFACTS_DIR` + `artifacts_panel` | — |
| **C2 Artifact capture from browser** | ○ | **The manual-download pain.** Engine must detect an artifact/file pane (DOCX side-panel etc.), pull it, and save to `ARTIFACTS_DIR`. *(BUGS.md #3, engine)* | **P0** |
| **C3 Artifacts as run context** | ○ | Prior artifacts available to later runs / the next AI, "so it knows what was before". Feed selected artifacts back into a run's context | P1 |
| **C4 Output kept vs binned** | ○ | Track whether a result was used or discarded (feeds Signals `output_used`) | P1 |
| **C5 Export / share a result** | ◑ | Reveal-in-folder exists; needs one-click export/bundle of a run's outputs | P2 |

## Pillar D — Reliability
*It works on a real customer's machine, or fails gracefully.*

| Capability | State | Gap / Approach | Pri |
|---|---|---|---|
| **D1 Structured stages via API** | ◑ | Groq JSON-mode + Reel scene-spec fallback built (engine, unpushed). Extend to all machine-consumed no-web stages *(BUGS.md #9)* | P1 |
| **D2 Selector-drift resilience** | ○ | Browser submit/scrape breaks when a site's DOM changes; server-published selector fixes exist but the failure modes (#2, #5) need hardening | P1 |
| **D3 Uniform error surfacing & retry** | ◑ | Some stages retry; no consistent "this failed, here's why, retry?" surface | P1 |
| **D4 UTF-8 / encoding** | ✅ | Forced at entry this session *(BUGS.md #1a)* | — |
| **D5 Offline licence grace** | ○ | A licence-server blip blocks a paying run; a short signed-token grace window softens it | P1 |

## Pillar E — Observability
*Reading the product's own behaviour and health.*

| Capability | State | Gap / Approach | Pri |
|---|---|---|---|
| **E1 Signals — product-usage telemetry** | 📄 ○ | **Fully specified** in `docs/Prism Signals` (SIGNALS.md). Local, shapes-only, per add-on retention. P1 scope is ~1 day. Build before September | **P0** |
| **E2 Diagnostics & export** | ✅ | `diagnostics.py` — rolling scrubbed log + export | — |
| **E3 Run history & re-run** | ✅ | History panel | — |
| **E4 Crash reporting** | ◑ | Crashes hit the log; no first-class "send us this" flow | P2 |

## Pillar F — Onboarding, Config & Trust
*The first five minutes, and the standing promises.*

| Capability | State | Gap / Approach | Pri |
|---|---|---|---|
| **F1 First-run wizard** | ✅ | 3-step wizard; `onboarded` gate *(field bug #1 resolved)* | — |
| **F2 Config persistence** | ✅ | Key + agents + onboarded persist | — |
| **F3 Agent management** | ◑ | Pick/swap tools exists; needs per-tool login health ("are you signed in to X?") at a glance | P1 |
| **F4 Privacy posture, stated in-app** | ◑ | Signals defines the line ("we see that a BOQ ran, never your numbers"); needs a real privacy screen + opt-out toggle | P1 |
| **F5 Update flow** | ◑ | `updater.py` is phase-0 (notices only); a real download/apply path later | P2 |

## Pillar G — Reactive UI state *(cross-cutting)*
*The app reflects state changes live, everywhere — not only on navigation.*

| Capability | State | Gap / Approach | Pri |
|---|---|---|---|
| **G1 Live / reactive state** | ○ | Today the GUI is **pull-on-navigate**: `_show_screen()` calls a panel's `refresh()` only on arrival, and there is no global "state changed" signal — so a change in one place (key set, agents picked, licence, run finished) leaves every *other* panel stale until you re-enter it. Target: a single source of truth for config/app-state that **emits on change**, with panels *subscribing* (push-on-change). Systemic, so specced carefully; can land incrementally (config-changed signal first → widen to run/licence state) | **P1** |
| **G2 Config as one source of truth** | ◑ | Ties to the stale-copy bug: a single owned config object all dialogs read/write through (not copies), removing both the wipe class and the staleness class at once | P1 |

---

## The P0 shortlist (before the September cohort)
The four that matter most for the first ten installs, in order:

1. **B2 — Stop that actually stops** (a customer must be able to cancel; live bug)
2. **C2 — Artifact capture** (kills the manual-download pain; the run "just works")
3. **E1 — Signals** (the September cohort's first weeks are a one-time signal; ~1 day, spec ready)
4. **A2 — Follow-up** ✅ (done) — refine without starting over

## The rule
Every item above, when its turn comes, is studied and written to the depth of
`docs/Prism Signals` *before* a line is written — rationale, exact hook sites,
schema, failure semantics, rollout. That is what "production grade" means here:
not that it works in a demo, but that it is designed to not break on a real
customer's machine, and that the reasoning survives in writing for whoever
picks it up next.
