# Build checklist — Tier 1 + Tier 2

Ships as **Prism v1.1**. Roughly **three weeks** of focused work: two for the
licence system (T1), one for moving the engine payload off the client (T2).

Ordered so each step is testable before the next starts. Tier 3 is deliberately
out of scope — see [`06-tier-3-future.md`](06-tier-3-future.md).

> **Progress — Weeks 1 and 2 are done. Tier 1 is complete and usable.**
>
> · **Server** — `../../../license_server/` (sibling of this repo, ready to
>   split out): FastAPI + SQLAlchemy + Alembic, activate/refresh/deactivate,
>   the full admin surface, rate limiting, audit log. **30 tests passing.**
> · **Client** — `licensing/` (token, device, store, status, http, key format),
>   `devtools/mint.py`, packaging wired up. **48 tests passing.**
> · **Proven end to end**: the server issues a 10-day trial key, the client
>   activates against it and verifies the signature, an admin extension reaches
>   the next refresh, and a revoked licence keeps working on the cached token
>   for its remaining days — exactly as designed.
>
> · **UI** — activation / expired / problem screens, the add-on paywall,
>   padlocks in the rail, the licence banner, and a Licence section in Setup.
>   **12 gate tests** drive the real `MainWindow` and prove a locked add-on
>   does not open, not merely that the state says it shouldn't.
>
> **90 tests green** (60 client, 30 server).
>
> Left: deploy + production keypair (Day 1), cross-platform proving on real
> packaged builds (Day 10), and all of Tier 2 (Week 3).

---

## Week 1 — server and crypto (T1)

### Day 1 · Foundations
- [ ] Generate the Ed25519 keypair. Private key into the host's secret store,
      paper backup sealed. Public key written to `licensing/keys.py`.
- [x] New backend repo: FastAPI, Postgres, the schema from
      [`02-api-and-data.md`](02-api-and-data.md), migrations from commit one.
- [x] `GET /health`.
- [ ] Deploy to Render/Railway behind `api.alphakore.in`. **Turn on daily
      backups now**, not later.

### Day 2 · Token issuance
- [x] Signing function → the `PRSMv1.…` format.
- [x] **Commit a test vector**: a fixed token, its public key, and the expected
      parsed claims. Server and client verify against the same file. Cheap now;
      the only thing that will make a cross-platform signature bug findable
      later.
- [x] `exp` never exceeds `lend` — the last token of a 10-day trial expires on
      day 10, not day 14.
- [x] Licence key generation: Crockford Base32, checksum character, `sha256`
      stored and plaintext returned exactly once.

### Day 3 · Customer endpoints
- [x] `POST /v1/activate` — idempotent re-activation, seat counting.
- [x] `POST /v1/refresh`, `POST /v1/deactivate`.
- [x] The error envelope and every code in the table, with customer-facing
      `message` text written properly.
- [x] Rate limits on `activate` — with admin-only issuance this is the entire
      public attack surface.

### Day 4 · Admin
- [x] `POST /admin/licenses` (issue trial or paid), `/extend`, `/revoke`,
      `/devices/{id}/release`, search.
- [x] `grace_days` forced to `0` whenever `kind == 'trial'`. Enforce it
      server-side, not by remembering to pass it.
- [x] `audit_log` written by all of them.
- [x] Bearer auth, separate token, separate path prefix.
- [x] Plain HTML admin page or an authenticated `/docs` — do **not** spend this
      week building an admin UI. You are the only operator and `curl` works.

### Day 5 · Server tests
- [x] Seat N+1 → `SEAT_LIMIT_REACHED`; re-activating an existing device → 200
- [x] Release a seat, then activate → 200
- [x] Revoked licence → `LICENSE_REVOKED`
- [x] Expired licence → `LICENSE_EXPIRED`
- [x] A 10-day trial issued today yields a token that expires on day 10
- [x] Extending by 5 days moves `lend` and the next token follows it

---

## Week 2 — client (T1)

### Day 6 · The `licensing/` package
- [x] `device.py` — fingerprint on all three platforms **plus** both fallbacks.
      Test on real Windows and macOS machines, not just Linux; this is the one
      module where per-OS behaviour is the entire point.
- [x] `token.py` — verification exactly in the order given in
      [`01-token-and-crypto.md`](01-token-and-crypto.md), signature checked
      over the **raw base64 segment**, never re-serialised JSON.
- [x] `store.py` — `~/.prism/license.json`, `0600`, clock high-water mark,
      corrupt-file tolerance.
- [x] `status.py` — the five-state machine. (Not `state.py`: the package exposes
      a `state()` function and the names collide.)
- [x] `client.py` — off-thread, 5s timeout, no retry storm.
- [x] Unit tests: the licence half of the matrix in
      [`03-client-integration.md`](03-client-integration.md).

### Day 7 · Dialogs
- [x] `dialogs/license_dialog.py` — activation only. **No trial button**, in the
      existing Industry visual language.
- [x] `dialogs/paywall.py` — a small sheet naming the add-on, what it does, and
      a Contact action.
- [x] Expired screen — shows `lend`, your contact details, and a key field.

### Day 8 · Gates
- [x] Launch gate in [`main.py`](../../main.py).
- [x] `require()` on `_open_boq`, `_open_email`, `_open_reel`, `_route`,
      `_run_pipeline` in [`main_window.py`](../../main_window.py).
