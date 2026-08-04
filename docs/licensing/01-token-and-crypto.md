# Licence token, keys and crypto

The exact formats. Get these right once and everything else is plumbing.

Prerequisite reading: [`00-overview.md`](00-overview.md).

---

## 1. Signing keypair

**Ed25519.** Small keys, small signatures, no parameter choices to get wrong,
no padding oracle surface.

```
private key  →  licence server only. Never in the repo, never in a build.
public key   →  baked into every Prism build, as a constant.
```

**Key management:**

- Generate once. Store the private key in the host's secret manager (Render
  environment secret / Railway variable), **not** in the backend repo.
- Keep an offline printed/paper backup in a sealed envelope. If this key is
  lost, every existing licence stops being renewable and every customer needs a
  new build.
- The public key ships in the app as `licensing/keys.py`. It is not a secret —
  publishing it is harmless.

**Rotation** — the token carries a `kid` (key id). The app ships a *map* of
`kid → public key`, so a new key can be introduced while old tokens still
verify. Ship the new public key in build N, start signing with it in build
N+1's timeframe. Never sign with a `kid` that shipped builds don't know.

```python
# licensing/keys.py  (generated, committed)
PUBLIC_KEYS = {
    "k1": "302a300506032b6570032100…",   # hex, Ed25519 raw or SPKI
}
```

---

## 2. Token format

Deliberately **not** JWT. JWT's `alg` header is an attack surface (`alg: none`,
algorithm confusion) that exists purely to support flexibility we do not want.
Our verifier does exactly one thing: Ed25519.

```
PRSMv1.<base64url(payload_json)>.<base64url(signature)>
```

- Three segments, separated by `.`.
- Segment 1 is the literal string `PRSMv1`. Anything else → reject.
- `base64url` is unpadded (RFC 4648 §5, no `=`).
- The signature covers the **UTF-8 bytes of the string `PRSMv1.<segment2>`** —
  the prefix is included so a token can never be replayed under a future format
  version.

### Payload claims

```json
{
  "kid":   "k1",
  "sub":   "lic_01HZX8K2M9",
  "cust":  "RS Infotech Pvt Ltd",
  "plan":  "business",
  "feat":  ["core", "boq", "email"],
  "seats": 5,
  "dev":   "a3f9c2b81e4d7a05",
  "kind":  "trial",
  "iat":   1754300000,
  "nbf":   1754300000,
  "exp":   1754904800,
  "grace": 3
}
```

| Claim | Type | Meaning |
|---|---|---|
| `kid` | string | Which public key verifies this. Read *before* verifying. |
| `sub` | string | Licence id. Sent back on refresh. |
| `cust` | string | Display name, shown in Setup → Licence. Cosmetic only. |
| `plan` | string | `trial` \| `core` \| `business`. Display + upsell copy. |
| `feat` | string[] | **The entitlements.** The only claim gates read. |
| `seats` | int | Display only — seat enforcement is server-side. |
| `dev` | string | Device fingerprint. Must equal this machine's, or reject. |
| `kind` | string | `trial` \| `paid`. Drives which expiry copy is shown. |
| `iat` | int | Unix seconds, issued at. |
| `nbf` | int | Not valid before. Guards against clock skew games. |
| `exp` | int | Unix seconds. **7 days after `iat`** for normal issuance. |
| `grace` | int | Extra days of full function after `exp`. Default `3`. |

### Feature identifiers

Fixed vocabulary. Adding one means shipping a build that knows about it, so
keep the list short and stable.

| Id | Unlocks |
|---|---|
| `core` | Routing, the pipeline, History. Without this the app is read-only. |
| `boq` | The BOQ add-on |
| `email` | The Email add-on |
| `reel` | Prism Reel + Prism Studio |
| `bom` | BOM & Stock (not built yet — reserved) |

---

## 3. Verification algorithm

Implement it in this order. The order matters.

```
 1. Split on "." → exactly 3 segments, else REJECT
 2. Segment[0] == "PRSMv1", else REJECT
 3. Decode segment[1] → payload JSON. Parse it.
 4. Look up PUBLIC_KEYS[payload["kid"]] — unknown kid → REJECT
 5. Verify Ed25519 signature over the raw bytes of
    ("PRSMv1." + segment[1]).encode()          ← NOT re-serialized JSON
    Bad signature → REJECT (state = TAMPERED)
 6. payload["dev"] == this machine's fingerprint, else REJECT
 7. now < payload["nbf"] - 300 → REJECT (clock is wrong or being played with)
 8. now < payload["exp"]                       → VALID
    now < payload["exp"] + grace*86400         → GRACE
    otherwise                                  → EXPIRED
```

### The one rule that must not be broken

