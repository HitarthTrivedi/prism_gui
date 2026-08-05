# Licence server — API and data model

Everything the backend does. Stack: **FastAPI + Postgres**, one service, hosted
on Render or Railway. Base URL `https://api.alphakore.in`.

Prerequisite reading: [`01-token-and-crypto.md`](01-token-and-crypto.md).

> **Admin-issued keys only.** There is no self-serve trial endpoint. Every
> install — trial or paid — requires a key we generate. A trial is simply a key
> with a short `days` value and no grace period. This removes an entire class of
> abuse (trial farming, disposable-email resets) and is *less* code than the
> self-serve alternative.

---

## Conventions

- All endpoints are `POST` except `GET /v1/me` and `GET /health`.
- JSON in, JSON out. `Content-Type: application/json`.
- Every client request carries `X-Prism-Version` (e.g. `1.1.0`) and
  `X-Prism-Platform` (`linux` / `darwin` / `win32`). These cost nothing and
  make support diagnosis possible.
- Errors use one envelope, always:

```json
{ "error": { "code": "SEAT_LIMIT_REACHED",
             "message": "All 5 seats on this licence are in use.",
             "detail": { "seats": 5, "in_use": 5 } } }
```

**`message` is shown to the user verbatim.** Write it as customer-facing copy,
not as a developer log line. The client only writes its own copy for network
failures, where the server said nothing.

### Error codes

| Code | HTTP | When | What the user sees |
|---|---|---|---|
| `INVALID_KEY` | 404 | No such licence key | "That licence key wasn't recognised — check for typos." |
| `LICENSE_REVOKED` | 403 | Manually revoked | "This licence has been cancelled. Contact support." |
| `LICENSE_EXPIRED` | 403 | Trial ended or subscription lapsed | "Your trial ended on X. Get in touch to continue." |
| `SEAT_LIMIT_REACHED` | 409 | All seats in use | "All N seats are in use." + the device list |
| `DEVICE_NOT_ACTIVATED` | 404 | Refresh from an unknown/released device | Silently re-activate, then retry once |
| `RATE_LIMITED` | 429 | Brute force guard | "Too many attempts. Try again in a few minutes." |
| `INVALID_REQUEST` | 400 | Malformed | Generic — this is our bug, log it |

---

## Endpoints

### `POST /v1/activate`

The only way into the product.

```jsonc
// request
{ "key": "PRSM4K2XA9WQ7M3TYRB8HNVE",   // normalised: upper, no hyphens
  "device_fp": "a3f9c2b81e4d7a05", "platform": "darwin",
  "app_version": "1.1.0", "hostname_label": "kiran-macbook" }

// 200
{ "token": "PRSMv1.eyJ…", "expires_at": 1754904800,
  "license_ends_at": 1755600000, "plan": "trial", "kind": "trial",
  "features": ["core","boq"], "seats": 2 }
```

1. `sha256` the normalised key → look up `licenses.key_hash`.
2. Reject if `status != 'active'` or `now > expires_at`.
3. If this `device_fp` already holds a seat on this licence, **succeed** — a
   re-activation is idempotent, not a second seat.
4. Otherwise count active devices. `>= seats` → `SEAT_LIMIT_REACHED`, with the
   current device list in `detail` so the app can offer to release one.
5. Insert the device, issue a token.

`hostname_label` is a human label for the seat list ("kiran-macbook"). Purely
cosmetic, and worth having the first time a customer asks *which* five machines
are using their seats.

**Rate limit hard**: 10 attempts per IP per hour, 5 per `device_fp` per hour.
This is the only endpoint where guessing gains anything, and with admin-only
issuance it is the *entire* public attack surface.

---

### `POST /v1/refresh`

The workhorse — called on every app launch and every 12 hours while running.
Re-evaluates licence status and returns a fresh 7-day token.

```jsonc
{ "license_id": "lic_01HZX8K2M9", "device_fp": "a3f9c2b81e4d7a05",
  "app_version": "1.1.0", "payload_etag": "pl_7c1f" }
```

- Device released or unknown → `DEVICE_NOT_ACTIVATED`. The client re-activates
  from its stored key and retries **once**, which quietly heals the common case
  of an admin releasing the wrong seat.
- Licence expired → `LICENSE_EXPIRED`. The client keeps its existing token
  until that token's own expiry. The token is the authority, not this response.
- Updates `devices.last_seen`. **This is your usage telemetry** — free,
  privacy-preserving, and the basis of every renewal conversation. Who has not
  opened Prism in 30 days is exactly who is about to churn.
