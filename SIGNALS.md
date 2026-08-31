# Prism Signals — product-direction telemetry (build spec v0.1)

**Status:** proposal, not yet built. Target: wired into the ~10 Vadodara installs before the September setup so the deliveries answer *which add-on has pull* on their own.

**Purpose:** measure *pull* — which add-ons customers actually open, use, and come back to — and *what breaks*, so product direction is set by the buyer's usage instead of by either founder's taste. This is the local, ethical version of what Grok Bot does invisibly at scale: the product measures itself.

**Non-goal:** billing. Money-metering already lives in `licensing/meter.py` and must stay separate (see "Why not reuse meter" below).

---

## The one principle

Copy `licensing/meter.py`'s discipline exactly, because it is already correct:

- **Shapes and counts only, never content.** No brief, no prompt, no output, no rate list, no email body. A count of stages, a tool name, a duration — never a customer's number.
- **Never raise into the caller.** A telemetry failure must never cost a customer their run. Every `emit`/`flush` is wrapped `try/except: pass`.
- **Offline-tolerant.** Buffer locally, lose nothing on a dead network, never block the UI.
- **At N=10, the machine is the backstop — the weekly call is the boss.** Telemetry tells you *what*; sitting in the customer's office tells you *why*. Do not over-build a dashboard for ten people you can phone.

## Why not reuse `meter.py`

`meter` is billing: it flushes to the licence server and must be honest for money. Signals is product analytics: you want to *query* it for retention, and you do not want product events diluting billing usage or vice-versa. Same shape discipline, different module, different destination. Keep them peers.

---

## What already exists (the delta to build)

| Already instrumented | Emits | Where |
|---|---|---|
| Agents pipeline, per stage | `meter.record("stage", tool, stage, ok)` | `main_window.py` `_on_stage_event` (≈1159, 1201, 1211) |
| Groq tokens | `meter.record("groq", …)` | `licensing/meter.py` `install_groq_meter` |
| Flush | `report_usage(run_id)` | `_on_run_done` (≈1322), `_on_run_failed` (≈1352), `closeEvent` (≈1410) |

| **Not instrumented — the blind spot** | |
|---|---|
| BOQ / Email / Reel / Inquiry dialogs | open via `_authorized_then` then `.exec()` — **emit nothing** |
| Run-level start/outcome + input shape | only per-stage exists today |
| Output kept vs discarded | nowhere |
| Retention / session frame | nowhere |
| "I wish it did X" | nowhere |

---

## The module: `signals.py` (top-level peer of `main_window.py`)

```python
def emit(ev: str, *, addon: str = "", ok: bool = True, ms: int = 0, **counts) -> None:
    """Buffer one shapes-only event. `counts` accepts ints only; anything else
    is dropped, so content cannot leak by accident. Never raises."""

def note(ev: str, *, addon: str = "", text: str = "") -> None:
    """The ONE exception that carries free text — only ever from an explicit,
    user-typed 'suggest a feature' box that says the text is sent to us."""

def flush() -> None:
    """Append buffered events to ~/.prism/signals/events.jsonl, atomically.
    Rotates at 5 MB (keep events.jsonl + .1 + .2). Never raises."""

def addon_session(addon: str):
    """Context manager around a modal dialog's .exec(): emits addon_opened on
    enter, addon_closed{ms, used} on exit."""
```

**Event record on disk (one JSON line):**
```json
{"ev":"run_completed","addon":"pipeline","ok":true,"ms":41200,
 "stages":3,"stages_failed":0,"ts":1756...,"session":"<uuid4>",
 "device":"<device_fingerprint>","app_version":"1.x.y"}
```
`device` reuses `licensing.device_fingerprint()` (already exists, anonymous). `session` is a per-launch uuid4.

**Storage:** local `~/.prism/signals/events.jsonl` (`config.CONFIG_DIR` is `~/.prism`; mirror `RUNS_DIR`). Phase 1 has **no server** — you read the file on the weekly visit, or add an "Export my usage" button that opens it. Phase 2 adds a remote flush when N outgrows in-person reach.

---

