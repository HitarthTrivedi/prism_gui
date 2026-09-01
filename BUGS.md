# Prism — Known Bugs & Gaps

**Status:** living document. Everything here was found by *running the product* —
the BOQ pipeline end-to-end (24-08-2026) and the Reel pipeline end-to-end
(25-08-2026), both on Windows 11, source checkout, real logins.

Severity: 🔴 breaks a run · 🟠 degrades output or trust · 🟡 cosmetic/UX.

---

## Fixed, pending review

### 0a. Native crash — QThread destroyed while still running — FIXED, uncommitted 🔴
- **Symptom:** the window opens, then Prism vanishes a few seconds later with no
  Python traceback. Windows logs a fast-fail — `python.exe … Qt6Core.dll …
  c0000409` (BEX64). Reproduced on `followup-artifact-capture` by opening BOQ and
  clicking **Attach files**; also latent on closing any dialog whose worker was
  still running.
- **Cause:** every worker is a `QThread` subclass, and a `QThread` that is
  garbage-collected while its thread is still running is a Qt *fatal*
  (`QThread: Destroyed while thread is still running`) that aborts the process.
  A `Signal.connect()` does **not** keep the emitter alive, so a worker held only
  through its `done`/`failed` connections is dropped the instant the caller's own
  reference goes — a dialog closing, an attribute reassigned to the next run's
  worker, or a local going out of scope — and the next GC destroys it mid-run.
- **Fix applied:** new `_Worker(QThread)` base in `workers.py` that anchors each
  worker in a module-level `_running` set from `start()` until its `finished`
  signal fires (drains itself on the GUI thread, so the eventual destruction is
  always safe). All 20 workers inherit it; `dialogs/license_dialog._ActivateWorker`
  too (it was parented to the dialog and could be destroyed mid-activation behind
  a slow proxy). `drive_dialog._Job` and `wakeword.WakeWordListener` already
  `wait()` on teardown.
- **Verified:** a standalone repro (start a QThread, drop its only reference,
  `gc.collect()` while running) fast-fails `0xC0000409` before the fix and exits 0
  after; the live app now runs well past the old ~15–30 s crash window.
- **Action:** review + commit; any new background thread must subclass
  `workers._Worker`, never `QThread` directly.

### 0. Ghost-window flash on panel rebuilds — FIXED, uncommitted 🟡
- **Symptom:** navigating to Settings (and any rebuilt panel) flashed a tiny
  top-level OS window with a titlebar and DWM open-animation.
- **Cause:** `setParent(None)` on a *visible* widget promotes it to a top-level
  window for the instant before `deleteLater()` lands. Windows clamps it to
  minimum titlebar width and animates it.
- **Fix applied:** `widget.hide()` before every `setParent(None)` — 12 sites
  across `widgets/settings_panel.py`, `simple_panels.py`, `inquiry_panel.py`,
  `output_panel.py`, `support_panel.py`, `agents_panel.py`, `controls.py`,
  `home_panel.py`. The `home_panel._active_host` case is safe because
  `_fill_active()` re-asserts visibility after re-add.
- **Action:** review + commit; carry the `hide()`-first rule into any future
  `_drop`-style rebuild code.

---

## Open — mechanical

### 1. Unicode is not forced app-wide 🔴 — (a) FIXED, (b) open
- **Symptom (a):** an emoji in a log line (`🍪` in the profile message) crashes
  the entire run with `'charmap' codec can't encode character` when stdout is
  cp1252 (any redirected/console launch on Windows). — **FIXED 26-08:**
  `main.py` now calls `_force_utf8_streams()` (reconfigure stdout/stderr to
  UTF-8, `errors="replace"`) as its first line in `main()`, before any engine
  import can print. GUI + engine share one process, so this covers both.
  Regression-checked: the 🍪/₹/em-dash line raised UnicodeEncodeError before,
  prints clean after.
