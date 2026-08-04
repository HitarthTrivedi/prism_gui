# How Prism gets sold — the plain-English version

**Read this first.** No code, no jargon. It explains what we're building and
why, so anyone — technical or not — can follow the rest of the docs.

The other documents in this folder are the detailed specs:

| Doc | What it answers |
|---|---|
| `01-token-and-crypto.md` | What a licence actually *is*, and why it can't be forged |
| `02-api-and-data.md` | What the server does and what it stores |
| `03-client-integration.md` | What changes inside the Prism app |
| `04-operations.md` | Day-to-day: issuing keys, fixing customer problems |
| `05-build-checklist.md` | The build order for Phase 1 |

The strategy and the reasoning behind the decisions live one level up, in
[`LICENSING.md`](../../LICENSING.md).

---

## The problem in one paragraph

Right now anyone can download Prism from Releases and use it forever, free. We
want: a **30-day free trial**, then a **paid subscription**, with **add-ons**
(BOQ, Reel/Studio, BOM) unlocking based on what the customer pays for. That
needs a server we host, because the customer's own computer cannot be trusted
to remember honestly when their trial started.

---

## The customer journey

```
   1. DOWNLOAD                2. FIRST LAUNCH              3. TRIAL
   ┌──────────┐              ┌────────────────┐          ┌──────────────┐
   │ Releases │─────────────▶│ "Start your    │─────────▶│ 30 days,     │
   │ page     │              │  30-day trial" │          │ everything   │
   └──────────┘              │  name, email,  │          │ unlocked     │
                             │  company       │          └──────┬───────┘
                             └────────────────┘                 │
                                     │                          │
                             or "I have a key"                  │
                                     │                          ▼
   6. RENEWAL                        │              4. TRIAL ENDS
   ┌──────────────┐                  │              ┌────────────────────┐
   │ Card charged │                  │              │ App still opens.   │
   │ or invoice   │◀─────────────────┼──────────────│ History readable.  │
   │ paid         │                  │              │ New runs blocked.  │
   └──────┬───────┘                  │              └─────────┬──────────┘
          │                          │                        │
          │                          │              5. THEY BUY
          │                          │              ┌────────────────────┐
          └─────────────────────────▶└──────────────│ We issue a licence │
                                                    │ key. They paste it.│
                                                    └────────────────────┘
```

### 1. Download
Unchanged. Same GitHub Releases page, same portable build.

### 2. First launch
Instead of going straight to Setup, the app asks: **start a trial**, or **enter
a licence key**. Starting a trial needs an internet connection once — name,
work email, company. That's it.

### 3. Trial (30 days)
Everything works: every add-on, no limits. The point of a trial is to sell the
product, not to tease it.

We can **extend any customer's trial from the admin panel** without shipping a
new build. If a pilot stalls because the client's CAD guy was on leave, we give
them another two weeks in ten seconds.

### 4. Trial ends
The app **still opens**. History still readable, past outputs still there,
Setup still works. Only *new runs* are blocked, with a clear "here's how to
buy" message.

This matters: never hold a customer's own work hostage. That converts a lapsed
trial into an angry email instead of a sale.

### 5. They buy
Two routes, and the second is the one that'll actually get used at first:

- **Self-serve** — card/UPI through Razorpay, licence key emailed automatically.
- **Invoice** — they send a PO, we invoice, they bank-transfer, we issue the
  key by hand from the admin panel. Indian B2B runs on this. It has to work on
  day one.

Either way they get a key like `PRSM-4K2XA-9WQ7M-3TYRB-8HNVE`, paste it into
Prism, and their plan's add-ons light up.

### 6. Renewal
Subscription renews. If it lapses or gets refunded, the app notices within a
week and goes back to the "trial ended" state.

---

## How the app knows what's unlocked

This is the one technical idea worth understanding, because everything else
follows from it.

The server gives the app a **licence token** — a small block of text saying
*"this machine, this customer, these add-ons, valid until this date"* — with a
**digital signature** on it.

