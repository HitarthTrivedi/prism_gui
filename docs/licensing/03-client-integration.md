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
  state.py       the NONE/VALID/GRACE/EXPIRED/TAMPERED machine
```

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
licensing.start_trial(...) -> Result
licensing.deactivate() -> Result
```

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
    def usable(self) -> bool:   # status in ('valid', 'grace')
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
  "server": "https://api.alphakore.in" }
```

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
    if LicenseDialog(app).exec() != QDialog.Accepted:
        sys.exit(0)                      # they closed it — no silent free ride
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

### 6. Grace banner — [`main_window.py`](../../main_window.py)

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

**[`packaging/prism.spec`](../../packaging/prism.spec)** — add PyNaCl to
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
| Expired by 5 days, grace 3 | `EXPIRED`, read-only |
| Clock set back 40 days | `TAMPERED` until an online refresh |
| Server unreachable, token valid | `VALID`, no visible error |
| Server 500s on refresh | `VALID`, silent, retry later |
| `license.json` deleted | `NONE`, re-activates from the stored key if present |
| `license.json` truncated / corrupt | `NONE`, never a crash |
| Unknown `kid` in token | Rejected, prompts re-activation |
