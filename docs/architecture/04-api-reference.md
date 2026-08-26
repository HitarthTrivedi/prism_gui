# 4 · API Reference

[← Data flow](03-data-flow.md) · [Index](README.md) · [Next: Licensing →](05-licensing.md)

---

Two halves:

- **[Part 1 — External APIs](#part-1--external-apis)**: every service Prism
  talks to over the network, with request and response shapes.
- **[Part 2 — Internal module API](#part-2--internal-module-api)**: the
  functions each module exposes to the rest of the system.

---

# Part 1 — External APIs

Prism makes network calls to exactly four kinds of endpoint. There are no
others.

| Service | Purpose | Sees customer content? |
|---|---|---|
| [Groq](#11-groq) | Fast structured AI: routing, triage, extraction, transcription | **Yes** — snippets, conditionally |
| [Licence server](#12-licence-server) | Activation, authorisation, metering, published config | **No** — never |
| [IMAP / SMTP](#13-imap--smtp) | The customer's own mail | Yes — it *is* their mail |
| [Google Drive](#14-google-drive) | Optional file picker | Yes — files they pick |

Plus **the user's own Chrome**, driven locally with Selenium. That is not an
API call; it is a browser on their desktop, signed in as them.

---

## 1.1 Groq

**Base URLs**

| Endpoint | Constant | Used by |
|---|---|---|
| `https://api.groq.com/openai/v1/chat/completions` | `router.GROQ_URL` | routing, triage, extraction, intent, PO reading |
| `https://api.groq.com/openai/v1/audio/transcriptions` | `voice.TRANSCRIBE_URL` | push-to-talk and wake word |

**Auth:** `Authorization: Bearer <cfg["api_key"]>` — a `gsk_…` key the customer
supplies. This is the *only* AI credential Prism holds.

### The model chain

```
cfg["model"]  (default "llama-3.3-70b-versatile", user-selectable)
  ↓ on failure
"openai/gpt-oss-120b"
  ↓
"openai/gpt-oss-20b"
  ↓
"groq/compound-mini"
```

`router.model_chain(preferred)` returns the list with the caller's choice first
and never duplicated. `router.apply_model_chain(models)` lets a **verified**
server payload replace the chain.

**Triage uses its own fast model:** `triage.FAST_MODEL = "llama-3.1-8b-instant"`.
`mailflow.check()` overrides it with `cfg["model"]` when one has been learned —
leaving it at the hardcoded default meant every check restarted from a dead
model regardless of what had already been saved to disk.

### `router.groq_chat()` — the single call site

```python
groq_chat(api_key, model, prompt, *, temperature=0.3, timeout=60, retries=1) -> str
```

| Concern | Handling |
|---|---|
| Rate limit / server error | `_RETRY_STATUS = (429, 500, 502, 503, 504)` → retry |
| Model retired | `_model_is_gone(status, body)` distinguishes "this model is unavailable" from "this request was bad" → move down the chain |
| A fallback that worked | `_remember_model()` persists it into `cfg["model"]`, so the next run starts there |

### What is sent, per call type

| Call | Payload | Size |
|---|---|---|
| `enrich_query()` | The raw query + `cfg["profile"]` | Small |
| `route()` | Query, brief, profile, agent list, attachment **note only** (never contents) | Small |
| `triage.classify()` | Batch of ≤10 `Message.snippet(1500)` — subject + ≤1,500 chars, **unknown senders only**, after `defang()` | ≤ ~15 KB |
| `mailflow.extract_details()` | One inquiry message | Small |
| `mailflow.reply_intent()` | `_own_words()` — the reply with quoted history stripped, ≤1,500 chars | Small |
| `po.extract()` | The PO text | Up to a few pages |
| `pathfinder._llm_parse()` | The file description only — **no file contents** | Tiny |
| `voice.transcribe()` | WAV audio, 16 kHz mono, ≤ `MAX_TAKE_S = 300` s | Up to a few MB |

### Verifying a key

`router.verify_key(api_key, model="")` → `""` if it works, else why not.

---

## 1.2 Licence server

**Default:** `https://prism-license-server.onrender.com` (`client.DEFAULT_SERVER`).

**Override:** `PRISM_LICENSE_SERVER` — honoured **only when running from
source**. An environment variable that redirected a release build would let
anyone point Prism at a licence server they control, which is precisely the
backdoor this design exists to not have.

**Headers on every request**

```
X-Prism-Version:  <app_meta.VERSION>
X-Prism-Platform: <sys.platform>
Content-Type:     application/json
```

**Timeouts**

| Constant | Value | Applies to |
|---|---:|---|
| `TIMEOUT` | 8 s | `refresh`, `deactivate`, `usage`, `payload` |
| `AUTHORIZE_TIMEOUT` | 45 s | `authorize`, `lease` |
| `AUTHORIZE_RETRIES` | 1 | |
| `ACTIVATE_TIMEOUT` | 75 s | `activate` — sized for a cold host |
| `ACTIVATE_RETRIES` | 0 | |

> **Only a transport failure retries.** A server that answered has said
> something, even if it said no, and repeating the request would double-count a
> metered run.

### Endpoints

#### `POST /v1/activate`

Turn a licence key into a token on this machine.

```json
{ "key": "PRSM-XXXXX-XXXXX-XXXXX-XXXXX",
  "device_fp": "<salted hash>",
  "app_version": "1.3.0",
  "hostname_label": "Ravi's PC" }
```

`hostname_label` exists so a customer asking *which* five machines are using
their seats gets a human answer rather than five hashes.

#### `POST /v1/refresh`

Renew the token; optionally pull new published configuration.

```json
{ "license_id": "...", "device_fp": "...",
  "app_version": "1.3.0", "payload_etag": "..." }
```

#### `POST /v1/deactivate`

Release this machine's seat.

```json
{ "license_id": "...", "device_fp": "...", "token": "PRSMv1..." }
```

> `token` is **proof we are the machine that holds the seat**. The licence id
> and the fingerprint are not secrets — both sit in `~/.prism` and travel in the
> token itself — so without it the server had no way to tell this call apart
> from a stranger releasing someone else's seat.

#### `POST /v1/authorize` — **the metered call**

```json
{ "license_id": "...", "device_fp": "...",
  "action": "run" | "plan", "feature": "core" | "reel" | "inbox" | ...,
  "scopes": ["core", "workflow"], "app_version": "1.3.0" }
```

The server writes a usage row and counts it against the daily allowance.

#### `POST /v1/lease` — **free**

Same check — licence status, revocation, seat, device, entitlements, client
version — but records **no** usage event and consumes no allowance.

> Use `lease` when all you need is authorisation. **Spending a quota unit to
> answer "may I open a dialog" would bill the customer for the question rather
> than the work.**

#### `POST /v1/usage`

```json
{ "license_id": "...", "device_fp": "...", "run_id": "...",
  "app_version": "1.3.0",
  "events": [ { "kind": "groq", "tool": "", "stage": "research",
                "prompt_tokens": 812, "completion_tokens": 240,
                "ok": true, "ms": 1840 } ] }
```

`kind` is one of `plan` · `run` · `stage` · `groq` · `addon`.

> **What the customer consumed, never what they wrote.** No prompt text, no
> email content, no file names, no customer names.

#### `POST /v1/payload`

Returns the server-published configuration blob (agent selector overrides and
the Groq model chain), signed and verified offline before anything is applied.

### Error shape

Any status ≥ 400:

```json
{ "error": { "code": "seat_limit", "message": "…", "detail": { } } }
```

→ raised as `ServerError(code, message, detail)`. A transport failure raises
`Unreachable` instead, which is **almost never worth showing** to the user.

---

## 1.3 IMAP / SMTP

The customer's own mail servers. Prism holds the credentials locally and talks
to them directly.

### IMAP (reading) — `prism_terminal/core/inbox.py`

| Concern | Detail |
|---|---|
| Transport | Port 993 → `IMAP4_SSL`. Anything else → `IMAP4` + `starttls()`. Always a real `ssl.create_default_context()` |
| Mode | `select(folder, readonly=True)` and `BODY.PEEK[]` — **nothing is marked read, moved or deleted** |
| Host discovery | `imap_for(address)` for known consumer providers; `mx_host(domain)` resolves MX records via `_MX_IMAP`; `guess_hosts(address)` produces the candidate list. A **typed** host is tried first |
| Auth failure vs. unreachable | `is_auth_failure(error)` checks `_AUTH_MARKERS`. Gmail and Microsoft 365 throttle then lock an account on repeated failed logins, so a timer that keeps re-presenting a refused password ends with "Prism locked me out of my email" |
| Errors | `explain_error(error, address)` turns an `imaplib` failure into the sentence that unblocks the user |
| Batching | `_fetch_headers()` fetches `HEADER_BATCH = 100` at a time — headers for many messages in a few round trips rather than one each |

**Provider map** (`_IMAP_HOSTS`): gmail.com / googlemail.com →
`imap.gmail.com:993`; outlook.com / office365.com → `outlook.office365.com`;
GoDaddy → `imap.secureserver.net`; and more.

### SMTP (sending) — `prism_terminal/core/mailer.py`

| Concern | Detail |
|---|---|
| Transport | Port 465 → `SMTP_SSL`. Otherwise `SMTP` + STARTTLS |
| Host map | `_SMTP_HOSTS`: gmail → `smtp.gmail.com:465`, outlook → `smtp-mail.outlook.com`, … |
| Pacing | `SEND_DELAY = 2.0` s between messages |
| Timeout | `_send_timeout(files)` scales the socket timeout to the attachment payload — uploading a big PDF on a slow line is not a hang |
| One message per recipient | So `{name}` can be substituted per person |
| Passwords | `clean_password()` — outer whitespace always trimmed; inner spaces removed when the shape matches `_APP_PASSWORD` (four groups of four) |

---

## 1.4 Google Drive

`integrations/gdrive.py` (335 lines) — optional. Lets the user pick a file out
of Drive the same way they would pick one off the disk
(`dialogs/drive_dialog.py`). The file is downloaded locally and then handed to
the **same** attach path as any local file.

---

## 1.5 The remote bridge (LAN / relay)

`prism_terminal/core/remote.py` — drive Prism from a phone on the same network.

| | |
|---|---|
| Port | `BASE_PORT = 7777` |
| Pairing | `start()` → LAN URL; the phone shows a code; `pair(code)` approves it |
| Poll | `next_prompt(code)` → `(pid, text)`; `set_status(pid, status)` |
| Hosted relay | `relay_pair(base, code)` → token; `relay_next()`, `relay_set_status()` |

---

# Part 2 — Internal module API

Only the surface each module *exposes*. Private helpers are omitted; the source
docstrings are the detail.

---

## 2.1 `core_bridge` — the engine bridge

Puts `prism_terminal/core` on `sys.path` and re-exports it. **Every accessor is
lazy**, so heavy optional dependencies are probed rather than imported at boot.

| Function | Returns |
|---|---|
| `automation_available()` | `(bool, reason)` — Selenium / undetected-chromedriver |
| `boq_available()` | `(bool, reason)` — needs `ezdxf` |
| `gerber_available()` | `(bool, reason)` — `shapely` optional; four of five numbers work without it |
| `reel_available()` | `(bool, reason)` — Pillow draws, FFmpeg encodes |
| `studio_available()` | `(bool, reason)` — plus a browser engine |
| `get_automation()` `get_boq()` `get_gerber()` `get_inbox()` `get_triage()` `get_register()` `get_quoting()` `get_sop()` `get_po()` `get_mailflow()` `get_files()` `get_drafting()` `get_reel()` `get_studio()` `get_assets()` `get_ffmpeg()` | The module |

`_warn_about_sibling()` prints a note naming both paths when a sibling
`../prism_terminal` checkout exists and is being ignored.

---

## 2.2 `workers` — the concurrency surface

Every class is a `QThread`. All communication is by Qt signal.

| Worker | Constructor | Does |
|---|---|---|
| `AuthorizeWorker` | `(feature='core', action='run')` | Ask the licence server whether this run may go ahead |
| `RouteWorker` | `(query, cfg, attachments)` | One `router.route()` call |
| `AutomationWorker` | `(routing, cfg, attachments, query, custom_stages, chatgpt_analysis, reel_design_stage)` | The whole browser pipeline. `stop()` / `stopping()` |
| `RecordWorker` | `(cfg)` | Push-to-talk: recording starts as soon as the thread runs |
| `InterpretWorker` | `(text, cfg)` | Polish a transcript, split out file mentions |
| `SendWorker` | `(cfg, recipients, subject, body, files)` | The email blast. `stop()` / `stopped()` |
| `VerifyWorker` | `(cfg)` | Log in and hang up — check the account before a real blast |
| `FindWorker` | `(desc, cfg)` | Natural-language file finding |
| `MeasureWorker` | `(path, unit='', scope=None)` | Parse a CAD drawing off the UI thread |
| `GerberWorker` | `(paths)` | Measure one or several PCB jobs |
| `ReelWorker` | `(spec, out_path, studio=False)` | Render the reel |
| `InboxVerifyWorker` | `(address, password, host='')` | Find the mail server and check the password |
| `InboxCheckWorker` | `(cfg, root, *, state, knowledge, local_only, followup_days, max_reminders, catch_up_with_new)` | One run of the daily loop |
| `POReadWorker` | `(cfg, text, source='')` | Read one purchase order into fields |
| `SupportWorker` | `(cfg, prompt)` | One answer from the support assistant |
| `DraftWorker` | `(cfg, prompt, *, purpose='draft', attachments=None)` | Write one email using the browser tools. `stop()` |
| `FFmpegWorker` | `()` | Download and install FFmpeg |

---

## 2.3 `licensing` — the public surface

```python
__all__ = ['state', 'has', 'require', 'activate', 'deactivate', 'refresh',
           'authorize', 'report_usage', 'Authorization', 'meter', ...]
```

| Function | Purpose |
|---|---|
| `state() -> LicenseState` | Cached, cheap, **safe to call from paint code** |
| `reload() -> LicenseState` | Drop the cache and re-read from disk |
| `has(feature) -> bool` | Entitlement check |
| `require(feature, parent=None) -> bool` | Gate an action — **shows the paywall itself**, so call sites stay one line |
| `set_paywall_handler(fn)` | Registered once from `main.py`, so `licensing` never imports Qt |
| `activate(key) -> LicenseState` | Key → token on this machine |
| `deactivate()` | Release the seat. Local state is cleared even if the server call fails |
| `refresh(blocking=False)` | Renew token and lease |
| `authorize(feature='core', action='run') -> Authorization` | May this protected operation go ahead? |
| `report_usage(run_id='')` | Fire-and-forget; never blocks, never raises |
| `lease_state() -> str` | `FRESH` \| `GRACE` \| `STALE` \| `NONE` \| `TAMPERED` |
| `lease_bearer() -> str` | The raw signed lease, for `Authorization: Bearer …` |
| `apply_cached_payload() -> int` | Re-apply the last verified payload at startup |
| `selftest() -> (bool, str)` | Verify the committed test vector — called by `main.py --selftest` |

`PROTECTED_ACTIONS = {'plan'}`.

---

## 2.4 `prism_terminal/core` — engine modules

### `config`

| Function | |
|---|---|
| `load() -> dict` | Reads `~/.prism/config.json`; a file that fails to parse is quarantined |
| `save(cfg)` | Atomic — an interrupted write cannot destroy it |
| `is_configured(cfg) -> bool` | |
| `active_agents(cfg) -> dict` | Categories the user actually assigned an agent to |
| `save_run(record, runs_dir='') -> str` | Persist one run's routing + responses |

### `router`

| Function | |
|---|---|
| `route(query, cfg, attachments=None) -> dict` | `{stage: {questions, needed}}` |
| `enrich_query(query, profile, api_key, model) -> str` | Raw request → professional task brief |
| `groq_chat(api_key, model, prompt, *, temperature, timeout, retries) -> str` | The one Groq call site |
| `model_chain(preferred='') -> list[str]` | |
| `apply_model_chain(models) -> int` | Replace the chain from a verified payload |
| `verify_key(api_key, model='') -> str` | |
| `detect_named_tools(query) -> dict` | The user named a tool explicitly |
| `apply_make_guardrail(query, routing, agents) -> list[str]` | Force make-stages the user clearly asked for |
| `apply_script_guardrail(routing, agents) -> bool` | A reel/deck needs words |
| `suggest_alternatives(query, brief, routing, agents, api_key, model) -> list[dict]` | |
| `build_prompt(...) -> str` | |

### `agents`

| Symbol | |
|---|---|
| `PIPELINE_ORDER` | The ten stages, in order |
| `CATEGORIES` | label · emoji · colour · description per stage |
| `AGENT_REGISTRY` | Every tool: url, specialty, cost, avg time, wait cap, selectors |
| `resolve_agent(stage, name) -> dict` | |
| `alternatives_for(stage, tried, cfg, limit=2) -> list[str]` | Other tools that could do this stage |
| `summary_agent_name(agents) -> str` | |
| `apply_overrides(mapping) -> int` / `overrides() -> dict` | Verified server overrides |
| `wants_canva(text) -> bool` | Did the user actually ask for an editable design |

Wait tuning: `WAIT_FLOOR = 300` · `WAIT_MULTIPLIER = 2.0` · `WAIT_CEILING = 1800`.

### `automation`

| Function | |
|---|---|
| `run(routing, cfg, attachments, on_event, query, chatgpt_analysis, custom_stages, should_stop, failover, reel_design_stage) -> (responses, links)` | Execute the pipeline |
| `shutdown()` | Close Prism's browser |
| `detect_chrome_version() -> int \| None` | |
| `chrome_profiles() -> list[dict]` | Every profile in the real Chrome, most likely first |
| `preferred_profile(cfg) -> dict \| None` | |
| `seed_profile(force=False, cfg=None) -> bool` | Copy the chosen real profile into Prism's |
| `profile_is_seeded() -> bool` / `seeded_from() -> str` | |
| `open_login_tabs(urls, cfg=None)` | Sign in before a real run |

### `inbox`

| Function | |
|---|---|
| `fetch_new(cfg, state, *, limit, first_days, timeout, always_full, must_read, backfill, catch_up_with_new) -> (messages, state, error)` | |
| `verify(cfg) -> str` | Log in, look, hang up |
| `discover(address, password, timeout=20, host='') -> (dict, str)` | Work out the server from two things they know |
| `guess_hosts(address) -> list[str]` / `imap_for(address)` / `mx_host(domain)` | |
| `parse_message(raw, uid=0) -> Message` | |
| `save_attachments(msg, folder) -> list[str]` | |
| `safe_name(name, fallback) -> str` | Cannot escape its folder or upset Windows |
| `html_to_text(html) -> str` | |
| `is_robot_address` / `bulk_header` / `says_it_is_bulk` | |
| `explain_error(error, address='') -> str` / `is_auth_failure(error) -> bool` | |

### `triage`

| Function | |
|---|---|
| `classify(messages, api_key, *, knowledge, model, local_only, batch_size=10) -> list[Verdict]` | A verdict for every message, in order |
| `rules_pass(msg, knowledge) -> Verdict` | Local only — no network |
| `learn(knowledge, msg_or_address, category) -> Knowledge` | That sender is never sent to an AI again |
| `summarise(verdicts) -> dict` / `describe(counts) -> str` | |
| `defang(text) -> str` | Strip a message's power to imitate the prompt carrying it |
| `asks_for_a_price(subject, body)` / `offers_a_price(text)` | |

### `register`

| Function | |
|---|---|
| `load(path)` / `save(rows, path)` | Atomic; `RegisterLocked` when Excel holds it |
| `next_number(rows, prefix='INQ', when=None) -> str` | |
| `fy_label(when=None) -> str` | Indian financial year |
| `from_message(message, details, *, prefix, rows, folder) -> dict` | |
| `find_by_thread(rows, message)` / `find(rows, inquiry_no)` / `add_thread(row, message)` | |
| `product_summary(message) -> str` | |
| `mark_quoted` / `mark_lost` / `mark_converted` / `mark_reply` / `note_reminder` | Status transitions |
| `update(rows, inquiry_no, changes) -> dict` | |
| `awaiting_followup(rows, after_days, max_reminders, today)` | |

### `quoting`

| Function | |
|---|---|
| `load_rates(path) -> list[RateItem]` | CSV or XLSX; `RateFileError` always carries the fix |
| `match_item(query, items, limit=5) -> list[Match]` | Each with a `reason` |
| `is_confident(matches, margin=1.6) -> bool` | |
| `load_cost_lines(path)` / `cost_sheet(lines, *, weight_kg, quantity) -> CostBreakdown` | |
| `rupees(value) -> Decimal` | `ROUND_HALF_UP` — the way an invoice rounds |
| `indian_currency(value) -> str` | Lakh grouping |
| `next_quote_number(rows, prefix='QTN', when=None) -> str` | |
| `render_text(quote, company='') -> str` / `write_csv(quote, path) -> str` | |
| `covering_letter_prompt(quote, inquiry_text, signature) -> str` | |
| `wire_weight_kg` / `coil_length_mm` / `spring_wire_weight_kg` / `density_for` | |

### `mailflow`

| Function | |
|---|---|
| `check(cfg, paths, *, state, knowledge, model, local_only, followup_days, max_reminders, catch_up_with_new, today) -> Result` | One run of the whole loop. **Never raises, never sends** |
| `extract_details(message, api_key, model) -> dict` | |
| `reply_intent(message, api_key, model) -> str` | |
| `local_intent(message) -> str` | What the reply plainly says, or `""` |
| `day_summary(paths, *, today) -> str` | The fifteen-second read at 6 p.m. |
| `Paths(root)` | `.inquiries` `.register_csv` `.sops` `.sop_log` `.client_sops` `.quotations` `.folder_for(no)` `.ensure()` |

### `po`

| Function | |
|---|---|
| `text_from(path) -> str` | Raises `POError` with advice |
| `looks_scanned(text, pages=1) -> bool` | |
| `find_attachment(message) -> str \| None` | |
| `extract(text, api_key, model='', *, source='') -> PurchaseOrder` | |
| `compare(order, quote, *, tolerance=Decimal('1')) -> list[Difference]` | |
| `summary(order, differences) -> str` | |

### `mailer`

| Function | |
|---|---|
| `parse_recipients(path) -> list[dict]` / `recipients_from_text(text)` | |
| `split_attachments(attachments)` | CSVs hold recipients; the rest is payload |
| `discovery_prompts(goal, finder='') -> (str, str)` | |
| `parse_structured_csv_text(text)` / `write_recipients_csv(rows, path)` | |
| `parse_draft(text) -> (subject, body)` / `is_prompt_echo(text) -> bool` | |
| `verify(cfg) -> str` / `is_configured(cfg) -> bool` / `smtp_for(address)` | |
| `clean_password(password) -> str` / `explain_error(error, address) -> str` | |
| `send_bulk(cfg, recipients, subject, body, files, delay, on_progress, should_stop)` | |

### `drafting`

| Function | |
|---|---|
| `available(cfg) -> (bool, str)` | Can we draft in the browser right now |
| `choose_agent(cfg) -> str` | The customer's own choice wins |
| `draft(cfg, prompt, *, purpose, attachments, agent, on_event, should_stop) -> Draft` | |
| `negotiation_prompt(...)` / `followup_prompt(...)` | |
| `load_policy(path) -> (text, attachments)` | The bargaining file |

`PREFERRED = ('Claude', 'ChatGPT', 'Perplexity')`.

### `sop`

`load_library(folder)` · `load_client_map(path)` · `for_client(address, rules,
library)` · `for_product(product, library)` · `pending(rules, library, log, *,
annual_days=365, today)` · `record_sent(...)` · `last_sent(log, address, code)`
· `covering_prompt(docs, customer, reason, signature)`.

### `boq`

`ensure_dxf(path) -> (dxf_path, notes)` · `measure(dxf_path) -> dict` ·
`apply_known_unit(q, unit_name)` · `filter_by_keywords(q, keywords)` ·
`write_quantities_csv(q, path)` · `summary_text(q)` · `classify_inputs(attachments)`
· `standards_prompt(...)` · `interpretation_prompt(...)` ·
`formatting_prompt(..., allow_derived=True, ...)`.

### `gerber`

`gather(paths) -> list[str]` · `split_jobs(paths)` · `classify(paths)` ·
`analyse(paths, snap_mm=0.01, on_progress=None) -> dict` · `crosscheck(job)` ·
`crosscheck_text(checks)` · `design_rules(files)` · `answers_text(job)` ·
`summary_text(job)` · `files_text(job)` · `agent_brief(job, context='')` ·
`write_report_csv(job, path)` · `write_summary_csv(jobs, path)`.

### `files` / `pathfinder` / `voice`

| Module | Surface |
|---|---|
| `files` | `attach(path)` · `attach_dir(path)` · `describe(att)` · `context_block(attachments)` · `routing_note(attachments)` · `upload_paths(attachments)` |
| `pathfinder` | `find(desc, cfg) -> dict` · `parse_description(desc, cfg)` · `list_dir_files(path, limit=15)` |
| `voice` | `available()` · `record_until(should_stop)` · `transcribe(wav, cfg) -> (text, lang)` · `record_and_transcribe(cfg, stop_key)` · `interpret(raw, cfg) -> dict` |

---

## 2.5 GUI support modules

| Module | Surface |
|---|---|
| `paths` | `is_frozen()` · `bundle_dir()` · `resource(*parts)` · `user_dir(*parts)` · `ensure_user_dir()` · `open_result(url)` · `reveal_result(path)` · `is_local_result(url)` · `app_root()` |
| `identity` | `current()` · `display_name(cfg)` · `reload()` · `activate(key)` · `clear()` · `view_as(mid)` · `viewing()` · `is_viewing_other()` · `hue()` · `describe()` |
| `roles` | `get(key)` · `label(key)` · `hue(key)` · `is_admin(key)` · `ordered()` · `default_agents(key, available)` |
| `workspace` | `root(cfg)` · `is_shared(cfg)` · `member_id(role, name)` · `load_team(cfg)` · `save_team(members, cfg)` · `upsert_member(...)` · `member_dir(mid, cfg, *parts)` · `ensure_member(mid, cfg)` · `runs_dir(mid, cfg)` · `files_dir(mid, cfg)` · `company_dir(cfg)` · `readable_members(cfg, identity)` · `may_read(cfg, identity, mid)` · `unreachable(cfg)` |
| `plans` | `features_for(plan_key)` · `label(f)` · `blurb(f)` · `pitch(f)` · `plan_of(features)` · `missing_from(plan_key)`. `ORDER = ('studio','works','complete')` |
| `dashboard_data` | `recent_runs(cfg, limit=6)` · `run_counts(cfg, days=7)` · `runs_per_day(cfg, days=7)` · `register_rows(cfg)` · `inquiry_stats(cfg, rows)` · `inquiries_per_day(cfg, rows, days=7)` · `register_view(cfg, rows)` · `waiting_view(cfg, rows)` · `rupees(value, compact=False)` · `status_tone(status)` |
| `favorites` | `load()` · `save(items)` · `add(path)` · `remove(path)` |
| `friendly` | Any error → `(title, plain English, numbered next steps)` |
| `theme` | `load_fonts()` · `apply_role(hue)` · `role_stylesheet(qss, hue)` + the Industry tokens |
| `i18n` | `start(cfg, app)` · `t(text)` · `install()` · `style_for_script(qss)` |

> **`friendly.py`'s rule:** never show someone a problem without showing them
> the next action. A message with no action is a phone call.

---

[← Data flow](03-data-flow.md) · [Index](README.md) · [Next: Licensing →](05-licensing.md)
