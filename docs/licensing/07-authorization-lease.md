# 07 — The authorisation lease

> Read [`01-token-and-crypto.md`](01-token-and-crypto.md) first. This document
> describes the **second** signed credential, added alongside the licence
> token rather than replacing it.

---

## 1. Two questions, two credentials

The original design had one credential answering one question, and every
protected operation had to go to the network to get a live answer. That is now
split:

| | **Licence token** | **Authorisation lease** |
|---|---|---|
| Answers | *Is this installation licensed?* | *May this licensed client do protected work right now?* |
| Format | `PRSMv1.<payload>.<sig>` | `PRSMLv1.<payload>.<sig>` |
| Lives | hours – days (`TOKEN_TTL_DAYS`, 7) | ~30 minutes (`LEASE_TTL_SECONDS`) |
| Stored | `~/.prism/license.json` | `~/.prism/authorization.json` |
| Read | at startup, offline, always | before each protected operation |
| Verified by | `licensing/token.py` | `licensing/lease.py` |
| Issued by | `/v1/activate`, `/v1/refresh` | `/v1/lease`, `/v1/authorize` |
| Costs a quota unit | no | no (`/v1/lease` is free) |

Both are Ed25519, signed by the **same** private key, which exists only on the
licence server. The client holds public keys and can verify; it cannot mint.

The version prefix is inside the signed bytes on both — `signing_input()` on
each side — so a token can never be replayed as a lease or vice versa. There
are tests for exactly that on both sides, because they are one careless
refactor apart.

---

## 2. Why the split

Before, `licensing.authorize()` made a blocking HTTP call on **every plan**,
with a 45-second timeout, one retry, and **no offline fallback at all**. A
customer on a train, behind a corporate proxy, or simply hitting our host
while it restarted, could not work.

Now:

- **Startup** reads the token locally. No network, ever, on that path.
- **Protected operations** check the cached lease. No network in the common
  case — measured at ~0.2 ms against ~45 s worst case before.
- **The network** happens on a background thread, every 10 minutes.
- **Metered actions** on a metered licence still call the server, because a
  quota can only be counted where the counter lives.

The security property is *stronger*, not weaker. The old `/v1/authorize`
returned `{"allowed": true}` — an unsigned boolean, which a modified client
can synthesise in one line. A lease is a signature.

---

## 3. Claims

```json
{
  "kid":   "k1",                       // signing key id, as in the token
  "lid":   "lic_8842",                 // licence this belongs to
  "dev":   "9f2c1a…",                  // device fingerprint
  "scope": ["boq", "core", "workflow"],// what this lease grants
  "feat":  ["boq", "core", "email"],   // AUTHORITATIVE entitlements
  "mtr":   false,                      // is this licence metered?
  "iat":   1750000000,
  "nbf":   1750000000,
  "exp":   1750001800,                 // normal validity ends
  "off":   3600,                       // offline grace AFTER exp, seconds
  "jti":   "lse_a1b2c3",               // unique, for audit and revocation
  "ver":   1                           // payload version
}
```

Three of these are worth dwelling on.

**`scope` is an intersection, not a request.** The client asks for what it
thinks it has; `signing.build_lease_claims()` intersects that with the
licence's actual feature list before signing. A modified client asking for
`["core", "reel", "grok"]` on a `["core"]` licence gets `["core", "workflow"]`
back. This is the line where client-side tampering meets something it cannot
patch.

**`off` is signed.** The offline window is not a local constant and not a
config value, so a customer cannot widen their own by editing anything on
their machine. It is set per-licence from `License.offline_hours`, which admin
can already change.

**`ver` is refused if too new.** A lease claiming a higher version is rejected
outright rather than partially honoured — otherwise a future backend adding a
*restricting* claim would have it silently ignored by every old client, which
is how a "compatible" change becomes a bypass.

---

## 4. The offline policy

`licensing/authorization.py` resolves a cached lease to one of five states:

```
NONE      no lease cached                → ask the server
FRESH     now < exp                      → proceed, no network
GRACE     exp ≤ now < exp + off          → proceed, refresh in background
STALE     now ≥ exp + off                → ask the server; refuse if it is down
TAMPERED  forged / wrong machine /
          wrong licence / clock wound    → discard the cache, ask the server
```

A network failure is **not** a licence failure. GRACE is what makes a flaky
connection a non-event. STALE is what stops "offline" becoming a permanent
operating mode for a revoked licence.

And the licence itself still has the final say: `none`, `expired` and
`tampered` are checked **as well as** the lease, never instead of it. A lease
sitting on disk cannot authorise work on an expired licence, and pulling the
network cable is not a way around one.

---

## 5. What still goes to the server

`licensing.PROTECTED_ACTIONS` — currently just `plan` — when the lease's `mtr`
claim says the licence is metered.

A lease says what a client **may** do. It can never say how much of it has
already been done, so a daily allowance has to be counted server-side, from
rows `/v1/authorize` writes itself. Prism's pipeline is browser automation
against the customer's own logged-in sessions and costs Alphakore nothing, so
only planning — three Groq calls — is in that set.

**The honest limit:** inside GRACE, a metered licence can plan without the
server counting it. That window is `off` (default one hour), per-licence and
adjustable without shipping an app. A local counter would look like a fix and
would not be one — anything this process counts, this process can be patched
to forget.

---

