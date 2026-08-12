# Shipping Prism

How to get from this repo to something a person can install, in three stages:

| Stage | Who gets it | What you need |
|---|---|---|
| **1 · Team test** | Your own team | A server your team can reach, and a build |
| **2 · Subscriptions** | Still you | Razorpay, once you know what you're charging for |
| **3 · Clients** | Paying customers | A real domain, signing certificates, a support inbox |

Stage 1 is a day's work and everything else builds on it. Do it first.

Related: [`RUNNING.md`](RUNNING.md) for running from source ·
[`BUILD.md`](BUILD.md) for build mechanics ·
[`LICENSING.md`](LICENSING.md) for how licensing works ·
[`../license_server/README.md`](../license_server/README.md) for the server.

---

# The one thing to understand first

Prism is **two separate things** that only meet at a URL:

```
   The licence server                    The app
   ┌──────────────────────┐              ┌────────────────────────┐
   │ You run it. One      │              │ You hand it over as a  │
   │ service + database.  │◀────────────▶│ .tar.gz / .exe / .dmg  │
   │ Holds the PRIVATE    │   the URL    │ Holds the PUBLIC key   │
   │ signing key.         │  compiled    │ and nothing else.      │
   └──────────────────────┘   into it    └────────────────────────┘
```

**The server has to exist before you build the app**, because its address is
compiled in. A frozen build ignores `PRISM_LICENSE_SERVER` at runtime — that
override would let anyone point Prism at a licence server they control — so
there is no fixing the URL afterwards. Wrong URL means rebuild.

That is the single ordering constraint in this whole document.

---

# Stage 1 · Get it to your team

## 1.1 Deploy the licence server

Render or Railway, one web service plus managed Postgres. Roughly
₹1,500–2,000/month.

```
Repository:  license_server/
Build:       pip install -r requirements.txt
Start:       alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Environment (in the host's secret store, never in a file):

| Variable | Value |
|---|---|
| `ENV` | `prod` |
| `DATABASE_URL` | the managed Postgres URL |
| `SIGNING_KEY_HEX` | contents of `license_server/prod-signing-key.hex` |
| `SIGNING_KID` | `k1` |
| `ADMIN_TOKEN` | `python3 -c "import secrets;print(secrets.token_urlsafe(48))"` |

It refuses to start without the last three, and refuses to start on SQLite when
`ENV=prod`. Both are deliberate.

Check it: `curl https://your-service.onrender.com/health` → `{"ok":true,...}`

### Using Supabase for the database

Supabase is managed Postgres, so this is a `DATABASE_URL` change and nothing
else — no rewrite, no migration loss, all server tests still pass. You get a
table browser and SQL editor for monitoring, which Render Postgres does not
have.

Three migrations create read-only views for that console:

| View | What it answers |
|---|---|
| `v_licences` | Who holds what — seats used vs total, tasks today vs limit, days left |
| `v_usage_daily` | Plans, runs, stages and Groq tokens per licence per day |
| `v_dormant_seats` | Activated machines not opened in 30 days — your churn list |

> **Use the Session pooler connection string, not the Transaction pooler.**
> Supabase offers both. The transaction pooler (port 6543) recycles
> connections between statements, which breaks SQLAlchemy's prepared
> statements — you get intermittent, hard-to-reproduce errors rather than a
> clean failure. Long-running uvicorn wants the session pooler or the direct
> connection.

**The console is for reading.** Issuing, extending, revoking and changing
limits still go through the API, because:

- **You cannot create a working licence by typing a row.** Only `sha256(key)`
  is stored; the plaintext exists for one moment, when `/admin/licenses`
  generates it. A hand-typed row is a licence nobody can activate.
- Hand edits write no `audit_log` — the record you want when a client says
  they never cancelled.
- Hand edits skip the invariants: `grace_days` on a trial, `expires_at` in the
  past while `status='active'`.

**Turn on daily database backups now, and restore one once to prove it works.**
An hour of downtime is invisible to your team. Losing this database loses every
licence and activated machine.

> **Free tiers sleep.** Render's free plan idles a service after ~15 minutes,
> and the first request then takes 30–50 seconds to wake it. Prism asks the
> server before every run, so your team will feel that as Prism hanging. Use a
> paid instance even for the team test, or expect to explain the pause.

## 1.2 Point the build at it

Add a **repository variable** (Settings → Secrets and variables → Actions →
Variables) — a variable, not a secret, because secrets are masked in logs and a
wrong URL then becomes impossible to diagnose:

```
PRISM_SERVER_URL = https://your-service.onrender.com
```

CI passes it to the build, which compiles it in. Leave it unset later and the
`DEFAULT_SERVER` in `licensing/client.py` ships instead.

## 1.3 Build all three platforms

**PyInstaller cannot cross-compile.** Your Linux laptop cannot produce a `.exe`
or a `.dmg` — not with a flag, not with Wine. The OS you build on is the OS you
get. That is why CI builds four targets on four runners, and why you should not
try to do this locally.

