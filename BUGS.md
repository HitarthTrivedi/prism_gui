# Prism — Known Bugs & Gaps

**Status:** living document. Everything here was found by *running the product* —
the BOQ pipeline end-to-end (24-08-2026) and the Reel pipeline end-to-end
(25-08-2026), both on Windows 11, source checkout, real logins.

Severity: 🔴 breaks a run · 🟠 degrades output or trust · 🟡 cosmetic/UX.

> **When an entry leaves this file.** Not when the fix is written — when the
> fix is **on `main`**, and either the mistake is now structurally impossible
> or a test pins it.
>
> An entry ending *"any new X must remember to Y"* is not finished. It is a
> bug with a delay on it. Entry 0a is the worked example: the same defect was
> fixed six times by three people across four weeks, five of those as
> per-call-site patches, because the rule lived in a sentence rather than in a
> test. See `docs/architecture/09-boundaries.md`.

---

## Fixed, pending review

### R1–R10. The Reel Studio round (07-09-2026, branch `reel-studio-fixes`)
Found by running the product on Linux (source checkout, real ChatGPT), one
reel end to end, then the follow-up, then the editor. Each entry names the
test that pins it; none is a rule that lives in a sentence.

- **R1. A ticked plan step with no prompt made the engine wait out 300 s on a
  tab it never typed into 🔴.** "Find the people" ticked by hand → upload, no
  prompt, full cap, twice. `custom_stages` bypassed `_needed_stages`' empty
  filter and the "never received the prompt" guard sits inside the loop that
  had nothing to loop over. Fix: the engine skips a browser stage with no
  prompt (`stage_skipped`, before a tab opens); the plan screen offers to run
  without it, naming the step. Pinned: `test_unprompted_stage.py`,
  `test_gates.py::UnpromptedStepGate`.
- **R2. The planner's JSON died on a raw quote inside a prompt string 🔴.**
  `Expecting ',' delimiter: line 16 column 49`, twice in a row, bare
  `json.loads`, no retry. Fix: `router._parse_plan` repairs, then re-asks once
  in Groq's `json_mode`. Pinned: `test_router_json.py`.
- **R3. Generated and attached PNGs lost their alpha; a wordmark reached the
  film as one red "d" 🟠.** `assets.cutout` flattened to RGB, read the
  transparent pixels' colour as "the background", cleared every pixel near it.
  Fix: real alpha is kept; a flat card is cut edge-inward with a soft,
  defringed boundary; the manifest tells the truth (and how to use an opaque
  photo). Pinned: `test_asset_cutout.py`.
- **R4. The Studio checker could not see two texts printed over each other
  🟠.** One fault on a reel with four collisions. Fix: pairwise text-box
  overlap and 3×3 partial-cover sampling in `__check`; counters/continuity and
  an asset plan in the prompts. Pinned: `test_layout_overlap.py` (real
  Chromium, including the reel that started this), `test_asset_plan.py`.
- **R5. The deb VLC died on Play — `libpthread.so.0: undefined symbol:
  __libc_pthread_init` 🔴 (Linux dev) / 🟠 (frozen).** Prism launched from a
  VS Code-snap terminal inherits `GTK_PATH`; the packaged build has the same
  shape via PyInstaller's `LD_LIBRARY_PATH`. Fix: `paths.scrub_environment()`
  at startup, for every child Prism opens. Pinned: `test_environment_scrub.py`.
- **R6. Follow-ups were one-time only, and a reel's never reached its own chat
  🟠.** The follow-up run's completion replaced the session with its one
  stage; the classifier routed a reel to the local renderer. Fix: a merged
  session per task; a planned follow-up (artwork → design chat → re-film, or a
  relay of steps in their own chats); `studio_followup`; History offers one;
  waits raised. Pinned: `test_followup_session.py`, `test_followup_plan.py`,
  `test_studio_followup.py`.
- **R7. Unticking "Make the images" changed nothing 🟠.** Studio's image maker
  is inserted by the engine on a config key the plan never touches. Fix:
  `skip_stages` from the plan screen, honoured by the insertion. Pinned:
  `test_skip_imagery.py`.
