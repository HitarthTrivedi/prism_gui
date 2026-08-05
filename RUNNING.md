# Running Prism

Four ways to run it, depending on what you are doing. Pick the row that matches.

| I want to… | Mode | Licence server needed? |
|---|---|---|
| Work on a dialog, a widget, the layout | [A · UI only](#a--ui-only) | **No** |
| Test licensing, activation, add-on gates | [B · Full stack](#b--full-stack-local) | Yes, locally |
| Reproduce something a client reports | [C · Against production](#c--against-production) | Yes, live |
| Check a packaged build before release | [D · Packaged build](#d--packaged-build) | Yes |

> **Why the server matters now.** Prism asks the licence server before it will
> plan, run, or open an add-on, and refuses if it cannot reach one. There is no
> offline allowance — see [`LICENSING.md`](LICENSING.md). So with no server
> running, the app opens but does nothing, which looks like a bug and isn't.

---

## A · UI only

For everything that is not licensing: dialogs, panels, styling, the pipeline UI.

```bash
cd prism_gui
python3 devtools/mint.py install --days 30 --features core,boq,email,reel
PRISM_LICENSE_OFFLINE_DEV=1 python3 main.py
```

`mint install` writes a signed token straight into `~/.prism/license.json`, so
the app starts activated. `PRISM_LICENSE_OFFLINE_DEV=1` then lets it fall back
to that token when there is no server to ask.

**This flag cannot exist in a shipped build.** It is read only when running
from source — a frozen build returns `False` no matter what the environment
says, exactly like `PRISM_LICENSE_SERVER` and the `DEVELOPMENT` keys in
`licensing/keys.py`. If it were readable in a release build, any customer could
switch licensing off with an environment variable.

Give yourself only the add-ons you are working on if you want to see the locked
states:

```bash
python3 devtools/mint.py install --days 30 --features core     # BOQ/Email padlocked
```

Clear it entirely to get the first-launch activation screen:

```bash
rm ~/.prism/license.json
```

---

## B · Full stack, local

The real thing: your machine talking to a real licence server. Use this for
anything touching activation, seats, add-on gates, expiry, or metering.

**Terminal 1 — the licence server.** Leave it running.

```bash
cd license_server
./run-local.sh
```

It prints where it is listening, which database it opened, and the admin token.
`http://127.0.0.1:8891/docs` gives you the whole API in a browser.

**Terminal 2 — the app:**

```bash
cd prism_gui
PRISM_LICENSE_SERVER=http://127.0.0.1:8891 python3 main.py
```

### Issue yourself a licence

```bash
API=http://127.0.0.1:8891; H="Authorization: Bearer dev-admin-token"

curl -sX POST $API/admin/licenses -H "$H" -H 'Content-Type: application/json' -d '{
  "name":"Kiran Shah","email":"kiran@rsinfotech.in","org":"RS Infotech",
  "kind":"trial","days":7,"features":["core","boq"],"seats":2}'
```

Paste the key it returns into the activation screen.

### Things worth exercising

| Try | Expect |
|---|---|
| **Make a plan** | *"Checking your licence…"* in the status bar first |
| Click **Email** (not licensed) | Paywall sheet naming what you *do* have |
| **Settings → Licence** | Plan, seats, end date, ticks vs padlocks, Deactivate |
| **Discard** next to Start the work | Confirms, clears the plan, keeps attachments |
| **Stop the run** while running | Winds up cleanly, keeps every finished step |
| **Ctrl-C the server**, then Make a plan | *"couldn't reach the licence server"* — History still readable |
| Revoke the licence, then Make a plan | Refused immediately, not in a week |

```bash
curl -sX POST $API/admin/licenses/lic_xxx/revoke -H "$H" \
     -H 'Content-Type: application/json' -d '{"reason":"testing"}'
curl -s "$API/admin/usage?license_id=lic_xxx" -H "$H"     # what you consumed
```

---

## C · Against production

For reproducing a client's problem with their real licence.

```bash
cd prism_gui
python3 main.py          # DEFAULT_SERVER in licensing/client.py is used
```

No override needed — that is the point. Set `PRISM_LICENSE_SERVER` only to aim
at staging.

**Use a licence you issued to yourself, never a client's key.** Activating
theirs consumes one of their seats, and they will hit `SEAT_LIMIT_REACHED` at
the worst possible moment.

---

## D · Packaged build

The only mode that proves the crypto survived freezing.

```bash
cd prism_gui
pip install -r packaging/requirements-build.txt
python3 packaging/build.py --clean
PRISM_SELFTEST=1 ./dist/Prism/Prism           # verifies the licence test vector
```

The build **refuses to start** if `licensing/keys.py` has no `PRODUCTION` key,
because a frozen Prism would otherwise reject every licence you ever issue —
and nothing else catches it, since the app starts fine and the self-test still
passes. Add the public half of your production keypair first.

Building only to check packaging? `PRISM_UNLICENSED_TEST_BUILD=1` skips that
guard; the result cannot activate.

Neither `PRISM_LICENSE_OFFLINE_DEV` nor `PRISM_LICENSE_SERVER` does anything
here. That is deliberate.

---

## Tests

```bash
cd prism_gui      && python3 -m unittest discover -s tests -q    # 73
cd license_server && python3 -m unittest discover -s tests -q    # 40
```

The client suite needs a display; it sets `QT_QPA_PLATFORM=offscreen` itself.

---

## When something is wrong

**The app opens but nothing runs.** No licence server reachable. Start one
(mode B) or use `PRISM_LICENSE_OFFLINE_DEV=1` (mode A). The banner across the
top says which.

**"This licence was issued for a different version of Prism."** The token was
signed with a key this build does not trust. Running from source, that means
the server's `SIGNING_KID`/`SIGNING_KEY_HEX` do not match a key in
`licensing/keys.py` — `run-local.sh` reads the dev key for you, so this usually
means the server was started by hand with the wrong one.

**"Port 8891 is already in use."** A server is already running.
`lsof -ti:8891 | xargs kill` clears it.

**Activation says the key wasn't recognised.** Keys live in the database the
server opened. `run-local.sh` uses `license_server/local.db`; a key issued
against a different database will not be found.

**Everything padlocked after an outage.** Should not happen — padlocks mean
"not in your licence" only. Availability shows as a banner. If you see it, it
is a bug.

---

## Where state lives

| Path | What | Safe to delete? |
|---|---|---|
| `~/.prism/license.json` | Token, licence id, key, clock high-water mark | Yes — back to the activation screen |
| `~/.prism/config.json` | Groq key, profile, agents. **Shared with the CLI** | Loses your setup |
| `~/.prism/runs/` | Every run's output — History reads this | Loses past work |
| `~/.prism/device_id` | Fallback fingerprint, only if the platform id was unreadable | Consumes a new seat |
| `license_server/local.db` | Local licences, seats, usage | Every machine must re-activate |

`local.db` deliberately lives in the repo (gitignored) rather than `/tmp`,
which is cleared on reboot.
