# Operations runbook

What you do day to day once this is live. Written for the person on support —
which, for a while, is you.

---

## The six things that will actually happen

### 1. Handing a build to a new client for evaluation

**This is now the entry point to everything.** Nobody can use Prism without a
key you generated, so issuing one *is* the sales handover.

```
POST /admin/licenses
{ "name": "Kiran Shah", "email": "kiran@rsinfotech.in",
  "org": "RS Infotech Pvt Ltd",
  "kind": "trial", "plan": "trial", "days": 10,
  "features": ["core","boq"], "seats": 2,
  "notes": "Eval for BOQ. Demo 4 Aug. Decision by 20 Aug." }

→ { "key": "PRSM-4K2XA-9WQ7M-3TYRB-8HNVE", "license_id": "lic_01HZX8K2M9" }
```

Send them the Releases link and the key. That's the whole handover.

Set `days` to whatever you promised — 10, 14, 30. It ends on that day, exactly:
trials carry `grace_days = 0`. Give them only the `features` they're actually
evaluating; a BOQ pilot doesn't need Reel unlocked, and a shorter feature list
is a cleaner conversation.

**The key is shown exactly once.** The server stores only its hash. Copy it
into the email before closing the tab. If you lose it, revoke and reissue —
there is no recovery, by design.

### 2. They buy (invoice route)

The common path for Indian B2B. They send a PO or ask for a proforma invoice;
they pay by NEFT/RTGS; you issue a paid key.

```
POST /admin/licenses
{ "…": "…", "kind": "paid", "plan": "business",
  "features": ["core","boq","email"], "seats": 5, "days": 365,
  "notes": "PO 4471, NEFT recd 12 Aug 2026, contact Kiran +91…" }
```

They paste the new key over the old one in Setup → Licence. Nothing is
reinstalled, and their history and settings are untouched.

Fill in `notes` properly. Eight months from now, at renewal, it is the only
thing that will tell you who this was and how they paid.

### 3. "Our trial ran out but we're still evaluating"

```
POST /admin/licenses/lic_01HZX8K2M9/extend    { "days": 14, "reason": "…" }
```

Takes effect on the customer's next launch — within a few seconds if they
restart, otherwise at the next 12-hour refresh. **No new build, no
re-download.** Tell them to restart Prism.

This is the single most useful operational lever you have. Use it freely: an
extended trial that converts is worth infinitely more than a lapsed one that
was technically correct.

### 4. "It says all our seats are in use, but we only have 3 computers"

Almost always reimaged machines or replaced laptops. The old fingerprints are
still holding seats.

```
GET  /admin/licenses?q=rsinfotech      → device list with last_seen
POST /admin/devices/{id}/release
```

Release anything whose `last_seen` is more than ~30 days old. Then have them
relaunch.

**This will be your most common ticket.** Machine fingerprints change on OS
reinstall — see the reimage note in
[`01-token-and-crypto.md`](01-token-and-crypto.md). The permanent fix is the
self-service device list in the customer portal (Phase 2); until that ships,
this is a manual job and worth doing within the hour.

### 5. "Prism says my licence couldn't be verified"

The grace banner. Work through it in this order:

1. **Are they online?** The banner appears when refresh fails. If the machine
   is offline, that is the system behaving correctly — they have 7 days plus 3
   of grace. Nothing to fix.
2. **Corporate proxy or firewall?** Have them open `https://api.alphakore.in/health`
   in a browser on that machine. Many engineering firms block unknown outbound
   hosts; the fix is an allowlist entry on their side.
3. **Is the server up?** Check `/health` yourself.
4. **Clock wrong?** If the machine's date is badly wrong (new build, dead CMOS
   battery), the app reports `TAMPERED`. Fixing the clock and relaunching
   clears it.
5. **Seat released by mistake?** Re-activating with their key fixes it and
   costs nothing.

Note the shape of this list: in four of five cases nothing is broken on our
side, and the customer is still working the whole time. That is the offline
token design doing its job.

### 6. Refund or cancellation

```
POST /admin/licenses/{id}/revoke   { "reason": "refunded 14 Sep" }
```

