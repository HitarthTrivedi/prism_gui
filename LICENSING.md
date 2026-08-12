# Licensing & Subscription Plan

Plan for turning Prism from a freely-distributed build into a licensed product:
**every install runs on a key we issue by hand**, trials end on the day we set,
and add-ons unlock per licence — backed by a hosted licence server.

**Decided:** build Tier 1 + Tier 2 (§1). Tier 3 is deferred and specified in
[`06-tier-3-future.md`](docs/licensing/06-tier-3-future.md).

**Status: in progress — Tier 1 works end to end.**

- **Licence server** — `../license_server/` (sibling directory, ready to become
  its own repo). FastAPI + Postgres/SQLite + Alembic; activate, refresh,
  deactivate, and the full admin surface. 30 tests.
- **Client** — `licensing/` in this repo, plus `devtools/mint.py`. 48 tests.
- **Proven together**: server issues a 10-day trial key → client activates and
  verifies the signature → admin extension reaches the next refresh → a revoked
  licence keeps working on its cached token for the remaining days, as designed.

Left: deployment and the production keypair, the dialogs and gates in the app,
cross-platform proving, and all of Tier 2. Live progress in the checkboxes of
[`05-build-checklist.md`](docs/licensing/05-build-checklist.md).

This file holds the **strategy and the reasoning**. The detailed specs live in
[`docs/licensing/`](docs/licensing/):

| Doc | What it answers | For |
|---|---|---|
| [00 · Overview](docs/licensing/00-overview.md) | How Prism gets sold, in plain English. **Start here.** | Anyone |
| [01 · Token & crypto](docs/licensing/01-token-and-crypto.md) | What a licence *is*, and why it can't be forged | Implementer |
| [02 · API & data](docs/licensing/02-api-and-data.md) | Every endpoint, the Postgres schema, hosting | Backend |
| [03 · Client integration](docs/licensing/03-client-integration.md) | Exactly what changes in this repo, and where | Desktop |
| [04 · Operations](docs/licensing/04-operations.md) | Issuing keys, extending trials, fixing tickets | Support |
| [05 · Build checklist](docs/licensing/05-build-checklist.md) | Three weeks, day by day, with a definition of done | Everyone |
| [06 · Tier 3 (future)](docs/licensing/06-tier-3-future.md) | The "completely uncrackable" option, and why it's deferred | Future us |

---

## What already exists (and constrains the design)

- **Add-ons are already a product concept.** `widgets/sidebar.py` has an
  `ADD-ONS` shelf (BOQ, Email, BOM "coming soon"), and Reel/Studio are separate
  engines already gated behind `CB.reel_available()` / `CB.studio_available()`.
- **Distribution is unsigned PyInstaller bundles** via GitHub Releases across
  four targets (`.github/workflows/build.yml`) — portable, no installer, so
  there is no protected on-disk location to hide state in.
- **Customers bring their own Groq key.** The app has no server-side component
  at all today.
- **`cfg["premium"]` is already taken** and means *"the user pays for
  Claude/ChatGPT"* (`prism_terminal/core/onboarding.py`, consumed by the
  router). Do **not** reuse that key for Prism's own subscription — use a
  separate `license` namespace in its own file.

---

## 1. Threat model — be honest up front

A frozen Python app is patchable. Anyone determined can unpack the `.pyc` and
stub out a boolean check. So a licence check that is *only* a check will always
be defeatable. The way out is not to make the check harder to find — it is to
make the app **incomplete without us**.

Three tiers:

| Tier | Mechanism | Bypassed by | Status |
|---|---|---|---|
| **T1** | Ed25519-signed keys, admin-issued, device-bound | Unpack `.pyc`, patch the check, repack — an afternoon's work | **Building** |
| **T2** | The engine payload — tool knowledge, prompts, CSS selectors — is **not in the build**. It arrives on activation, encrypted to the token | Nothing to patch; the valuable part was never delivered | **Building** |
| **T3** | The routing call itself runs on our server | Nothing | [Deferred](docs/licensing/06-tier-3-future.md) |

