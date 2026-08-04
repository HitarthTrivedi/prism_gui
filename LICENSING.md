# Licensing & Subscription Plan

Plan for turning Prism from a freely-distributed build into a licensed product:
a 30-day trial, a paid subscription after it, and add-ons that unlock per plan —
backed by a hosted licence server.

Status: **proposal, nothing built yet.** Nothing in the repo touches trials,
keys, or entitlements today.

This file holds the **strategy and the reasoning**. The detailed specs live in
[`docs/licensing/`](docs/licensing/):

| Doc | What it answers | For |
|---|---|---|
| [00 · Overview](docs/licensing/00-overview.md) | How Prism gets sold, in plain English. **Start here.** | Anyone |
| [01 · Token & crypto](docs/licensing/01-token-and-crypto.md) | What a licence *is*, and why it can't be forged | Implementer |
| [02 · API & data](docs/licensing/02-api-and-data.md) | Every endpoint, the Postgres schema, hosting | Backend |
| [03 · Client integration](docs/licensing/03-client-integration.md) | Exactly what changes in this repo, and where | Desktop |
| [04 · Operations](docs/licensing/04-operations.md) | Issuing keys, extending trials, fixing tickets | Support |
| [05 · Build checklist](docs/licensing/05-build-checklist.md) | Phase 1, day by day, with a definition of done | Everyone |

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
stub out the gate. So enforcement must be aimed at the realistic case, not the
movie case.

The buyers look like SMB/enterprise firms (BOQ from CAD drawings, the RS
Infotech work, `sample_boq.docx`). That market does not crack binaries. It
*does* let trials lapse, share one install across five desks, and forget to
renew. Design for **billing hygiene, not DRM**.

Three tiers of teeth, in ROI order:

| Level | Mechanism | Stops |
|---|---|---|
| **Ship this** | Ed25519-signed licence tokens | Editing `license.json`, clock rollback, expired/refunded licences |
| **Ship this** | Server-issued trial keyed to device + email | Delete-the-folder trial resets |
| **Phase 3, optional** | Move one flagship add-on's brain server-side | Everything — genuinely uncrackable |

Do **not** invest in obfuscation or anti-debug. Bad cost/benefit at this
customer count.

---

## 2. Architecture

```
Prism desktop (PySide6)          api.alphakore.in (FastAPI + Postgres)
┌──────────────────────┐         ┌────────────────────────────────┐
│ licensing/           │  HTTPS  │ /v1/trial/start                │
│  ├ device.py  fp     │────────▶│ /v1/activate    → signed token │
│  ├ client.py  http   │         │ /v1/refresh                    │
│  ├ token.py   verify │◀────────│ /v1/deactivate  (seat release) │
│  └ store.py   cache  │  token  │ /webhooks/razorpay             │
│                      │         │ /admin/*        (you)          │
│ Ed25519 PUBLIC key   │         │ Ed25519 PRIVATE key            │
│ baked into bundle    │         │ never leaves server            │
└──────────────────────┘         └────────────────────────────────┘
```

**The token is the whole design.** The server signs a compact claims blob; the
app verifies it offline against the embedded public key:

```json
{ "sub":"lic_7f2a", "cust":"RS Infotech", "plan":"business",
  "feat":["core","boq","email"], "seats":5, "dev":"sha256:...",
  "iat":1754300000, "exp":1754904800, "grace_days":3, "ver":1 }
```

Why signed-offline rather than call-home-on-launch:

- Runs drive Chrome for **long** jobs — a network blip must never kill work in
  progress.
- Site and factory machines (the BOQ users) have flaky or proxied connectivity.
- The backend going down must not brick every customer. With a 7-day TTL it
  simply doesn't.
- Revocation still works: a refunded or cancelled licence dies at the next
  expiry, within 7 days.

### Backend endpoints