- [x] Reel/Studio entitlement in the `_run_pipeline` pre-flight — the routed
      path, which the sidebar gate alone does not cover.
- [x] Lock state in [`widgets/sidebar.py`](../../widgets/sidebar.py).
- [x] Grace banner; UI shows `lend`, never `exp`.

### Day 9 · Setup, packaging
- [x] Licence section in [`dialogs/setup_dialog.py`](../../dialogs/setup_dialog.py),
      deep-linkable from the rail like the existing sections.
- [x] `cryptography` leaf modules in `hiddenimports` in [`packaging/prism.spec`](../../packaging/prism.spec).
- [x] **Delete the dead `block_cipher` lines** from the spec — PyInstaller 6
      removed bytecode encryption and leaving them there implies protection
      that does not exist.
- [x] Test-vector verification added to `_selftest()` in [`main.py`](../../main.py).
- [x] `PRISM_LICENSE_SERVER` override gated on `not paths.is_frozen()`.

### Day 10 · T1 proving
- [ ] CI builds all four targets green.
- [ ] Real packaged builds on real Windows, macOS and Linux: activate → use →
      expire → re-activate → deactivate.
- [ ] Fingerprint stable across reboots on each OS.

---

## Week 3 — payload off the client (T2)

### Day 11 · Extract the payload
- [ ] Pull into one JSON document: `AGENT_REGISTRY` specialty strings, budgets,
      URLs and **selectors** from [`core/agents.py`](../../prism_terminal/core/agents.py);
      the three prompt templates from [`core/router.py`](../../prism_terminal/core/router.py);
      the contents of `pros_cons.txt`.
- [ ] Define and version its schema. The client refuses a payload that fails it.
- [ ] Leave a **skeleton** registry in the code — tool names and structure, no
      specialties, no prompts, no selectors. The submodule must still import and
      the CLI must still run standalone.

### Day 12 · Serve it
- [ ] `payloads` table, `POST /admin/payload`, `/publish`, rollback.
- [ ] `POST /v1/payload` — ChaCha20-Poly1305, content key in the token's `pk`
      claim, `petag` version tagging.
- [ ] Key rotation and re-encryption on every refresh.

### Day 13 · Consume it
- [ ] `licensing/payload.py` — fetch, decrypt in memory, cache ciphertext to
      `~/.prism/payload.enc`, schema-check, never write plaintext.
- [ ] Injection in [`core_bridge.py`](../../core_bridge.py) — **not** by editing
      `core/`. The submodule is shared with the unlicensed CLI and must stay
      untouched.
- [ ] Confirm `_tool_notes()` still merges `~/.prism/tool_notes.md`. That user
      feature must survive.

### Day 14 · Payload tests
- [ ] The payload half of the matrix in
      [`03-client-integration.md`](03-client-integration.md).
- [ ] **The shell test**: a build with no key ever activated must open, route
      nothing, and crash nowhere.
- [ ] **The inert-cache test**: valid `payload.enc`, deleted token → refuses to
      decrypt.
- [ ] Publish a deliberately broken payload to staging, confirm the client
      refuses it and keeps its previous cache.

### Day 15 · Ship
- [ ] Full journey on all three OSes, packaged builds only.
- [ ] Docs: [`GETTING_STARTED.md`](../../GETTING_STARTED.md) gains the
      activation step; [`README.md`](../../README.md) and
      [`BUILD.md`](../../BUILD.md) updated.
- [ ] Issue yourself a 10-day trial key and live with it for a day.

---

## Definition of done

All true on a **packaged build**, on all three operating systems:

**Tier 1**
1. Fresh install, no key → activation screen, nothing else reachable.
2. A 10-day key grants exactly 10 days. Day 11 blocks new runs.
3. App still opens after expiry; History and past outputs readable.
4. Hand-editing `license.json` to add a feature → rejected.
5. Clock set back 40 days → does not extend anything.
6. Deleting `~/.prism` → back to the activation screen, not a free reset.
7. Seat limits hold; a seat can be released and reused.
8. Extending a trial from admin works with no new build.
9. Network pulled → keeps working, no error dialog.
10. Licence server stopped → every customer keeps working.

**Tier 2**
11. A build that never had a key routes nothing — no prompts, no selectors.
12. `payload.enc` without a valid token will not decrypt.
13. A selector fix published server-side reaches a running client within 12h.
14. A bad payload is refused and the previous one is kept.
15. `~/.prism/tool_notes.md` still reaches the routing prompt.

Items 10 and 11 are the ones to test deliberately, by actually stopping the
service and by actually running a never-activated build. They are the two
properties this whole design exists to provide, and the only way to know they
hold is to try them.

---

## Explicitly not in scope

| Deferred | Why | When |
|---|---|---|
| Self-serve trial signup | You hand-pick who evaluates | Maybe never |
| Razorpay self-serve | Manual invoicing is the real first path | Phase 2 |
| Customer portal | Admin covers it at this volume | Phase 2 |
| Self-service seat release | Manual release is one endpoint call | Phase 2 |
| Offline activation | Only if a customer has an air-gapped machine | On demand |
| Server-side routing (T3) | Costs offline use and customer privacy | [`06`](06-tier-3-future.md) |
| Nuitka | Build fragility across 4 targets; revisit if adversarial | On demand |
| Obfuscation | Bad cost/benefit at any tier | Never |