**T2 is what makes this worth doing.** Prism's value isn't the Qt window — it's
the accumulated tool knowledge, three engineered prompt templates, and the CSS
selectors that drive Claude/ChatGPT/Kimi. Strip the licence check from a build
that never activated and you get a shell that opens, routes nothing, and drives
no browser.

It also has a property specific to this product: **those selectors rot.** The
tools change their pages constantly — that maintenance is why they live in a
registry at all. A cracked copy stops receiving payload updates and degrades on
its own within weeks, with no action from us.

And the same mechanism is an operations win independent of licensing: a broken
selector becomes a **server-side fix that reaches every customer in hours**,
instead of four platform builds and a chase to get everyone to update.

Do **not** invest in obfuscation or anti-debug at any tier. Bad cost/benefit.
Note also that PyInstaller 6 removed bytecode encryption, so there is no
"encrypt the `.pyc`" option available — the inert `block_cipher` lines that
implied otherwise have been deleted from `packaging/prism.spec`.

### The one honest gap

A client who takes a legitimate trial, patches the binary, and keeps the payload
they were given. T2 makes that copy perish; only T3 makes it impossible. For
handing a build to a named firm on a 10-day evaluation, T2 is enough — the
person who would reverse-engineer this is not the person running quantity
takeoffs.

---

## 2. Architecture

The server's address is one constant, `DEFAULT_SERVER` in
`licensing/client.py`. It currently ships as
`https://prism-license-server.onrender.com` — a temporary pin, because
`api.alphakore.in` has no DNS record yet. **SHIPPING.md §3.2 is the one place
that says how to move it**, and `tests/test_licensing_endpoint.py` fails if
that note goes missing.

```
Prism desktop (PySide6)          the licence server (FastAPI + Postgres)
┌──────────────────────┐         ┌────────────────────────────────┐
│ licensing/           │  HTTPS  │ /v1/activate    → signed token │
│  ├ device.py  fp     │────────▶│ /v1/refresh                    │
│  ├ client.py  http   │         │ /v1/deactivate  (seat release) │
│  ├ token.py   verify │◀────────│ /v1/payload     → the engine   │
│  ├ store.py   cache  │  token  │ /admin/*        (you: issue,   │
│  └ payload.py decrypt│    +    │                  extend, publish)│
│                      │ payload │                                │
│ Ed25519 PUBLIC key   │         │ Ed25519 PRIVATE key            │
│ baked into bundle    │         │ never leaves server            │
│                      │         │ payload JSON — never shipped   │
│ NO prompts.          │         │  · tool knowledge + selectors  │
│ NO selectors.        │         │  · 3 prompt templates          │
│ NO tool knowledge.   │         │  · field notes                 │
└──────────────────────┘         └────────────────────────────────┘
```

The left box is what a customer downloads. On its own it is a shell — that is
the T2 design, not an omission from the diagram.

**The token is the whole design.** The server signs a compact claims blob; the
app verifies it offline against the embedded public key:

```json
{ "sub":"lic_7f2a", "cust":"RS Infotech", "plan":"business",
  "feat":["core","boq","email"], "seats":5, "dev":"sha256:...",
  "iat":1754300000, "exp":1754904800, "grace_days":3, "ver":1 }
```

### The server authorises every run

**Corrected from an earlier draft.** That draft argued for long-lived offline
tokens partly on the grounds that a customer might be working somewhere with no
signal — a site office, a factory floor. That is not a real scenario for this
product, and the claim should never have been made: `core/router.py` calls the
Groq API for every plan and `core/automation.py` drives Chrome against
claude.ai and chatgpt.com. **No internet means no Prism, licence or not.** The
network references in `boq.py` and `reel.py` turn out to be documentation URLs
in error text, not calls.

So the design is now server-authoritative:

- **`POST /v1/authorize` at the start of every run**, and when an add-on is
  opened. The server decides live — a revoked licence stops on the next run
  rather than whenever a cached token happens to lapse.
- **Never during a run.** A pipeline is tens of minutes of browser automation;
  a check that could fail part-way would throw away real work for a transient
  reason the customer can do nothing about.
- **No offline fallback at all.** If the licence server cannot be reached, the
  answer is no — for planning, for runs, and for opening any add-on. There is
  no window in which work happens unauthorised.

