# Licence server — API and data model

Everything the backend does. Stack: **FastAPI + Postgres**, one service, hosted
on Render or Railway. Base URL `https://api.alphakore.in`.

Prerequisite reading: [`01-token-and-crypto.md`](01-token-and-crypto.md).

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
| `TRIAL_ALREADY_USED` | 409 | Device or email already trialled | "Your trial ended on 3 Sep 2026. Here's how to continue." |
| `INVALID_KEY` | 404 | No such licence key | "That licence key wasn't recognised — check for typos." |
| `LICENSE_REVOKED` | 403 | Manually revoked | "This licence has been cancelled. Contact support." |
| `LICENSE_EXPIRED` | 403 | Subscription lapsed | "Your subscription ended on X. Renew to carry on." |
| `SEAT_LIMIT_REACHED` | 409 | All seats in use | "All N seats are in use." + the device list |
| `DEVICE_NOT_ACTIVATED` | 404 | Refresh from an unknown/released device | Silently re-activate, then retry once |
| `RATE_LIMITED` | 429 | Brute force guard | "Too many attempts. Try again in a few minutes." |
| `INVALID_REQUEST` | 400 | Malformed | Generic — this is our bug, log it |

---

## Endpoints

### `POST /v1/trial/start`

```jsonc
// request
{ "email": "kiran@rsinfotech.in", "name": "Kiran", "org": "RS Infotech",
  "device_fp": "a3f9c2b81e4d7a05", "platform": "win32", "app_version": "1.1.0" }

// 200
{ "token": "PRSMv1.eyJ…", "expires_at": 1754904800,
  "trial_ends_at": 1756900000, "plan": "trial",
  "features": ["core","boq","email","reel"] }
```

Creates a customer (or matches an existing one by email), creates a trial
licence with `trial_days` (default **30**), records the device, returns a
token.

**The anti-reset check.** Refuse a new trial when *either* the `device_fp` has
trialled before, *or* the exact email has. Return `TRIAL_ALREADY_USED` with the
original end date in `detail` so the app can say something specific instead of
"no".

Do **not** block a whole email domain — a 60-person firm evaluating Prism on
three machines is a good outcome, not abuse.

Trials get **every** feature. A trial exists to sell the product.

---

### `POST /v1/activate`

```jsonc
// request
{ "key": "PRSM4K2XA9WQ7M3TYRB8HNVE",   // normalised: upper, no hyphens
  "device_fp": "a3f9c2b81e4d7a05", "platform": "darwin",
  "app_version": "1.1.0", "hostname_label": "kiran-macbook" }

// 200 — same shape as trial/start
```

1. `sha256` the normalised key → look up `licenses.key_hash`.
2. Reject if `status != 'active'`.
3. If this `device_fp` already holds a seat on this licence, **succeed** — a
   re-activation is idempotent, not a second seat.
4. Otherwise count active devices. `>= seats` → `SEAT_LIMIT_REACHED`, with the
   current device list in `detail` so the app can offer to release one.
5. Insert the device, issue a token.

`hostname_label` is a human label for the seat list ("kiran-macbook"). Purely
cosmetic, and worth having the first time a customer asks *which* five machines
are using their seats.

**Rate limit hard**: 10 attempts per IP per hour, 5 per `device_fp` per hour.
This is the only endpoint where guessing gains anything.

---

### `POST /v1/refresh`

```jsonc
{ "license_id": "lic_01HZX8K2M9", "device_fp": "a3f9c2b81e4d7a05",
  "app_version": "1.1.0" }
```

The workhorse — called on every app launch and every 12 hours while running.
Re-evaluates subscription status and returns a fresh 7-day token.

- Device released or unknown → `DEVICE_NOT_ACTIVATED`. The client re-activates
  from its stored key and retries **once**, which quietly heals the common case
  of an admin releasing the wrong seat.
- Subscription lapsed → `LICENSE_EXPIRED`. The client keeps its existing token
  until that token's own grace runs out. Do not expect the client to expire
  instantly on your say-so; the token is the authority.
- Updates `devices.last_seen`. **This is your usage telemetry** — free,
  privacy-preserving, and the basis of every renewal conversation. Who has not
  opened Prism in 30 days is exactly who is about to churn.

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
seats, device list with release buttons, invoices, renewal date.

---

### `POST /webhooks/razorpay`

Verify the signature header before anything else. Then:

| Event | Effect |
|---|---|
| `subscription.activated` | Issue the licence key, email it, `status='active'` |
| `subscription.charged` | Extend `current_period_end` |
| `subscription.halted` / `.cancelled` | `status='expired'` — takes effect within 7 days |
| `refund.processed` | `status='revoked'` |

