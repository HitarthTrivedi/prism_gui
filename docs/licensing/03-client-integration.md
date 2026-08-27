# Wiring it into the Prism app

Exactly what changes in this repo, and where. Written so it can be implemented
without re-deriving any decisions.

Prerequisite reading: [`01-token-and-crypto.md`](01-token-and-crypto.md).

---

## New package

```
licensing/
  __init__.py    the public API — everything else imports only this
  device.py      per-OS fingerprint (+ fallbacks)
  token.py       Ed25519 verification, claim parsing
  keys.py        PUBLIC_KEYS = {kid: pubkey}   (generated, committed)
  client.py      HTTP to the licence server; retries; offline tolerance
  store.py       ~/.prism/license.json, clock high-water mark
  status.py      the NONE/VALID/GRACE/EXPIRED/TAMPERED machine (named
                 status, not state: the package also exposes a state()
                 function, and the collision silently shadows one)
  meter.py       usage buffering + the Groq token counter
  payload.py     Tier 2 — fetch, decrypt, cache, schema-check the engine payload
```

`meter.py` wraps the `requests` handle inside `core/router.py` from
[`core_bridge.py`](../../core_bridge.py) — **not** by editing the module. The
engine is a submodule shared with the CLI, which carries no licence and must
keep running standalone. Wrapping the name it already looks up catches all
three of its Groq call sites without touching a line of it, and degrades to
"no token counts" rather than an error if the engine is refactored.

### The public API — the whole surface

Keep it this small. Every call site below uses only these.

```python
import licensing

licensing.refresh()                 # non-blocking; called at launch
licensing.state() -> LicenseState   # cached, cheap, safe to call in paint code
licensing.has("boq") -> bool        # entitlement check
licensing.require("boq", parent) -> bool
                                    # checks; on failure shows the paywall
                                    # sheet and returns False
licensing.activate(key) -> Result   # from the licence dialog
licensing.deactivate() -> Result
licensing.payload() -> dict | None  # Tier 2 — decrypted engine data, cached

licensing.authorize(feature, action) -> Authorization
                                    # ASK THE SERVER, live. Run start and
                                    # add-on entry only — never mid-run.
licensing.report_usage(run_id)      # flush buffered metering; never blocks
licensing.meter.record(kind, ...)   # buffer one event
```

`authorize()` is the live gate and `has()`/`require()` are the cached one. Both
exist on purpose: `require()` is instant and drives the UI (padlocks, paywall
sheets, whether a button is enabled), while `authorize()` is the decision that
actually lets work start. Never use `has()` alone to permit a run — that is the
cached token talking, and the point of this design is that the server has the
last word.

**`authorize()` must not be called on the UI thread.** It is a network round
trip behind a button press; use `AuthorizeWorker` in
[`workers.py`](../../workers.py), which is what `_run_pipeline` does. A frozen
window reads as a crash.

There is deliberately **no `start_trial()`**. Trials are keys we issue; the
client cannot mint one. See the admin-only rule in
[`02-api-and-data.md`](02-api-and-data.md).

`state()` returns a small frozen dataclass:

```python
@dataclass(frozen=True)
class LicenseState:
    status: str        # 'none'|'valid'|'grace'|'expired'|'tampered'
    plan: str
    customer: str
    features: frozenset[str]
    expires_at: int
    kind: str          # 'trial'|'paid'
    seats: int
    days_left: int     # negative once inside grace
    @property
    def usable(self) -> bool:   # 'valid', 'grace', or 'stale' for < 7 days
```

---

## Storage

`~/.prism/license.json`, `chmod 0600`:

```json
{ "token": "PRSMv1.eyJ…",
  "license_id": "lic_01HZX8K2M9",
  "key": "PRSM4K2XA9WQ7M3TYRB8HNVE",
  "last_seen_utc": 1754301234,
  "last_refresh_attempt": 1754301234,
  "payload_etag": "pl_7c1f",
  "server": "https://api.alphakore.in" }
```

Plus `~/.prism/payload.enc` — the encrypted engine payload. Ciphertext only;
the key that opens it lives in the token's `pk` claim. Never write the
decrypted form to disk.