```bash
git tag v1.1.0
git push origin v1.1.0
```

That runs `.github/workflows/build.yml`, which builds and **smoke-tests** each
bundle, then publishes a GitHub Release with:

| File | For |
|---|---|
| `Prism-1.1.0-linux-x64.tar.gz` | Linux |
| `Prism-1.1.0-x64.AppImage` | Linux, single file |
| `Prism-1.1.0-windows-x64.zip` | Windows |
| `Prism-1.1.0-macos-arm64.dmg` | Apple Silicon |

There is deliberately **no Intel Mac build** — see the matrix in
`.github/workflows/build.yml` for why, and note that the arm64 `.dmg` will not
run on an Intel Mac. Anyone still on one needs that leg added back first.

Push any other branch and you still get artifacts on the run — useful for
testing without cutting a release.

**Before the first tag, check `licensing/keys.py` has your production key under
`PRODUCTION`.** The build refuses to run without one, because a frozen Prism
would otherwise reject every licence you ever issue — and nothing else catches
it: the app starts fine and the self-test still passes.

## 1.4 Issue your team keys

```bash
API=https://your-service.onrender.com
H="Authorization: Bearer $ADMIN_TOKEN"

curl -sX POST $API/admin/licenses -H "$H" -H 'Content-Type: application/json' -d '{
  "name":"Hitarth","email":"hitarth@alphakore.in","org":"Alphakore",
  "kind":"trial","days":90,"features":["core","boq","email","reel"],
  "seats":2,"offline_hours":24,"notes":"internal — team test"}'
```

For your own team: long `days`, every feature, a couple of seats each so they
can use a laptop and a desktop. `offline_hours: 24` keeps a Render restart from
interrupting anyone.

Send each person their key and the Releases link. **The key is shown once** —
only its hash is stored.

## 1.5 What your team needs to be told

Two things, or your first three messages will all be the same.

**The builds are unsigned.** Both OSes will warn, and the warnings look like
malware alerts:

- **Windows** — "Windows protected your PC" → **More info** → **Run anyway**
- **macOS** — "cannot be checked for malicious software" → **right-click** the
  app → **Open** → **Open**. If macOS says it "is damaged", that is the
  quarantine flag: `xattr -dr com.apple.quarantine /Applications/Prism.app`
- **Linux** — no warning

**They also need Google Chrome** and their own Groq API key — Prism drives their
real logged-in browser and uses Groq for routing. First launch walks through it.

## 1.6 Watch what happens

```bash
curl -s "$API/admin/licenses?q=alphakore" -H "$H"          # who activated
curl -s "$API/admin/usage?license_id=lic_xxx&days=30" -H "$H"   # what they ran
```

`runs` and `by_day` tell you whether Prism actually got used or was opened once
politely. That is the question this stage exists to answer.

---

# Stage 2 · Subscriptions

Only worth doing once the team test tells you what people use. Two paths, and
the second matters more than it looks:

**Manual invoicing** — already works. Issue a paid key with `curl`, send an
invoice, done. For the first ~20 customers in Indian B2B this is the *primary*
path: they will want to pay by NEFT against a PO, not by card.

**Self-serve (Razorpay)** — not built yet. Needs `POST /webhooks/razorpay`,
subscription/webhook tables (already in the schema), a customer portal, and
dunning emails. About a week. See Phase 2 in
[`docs/licensing/05-build-checklist.md`](docs/licensing/05-build-checklist.md).

Nothing in the app changes for either. It never touches money — it only ever
asks the licence server what a key allows.

**Decide pricing shape before building this.** The recommendation in
[`LICENSING.md`](LICENSING.md) is base + à la carte add-ons rather than tiers: a
BOQ buyer at a construction firm does not want reels, and bundling them makes
your price look inflated.

---

# Stage 3 · Clients

## 3.1 Sign the builds

The single biggest difference between "internal tool" and "product". An
unsigned app tells a project manager at a client firm that it might be malware.

- **Windows** — OV or EV code-signing certificate, ~₹25–40k/year
- **macOS** — Apple Developer Program, $99/year, plus notarisation

The hooks are already in `packaging/prism.spec` (`codesign_identity`,
`entitlements_file`), and the macOS bundle already carries the
`NSMicrophoneUsageDescription` notarisation requires.

## 3.2 Real domain — **outstanding, and it has a cost**

Right now `licensing/client.py` ships:

```python
DEFAULT_SERVER = "https://prism-license-server.onrender.com"
```

That is a deliberate, temporary pin, and it is not where this should end up.
It is there because **`api.alphakore.in` has no DNS record** — the name does
not resolve at all, so a build pointed at it cannot activate a single
customer. A provider address that works beats a domain that does not.

What it costs, so nobody discovers it later:

- Every build made from this source is **welded to Render**. Moving host,
  region, or off the free tier means rebuilding and reinstalling on every
  customer machine.