- If `payload_etag` is stale, the response sets `"payload_stale": true` and the
  client re-fetches (below).

---

### `POST /v1/authorize`

Live permission for one run, or one add-on being opened. **This is what makes
the server authoritative** rather than the cached token.

```jsonc
// request
{ "license_id": "lic_…", "device_fp": "a3f9c2b81e4d7a05",
  "action": "run",            // run | addon
  "feature": "core", "app_version": "1.1.0" }

// 200
{ "allowed": true, "run_id": "run_72fc6123e48452b9",
  "token": "PRSMv1.eyJ…", "expires_at": …, "license_ends_at": …,
  "features": ["core","boq"], "plan": "trial", "kind": "trial", "seats": 2 }
```

- Called at the **start** of a run and never during one. A pipeline is tens of
  minutes of browser automation; failing it half way discards real work for a
  reason the customer cannot act on.
- Returns a fresh token too, so authorising doubles as a refresh — one round
  trip on the path the customer is actually waiting on.
- Feature not in the licence → `FEATURE_NOT_LICENSED`, with `included` in
  `detail` so the app can say what they *do* have.
- Revoked or expired → refused immediately. This is the whole point of going
  online: revocation bites on the next run, not whenever a token lapses.
- Writes the `run`/`addon` usage event, which is what `run_id` then ties
  stage events to.

---

### `POST /v1/usage`

```jsonc
{ "license_id": "lic_…", "device_fp": "…", "run_id": "run_…",
  "app_version": "1.1.0",
  "events": [ {"kind":"groq","prompt_tokens":1840,"completion_tokens":512,"ms":1100},
              {"kind":"stage","tool":"Claude","stage":"brains","ms":51000} ] }
```

`kind` is `run` | `stage` | `groq` | `addon`. Returns `{"recorded": N}` and
**never fails loudly** — a metering write that 500s must not become a
customer-visible error, because nothing they do depends on it. An unknown
licence returns `{"recorded": 0}` rather than an error.

**Records shapes and counts, never content.** No brief, no prompt, no output.
A BOQ query names a real project on a real site; storing it would turn billing
infrastructure into something needing a data-processing agreement, for data we
have no use for. There is a test asserting the schema has nowhere to put it.

**Token counts are honest only for Groq.** Those come back in the API
response. Claude / ChatGPT / Perplexity stages are driven through a browser —
no usage figure exists — so they are counted as stages per tool. Do not quote
`total_tokens` at a customer as though it covered everything they ran.

---

### `POST /v1/payload` — Tier 2

Delivers the engine payload: the strings that make Prism work, which are **not
in the shipped build**.

```jsonc
// request
{ "license_id": "lic_…", "device_fp": "a3f9c2b81e4d7a05", "app_version": "1.1.0" }

// 200
{ "etag": "pl_7c1f", "ciphertext": "<base64 ChaCha20-Poly1305, 12-byte nonce prefixed>",
  "expires_at": 1754904800 }
```

**What's in the payload** — verified against the current code:

| Content | Source today | Why it's IP |
|---|---|---|
| `AGENT_REGISTRY` specialty strings, budgets, URLs | `core/agents.py` | The tool knowledge |
| **CSS selectors** (`textarea_selector`, `response_selector`) | `core/agents.py`, used across `core/automation.py` | Hard-won, breaks constantly, the most maintenance-heavy asset in the product |
| Three prompt templates | `core/router.py` (brief expander, plan auditor, routing brain) | The routing IP |
| Shipped field notes | `prism_terminal/pros_cons.txt` | Written from real experience |

**What stays local:** the code that assembles them, and the user's own
`~/.prism/tool_notes.md`. That file is a documented feature — `_tool_notes()`
merges user notes with shipped ones — and must keep working untouched.

**Encryption:** ChaCha20-Poly1305 (`cryptography`, AEAD). The content key is
delivered in the `pk` claim of the signed licence token, so the cached
ciphertext is inert without a valid token. See
[`01-token-and-crypto.md`](01-token-and-crypto.md).

**Rotate the content key and re-encrypt on every token refresh** — at most
every 7 days.

### Why rotation matters more than it looks

This is the property that makes Tier 2 worth building, and it is specific to
this product.

Those CSS selectors **rot**. Claude, ChatGPT and Kimi change their DOM without
warning; keeping 18 selector sites working is ongoing maintenance, which is
exactly why they live in a registry rather than inline.