> **Do not put any of this in `config.json`.**
> [`prism_terminal/core/config.py`](../../prism_terminal/core/config.py)'s
> `save()` rewrites the whole dict from whatever the caller holds. The GUI keeps
> `self.cfg` in memory across dialogs, so any stale copy written back would
> silently erase the licence — a bug that would look like random deactivations
> and be miserable to trace. A separate file also leaves the `prism_terminal`
> submodule completely untouched, which keeps the CLI a separate product.

---

## Call sites

### 1. Launch gate — [`main.py`](../../main.py), in `main()`

After the stylesheet is applied and **before** `MainWindow()` is constructed:

```python
import licensing
licensing.refresh()                      # fire-and-forget, ~50ms, never blocks

st = licensing.state()
if st.status == 'none':
    # No key. The only screen available is activation — there is no trial
    # button, because trials are keys we issue.
    if ActivationDialog(app).exec() != QDialog.Accepted:
        sys.exit(0)
elif st.status in ('expired', 'tampered'):
    ExpiredDialog(app).exec()            # informs, offers activation, then
                                         # falls through to read-only mode
```

`refresh()` must **never** block the UI thread on the network. Fire it on a
`QThread` (the pattern already exists in [`workers.py`](../../workers.py)) and
let the window build against the cached token. A slow DNS lookup on a corporate
network must not add eight seconds to every launch.

### 2. Add-on gates — [`main_window.py`](../../main_window.py)

One line at the top of each opener. `require()` shows the paywall itself, so
the call site stays a single guard clause:

```python
def _open_boq(self):
    if not licensing.require("boq", self):
        return
    ok, err = CB.boq_available()          # the existing dependency probe
    ...
```

| Method | Feature |
|---|---|
| `_open_boq` | `boq` |
| `_open_email` | `email` |
| `_open_reel` | `reel` |
| `_route` | `core` |
| `_run_pipeline` | `core` |

Note the ordering in `_open_boq`: **entitlement first, dependency probe
second.** A customer without the BOQ add-on should be told they need to buy it,
not sent to install `ezdxf` for a feature they cannot use.

### 3. Pipeline agents — `_run_pipeline`

Prism Reel and Prism Studio are reachable as *routed agents*, not just via the
sidebar — so gating `_open_reel` alone leaves a hole. Extend the existing
Studio pre-flight (the block that already checks `CB.studio_available()` and
offers a fallback) to also check the `reel` entitlement, and substitute a
different agent rather than aborting the run.

### 4. Sidebar lock state — [`widgets/sidebar.py`](../../widgets/sidebar.py)

`SECONDARY` entries already carry an optional 5th element, a `ready` bool that
renders a disabled `(soon)` item. Generalise it to a three-state field:

```python
("boq", "BOQ", "file", "Bill of Quantities…", "core"),   # 5th = feature id
```

- entitled → normal
- not entitled → lock icon, still **enabled**, click opens the upsell sheet
- unbuilt (`bom`) → keep today's disabled `(soon)` behaviour

Keep locked items clickable. The comment already in that file argues that a
visible "next one" sells better than an empty gap — a greyed-out row sells
nothing either. A lock is an invitation; a disabled control is a dead end.

### 5. Licence section — [`dialogs/setup_dialog.py`](../../dialogs/setup_dialog.py)

A new `Section` in the existing scrolling list, deep-linkable from the rail the
same way the others are:

- Plan, customer name, renewal/expiry date
- Feature list with tick / lock per add-on
- Seats: "3 of 5 in use"
- **Deactivate this device** (with a confirmation — it logs this machine out)
- **Enter a different licence key**

### 6. The payload shim — Tier 2

The strings leave the bundle; the code that assembles them stays. Three places
read payload data instead of module constants:

| Today | Becomes |
|---|---|
| `A.AGENT_REGISTRY` in [`core/agents.py`](../../prism_terminal/core/agents.py) — specialties, budgets, URLs, **and the `textarea_selector` / `response_selector` values** | merged from `licensing.payload()["agents"]` |
| The three prompt templates in [`core/router.py`](../../prism_terminal/core/router.py) (brief expander ~L225, plan auditor ~L320, routing brain ~L397) | `payload["prompts"][name].format(...)` |
| `pros_cons.txt`, read by `_tool_notes()` | `payload["notes"]`, merged as one more source |

**Where the shim lives matters.** `prism_terminal` is a git submodule shared
with the CLI product, and the CLI is not licensed. So do not edit `core/` to
import `licensing`. Instead have [`core_bridge.py`](../../core_bridge.py) —
which already exists to adapt the engine for the GUI — inject the payload into
the engine modules at startup, before any widget is built. The submodule keeps
working standalone, with its own local defaults, exactly as it does now.