They keep working until their current token expires — **up to 7 days**. That is
inherent to offline verification and it is the right trade. Do not try to build
instant kill; the machinery required would break the offline guarantee that
every other customer depends on.

---

---

## Publishing a payload (Tier 2)

New capability, and the one with real blast radius. The tool registry, CSS
selectors and prompt templates now live on the server, so **you can fix them for
every customer without shipping a build** — and you can break them for every
customer just as fast.

### When a selector breaks

Claude or ChatGPT changes their page; runs start failing at that stage. Today
this means four platform builds and chasing everyone to update. Now:

```
POST /admin/payload            { "base": "pl_7c1f",
                                 "changes": {"agents": {"Claude": {…}}},
                                 "min_version": "1.1.0" }
→ { "etag": "pl_8d20", "published": false }     # staged, not live

POST /admin/payload/pl_8d20/publish
```

Customers pick it up on their next refresh — within 12 hours, or instantly on
relaunch.

### Rules for publishing

**Always stage, verify, then publish.** A payload goes to every customer at
once. There is no canary and no gradual rollout, which makes the staging step
the only safety net there is.

**Verify against a real run before publishing.** Point a dev build at the staged
etag and drive the affected tool end to end. A selector that looks right in the
DOM inspector and fails under `undetected-chromedriver` is the normal case, not
the exception.

**Roll back by publishing the previous etag.** One row update, effective
immediately. Never hot-edit a live payload — publish a new version, so
`audit_log` records what changed and you can get back.

**Bump `min_version` when a change needs new client code.** An old build
receiving a payload it cannot parse must refuse it and keep its cache, but do
not rely on that as the plan.

### Watch after every publish

Refresh volume and error reports for the following hour. A payload that breaks
routing produces failing runs across your whole customer base simultaneously —
this is now the single largest operational risk in the product, and it is the
price of being able to fix selectors in minutes.

---

## Monthly rhythm

**Renewals** — query licences expiring in the next 30 days. Reach out before
expiry, not after. A lapsed subscription that goes read-only without warning
reads as a bug to the customer, whatever the contract says.

**Dormant seats** — devices with `last_seen` older than 30 days on an active
licence. This is churn, visible a quarter early. It is also a sales opening:
"we noticed two of your five seats haven't opened Prism since June — anything
we can help with?"

**Failed refreshes** — a spike from one customer means a proxy or firewall
change on their side. They will not report it, because the app keeps working
until it suddenly doesn't.

**Backup restore drill** — once a quarter, restore the database backup to a
scratch instance and confirm it loads. An untested backup is not a backup, and
losing this database means losing every seat and subscription record.

---

## Things not to do

**Don't hand-edit the database to fix a licence.** Use the admin endpoints —
they write `audit_log`. When a customer disputes a cancellation, that log is
the entire record.

**Don't reuse a revoked key.** Issue a new one. Keys are cheap.

**Don't extend a trial by editing `expires_at` directly.** The extend endpoint
records who did it and why.

**Don't put the private signing key anywhere but the host's secret store.** Not
in the repo, not in a `.env` that gets committed, not in a screenshot in a
support thread. Losing control of it means every licence ever issued can be
forged; losing the key itself means no customer can ever renew without a new
app build.

---

## Emergencies

### The licence server is down

Nothing urgent happens. Every customer has an offline-valid token for up to 7
days, plus 3 days of grace. Fix it calmly, within the day.

### The signing key leaked

1. Generate a new keypair, new `kid`.
2. Ship an app build containing **both** public keys.
3. Once most customers have updated, start signing with the new `kid` only.
4. Revoke nothing — old tokens expire within 7 days on their own.

The `kid` field exists for exactly this. Without it, this incident would mean a
forced simultaneous upgrade for every customer.

### The database is lost and the backup is bad

The worst case, and the reason backups get a dedicated line here. Recovery
means rebuilding `licenses` from Razorpay's records plus your invoice trail,
and asking invoice customers to re-activate. `notes` and your sent email are
what make it survivable. Test the restore before you need it.