So a cracked copy — patched binary, frozen payload, no more refreshes — does not
stay working. It degrades on its own as the tools it drives change underneath
it, within weeks, with no action from us. **The payload is perishable.** A
crack does not yield a permanent free copy; it yields a copy with an expiry date
set by third parties.

The same mechanism is a straightforward operations win, independent of
licensing: **when a selector breaks, we fix it server-side and every customer is
working within hours — no build, no release, no re-download.** Today that same
fix requires shipping four platform builds and asking every customer to update.
Build this for that reason alone and the licensing benefit is a bonus.

---

### `POST /v1/deactivate`

```jsonc
{ "license_id": "lic_…", "device_fp": "a3f9c2b81e4d7a05" }
```

Sets `devices.released_at`, freeing the seat. Called by *Deactivate this
device* in Setup → Licence. Always return 200 — a deactivation that "fails"
strands a seat and creates a ticket.

---

### `GET /v1/me`

Bearer auth with the licence key. Powers the customer portal (Phase 2): plan,
seats, device list with release buttons, renewal date.

---

### `POST /webhooks/razorpay` — Phase 2

Not needed for Phase 1; every licence is issued by hand. When it lands, verify
the signature header first, then:

| Event | Effect |
|---|---|
| `subscription.activated` | Issue the licence key, email it, `status='active'` |
| `subscription.charged` | Extend `expires_at` |
| `subscription.halted` / `.cancelled` | `status='expired'` |
| `refund.processed` | `status='revoked'` |

**Idempotency is mandatory.** Razorpay retries. Insert `event_id` into
`webhook_events` with a unique constraint and no-op on conflict — otherwise a
retry double-extends a subscription.

---

### Admin endpoints

**This is the primary interface in Phase 1**, not a side feature. Behind a
separate long random bearer token in the environment, and not reachable on the
same path prefix as the customer API.

```
POST /admin/licenses                   issue a key — trial or paid
POST /admin/licenses/{id}/extend       add days
POST /admin/licenses/{id}/revoke
POST /admin/devices/{id}/release       free a stuck seat
POST /admin/payload                    publish a new payload version
GET  /admin/licenses?q=rsinfotech      search
```

Every one writes to `audit_log`. When a customer says "we never cancelled", you
want the record.

---

## Data model