## The six events + session frame — exact hook sites

| # | Event | Fires when | Hook site |
|---|---|---|---|
| 1 | `addon_opened{addon}` | an owned add-on actually opens | `main_window.py` `_authorized_then.proceed()` (≈422), just before `then()` when `auth.allowed`. **One line covers all four add-ons.** |
| 2 | `addon_closed{addon, ms, used}` | dialog closes; `used`=did anything happen | wrap `.exec()` with `signals.addon_session(feature)` in `_open_boq_dialog` (≈527), `_open_email_dialog` (≈538), `_open_reel_dialog` (≈443), `_open_inquiry_dialog` (≈505). `ms<20000 & !used` = the demo-lie / abandon signal, derived at analysis time |
| 3 | `run_started{addon:"pipeline", stages, attachments}` | pipeline run commits | `_start_run` (≈1084), before `worker.start()` |
| 4 | `run_completed{addon:"pipeline", ok, ms, stages_failed}` | run ends | `_on_run_done` (≈1322) → `ok:true`; `_on_run_failed` (≈1352) → `ok:false`. Roll up per-stage ok from `self._stage_results` |
| 5 | `output_used` / `output_discarded{addon}` | user keeps vs bins the result | pipeline: `_discard_plan` (≈1096) = discarded; save/act path = used. **Add-on dialogs = Phase 2** (needs a hook inside `boq_dialog`, email send, reel render) |
| 6 | `feature_requested{addon, note}` | user types a wish | **Phase 2**: a "Suggest…" item (Help menu + optionally each dialog) → 1-field box labelled *"sent to the Prism makers"* → `signals.note(...)` |

**Session frame (for retention):**
- `session_start` — end of `MainWindow.__init__`.
- `session_end` + `signals.flush()` — in `closeEvent` (≈1401), next to the existing `report_usage` at 1410.

---

## Privacy, opt-out, guardrails

- **Opt-out flag** in `~/.prism/config.json` (`"telemetry": true` default). A Settings toggle flips it; when off, `emit`/`note` are no-ops.
- **Say it in the app.** The DPDP privacy screen states verbatim: *"We record that a BOQ ran and took 40 seconds. We never see your numbers."* That sentence is the telemetry spec, the DPDP posture, and the differentiator against Grok Bot, all at once.
- **Whitelist numeric fields**; drop anything else in `**counts`. The only free text in the whole system is `note()`, and it is user-typed into a box that says where it goes.
- **Bounded file**, never-raise, offline-buffered — same as `meter`.

---

## The one number (the debate-ender)

`devtools/retention.py` reads the concatenated `events.jsonl` from the installs and prints, per add-on per ISO week:

- **Weekly active devices** = distinct `device` with ≥1 `run_started`/`addon_opened` in the trailing 7 days → *unprompted retention*.
- **Output-acceptance rate** = `output_used / (output_used + output_discarded)` → *is it good enough to actually use*.

Retention holding or climbing across weeks 2–4 = you have a wedge. Decaying = the buyer is telling you this add-on isn't it, however clean the pipeline. Neither founder's taste is on this table — only the buyer's behaviour.

---

## Phasing & effort

| Phase | Scope | Effort | Buys |
|---|---|---|---|
| **1 — before Sept** | `signals.py` + local jsonl + events 1–4 + session frame + opt-out + privacy line | ~1 day | "which add-on has pull" + "what breaks" |
| **2 — post-launch** | events 5–6 (dialog hooks), remote flush (`client.signals` → `/v1/events`), retention view → small dashboard | ~2–3 days | quality signal + roadmap-from-buyers + scale past in-person |

Phase 1 alone turns the ten September installs into the self-measuring machine. The human weekly calls carry the "why" until N is large enough for the automated half to lead.

---

## Open decisions for the founders

1. **Default on or off?** (Recommend on + visible + one-click off. At N=10 you can also just tell each customer.)
2. **Local-only for how long?** (Recommend local until ~N=30 or until you stop visiting in person.)
3. **Who watches the one number, weekly?** (It only ends the taste-debate if someone actually reads it every week.)