- **R8. Every run with the same words shared one Artifacts folder; a
  follow-up attached twelve files from four runs 🟠.** Fix: one folder per run
  (`config.begin_run`), cards per run, the run record remembers its folder.
  Pinned: `test_artifacts_config.py`, `test_artifacts_panel.py`.
- **R9. Names: the request verbatim everywhere, and every chat titled by its
  own opening line ("Senior Creative Director Task") 🟡.** Fix: the planner
  writes `_title`; folders, files, History and Home use it; each step's first
  message opens `Prism · <title> · <step>`. Pinned: `test_run_titles.py`.
- **R10. `ReelDialog._on_rendered` raised `AttributeError: request` on a reel
  reopened from disk and re-rendered from the editor 🔴.** `self.request` was
  only set by `_run`. Fix: initialised in `__init__`. Not separately pinned.

### 0a. Native crash — QThread destroyed while still running — CLOSED 🔴
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
- **Closed 07-09-2026.** On `main`, and no longer a rule anybody has to
  remember: `tests/test_worker_mandate.py` fails on any `class X(QThread)`
  outside the `_Worker` definition, and separately asserts that `_Worker`
  still anchors and releases (the inheritance check alone would pass if
  somebody gutted `start()`). It found two survivors on its first run --
  `wakeword.WakeWordListener`, the ORIGINAL instance of this bug, and
  `drive_dialog._Job`, which had worked around it by hand. Both converted.

### 0. Ghost-window flash on panel rebuilds — FIXED, on `main` 🟡
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
- **On `main`. Still a rule that lives in a sentence, though** -- the
  `hide()`-first rule has to be remembered at 12 sites across 8 files and
  nothing enforces it. A test that flags `setParent(None)` without a
  preceding `hide()` in the same block would close this properly; see the
  note at the top of this file.
- Note on the paths above: `simple_panels.py` was split in the add-ons
  restructure and `inquiry_panel.py` moved. The fix travelled with them --
  see `docs/ADDONS_MOVE_MAP.md`.

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

### 11. Any test that pumps the Qt event loop kills the whole suite 🔴
- **Symptom:** `Windows fatal exception: code 0xc0000374` — heap corruption —
  several hundred tests after the test that actually caused it. The traceback
  names an *innocent* test, because the damage was done earlier.
- **Cause:** panels are built and destroyed all over the suite, and
  `addons/inquiry/dialog.py` posts `QTimer.singleShot(0, lambda:
  self._first_look(...))` capturing `self`. Under pytest **no event loop ever
  runs**, so those callbacks are never delivered and never discarded — they
  accumulate, holding Python wrappers around C++ objects destroyed long ago.
  The first thing to call `processEvents()` runs them all, against freed
  memory.
- **Found by:** writing a test that legitimately needed to pump events, and
  watching it take the run down. `tests/test_worker_mandate.py` now calls
  `_forget()` directly and asserts the wiring by source inspection instead.
- **Why it is not fixed here:** `tests/conftest.py` drains straggler
  *threads* between tests but has no equivalent for the event queue, and
  adding one changes how every test in the suite is isolated. It also has an
  in-flight branch against it (`feature/chrome-profile-and-inbox`).
- **Fix:** an autouse fixture that drains posted events between tests, or
  `QCoreApplication.removePostedEvents()` on teardown. Until then: **do not
  call `processEvents()`, `exec()` or `QEventLoop` in a test.**

### 12. The licence server's published payload can go stale silently 🟠
- **Symptom:** none, which is the problem. Customers get behaviour from an
  old snapshot and nothing anywhere says so.
- **Cause:** `/v1/payload` serves a **hand-copied** extract of
  `prism_terminal/core/agents.py`'s selectors and timings,
  `core/router.py`'s prompt templates, and `pros_cons.txt`. Nothing detects
  when those source files change. The client's only defence is
  `licensing/payload.py`'s "refuse and use built-in config" on a schema
  failure — which does not fire for content that is merely *out of date*.
- **Related trap:** the override rows are keyed by `AGENT_REGISTRY` **display
  names** (`"ChatGPT"`, `"Prism Reel"`). Rename one and its published row
  silently stops matching. Moving files is free; renaming these is not — see
  `docs/architecture/09-boundaries.md` §5.
- **Fix:** record a checksum of the three sources at publish time and compare
  it in CI, so a drift is a red build rather than a quiet regression.

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