```
  ┌─────────────────────────────────────────────────────┐
  │  customer: RS Infotech                              │
  │  plan:     business                                 │
  │  unlocks:  core, boq, email                         │
  │  machine:  a3f9c2…                                  │
  │  expires:  11 August 2026                           │
  ├─────────────────────────────────────────────────────┤
  │  signature: (only our server can produce this)      │
  └─────────────────────────────────────────────────────┘
```

Think of it as a **passport**. The customer holds it. They can read it. They
cannot alter it — change one character and the signature stops matching, and
the app rejects it. Only our server holds the key that can produce a valid
signature.

**Why this design and not "phone the server every time":**

- **Runs take a long time.** Prism drives Chrome through multi-stage pipelines.
  If a Wi-Fi hiccup could kill a run at stage 4, we'd be creating support
  tickets, not preventing piracy.
- **Site machines have bad internet.** BOQ users are on construction sites.
- **If our server goes down, nobody stops working.** The passport is already in
  their pocket.

**The trade-off:** the passport is valid for 7 days. So if someone cancels or
charges back, they keep working for up to a week. That's fine — it's a rounding
error against the support cost of the alternative.

The app quietly asks for a fresh passport every time it starts. If it can't
reach the server, it keeps using the old one until it expires, plus 3 days of
grace, showing a gentle countdown banner.

---

## What stops people cheating

Being straight about this, because it shapes how much we invest.

| Someone tries… | What happens |
|---|---|
| Editing the licence file to add add-ons | **Blocked.** The signature stops matching. |
| Setting their clock back to extend the trial | **Blocked.** The app remembers the latest date it has ever seen. |
| Deleting `~/.prism` to restart the trial | **Blocked.** The server remembers the machine, not the folder. |
| Copying one licence to 10 machines | **Blocked.** Seats are counted server-side. |
| Unpacking the app and deleting the check | **Works.** They'd have to want it badly. |

That last row is deliberate. Prism is a frozen Python app; a determined person
can patch it. Our customers are engineering and construction firms — they don't
crack software, they let subscriptions lapse. **We're building billing hygiene,
not anti-piracy.** Spending weeks on obfuscation would buy nothing.

If we ever want a truly uncrackable lock, there's exactly one way: move part of
the work to our server, so the app is useless without us. That's discussed as
Phase 3 in [`LICENSING.md`](../../LICENSING.md) — it's tied to a bigger decision
about the Groq API key.

---

## What we're building, concretely

**A server** (small — one Python service plus a database, roughly ₹1,500–2,000
a month to host):
- issues trials and licence keys
- signs passports
- counts seats
- receives payment notifications from Razorpay
- gives us an admin page to issue keys and extend trials by hand

**Changes inside the Prism app:**
- a first-launch screen: start trial / enter key
- a check at startup
- a check when opening BOQ, Email, Reel — locked ones show an upgrade message
  instead of opening
- a Licence section in Setup showing plan, seats used, renewal date

---

## Glossary

| Term | Meaning |
|---|---|
| **Licence key** | What the customer types in, once. `PRSM-XXXXX-XXXXX-XXXXX-XXXXX`. Identifies their subscription. |
| **Token / passport** | What the app stores and checks on every launch. Signed, expires in 7 days, refreshed automatically. The customer never sees it. |
| **Entitlement / feature** | One unlockable thing: `core`, `boq`, `email`, `reel`, `bom`. |
| **Seat** | One activated machine. A 5-seat licence runs on 5 computers. |
| **Device fingerprint** | A one-way hash of a machine's hardware ID. Lets us count seats without collecting anything identifying. |
| **Grace period** | 3 extra days after expiry where the app still works, with a warning. Absorbs failed payments and travel. |
| **Activation** | Turning a licence key into a passport on one machine. Uses one seat. |
| **Deactivation** | Releasing a seat so the customer can move to a new machine. |