**The trade, stated plainly: our uptime is now our customers' uptime.** If the
licence server is down, every customer stops. That is a deliberate choice, made
on the basis that this service is tiny — three endpoints and a few rows written
per run — and can therefore be hosted for reliability cheaply. It is worth
re-reading that sentence before the first client is live, because the failure
mode is total and simultaneous.

Two things follow that must not be traded away:

- **Never check mid-run.** Authorise at the start; a pipeline is tens of
  minutes of browser automation and killing it half way destroys real work.
- **Expiry and unreachability must never share copy.** "Your licence ended" and
  "we couldn't reach Alphakore" send the customer in different directions, and
  telling a paying customer the first when the second is true costs a support
  call and a lot of goodwill.

`offline_hours` survives on the licence but no longer gates anything — it only
sets how long the cached token stays fresh enough to drive the app's own
display (which add-ons show a padlock, what Setup reports).

### Backend endpoints

```
POST /v1/activate      {key, device_fp}            → token
POST /v1/authorize     {license_id, device_fp,
                        action, feature}           → allowed + run_id + token
POST /v1/usage         {run_id, events[]}          → metering
POST /v1/refresh       {license_id, device_fp}     → token
POST /v1/deactivate    {license_id, device_fp}     → seat released
POST /v1/payload       {license_id, device_fp}     → encrypted engine payload
GET  /v1/me                                        → portal / status  (Phase 2)
POST /webhooks/razorpay                            → (Phase 2)
     /admin/*          issue key, extend, revoke, release seat, publish payload
```

There is no trial endpoint. Keys are minted in `/admin/*` only.

### Usage metering

`/v1/usage` records **shapes and counts, never content** — no brief, no prompt,
no output. A BOQ query names a real project on a real site; storing it would
turn billing infrastructure into something needing a data-processing agreement,
for data we have no use for. `tests/test_api.py` asserts the schema has nowhere
to put it, so nobody adds a column later.

What you get per licence, via `GET /admin/usage`:

| Metric | Source | Honest? |
|---|---|---|
| Runs, add-on opens | `/v1/authorize` | Exact |
| Stages per tool | Stage events | Exact |
| **Groq prompt/completion tokens** | The Groq API response | Exact |
| Claude / ChatGPT / Perplexity tokens | — | **Not available** |

That last row matters. Those stages are driven through a browser — there is no
API response to read usage from — so they are counted as *stages run per tool*.
Quoting `total_tokens` at a customer as though it covered everything they ran
would be wrong. True per-token metering across all tools needs the Tier 3 proxy.

### Device fingerprint

Hash a stable per-machine id with a salt; never send the raw value.

- **Linux** — `/etc/machine-id` (fallback `/var/lib/dbus/machine-id`)
- **macOS** — `IOPlatformUUID` via `ioreg`
- **Windows** — `MachineGuid` from `HKLM\SOFTWARE\Microsoft\Cryptography`

These change on reimage, which is exactly why self-service seat release
(Phase 2) is not optional — without it every OS reinstall becomes a support
ticket.

---

## 3. Trials — admin-issued keys only

> **No key, no Prism.** No free tier, no self-signup, no anonymous trial. Every
> install — evaluation or paid — runs on a key we generated by hand.

A trial is not a separate mode. It is a key with a short life:

| We issue | They get |
|---|---|
| `days: 10, features: [core, boq]` | Ten days, BOQ unlocked, Email locked |
| `days: 30, seats: 2` | A month on two machines |
| `days: 365, seats: 5` | A year |

This is **less code** than the self-serve alternative an earlier draft assumed.
There is no trial endpoint to farm, no disposable-email problem, and no
`trial_claims` table. The entire public attack surface is one rate-limited
`activate` call.

Consequences that follow:

- **`days` is set per customer at issue time**, and extendable from admin with
  no rebuild and no re-download. A stalled pilot gets another fortnight in ten
  seconds.
- **Trials carry `grace_days = 0`.** A 10-day trial ends on day 10 — the date
  in the email you sent. Grace exists to absorb a late bank transfer on a *paid*
  account; applying it to trials just makes every deadline soft.
- **Clock rollback** — a monotonic `last_seen_utc` high-water mark. More than
  24h backwards forces an online refresh. A speed bump only; the real control is
  that tokens live 7 days and never outlast the licence end.