## 6. Revocation

Two clocks, and they are very different lengths:

- **Protected work** stops within one lease TTL (30 min) plus that licence's
  offline window. The client also drops its cached lease the instant the
  server answers `LICENSE_REVOKED` or `LICENSE_EXPIRED`.
- **Opening the app** keeps working until the licence token expires (up to 7
  days). Inherent to offline verification, and it is the right trade —
  opening the app is not the thing worth revoking.

Nothing reaches out to a running client. Revocation is enforced by **refusing
to issue**, which is the only mechanism a customer's firewall cannot defeat.

---

## 7. Version enforcement

`MIN_CLIENT_VERSION` gates **leases only** — never `/v1/activate`, never
`/v1/refresh`, never startup. An old build can always open, always show its
History, and always tell its user what is wrong; what it cannot do is get
fresh authorisation for protected work.

That is the lever for the day a serious vulnerability is found in a shipped
build, and it is deliberately the narrowest one that would work. Blocking
startup over a version would turn one bad release into every customer's
problem at once.

`LATEST_CLIENT_VERSION` is advisory. A newer version existing is never a
reason to stop someone working.

Both are read at call time (`config.SETTINGS`, not a from-import), so the
floor can be raised without a redeploy.

---

## 8. Settings

Server-side, all optional with working defaults:

| Variable | Default | What it does |
|---|---|---|
| `LEASE_TTL_SECONDS` | `1800` | Default lease life |
| `MIN_CLIENT_VERSION` | *(unset)* | Version floor for lease issuance |
| `LATEST_CLIENT_VERSION` | *(unset)* | Advisory nudge |

Per-licence, via `POST /admin/licenses/{id}/limits`:

| Field | Default | What it does |
|---|---|---|
| `lease_ttl_seconds` | `0` (= server default) | How long a lease is fresh |
| `offline_hours` | `1` | How long it stays usable after expiry, offline |

Give a customer on a bad site connection a longer `offline_hours`; do **not**
raise `lease_ttl_seconds` for that, or revocation stops biting for a customer
who is perfectly well connected.

---

## 9. Sequence diagrams

### First activation

```
Customer     Prism client                    Backend
   │              │                              │
   │─ types key ─►│                              │
   │              │── POST /v1/activate ────────►│  hash key, find licence
   │              │   key, device_fp, version    │  guard: revoked? expired?
   │              │                              │  count seats, insert device
   │              │◄── token + lease ────────────│  sign both (Ed25519)
   │              │                              │
   │              │  verify token signature      │
   │              │  verify lease signature      │
   │              │  key → OS credential store   │
   │              │  token → license.json        │
   │              │  lease → authorization.json  │
   │◄─ app opens ─│                              │
```

### Normal startup — no network on this path

```
Prism client                                   Backend
   │                                              │
   │  read ~/.prism/license.json                  │
   │  verify Ed25519 signature                    │
   │  verify device binding, nbf                  │
   │  resolve expiry + grace  → VALID             │
   │                                              │
   │──────────── GUI OPENS (~79 ms) ──────────────│
   │                                              │
   │  ┄┄ background daemon thread ┄┄┄┄┄┄┄┄┄┄┄┄┄┄►│
   │      POST /v1/refresh  ─────────────────────►│
   │      ◄── fresh token ────────────────────────│
   │      POST /v1/lease    ─────────────────────►│
   │      ◄── fresh lease ────────────────────────│
   │      (then every 10 minutes)                 │
```

### Protected operation

```
Prism client                                   Backend
   │                                              │
   │  read authorization.json                     │
   │  verify signature, device, licence           │
   │  state = FRESH, scope granted?               │
   │                                              │
   ├─ yes, and not metered ──► PROCEED (~0.2 ms, no network)
   │                                              │
   ├─ metered action ─────────► POST /v1/authorize│  guard status/seat/version
   │                                              │  check daily allowance
   │                                 ◄────────────│  write usage row
   │                                              │  sign token + new lease
   │                            PROCEED           │
   │                                              │
   └─ lease STALE/absent ─────► POST /v1/lease ──►│  guard, sign lease (free)
                                ◄─────────────────│
                                cache, PROCEED
```

### Offline

```
Prism client                                   Backend
   │                                              ✗  unreachable
   │  read authorization.json → verify → GRACE    │
   │                                              │
   │  PROCEED, and show a non-blocking            │
   │  "working offline" status message            │
   │  note_attempt() → throttle retries to 1/min  │
   │                                              │
   │  … once now ≥ exp + off  → STALE             │
   │  REFUSE, with copy about the NETWORK,        │
   │  never about the licence                     │
```

### Revoked licence

```
Admin          Backend                        Prism client
  │──revoke───►│ status = "revoked", audit row      │
  │            │                                    │
  │            │◄─── POST /v1/lease ────────────────│ (within 10 min)
  │            │──── 403 LICENSE_REVOKED ──────────►│
  │            │                                    │ authorization.clear()
  │            │                                    │ cached lease deleted
  │            │                                    │
  │            │◄─── protected operation ───────────│
  │            │                          no lease, │
  │            │◄─── POST /v1/lease ────────────────│
  │            │──── 403 LICENSE_REVOKED ──────────►│ REFUSED
  │            │                                    │
  │            │   app still OPENS until the token  │
  │            │   expires — History stays reachable│
```