**Idempotency is mandatory.** Razorpay retries. Insert `event_id` into
`webhook_events` with a unique constraint and no-op on conflict — otherwise a
retry double-extends a subscription.

---

### Admin endpoints

Behind a separate long random bearer token in the environment, and **not**
reachable on the same path prefix as the customer API.

```
POST /admin/licenses          issue a key (the invoice path — used most)
POST /admin/licenses/{id}/extend      extend trial or paid period
POST /admin/licenses/{id}/revoke
POST /admin/devices/{id}/release      free a stuck seat
GET  /admin/licenses?q=rsinfotech     search
```

Every one writes to `audit_log`. When a customer says "we never cancelled",
you want the record.

---

## Data model

```sql
-- Who is paying.
CREATE TABLE customers (
  id           TEXT PRIMARY KEY,            -- cus_01H…
  name         TEXT NOT NULL,
  email        TEXT NOT NULL UNIQUE,
  org          TEXT,
  country      TEXT DEFAULT 'IN',
  gstin        TEXT,                        -- Indian B2B will ask for this
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- What they bought. One row per subscription, trial or paid.
CREATE TABLE licenses (
  id           TEXT PRIMARY KEY,            -- lic_01H…
  customer_id  TEXT NOT NULL REFERENCES customers(id),
  key_hash     TEXT UNIQUE,                 -- sha256(normalised key). NULL for trials.
  kind         TEXT NOT NULL,               -- 'trial' | 'paid'
  plan         TEXT NOT NULL,               -- 'trial' | 'core' | 'business'
  features     TEXT[] NOT NULL,             -- ['core','boq','email']
  seats        INT  NOT NULL DEFAULT 1,
  status       TEXT NOT NULL DEFAULT 'active',  -- active | expired | revoked
  trial_days   INT,                         -- per-customer, extendable
  starts_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at   TIMESTAMPTZ NOT NULL,        -- trial end, or paid period end
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

-- Separate from licenses on purpose: it must survive the licence being
-- deleted, or deleting a trial row would hand out a fresh 30 days.
CREATE TABLE trial_claims (
  id          BIGSERIAL PRIMARY KEY,
  email       TEXT NOT NULL,
  device_fp   TEXT NOT NULL,
  license_id  TEXT REFERENCES licenses(id) ON DELETE SET NULL,
  claimed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX ON trial_claims (device_fp);
CREATE UNIQUE INDEX ON trial_claims (lower(email));

CREATE TABLE subscriptions (
  id                 BIGSERIAL PRIMARY KEY,
  license_id         TEXT NOT NULL REFERENCES licenses(id),
  provider           TEXT NOT NULL DEFAULT 'razorpay',
  provider_sub_id    TEXT UNIQUE,
  status             TEXT NOT NULL,
  current_period_end TIMESTAMPTZ,
  raw                JSONB
);

-- Idempotency. Without this, a webhook retry double-extends a subscription.
CREATE TABLE webhook_events (
  id           BIGSERIAL PRIMARY KEY,
  provider     TEXT NOT NULL,
  event_id     TEXT NOT NULL,
  payload      JSONB NOT NULL,
  received_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  processed_at TIMESTAMPTZ,
  UNIQUE (provider, event_id)
);

CREATE TABLE audit_log (
  id      BIGSERIAL PRIMARY KEY,
  actor   TEXT NOT NULL,          -- 'admin:parth' | 'webhook:razorpay' | 'system'
  action  TEXT NOT NULL,          -- 'license.issue' | 'trial.extend' | …
  target  TEXT,
  detail  JSONB,
  at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Three schema decisions worth defending

**`trial_claims` is its own table.** If the anti-reset check read from
`licenses`, then deleting a trial row — something you *will* do while testing,
or when tidying a duplicate customer — would silently hand that machine a fresh
30 days. The claim outlives the licence.

**`key_hash`, never the key.** The plaintext key exists in exactly two places:
the email you send, and the customer's machine. A database dump then contains
nothing that unlocks anything.

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
| Payments | Razorpay | ~2% + GST per txn |

Roughly **₹1,500–2,000/month** all in.

**Backups matter more than uptime here.** If the server is down for an hour,
nobody notices — the tokens are offline-valid for 7 days. If the database is
lost, every customer's seat and subscription record goes with it. Turn on daily
managed backups on day one and restore one, once, to prove it works.

**Staging**: run a second instance with its own keypair. The client reads
`PRISM_LICENSE_SERVER` to point at it — but only when
`not paths.is_frozen()`, so the override cannot exist in a release build.