- **The trade-off:** no self-serve growth funnel. Correct for hand-sold B2B, and
  reversible later by adding one endpoint.

### Offline activation (for on-site machines with no internet)

The app shows a device code → you paste it into admin → admin emits a signed
token blob → the user pastes it back. Same crypto, no network. Roughly a day of
work; skip it in Phase 1 if no customer needs it yet.

---

## 4. Entitlements — where to gate

Gate the **action**, not just the UI. Hiding a button is a UX affordance; the
check has to sit where the work starts.

| Gate | File | Change |
|---|---|---|
| App launch | `main.py` (`main()`) | Before `MainWindow()`: verify token → trial/activate dialog if invalid |
| Add-on dispatch | `main_window.py` (`_handle_command`, `_open_boq`, `_open_email`, `_open_reel`) | `require("boq")` / `require("email")` at the top of each |
| Pipeline agents | `main_window.py` (`_run_pipeline`) | Extend the existing Studio pre-flight to also check the `reel` / `studio` entitlement |
| Rail affordance | `widgets/sidebar.py` (the `SECONDARY` loop) | The `ready` flag already renders a disabled `(soon)` item — add a third `locked` state with a lock icon and an "Upgrade" tooltip |
| Licence UI | `dialogs/setup_dialog.py` | New "Licence" section: plan, seats used, renewal date, *Deactivate this device* |

Locked add-ons should stay **visible and clickable**, opening an upsell sheet.
A greyed-out row sells nothing — the shelf comment in `widgets/sidebar.py`
already makes this exact argument for "coming soon".

### New files

```
licensing/
  device.py     per-OS machine fingerprint
  client.py     HTTP to the licence server, retry, offline tolerance
  token.py      Ed25519 verification
  store.py      ~/.prism/license.json + clock high-water mark
dialogs/
  license_dialog.py   trial signup, key activation, status
  paywall.py          "this add-on needs plan X" sheet
```

### Two implementation notes that will bite otherwise

- **Store licence state in `~/.prism/license.json`, never in `config.json`.**
  `prism_terminal/core/config.py`'s `save()` rewrites the entire dict on every
  save — a stale in-memory `cfg` in the GUI would silently wipe the licence. A
  separate file also keeps the CLI submodule untouched.
- **New dependency**: `cryptography` for Ed25519 (and ChaCha20-Poly1305 for the
  T2 payload). It needs a
  `hiddenimports` entry in `packaging/prism.spec` **and** a check added to the
  self-test in `main.py` — a licence library that imports in dev and dies
  frozen bricks every customer at once.

---

## 5. Payments

**Razorpay Subscriptions as primary**, since Alphakore is India-based and the
customers are Indian firms: INR, UPI/netbanking, GST-compliant invoices. Stripe
only if selling outside India.

**Manual/offline licence issuance is not optional for this market.** Indian B2B
will want to pay by bank transfer against a PO and an invoice, not a card. The
admin panel issuing a key by hand is the *primary* path for the first ~20
customers; Razorpay self-serve is for the long tail. Build the admin path
first.

Webhook → update the subscription row → the next `/v1/refresh` picks up the new
plan and features. No client-side payment code at all; the app never touches
money.

### Plan shape

Recommend **base + à la carte modules**, not tiers. A BOQ buyer at a
construction firm does not want reels, and bundling them makes the price look
inflated.

- **Prism Core** — routing, pipeline, history — per seat/month
- **+ BOQ**, **+ Reel/Studio**, **+ BOM** (when it ships) — per module, per seat
- Annual prepay discount; seats enforced by the `seats` claim

---

## 6. Failure modes

The part that decides whether customers hate this. Treat these as requirements.

- Token TTL **7 days**, refreshed silently on every launch, plus a background
  retry. A token's expiry never outlasts the licence end, so the last token of a
  10-day trial runs out on day 10.
- Refresh fails → **keep working** until `exp` + grace, with a non-blocking
  banner counting down. Grace is 3 days for paid licences and **0 for trials**.
- **The UI always shows the licence end date, never the token expiry.** A
  customer told "expires in 4 days" on day 3 of a 10-day trial will phone you.