Two behaviours to preserve:

- **`_tool_notes()` also reads `~/.prism/tool_notes.md`.** That's a documented
  user feature — the user's own field notes get merged into routing prompts.
  The payload adds a source; it must not replace that lookup.
- **The registry's shape is unchanged.** `payload["agents"]` merges *over* the
  local skeleton, so a payload missing one tool degrades that tool rather than
  crashing the app.

### 7. Grace banner — [`main_window.py`](../../main_window.py)

When `status == 'grace'`, a dismissible strip above the work column: *"Your
subscription couldn't be verified. Prism keeps working for N more days."*
`QStatusBar` is not enough — it is already used for transient run messages and
this must persist.

---

## Behaviour rules

These are requirements, not preferences. Each one exists because violating it
creates a support incident worse than the piracy it prevents.

**Never check a licence mid-run.** Launch and add-on entry only. A pipeline
that dies at stage 4 because a token expired between stages loses an hour of
browser automation and cannot be resumed.

**Never block on the network.** Every server call is off the UI thread, with a
5-second timeout and no retry storm. If the server is unreachable the app is
fully functional on its cached token.

**Expiry is read-only, not shutdown.** History, Setup and past outputs stay
reachable forever. Only new runs and add-ons are gated. A customer locked out of
their own past BOQ output will not renew.

**The dev bypass must not exist in release builds.** Any `PRISM_LICENSE_*`
override is honoured only under `not paths.is_frozen()` — see
[`paths.py`](../../paths.py). An env-var bypass that survives freezing *is* the
crack, and it will be the first thing found by anyone who looks.

**Fail toward the customer.** Any unexpected exception inside `licensing/` —
corrupt JSON, an unreadable registry, a platform id that vanished — must be
caught and resolved to the *last known good* state, not to `EXPIRED`. A bug in
our code must never lock out a paying customer. Log it, refresh in the
background, and let them work.

---

## Packaging and tests

**[`packaging/prism.spec`](../../packaging/prism.spec)** — add `cryptography`'s leaf modules to
`hiddenimports`. It loads a compiled `_sodium` extension that PyInstaller's
analysis does not reliably discover.

**[`main.py`](../../main.py) `_selftest()`** — add a check that **verifies a
known-good test token** and asserts the expected claims. Not an import check: an
import can succeed while the native extension is broken, which is precisely the
failure mode that function exists to catch (see its existing SSL and browser
automation entries, both of which are there because a build that imported fine
still died on a customer's machine).

**Test matrix** worth writing before the first customer sees it:

| Case | Expected |
|---|---|
| Valid token, in date | `VALID`, features present |
| Token with one byte flipped | `TAMPERED` |
| Token for a different `device_fp` | `TAMPERED` |
| Expired by 1 day, grace 3 | `GRACE`, app usable |
| Token past its expiry by 3 hours, licence in date, server unreachable | `STALE`, app usable, soft banner (tokens live one hour) |
| Token past its expiry by 8 days, server unreachable | `STALE`, locked until it reaches the server |
| Expired by 5 days, grace 3 | `EXPIRED`, read-only |
| Clock set back 40 days | `TAMPERED` until an online refresh |
| Server unreachable, token valid | `VALID`, no visible error |
| Server 500s on refresh | `VALID`, silent, retry later |
| `license.json` deleted | `NONE`, re-activates from the stored key if present |
| `license.json` truncated / corrupt | `NONE`, never a crash |
| Unknown `kid` in token | Rejected, prompts re-activation |
| **Payload cases (Tier 2)** | |
| No payload ever fetched, no key | App is a shell: opens, routes nothing, no crash |
| `payload.enc` present, token deleted | Cache is inert — no `pk`, refuses to decrypt |
| `payload.enc` corrupted | Refused by the AEAD tag; keeps last good, re-fetches |
| Payload decrypts but fails schema | Refused; previous version kept; reported to server |
| Payload fetch fails, valid cache | Silent — cache used, no dialog |
| Payload fetch fails, no cache | New runs blocked with a connection message, **never** a bundled fallback |
| `petag` mismatch after refresh | Re-fetches automatically |
| `~/.prism/tool_notes.md` present | Still merged into routing prompts (user feature preserved) |