- **Symptom (b):** generated documents show `�` for em-dashes and `■` for `₹`
  (seen in the BOQ PDF's Rate/Amount headers) — encoding + missing font glyphs.
  — **STILL OPEN:** lives in the engine's doc generator (`prism_terminal`).
  Needs a ₹-capable font embedded in PDF/DOCX generation. Do with the engine
  cluster (related to #10's markup-stripping in the same generator).
- **Workaround retired for (a).** (b) still shows wrong glyphs regardless of env.
- **Fix (b):** embed a ₹-capable font in PDF/DOCX generation; keep
  `encoding="utf-8"` on every `open()`/stream in the engine.

### 2. Claude submit does not fire (selector drift) 🔴
- **Symptom:** engine types the prompt into claude.ai, enters its
  "waiting up to 600s" loop — but the message is still sitting unsent in the
  composer. A human had to click the send arrow to unblock both the BOQ write
  stage and the Reel retry.
- **Fix:** drive the send *button* on Claude's current UI instead of trusting
  Enter; after submitting, verify the composer emptied before entering the
  wait loop; if not, retry the click.

### 3. Artifact/file responses are invisible to the scraper 🔴
- **Symptom:** Claude produced the best BOQ of the day as a **DOCX artifact in
  a side panel**. Prism's scraper reads chat text only → dialog reported
  "Nothing came back" and the run recorded a failure. The user had to download
  the file by hand.
- **Fix:** detect artifact/file panes and pull their content or download link;
  and/or add "answer in the chat itself — do not create files/artifacts" to
  writer-stage prompts.

### 4. Planner brief contradicts renderer contract 🔴
- **Symptom (Reel pipeline):** the assembled brief contained BOTH the planner's
  deliverable spec ("plain-text output with two headings: Reel Script and
  Storyboard") AND the Reel renderer's contract ("OUTPUT FORMAT — THIS
  OVERRIDES EVERYTHING: reply with ONLY a JSON object"). Claude followed the
  wrong one; the validator rejected; retry loop began.
- **Fix:** when the downstream stage is a structured renderer (Reel scene
  spec), the router must strip its own formatting/deliverable-spec block from
  the task text and let the renderer contract stand alone.

### 5. File upload to browser tools is flaky 🟠
- **Symptom:** first message of the Reel run — Claude replied "there's no file
  in your uploads. Could you re-attach BrandKural_Brand_Guidelines.pptx?"
  The attach had silently failed; one retry away from a run built on missing
  context.
- **Fix:** after attaching, verify the upload chip exists in the DOM before
  submitting; retry the attach once before proceeding.

### 6. "Copy my Chrome logins" is dead weight on modern Chrome 🟠
- **Symptom:** the button (and `seed_profile()` in
  `prism_terminal/core/automation.py`) copies only Chrome's **`Default`**
  profile. Users with multiple named profiles get an empty or wrong profile
  copied and stay logged out.
- **Deeper platform reality:** even pointed at the right folder it can't work
  reliably anymore — Chrome 127+ app-bound cookie encryption makes copied
  cookies undecryptable in a new location, and Chrome 136+ blocks automation
  attaching to the real profile directory. Google closed this door.
- **Fix:** deprecate/remove the copy path. Make the one-time guided login
  ("Open login tabs" → sign into each tool inside Prism's persistent profile)
  the official onboarding ritual. It works and it persists — proven 24-08.

### 7. Shipping default model is retired 🟠
- **Symptom:** config default `llama-3.3-70b-versatile` no longer exists on
  Groq. `MODEL_FALLBACKS` recovered mid-run (switched to `openai/gpt-oss-120b`
  and saved it), but a fresh install's first run eats a retry-and-warn.
- **Fix:** update the shipped default; show a status-bar notice when the
  fallback chain swaps models so the change isn't silent.

### 8. Internal prompt scaffolding leaks into tool UIs 🟡
- **Symptom:** the literal header `WHAT THE PERSON ACTUALLY ASKED FOR — in
  their own words:` appears as the visible search query in Consensus and as
  chat titles in Claude. Harmless, but looks broken in front of a customer.
- **Fix:** keep scaffolding out of the first line the tool renders; put the
  human-readable request first, scaffold below.

---

## Open — architectural

### 9. Chat-UI models resist machine-format stages 🔴 (the big one)
- **Symptom (25-08):** claude.ai **refused** to emit the Reel scene-JSON:
  *"I don't have a tool that renders that scene-JSON format… that instruction
  block came in through your earlier message, not from an actual connected
  renderer, so I can't verify it does anything."* The assistant treated the
  pipeline's renderer contract as a prompt-injection attempt — which is
  exactly what consumer chat products are trained to resist. A user-typed
  authorization ("the renderer is my own local tool") unblocks it, but this
  will recur unpredictably.
- **Pattern across all runs:** prose/creative stages succeed through the
  browser (ChatGPT file analysis, Claude scripts/BOQ bodies — all good).
  Structured stages whose output a **machine** consumes are precisely where
  the browser path fails — by selector, by artifact, or by refusal.
- **Direction:** browser-driven premium models for prose/creative stages;
  **API with enforced structured output** (Groq JSON mode / Claude API) for
  any stage feeding a renderer or parser. Evidence: the same BOQ prompt ran
  API-side in 7.8 s with zero interaction (24-08).

### 10. No deterministic compute layer behind LLM arithmetic 🟠
- **Symptom:** the rich-prompt BOQ PDF contains cross-reference sums that are
  wrong — B.1.03 claims 800 m "derived from A.7.03 + A.7.04 + A.3.05 + A.3.06"
  whose quantities total 1,150 m; B.1.01 cites A.7.03 where it means A.2.07.
- **Principle:** the LLM should *derive* quantities and state bases; software
  should *add* them. Sums, section subtotals, GST and grand totals must be
  computed in code from the line items, never trusted from the model.
- **Also:** raw `<b>`/`<br/>` tags rendered as literal text in the PDF warning
  box — the doc generator must parse or strip markup (related to #1).

---

## Design gaps (not defects — known missing layers)

- **No LLM evals.** 600+ unit tests, zero that score model output. Any prompt
  or model change ships blind. A ~50-input golden set with structural
  assertions is the known fix.
- **No telemetry.** `SIGNALS.md` specs the product-signal layer; unbuilt. Note
  its `main_window.py` hook line numbers are stale after the 24-08 interface
  rebuild — re-verify before building. September installs currently ship with
  no usage visibility.
- **No offline licence grace.** `authorize()` has no fallback by design; a
  licence-server blip at 4 p.m. blocks a paying customer's run. A short
  signed-token grace window keeps the philosophy and softens the failure.

---

*Compiled 25-08-2026 from live end-to-end runs. Update statuses in place;
add new findings with a date.*