- Payload fetch fails but a valid cache exists → silent. No cache and no
  network → block new runs with a connection message, and **never** fall back to
  a bundled copy. There isn't one, by design.
- **Never** check a licence mid-run. Run *start* and add-on entry only. A
  pipeline that dies at stage 4 because a check failed is an unrecoverable
  support incident, and the customer can do nothing about it.
- Backend down → **every customer stops immediately.** No new plans, no runs,
  no add-ons. History and everything already produced stay readable, because
  holding a customer's own work hostage over our outage would be indefensible.
  This is the cost of live authorisation and it is being paid knowingly.
- **Authorising must never freeze the window.** It is a network round trip
  behind a button press; it runs on `AuthorizeWorker` with the status bar
  saying so. A frozen window reads as a crash.
- Metering must never break a run. `/v1/usage` failures put the events back on
  the buffer for next time and are invisible to the customer — nothing they do
  depends on that call arriving.
- Expired → the app still opens; History and past outputs stay readable. Only
  new runs are blocked. Never hold a customer's own data hostage.
- **The dev bypass must be gated on `not paths.is_frozen()`.** An env-var
  bypass that works in release builds *is* the crack.

---

## 7. Phases

### Phase 1 — T1 + T2 (~3 weeks), ships as v1.1

- **Week 1** — backend: FastAPI + Postgres on Render/Railway (~₹1,500–2,000/mo),
  on `api.alphakore.in`, Ed25519 keypair, activate/refresh/deactivate, admin
  issuance. No admin UI; `curl` is fine while you are the only operator.
  *(Shipped on Render. The domain is still outstanding — SHIPPING.md §3.2.)*
- **Week 2** — client: the `licensing/` package, launch gate, add-on gates,
  activation dialog, licence section in Setup.
- **Week 3** — T2: extract the payload, serve it encrypted, consume it through
  `core_bridge.py`, prove a never-activated build is a shell.
- Result: you can hand a build to a client and control exactly what they get and
  for how long.

Day-by-day breakdown in
[`05-build-checklist.md`](docs/licensing/05-build-checklist.md).

### Phase 2 — Self-serve billing (~1 week)

Razorpay subscriptions and webhooks, hosted customer portal, dunning emails,
self-service device release. Needed once you outgrow issuing keys by hand.

### Phase 3 — T3, if ever

[`06-tier-3-future.md`](docs/licensing/06-tier-3-future.md). Tied to the Groq
key decision below.

---

## 8. The one strategic call worth making now

Today every customer must go get their own Groq key
(`prism_terminal/core/onboarding.py`, `collect_key`). For a paid B2B product
this is backwards on two fronts:

1. It is a conversion killer. *"Sign up at console.groq.com and paste an API
   key"* loses a meaningful share of trials before they ever see the product
   work.
2. It leaves licensing purely client-side.

**If the backend proxies the routing calls**, both problems disappear at once:
onboarding becomes zero-step, and licensing becomes unbypassable — no valid
token, no routing brain, no product. It also yields real usage metering for
renewals and upsells.

The cost: real per-customer inference spend that pricing must absorb, added
latency, and the backend becoming a hard uptime dependency. Plan for it; do not
build it until there are paying customers.

**If it is ever scheduled, do T3 at the same time** — they are the same
plumbing, and building them separately means building it twice. Full costing in
[`06-tier-3-future.md`](docs/licensing/06-tier-3-future.md).

---

## 9. Open decisions

Settled:

- ~~Trial gate~~ — **admin-issued keys only** (§3).
- ~~Hardening level~~ — **T1 + T2**, T3 deferred (§1).

Still open, and none of them block starting:

1. **Payment rail** — Razorpay (India/INR/GST) or Stripe (international)? This
   doc assumes Razorpay plus manual invoicing. Only matters at Phase 2.
2. **Plan shape** — base + à la carte modules (recommended) or bundled tiers?
   Affects what goes in `features`, not how it works.
3. **Groq proxying** — on the roadmap? A "yes" pulls T3 forward and changes the
   Phase 1 API surface.

Phase 1 starts with the `licensing/` client package and the token format — the
backend schema falls out of the claims design.