```sql
-- Who is paying (or evaluating).
CREATE TABLE customers (
  id           TEXT PRIMARY KEY,            -- cus_01H…
  name         TEXT NOT NULL,
  email        TEXT NOT NULL UNIQUE,
  org          TEXT,
  country      TEXT DEFAULT 'IN',
  gstin        TEXT,                        -- Indian B2B will ask for this
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- What they hold. One row per licence, trial or paid.
CREATE TABLE licenses (
  id           TEXT PRIMARY KEY,            -- lic_01H…
  customer_id  TEXT NOT NULL REFERENCES customers(id),
  key_hash     TEXT NOT NULL UNIQUE,        -- sha256(normalised key)
  kind         TEXT NOT NULL,               -- 'trial' | 'paid'
  plan         TEXT NOT NULL,               -- 'trial' | 'core' | 'business'
  features     TEXT[] NOT NULL,             -- ['core','boq','email']
  seats        INT  NOT NULL DEFAULT 1,
  grace_days   INT  NOT NULL DEFAULT 3,     -- ALWAYS 0 for kind='trial'
  -- Token lifetime in hours. NOT an offline allowance — the client refuses to
  -- start work it cannot get authorised, full stop. This only sets how long
  -- the cached token stays fresh enough to drive the app's own display.
  offline_hours INT NOT NULL DEFAULT 1,
  status       TEXT NOT NULL DEFAULT 'active',  -- active | expired | revoked
  starts_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at   TIMESTAMPTZ NOT NULL,        -- the hard end. 10 days, 30, a year.
  notes        TEXT,                        -- "PO 4471, paid by NEFT 12 Aug"
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per activated machine. This is the seat.
CREATE TABLE devices (
  id             BIGSERIAL PRIMARY KEY,
  license_id     TEXT NOT NULL REFERENCES licenses(id),
  device_fp      TEXT NOT NULL,
  platform       TEXT,
  app_version    TEXT,
  hostname_label TEXT,
  first_seen     TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen      TIMESTAMPTZ NOT NULL DEFAULT now(),
  released_at    TIMESTAMPTZ,
  UNIQUE (license_id, device_fp)
);
CREATE INDEX ON devices (license_id) WHERE released_at IS NULL;

-- Tier 2. Versioned so a bad payload can be rolled back instantly.
CREATE TABLE payloads (
  id            BIGSERIAL PRIMARY KEY,
  etag          TEXT NOT NULL UNIQUE,       -- pl_7c1f
  min_version   TEXT NOT NULL,              -- lowest app version this suits
  content       JSONB NOT NULL,             -- registry + selectors + prompts + notes
  published_at  TIMESTAMPTZ,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE subscriptions (            -- Phase 2
  id                 BIGSERIAL PRIMARY KEY,
  license_id         TEXT NOT NULL REFERENCES licenses(id),
  provider           TEXT NOT NULL DEFAULT 'razorpay',
  provider_sub_id    TEXT UNIQUE,
  status             TEXT NOT NULL,
  current_period_end TIMESTAMPTZ,
  raw                JSONB
);

-- Idempotency. Without this, a webhook retry double-extends a subscription.
CREATE TABLE webhook_events (           -- Phase 2
  id           BIGSERIAL PRIMARY KEY,
  provider     TEXT NOT NULL,
  event_id     TEXT NOT NULL,
  payload      JSONB NOT NULL,
  received_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  processed_at TIMESTAMPTZ,
  UNIQUE (provider, event_id)
);

-- What customers consumed. Shapes and counts only — see /v1/usage.
CREATE TABLE usage_events (
  id                BIGSERIAL PRIMARY KEY,
  license_id        TEXT NOT NULL REFERENCES licenses(id),
  device_fp         TEXT NOT NULL,
  run_id            TEXT NOT NULL DEFAULT '',
  kind              TEXT NOT NULL,        -- run | stage | groq | addon
  tool              TEXT NOT NULL DEFAULT '',
  stage             TEXT NOT NULL DEFAULT '',
  prompt_tokens     INT  NOT NULL DEFAULT 0,   -- Groq only; browser stages
  completion_tokens INT  NOT NULL DEFAULT 0,   -- have no usage to read
  ok                BOOLEAN NOT NULL DEFAULT TRUE,
  ms                INT  NOT NULL DEFAULT 0,
  app_version       TEXT NOT NULL DEFAULT '',
  at                BIGINT NOT NULL
);
CREATE INDEX ON usage_events (license_id, at);

CREATE TABLE audit_log (
  id      BIGSERIAL PRIMARY KEY,
  actor   TEXT NOT NULL,          -- 'admin:parth' | 'webhook:razorpay' | 'system'
  action  TEXT NOT NULL,          -- 'license.issue' | 'license.extend' | …
  target  TEXT,
  detail  JSONB,
  at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Schema decisions worth defending

**No `trial_claims` table.** An earlier draft needed one to stop people
re-registering for trials. Admin-only issuance removes the requirement entirely
— there is no endpoint to farm.

**`grace_days` lives on the licence, and is 0 for trials.** A 10-day trial must
end on day 10. Grace exists to absorb failed card payments on *paid* accounts;
applying it to trials just makes every trial 13 days and confuses the deadline
you told the customer.

**`key_hash`, never the key.** The plaintext key exists in exactly two places:
the email you send, and the customer's machine. A database dump then contains
nothing that unlocks anything.

**`payloads` is versioned with an `etag` and a `min_version`.** A payload is
live code-adjacent content pushed to every customer at once; you will
eventually publish a bad one, and rolling back must be a single row update, not
a redeploy.

**`licenses.notes` is free text and it matters.** "PO 4471, paid by NEFT on 12
Aug, contact Kiran" is what makes a renewal call possible eight months later.
Structured billing data will never capture it.

---

## Hosting

| Thing | Choice | Cost |
|---|---|---|
| App | Render Web Service, or Railway | ~$7/mo |
| Database | Managed Postgres, same provider | ~$7/mo |
| Domain | `api.alphakore.in` | already owned |
| TLS | Automatic | — |

Roughly **₹1,500–2,000/month**.

**Backups matter more than uptime here.** If the server is down for an hour,
nobody notices — tokens are offline-valid for 7 days and the payload is cached.
If the database is lost, every customer's seat and licence record goes with it.
Turn on daily managed backups on day one and restore one, once, to prove it
works.

**Staging**: a second instance with its own keypair. The client reads
`PRISM_LICENSE_SERVER` to point at it — but only when
`not paths.is_frozen()`, so the override cannot exist in a release build.