**Step 5 verifies against the raw base64 segment, never against a
re-serialised copy of the parsed JSON.** Re-serialising introduces key
ordering, whitespace and unicode-escaping differences between the signer and
the verifier — the resulting bugs are intermittent, platform-dependent, and
appear only on some customers' machines. Sign bytes, verify the same bytes.

### States the client can be in

| State | Meaning | App behaviour |
|---|---|---|
| `NONE` | No token stored | First-run dialog: start trial / enter key |
| `VALID` | Verified, `now < exp` | Full access to `feat` |
| `GRACE` | Past `exp`, inside grace | Full access + countdown banner |
| `EXPIRED` | Past `exp + grace` | Read-only mode, upgrade prompt |
| `TAMPERED` | Bad signature, wrong `dev`, or clock rollback | Read-only, forces an online refresh |

**Read-only mode**: the app opens; History, Setup, and the Licence dialog work;
compose/route/run and every add-on are blocked. Never destroy or hide the
customer's own data.

---

## 4. Licence key format

What the customer actually types.

```
PRSM-4K2XA-9WQ7M-3TYRB-8HNVE
```

- Prefix `PRSM-`, then 4 groups of 5 characters.
- **Crockford Base32** alphabet: `0123456789ABCDEFGHJKMNPQRSTVWXYZ` — no
  `I`, `L`, `O`, `U`. Nothing is ambiguous when read aloud over a phone, which
  will happen.
- Input is normalised before checking: uppercase, strip spaces and hyphens,
  and map `I`/`L`→`1`, `O`→`0`. Customers *will* type the wrong ones.
- Characters 1–19 are random (95 bits). Character 20 is a **checksum** —
  `crockford[sum(values of first 19) % 32]` — so a typo is caught instantly in
  the dialog, offline, before any network call.

**Storage:** the server stores `sha256(normalised_key)`, never the key itself.
The plaintext key is shown exactly once, at issue time, and emailed to the
customer. A database leak then hands out nothing usable.

---

## 5. Device fingerprint

Identifies a machine for seat counting. One machine = one seat, regardless of
how many user accounts are on it.

```python
raw = {
    "linux":   read("/etc/machine-id") or read("/var/lib/dbus/machine-id"),
    "darwin":  ioreg -rd1 -c IOPlatformExpertDevice → IOPlatformUUID,
    "win32":   HKLM\SOFTWARE\Microsoft\Cryptography → MachineGuid,
}[sys.platform]

fingerprint = sha256(b"PRISM-DEVICE-V1" + raw.encode()).hexdigest()[:16]
```

- **Send the hash, never the raw id.** The salt means the server cannot recover
  a machine's real hardware id even if its database leaks.
- 16 hex chars (64 bits) — collisions are not a practical concern at this
  scale, and it stays short enough to display in a support conversation.
- **Fallbacks**, in order: the platform id above → the MAC address of the first
  non-loopback interface → a random UUID persisted to
  `~/.prism/device_id`. Log which tier was used; the random fallback means a
  reinstall consumes a new seat, so it should be rare and visible.

### The reimage problem

These ids change when a machine is reimaged or its OS is reinstalled. The
customer's seat is then silently consumed by a machine that no longer exists.

**This is the single most likely source of support tickets.** Mitigate with:
- Self-service *Deactivate this device* in Setup → Licence.
- A device list in the customer portal with a Release button (Phase 2).
- Until then, releasing a seat from the admin panel — see
  [`04-operations.md`](04-operations.md).

---

## 6. Clock tampering

`~/.prism/license.json` holds a `last_seen_utc` high-water mark, updated on
every successful launch and every server response.

```
if now < last_seen_utc - 86400:
    state = TAMPERED   # requires a successful online refresh to clear
```

Deliberately a 24-hour tolerance — timezone changes, DST, and genuinely wrong
BIOS clocks on new machines are all real, and a false accusation is far worse
than a missed rollback.

This is a speed bump, not a control. The file is user-writable and always will
be; the real limit on backdating is that `exp` is only 7 days out.

---

## 7. Dependency

Ed25519 needs **PyNaCl** (preferred — small, one job) or `cryptography`.

Two things must happen or the app ships broken:

1. Add a `hiddenimports` entry in [`packaging/prism.spec`](../../packaging/prism.spec).
   PyNaCl loads a compiled `_sodium` extension that PyInstaller's analysis does
   not always find.
2. Add a check to `_selftest()` in [`main.py`](../../main.py) that **verifies a
   known-good test token**, not just that the import succeeds. Freezing breaks
   native extensions in ways a bare import will not reveal, and this is exactly
   the class of failure that check exists to catch — see the existing SSL and
   automation entries.

Commit a fixed test token and its expected result as a vector so the same
assertion runs in the test suite, in CI, and in the packaged smoke test.