```
POST /v1/trial/start   {email, org, device_fp}     → token
POST /v1/activate      {key, device_fp}            → token
POST /v1/refresh       {license_id, device_fp}     → token
POST /v1/deactivate    {license_id, device_fp}     → seat released
GET  /v1/me                                        → portal / status
POST /webhooks/razorpay
     /admin/*          issue licence, extend trial, release seat, revoke
```

### Device fingerprint

Hash a stable per-machine id with a salt; never send the raw value.

- **Linux** — `/etc/machine-id` (fallback `/var/lib/dbus/machine-id`)
- **macOS** — `IOPlatformUUID` via `ioreg`
- **Windows** — `MachineGuid` from `HKLM\SOFTWARE\Microsoft\Cryptography`

These change on reimage, which is exactly why self-service seat release
(Phase 2) is not optional — without it every OS reinstall becomes a support
ticket.

---

## 3. Trial design (30 days, server-authoritative)

The trial start date **must not** live only in `~/.prism` — otherwise
`rm -rf ~/.prism` means infinite trials.

First launch shows two paths:

1. **Start 30-day trial** — name, work email, company → server records
   `(email, device_fp)` → issues a trial token. Doubles as lead capture, which
   you want anyway.
2. **I have a licence key** — `PRSM-XXXX-XXXX-XXXX-XXXX` → activate.

Anti-abuse, in order of value:

- The server refuses a second trial for the same `device_fp`, or the same email
  domain paired with the same device. It returns *"your trial ended on X, here
  is how to buy"* rather than silently issuing a fresh one.
- **`trial_days` is a server-side per-customer field, default 30.** This is the
  key operational win: a stalled pilot gets extended from the admin panel — no
  rebuild, no new download. Covers the "30–35 days" requirement directly.
- **Clock rollback** — store a monotonic `last_seen_utc` high-water mark. If
  system time is more than 24h behind it, force an online refresh before
  unlocking. A speed bump only; the real control is `exp`.

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
- **New dependency**: PyNaCl (or `cryptography`) for Ed25519. It needs a
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
  retry.
- Refresh fails → **keep working** until `exp` + 3-day grace, with a
  non-blocking banner counting down.
- **Never** check a licence mid-run. Launch and add-on entry only. A pipeline
  that dies at stage 4 because a token expired is an unrecoverable support
  incident.
- Backend down → every customer keeps working. That is the entire justification
  for offline tokens.
- Expired → the app still opens; History and past outputs stay readable. Only
  new runs are blocked. Never hold a customer's own data hostage.
- **The dev bypass must be gated on `not paths.is_frozen()`.** An env-var
  bypass that works in release builds *is* the crack.

---

## 7. Phases

### Phase 1 — Licensing MVP (~2 weeks), ships as v1.1

- Backend: FastAPI + Postgres on Render/Railway (~$15–25/mo), `api.alphakore.in`,
  Ed25519 keypair, trial/activate/refresh, minimal admin (a token-protected
  page, or plain SQL — you are the only operator).
- Client: the `licensing/` package, launch gate, add-on gates, trial and
  activation dialogs, licence section in Setup.
- Result: you can sell. Trials expire, keys work, add-ons unlock.

### Phase 2 — Self-serve billing (~1 week)

Razorpay subscriptions and webhooks, hosted customer portal, dunning emails,
seat management, self-service device release.

### Phase 3 — Hardening / strategic (see below)

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
latency, and the backend becoming a hard uptime dependency — which is exactly
why it is Phase 3, after offline tokens have proven stable. Plan for it; do not
build it until there are paying customers.

---

## 9. Open decisions

1. **Payment rail** — Razorpay (India/INR/GST) or Stripe (international)? This
   doc assumes Razorpay plus manual invoicing.
2. **Plan shape** — base + à la carte modules (recommended) or bundled tiers?
3. **Trial gate** — require email/company to start the trial (lead capture,
   blocks reset abuse), or a frictionless anonymous device-bound trial?
4. **Phase 3 proxy** — is moving Groq routing behind the backend on the
   roadmap? A "yes" changes Phase 1's API surface.

Phase 1 starts with the `licensing/` client package and the token format — the
backend schema falls out of the claims design.