- A Render subdomain in a client's firewall allowlist is a conversation you
  do not want to have.

### Undoing it — the whole job

1. At the registrar for `alphakore.in`, add:

   | Type | Name | Value |
   |------|------|-------|
   | CNAME | `api` | `prism-license-server.onrender.com` |

2. Render → the service → Settings → Custom Domains → add `api.alphakore.in`.
   Render issues the TLS certificate automatically, usually within minutes.

3. Confirm: `curl https://api.alphakore.in/health` → `{"ok":true,...}`

4. Set `DEFAULT_SERVER = "https://api.alphakore.in"` in `licensing/client.py`,
   and `PRODUCTION_HOST` in `tests/test_licensing_endpoint.py` to match.

5. Clear the `PRISM_SERVER_URL` repository variable if one is set, so releases
   use the compiled-in default.

Once the CNAME exists, every build already in customers' hands starts working
against the domain without a reinstall — which is the entire reason to do it.

## 3.2b The server sleeps

Render's free tier spins down after about 15 minutes idle. A cold `/health`
was measured at **42.6 seconds**.

`ACTIVATE_TIMEOUT` is 75s and `AUTHORIZE_TIMEOUT` is 45s with one retry, both
sized for that. Before those were raised, first-time activation failed against
a server that was perfectly healthy — it had simply not finished waking.

The customer-visible symptom that remains: the first action of each morning
hangs for up to a minute. Render's paid tier (~$7/month) does not sleep and
removes it. Keep the long timeouts either way; they cost nothing warm.

## 3.3 Support inbox

`app_meta.py` currently has **placeholder** contact details:

```python
SUPPORT_EMAIL = "hello@alphakore.in"      # TODO(alphakore): confirm
```

This appears on every licence screen — activation, expiry, every locked add-on.
It is the only route a stuck client has back to you. Make it an address someone
reads.

## 3.4 Before the first client build

- [ ] `PRODUCTION` key in `licensing/keys.py`
- [ ] `SUPPORT_EMAIL` and `WEBSITE` real
- [ ] `DEFAULT_SERVER` on your own domain
- [ ] `PRISM_SERVER_URL` repository variable cleared
- [ ] Server on a paid instance with daily backups **and a tested restore**
- [ ] `prod-signing-key.hex` backed up offline, outside the repo
- [ ] Signing certificates, or the warnings written into your handover email
- [ ] Version bumped in `app_meta.py`

---

# Cheat sheet

```bash
# a release, all platforms
git tag v1.1.0 && git push origin v1.1.0

# hand a client a 10-day evaluation
curl -sX POST $API/admin/licenses -H "$H" -H 'Content-Type: application/json' -d '{
  "name":"Kiran Shah","email":"kiran@rsinfotech.in","org":"RS Infotech",
  "kind":"trial","days":10,"features":["core","boq"],"seats":2}'

# they buy
curl -sX POST $API/admin/licenses -H "$H" -H 'Content-Type: application/json' -d '{
  "name":"Kiran Shah","email":"kiran@rsinfotech.in","org":"RS Infotech",
  "kind":"paid","plan":"business","days":365,"features":["core","boq","email"],
  "seats":5,"notes":"PO 4471, NEFT 12 Aug"}'

# pilot stalled — no rebuild, effective on their next launch
curl -sX POST $API/admin/licenses/lic_xxx/extend -H "$H" \
     -H 'Content-Type: application/json' -d '{"days":14,"reason":"pilot stalled"}'

# "all our seats are in use" — reimaged machines holding seats
curl -s "$API/admin/licenses?q=rsinfotech" -H "$H"
curl -sX POST $API/admin/devices/42/release -H "$H"

# renewals due
curl -s "$API/admin/licenses?expiring_days=30" -H "$H"
```

Full runbook: [`docs/licensing/04-operations.md`](docs/licensing/04-operations.md).

---

# Things that will go wrong

**Every client fails to activate at once.** The build shipped without a
`PRODUCTION` key, or the server's `SIGNING_KID` does not match one in
`licensing/keys.py`. The build guard prevents the first; the second is a server
env var. Symptom: *"This licence was issued for a different version of Prism."*

**Everyone stops working simultaneously.** Your server is down. There is no
offline mode — Prism calls Groq and drives claude.ai, so it needs the internet
regardless, and now it needs your server too. Customers keep working for their
`offline_hours` (24 by default) and then stop. This is the cost of live
authorisation; raise `offline_hours` for a client you cannot risk.

**Nobody can activate but everything else works.** Check `/health`. Activation
is the only path with a hard server dependency at first launch.

**A client reinstalls Windows and loses a seat.** Expected — the machine
fingerprint changes. Release the old device; expect this to be your most common
ticket until the customer portal ships.

**The database is gone.** Every licence and seat with it. This is why 1.1 says
to test a restore. Recovery means reissuing keys from your invoice trail.
