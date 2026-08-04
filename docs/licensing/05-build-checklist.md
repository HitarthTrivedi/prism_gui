# Phase 1 build checklist

Ships as **Prism v1.1**. Roughly two weeks of focused work. Ordered so each
step is testable before the next one starts.

Open decisions that could change this are listed at the end of
[`LICENSING.md`](../../LICENSING.md) — none of them block starting.

---

## Week 1 — server and crypto

### Day 1 · Foundations
- [ ] Generate the Ed25519 keypair. Private key into the host's secret store,
      paper backup sealed. Public key written to `licensing/keys.py`.
- [ ] New backend repo: FastAPI, Postgres, the schema from
      [`02-api-and-data.md`](02-api-and-data.md), migrations from commit one.
- [ ] `GET /health`.
- [ ] Deploy to Render/Railway behind `api.alphakore.in`. **Turn on daily
      backups now**, not later.

### Day 2 · Token issuance
- [ ] Signing function → the `PRSMv1.…` format.
- [ ] **Commit a test vector**: a fixed token, its public key, and the expected
      parsed claims. Both the server and the client verify against this same
      file. Cheap now; the only thing that will make a cross-platform signature
      bug findable later.
- [ ] Licence key generation: Crockford Base32, checksum character, `sha256`
      stored and plaintext returned exactly once.

### Day 3 · Customer endpoints
- [ ] `POST /v1/trial/start` — including the `trial_claims` anti-reset check.
- [ ] `POST /v1/activate` — idempotent re-activation, seat counting.
- [ ] `POST /v1/refresh`, `POST /v1/deactivate`.
- [ ] The error envelope and every code in the table, with customer-facing
      `message` text written properly.
- [ ] Rate limits on `activate`.

### Day 4 · Admin
- [ ] `POST /admin/licenses` (issue), `/extend`, `/revoke`,
      `/devices/{id}/release`, search.
- [ ] `audit_log` written by all of them.
- [ ] Bearer auth, separate token, separate path prefix.
- [ ] Plain HTML admin page or an authenticated `/docs` — do **not** spend this
      week building an admin UI. You are the only operator and `curl` works.

### Day 5 · Server tests
- [ ] Second trial from the same device → `TRIAL_ALREADY_USED`
- [ ] Second trial from the same email → `TRIAL_ALREADY_USED`
- [ ] Deleting a trial licence row → still blocked (proves `trial_claims`
      outlives it — the bug this table exists to prevent)
- [ ] Seat N+1 → `SEAT_LIMIT_REACHED`; re-activating an existing device → 200
- [ ] Release a seat, then activate → 200
- [ ] Revoked licence → `LICENSE_REVOKED`

---

## Week 2 — client

### Day 6 · The `licensing/` package
- [ ] `device.py` — fingerprint on all three platforms **plus** both fallbacks.
      Test on real Windows and macOS machines, not just Linux; this is the one
      module where per-OS behaviour is the entire point.
- [ ] `token.py` — verification exactly in the order given in
      [`01-token-and-crypto.md`](01-token-and-crypto.md), signature checked
      over the **raw base64 segment**, never re-serialised JSON.
- [ ] `store.py` — `~/.prism/license.json`, `0600`, clock high-water mark,
      corrupt-file tolerance.
- [ ] `state.py` — the five-state machine.
- [ ] `client.py` — off-thread, 5s timeout, no retry storm.
- [ ] Unit tests: the full matrix at the end of
      [`03-client-integration.md`](03-client-integration.md).

### Day 7 · Dialogs
- [ ] `dialogs/license_dialog.py` — start trial / enter key, in the existing
      Industry visual language.
- [ ] `dialogs/paywall.py` — a small sheet naming the add-on, what it does, and
      a Contact/Buy action.
- [ ] Expired state screen.

### Day 8 · Gates
- [ ] Launch gate in [`main.py`](../../main.py).
- [ ] `require()` on `_open_boq`, `_open_email`, `_open_reel`, `_route`,
      `_run_pipeline` in [`main_window.py`](../../main_window.py).
- [ ] Reel/Studio entitlement in the `_run_pipeline` pre-flight — the routed
      path, which the sidebar gate alone does not cover.
- [ ] Lock state in [`widgets/sidebar.py`](../../widgets/sidebar.py).
- [ ] Grace banner.

### Day 9 · Setup, packaging
- [ ] Licence section in [`dialogs/setup_dialog.py`](../../dialogs/setup_dialog.py),
      deep-linkable from the rail like the existing sections.
- [ ] PyNaCl in `hiddenimports` in [`packaging/prism.spec`](../../packaging/prism.spec).
- [ ] Test-vector verification added to `_selftest()` in
      [`main.py`](../../main.py).
- [ ] `PRISM_LICENSE_SERVER` override gated on `not paths.is_frozen()`.

### Day 10 · Cross-platform proving
- [ ] CI builds all four targets green.
- [ ] **Install the real build on real Windows, macOS and Linux machines and
      run the full journey**: trial → expiry → activation → add-on unlock →
      deactivate. Not a source checkout. The whole class of bug this catches —
      frozen native extensions, per-OS machine ids, path handling — is
      invisible from a dev environment, and the repo's own history shows two
      such bugs reaching customers already.
- [ ] Verify the fingerprint is stable across reboots on each OS.
- [ ] Docs: update [`GETTING_STARTED.md`](../../GETTING_STARTED.md) with the
      trial/activation step, and [`README.md`](../../README.md).

---

## Definition of done

Phase 1 is finished when all of these are true on a **packaged build**, on all
three operating systems:

1. Fresh install → trial dialog → 30 days, everything unlocked.
2. Deleting `~/.prism` does **not** grant a second trial.
3. Setting the clock back does **not** extend the trial.
4. Hand-editing `license.json` to add a feature → app rejects it.
5. Trial expiry → app opens, History readable, new runs blocked.
6. Entering a valid key → correct add-ons unlock, wrong ones stay locked.
7. Pulling the network → app keeps working with no error dialog.
8. Stopping the licence server → every customer keeps working.
9. A seat can be released and reused.
10. A trial can be extended from admin with no new build.

Item 8 is the one to test deliberately, by actually stopping the service. It is
the property the whole offline-token design exists to provide, and the only way
to know it holds is to try it.

---

## Explicitly not in Phase 1

Deferred on purpose. Do not let them creep in.

| Deferred | Why | When |
|---|---|---|
| Razorpay self-serve | Manual invoicing is the real first path for Indian B2B | Phase 2 |
| Customer portal | You can run it from admin at this volume | Phase 2 |
| Self-service seat release | Manual release is one endpoint call | Phase 2 |
| Dunning emails | No self-serve subscriptions to dun yet | Phase 2 |
| Offline activation | Only if a customer actually has an air-gapped machine | On demand |
| Groq proxying / metering | Big strategic change, needs paying customers first | Phase 3 |
| Obfuscation | Bad cost/benefit — see the threat model | Never |
