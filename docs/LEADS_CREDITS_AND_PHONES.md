# Leads & Outreach — the credit pool and phone numbers

Written 20-Sep-2026. Two owner decisions drive this: **no bring-your-own keys — customers spend a pool of
credits**, and **phone numbers must be part of Leads** (today the Lead model has a `phone` field that only a
spreadsheet import ever fills; nothing finds one).

## 0. Where things stand

| | State |
|---|---|
| Function / Current company / Company HQ filters | **Removed** (20-Sep). Old saved searches still load. |
| Credit ledger on the licence server | **Built** in `prism-license-server` (`app/credits.py`), tested; admin console has a Credits tab (24-Sep) |
| Provider gateway (`/v1/leads/*`) | **Built 24-Sep-2026, tested against fake providers and over real HTTP** — Exa (people, company, website, why-now), Groq (qualify/draft), the e-mail verifiers, Hunter (find). **Not yet run against a live provider**: it needs the owner's provider keys set on the server and a licence with the `leads` feature and some credits (§3a) |
| Leads screen on the pool | **Built 24-Sep-2026**: credits pill, every paid action says what it costs in credits before it runs and asks, no API-key boxes, no verifier-key card in Settings, an empty pool stops a run and says so. `PRISM_LEADS_DIRECT=1` keeps the developer's own-keys mode (a dev switch, not a setting) |
| Phone finding | Not built. **Owner decision 20-Sep: pooled credits, EasyLeadz (human Unlimited seat + API) as the source, Apollo as the comparator. Corrected comparison in §4.2. Everything now hinges on EasyLeadz's written answer (§8) — nothing is bought or built against them until it arrives.** |

## 1. What changes for a customer

* No API-key boxes and no "Local · BYO-key" badge. Leads shows **a credit balance** and, before any paid action,
  **what it will cost** ("Find phone numbers for 40 people — up to 400 credits"), replacing today's "can spend 300
  Apollo credits" warnings.
* Every paid action goes through the licence server, which holds the provider keys, charges the ledger, calls the
  provider and hands back the result. The customer's machine never sees a provider key.
* Running out stops the run cleanly with "Not enough credits" and the balance — never a half-charged run.

## 2. Architecture

```
Prism (Leads)  ──licence+seat──►  licence server  ──►  Exa / Apollo / verifiers / Groq / phone providers
   balance, estimate, results      auth · ledger · rate card · jobs
                                        ▲
   provider webhooks (phone results) ───┘   (EasyLeadz and Apollo deliver phones minutes later, to a public HTTPS URL)
```

The same shape as `/v1/whatsapp/*`: the licence server is the auth authority; the client holds no provider secret.
Phone results are asynchronous, so the gateway keeps a **job** per request and the app polls it.

## 3. The credit ledger (built)

* One balance per licence, kept in step with an **append-only ledger** (`credit_ledger`): grant, spend, refund,
  adjust. The balance can never go negative — a spend is a conditional update that fails if funds are short.
* **Idempotent**: every spend carries a key; a retry of the same key charges once. A refund is keyed to its spend, so
  a spend is refunded at most once and only up to what it charged.
* **The rate card is data** (`credit_rates`: action → credits), editable by an admin call, returned to the app so it
  can show estimates. The seeded values are **placeholders** — the owner sets the real prices.
* Admin: grant/adjust with a reason (audit-logged), read a licence's ledger. The client can only read its balance and
  the rate card; it can never spend, refund or grant.
* Not built yet, deliberately (they depend on decisions in §7): monthly allowances that expire, purchase / payment,
  low-balance alerts, per-seat limits.

## 3a. The Leads gateway (built 24-Sep-2026)

**Pattern — hold, work, settle.** A gateway call charges its *maximum* up front (`INSUFFICIENT_CREDITS` before any
provider is touched), calls the provider with the server's key, then refunds whatever was not used — all of it when the
provider failed. A retry of the same idempotency key replays the same request: charged once, provider asked again. The
spend key is `leads:{idem_key}:{sha1(op|request)[:12]}`, so one key can never be reused to buy a *different* lookup
for free. Every call is one `leads_calls` row (units, credits, provider-reported cost, tokens, ok/error, ms).

| Endpoint | Rate-card action | Charged |
|---|---|---|
| `/v1/leads/people` | `people_search` | **per search**: 1 unit if it returned anyone, 0 if not |
| `/v1/leads/company` | `company_lookup` | 1 unit |
| `/v1/leads/domain` | `domain_lookup` | 1 unit (a company's website, for the finders) |
| `/v1/leads/signals` | `signals` | 1 unit (why-now news) |
| `/v1/leads/llm` | `ai_qualify` / `ai_draft` | 1 unit; the server picks the model |
| `/v1/leads/verify` | `email_verify` | 1 unit, only when a verifier answered (free-first waterfall, stops at "valid") |
| `/v1/leads/find-email` | `email_find` | 1 unit, only when a finder knew the person. **Hunter only** — nothing is ever guessed (owner rule, 24-Sep) |
| `/v1/leads/status` | — | balance, price list, and which lookups are switched on |

*Why per search, not per person.* Charging per person returned made the cost of a press impossible to state — one
press can run up to 60 searches of up to 50 people. Per search, the app counts the searches exactly before it runs
(`source.planned_searches`) and can say "about 12 searches — up to 36 credits", and a search that finds nobody is free.

**Every gate a call goes through**, in order: a seated device on an active licence → the `leads` feature → a per-device
rate limit → the kill switch (`LEADS_GATEWAY_DISABLED=1`) → the provider key is set (else `PROVIDER_NOT_CONFIGURED`,
nothing charged) → the hold. Provider keys are read from the server's environment at call time, never stored in the
database and never returned (`GET /admin/leads-providers` returns booleans only).

**Client seam.** In pooled mode `prospector/gateway.py` swaps the engine's Exa/Groq keys for the sentinel `"pool"` and
drops every other provider key; each provider call in the engine has one `if gateway.is_pool(key)` branch that asks
the licence server instead of `requests`. Nothing else in the engine changed. When the pool is empty the client
remembers the refusal and refuses further paid calls at once, so a run **stops** rather than reading "the call failed"
as "no results".

**Admin console** (Manage licence → Credits): balance, top-up / correction with a note (idempotent per click), the
ledger, this customer's lookups against what the providers cost us, the price list (editable, with reset), and which
provider keys the server holds.

## 3b. Credit usage, plans and requests (built 24-Sep-2026)

The owner asked where a customer sees and checks their usage and upgrades, and sent Apollo's own screens (Credit usage
page, the side-nav "Team credit usage" card, the Upgrade flow, "What are credits?"). Built in Prism's shape:

* **In the app** (`addons/leads/credits_page.py`): the balance pill in the page header opens the small **Team credit usage**
  card (used of allowance, a bar, credits left, *Upgrade plan* / *View usage*). **View usage** is the **Credit usage** page —
  *Overview* (a donut by feature or by team member, *Available credits* with "credits will renew on …", *Add more credits*),
  *Usage details* (every movement, newest first, CSV export) and *About credits* (what each lookup costs) — with the Date /
  Team member / Features filters. **Upgrade** is *Select plan → Add-ons → Payment → Review*.
* **There is no payment gateway.** The last step **sends a request** to Alphakore (`POST /v1/credits/request`) and the Payment
  step says so ("No card is taken here"). The operator's console lists requests (Credits tab → *Credit requests*); **Apply**
  puts the licence on the plan (or adds the pack's credits) and marks the request done in one click, and the customer sees it
  on their next read. Asking twice for the same thing is one open request. Wiring a real gateway (Razorpay etc.) is a separate
  decision — the request record is what it would replace.
* **Plans renew; pools do not.** A licence with `credit_allowance > 0` is on a plan: every `credit_cycle_days` the leftover
  **expires** (unless *Roll over* is ticked) and the allowance is granted again — Apollo's "unused credits don't roll over".
  Renewal is lazy and idempotent (ledger keys `cycle:{licence}:{start}`), runs inside the licence row lock on any spend or
  read, and renews **once** however many cycles were missed. A licence with no allowance is a plain top-up balance and none of
  this touches it (every existing licence, and manual pilot top-ups). **Credits added by hand on a plan also expire with the
  cycle unless it rolls over** — say so when you grant.
* **Plans and packs are data** (`credit_offers`): until the owner saves his own, the built-in placeholder examples show (Starter
  500 / Growth 2,000 / Scale 6,000 credits a cycle, two packs) with **no price** — the app says "Ask Alphakore". Set real ones,
  and prices in ₹, in the console (Credits tab → *Plans & packs on offer*). Editing an offer does not change licences already
  on it.
* **Team members = seats.** The ledger records which seat a spend came from (`credit_ledger.device_id`; a refund stays with the
  seat that was charged), labelled by the machine's name, else "Seat N".
* Server: `POST /v1/credits/{usage,offers,request}` (seat-authenticated, no `leads` feature needed to *look*);
  admin `POST /admin/licenses/{id}/credit-plan`, `GET|POST|DELETE /admin/credit-offers`, `GET|POST /admin/credit-requests`.
  Migration `d2b6f8a41c93`.
* **Owner decisions this leaves open:** the real plans (credits per cycle, prices, cycle length, annual or monthly); whether a
  plan's credits should roll over (default no, as Apollo); whether hand-granted credits should be exempt from expiry on a plan
  (today they are not); and when to build a payment gateway. Not built: a monthly-invoice or GST flow, low-balance alerts, email
  when a request arrives (the operator sees a count on the console's Credits tab).

**Go-live checklist:** `prism-license-server/DEPLOY_LEADS_CREDITS.md` (order of steps, every environment variable, the
migrations, the kill switch, what still needs the owner). **Live smoke test:** `prism-license-server/tools/leads_live_smoke.py`
— one real lookup of each kind on a throwaway licence, with what each was charged and what the provider says it cost.

**To switch it on for a customer:** set the provider keys in the licence server's environment (`EXA_API_KEY`,
`GROQ_API_KEY`, the verifier keys, `HUNTER_API_KEY`), tick Leads & Outreach on their licence, and top up their credits.
Then run one live smoke test — a small search, an e-mail find and check, one qualify and one draft — and compare
**Credits charged** against **Provider cost** in the Credits tab before setting real prices (the seeded rates are
placeholders: people_search 3, company_lookup 1, domain_lookup 1, email_find 2, email_verify 1, signals 1,
ai_qualify 1, ai_draft 1).

## 4. Phone numbers

### 4.1 What a phone is
Three kinds, kept apart because they behave differently: **mobile** (the person), **direct dial** (their desk),
**company line** (switchboard). A found number carries `kind`, `status`/`confidence` (as the provider states them),
`source` and `found_at`. The Lead's existing `phone` string stays the one the export and drafts read; the rest goes in
`extra["phones"]`.

### 4.2 EasyLeadz vs Apollo — corrected (every price read from the vendor's live page, 20-Sep-2026)

Converted at **₹96 per US dollar** (18-Sep-2026: 96.07; the rupee is down about 9 % in twelve months). GST +18 % on
everything; figures below are ex-GST. "Per found mobile" is price ÷ numbers if every credit or day is used. EasyLeadz
charges only when a number is found; so does Apollo (0 credits if nothing is returned).

**Withdrawn from my earlier notes:** Apollo "≈ ₹135 a number" — Apollo's own plan cards give ≈ ₹15, and ₹135 was probably
the old pre-2026 overage pricing, which is not on today's page; the ₹86/$ rate — it is ₹96, so the Prospeo and FullEnrich
rupee figures I gave last turn were about 12 % low (corrected in §4.2b); and "API only on Hyper Growth" — the page
contradicts itself (footnote).

#### EasyLeadz — the live plan cards

| Plan | Price (ex-GST) | Numbers | ₹ per found mobile | API on the card? | Notes |
|---|---|---|---|---|---|
| **Unlimited** (human seat) | ₹9,999/user/month, billed yearly (₹1.20 lakh) | ≤ 170 a day, ≤ 5,000 a month | **₹2.0–2.7** (3,740–5,000 a month) | **no** | one user, India only, Chrome extension; **no invalid-number reporting** |
| **Fully Unlimited 20/day** | ₹4,167/month, billed yearly (₹50,004) | 20 a day | **₹6.9** (30 days) – ₹9.5 (22 days) | **yes, plus Bulk Upload** | single-user licence, India only, business profiles only |
| **Fully Unlimited 50/day** | ₹6,667/month, billed yearly (₹80,004) | 50 a day | **₹4.4** (30 days) – ₹6.1 (22 days) | **yes, plus Bulk Upload** | same |
| Standard annual — Hyper Growth | ₹19,249.91/month, billed yearly (₹2.31 lakh) | 7,500 a year | ₹30.8 | yes\* | 25 % bonus credits; invalid-number refunds ≤ 10 % of credits |
| Standard annual — Super Nova | ₹36,299.90/month, billed yearly (₹4.36 lakh) | 15,000 a year | ₹29.0 | yes\* | |
| Standard annual — Startup / Scaleup / Growth | ₹28,999 / ₹71,999 / ₹1.44 lakh a year | 600 / 1,950 / 4,500 | ₹48.3 / ₹36.9 / ₹32.0 | Growth: FAQ yes, feature list no | |
| Standard monthly — Startup → Super Nova | ₹2,419 → ₹36,299 | 40 → 1,000 a month | ₹60.5 → ₹36.3 | listed on every card | credits reset monthly |

\* "Subject to use-case approval". **The page contradicts itself about who has the API:** the FAQ says "Annual Growth and
higher"; the annual feature list shows it only on Hyper Growth and Super Nova; the help article says Hyper Growth or a
customised plan; yet every **monthly** card and both **Fully Unlimited** cards list "API". Only EasyLeadz can settle it, and
it decides the whole comparison — that is the first email (§8). The API itself (help article): `GET
https://app.easyleadz.com/api/prod/`, header `Enapi-Key`, body a LinkedIn `url` or an `email` plus `callbackUrl`;
**asynchronous** (result POSTed to the callback: `phone1`, `phone2`, `email[]`, `request_id`, `error`); **a credit is charged
only if `phone1` is found**; 10 calls a second.

#### Apollo — the live plan cards

| Plan | Price | Credits | ₹ per found mobile (8 credits) | Mobiles per seat-year |
|---|---|---|---|---|
| Basic | $49/seat/month, billed annually ($588 = ₹56,448) | 30,000 a year, granted upfront | **₹15.1** | 3,750 |
| Professional | $79 ($948 = ₹91,008) | 48,000 | **₹15.2** | 6,000 |
| Organization | $119, minimum 3 seats ($1,428 = ₹1.37 lakh a seat) | 72,000 | **₹15.2** | 9,000 |

Credits: e-mail 1, phone 8, enrichment 1–8 (up to 9 a record). The price of **add-on credits is not printed** ("see our
current credit rates"), so the real overage price is unknown. Apollo claims 240M+ contacts but publishes no India hit rate;
independent 2026 tests I could find report roughly 40 % connect rates and ~58 % international deliverability against ~73 %
for the US (vendor-blog evidence, not India-specific). Its own FAQ: the standard plans are **"internal business use only" —
"power external products, share data with customers, or resell Apollo data is not allowed… These use cases require a
separate agreement with custom pricing and terms"** (its **Data Reseller Program**: consult → trial key → reseller agreement,
"most partners complete it within a week").

#### What the comparison actually says
1. **EasyLeadz's Unlimited tiers are the cheapest by a wide margin** — ₹2–3 a number (human seat), ₹4–10 (Fully Unlimited, if
   its API is real) — against ₹15 for Apollo.
2. **EasyLeadz's standard API plans lose to Apollo on price**: ₹29–61 against ₹15. They only make sense if their India hit
   rate is much better than Apollo's. That has not been measured by anyone I can find.
3. **The pilot is tiny.** Ten customers × ~40 phones ≈ 400 a month ≈ 13–20 a day. One Fully Unlimited 20/day account (₹4,167 a
   month) covers it at ≈ ₹8 a number; the human seat's 170 a day is eight times what the pilot needs.
4. **Caps are per account and reset daily at 7 am IST; unused numbers vanish.** A quiet month wastes the seat, so cost per
   number rises as volume falls (₹4,167 ÷ 200 numbers = ₹21).
5. **Wrong numbers are on you** on the Unlimited plans (no invalid reporting); standard annual plans refund up to 10 %. Cost
   per *connecting* number is cost ÷ hit rate: at an assumed 60 % that is ₹7 (Fully Unlimited 50/day) against ₹25 (Apollo at
   an assumed 60 %) — illustrative arithmetic, not measurement.
6. **Currency:** EasyLeadz bills in rupees; Apollo, Prospeo and FullEnrich in dollars, which have cost about 9 % more in a year.
7. **Neither vendor can feed a pool on its standard terms** (§4.2b).

### 4.2a The design that follows: two lanes behind one price list
* **Lane A — API (minutes).** EasyLeadz's API (callback to the licence server) if EasyLeadz approves it on a Fully Unlimited or
  standard plan; Apollo's reseller API as the second source.
* **Lane B — Desk (next working day).** Phone requests queue in Prism's admin console; an Alphakore person on the **Unlimited
  human seat** works the LinkedIn URLs in EasyLeadz's own dashboard (EasySearch or a Bulk Upload CSV — see 4.2c; not the Chrome extension at
  volume), pastes the numbers back, and the ledger charges the same credits.
  Cheapest per number — ₹2–3 for the seat plus labour (one person at ₹30,000 a month on ~4,000 numbers ≈ ₹7.5 → about ₹10
  all-in) — capped at 170 a day per seat.
* Constraints: EasyLeadz's fair-usage policy **prohibits scripts and robots on its UI**, so the desk is a person doing it by
  hand; the licence is **single-user**, so serving customers from it needs EasyLeadz's written consent; and the extension on LinkedIn
  at volume risks LinkedIn's own flags, so the desk should use the dashboard. Which plan should carry the desk — the cheap ₹9,999
  seat (extension only, on its card) or a Fully Unlimited seat (EasySearch, Bulk Upload; 20 or 50 a day) — is open until the free
  account shows what the dashboard offers.
* The customer sees one action, "Find phone numbers". Whether "now" and "tomorrow" cost different credits is a pricing choice
  for the owner.

### 4.2b The resale wall — read before promising a credit pool
A pool lets several customers reveal numbers through one Alphakore account, which is **redistributing the vendor's data to
third parties**. What each vendor's own pages say (read live, 20-Sep-2026):

| Vendor | Standard terms | The route to a pool |
|---|---|---|
| **Apollo** | "internal business use only"; no external products, no sharing data with customers, no resale | Data Reseller Program: trial key, then a reseller agreement, custom pricing |
| **EasyLeadz** | terms of service silent on resale, BUT the Fair Usage Policy (read in full 21-Sep) limits use to *manual* use by individual, authorised End-Users, bans scripts, robots, tools and "intelligent agents", presumes automation when queries exceed what people could do by hand, and defines "Unlimited Credits" as manual one-by-one reveals; API "subject to use-case approval"; Unlimited plans are **single-user licences** | written approval / customised plan (the standard-plan API is the only automated route it describes) |
| **Prospeo** (≈ ₹10–24 a mobile: $49–249 plans, $10 per 1,000 add-on credits; monthly, no lock-in) | §1.2: "You may not resell, redistribute… Output Data to any third party" | "contact privacy@prospeo.io" for a resale arrangement |
| **FullEnrich** (≈ ₹46–53 a mobile: $0.048–0.055 a credit × 10) | forbids resale in standard terms | an explicit API Reseller Program: buy credits, set your own price, white-label, sub-API accounts |
| **Zintlr** (Pro $69/month billed annually ≈ ₹6,600: 5 seats, 1,200 phone + 1,200 email credits a month, expiring monthly; **API is Enterprise-only**) | T&C updated 18-Aug-2026 (read 21-Sep): for "internal business purposes"; the licensee "shall not resell, share, sublicense, or otherwise distribute either raw API data or processed data"; users may not act "on behalf of a third party" | Enterprise / custom deal (the only plan that lists API access) |

The same question applies to **every provider behind the pool** — Apollo, the e-mail verifiers, Hunter, Tomba — and only
the phone vendors' terms have been read so far. Exa and Groq are ordinary API products and least likely to object, but that
needs reading before launch.

**Second opinion from another AI (Brave, 21-Sep) — checked first-hand.** *Held up:* Meta bills the client under Tech Provider; Business Verification ≈ 2–5 working days and App Review ≈ 3–10 (practitioner reports); the 1-Oct change (service messages billable at the utility rate after 1,000 free a month per number — reported by several sites); DPDP substantive duties start 14-May-2027 (Rules notified 13-Nov-2025); no WhatsApp broadcasts to bought numbers; cold calls need DND scrubbing and a 140-series number. *Did not hold up:* Zintlr HAS an explicit no-resale / no-third-party clause and its API is Enterprise-only; EasyLeadz plans were conflated (₹9,999 and 170 a day vs ₹4,167 and 20 a day); email-accuracy figures were shown as phone accuracy; rupee figures used about ₹83/$ (it is ₹96); Apollo does not cap mobiles at 100 (live page: 48,000 credits a year on Pro, 8 credits a phone); 20 a day is 140 a week, not "thousands"; Meta bans general-purpose AI assistants on WhatsApp, not business support bots; FullEnrich and Kaspr were not researched. Net effect: **every phone vendor's standard terms are for the buyer's own staff, so phones in a package need a written managed-service / reseller deal or a client-held seat.**

**Review of that second opinion by Perplexity (21-Sep) — checked.** *Adopted:* the customer scope wording (up to 500 researched contacts and up to 500 email-verification attempts a month; phone enrichment subject to vendor coverage, lawful use and replacement rules; WhatsApp only for opted-in or customer-initiated conversations; Meta and vendor charges passed through), hedged cold-call wording, "publicly discoverable" instead of "publicly available", and modelling the 1-Oct change both ways (do not advertise "1,000 free service messages" until Meta confirms). *Not adopted:* ranking Zintlr first (its terms forbid resale and third-party use; API is Enterprise-only) and its Apollo figure (it repeated the wrong 100-mobile cap; live page: 48,000 credits a year, 8 per phone, about ₹15 a mobile); its "other stack ₹1,000–2,500" is low (sourcing alone is ₹930–2,330). *Confirmed first-hand:* Meta's Business Solution Terms (modified 6-Mar-2026) bar AI providers only where AI is the *primary* functionality, and bar using Business Solution Data to train or improve AI systems except for the business's own exclusive use (so no shared model trained on customers' chats); PIB confirms an 18-month phased DPDP timeline; the DPDP ₹250 crore cap is for security-safeguard failures and other breaches fall under "any other violation", up to ₹50 crore (secondary sources agree; counsel to confirm).

#### The Exa route — what Exa itself can do (tested 21-Sep-2026)
Exa's own price list (read live) has an **Agent API** with a fixed price per request by effort — minimal $0.012, low $0.025, medium $0.10, high $0.50, xhigh $1.00 — plus **contact enrichment billed per contact found: $0.02 an email, $0.07 a phone number** (≈ ₹6.7). No subscription, no minimum. A run takes `input.data` rows and an `outputSchema` (`format: phone` is supported) and returns values with citations and a confidence; fields it cannot support come back null.

**Test 1:** three large Indian companies -> their published head-office number, 3 of 3, with source links, $0.012 for the run.
**Test 2:** Exa's company search found 20 Vadodara engineering firms; one Agent run then looked up each firm's *published* phone: **14 of 20 at minimal ($0.012, 18 s), 16 of 20 at low ($0.025, 28 s)**, 12 and 15 of them +91, several in mobile format (owner or sales lines the firms publish themselves). About ₹0.1 per company.
**Test 3 (the owner's real leads, `Prism leads 150104.xlsx`, 100 rows — 62 Indian, 38 foreign):** the person-level run was **blocked by the session's safety classifier** (it sends named individuals' details to an outside service to fetch their phone numbers), so only company-level lookups ran, sending company name, city and website domain only. 61 unique Indian companies: **29 got a published phone (48%), 19 of them mobile-format (31%)**; 21 from the firm's own site, 5 from a business directory, 3 other; no duplicate numbers; 12 firms had no website and 5 of those still got a number; **$0.10 in total (about ₹9.6), 105 s**. Results: `Documents\Prism Leads\Exa company phone test.xlsx`. Lower than test 2 (70–80%) because these are LinkedIn-sourced one-man units, many without a site. At 48% a month of 500 numbers needs about 1,050 companies (≈ ₹125); the limit is finding enough fresh companies, not the price.

**Not tested:** person-level direct dials (the $0.07 phone enrichment) — that means looking up named individuals, so it needs the owner's own sample of leads; India coverage and accuracy are unknown. n = 20, one city and sector; a published number is not a direct dial, and its connect rate is unmeasured.

**Fiber.ai (asked by the owner, read 21-Sep):** a B2B database (850M+ people, 40M+ companies) that turns a LinkedIn URL into work/personal e-mail and phone, with phones checked by HLR/CNAM (the line is active, not that it is the right person) and no charge when nothing valid comes back. 1 credit = $0.02; a phone costs 2 (Lite), 3 (Quick, default), 4 (Exhaustive) or 5 (Turbo / premium) credits = $0.04–0.10. Two ways in: through Exa Connect (`dataSources: [{"provider": "fiber"}]`, pay as you go, no plan) or directly on Fiber plans from $300 a month (15,000 credits ≈ 5,000 Quick phones; $900 = 50,000; $2,400 = 150,000) — direct only pays at thousands of phones a month. India coverage is untested and Fiber's own terms are an interactive page I could not read (Exa's Connect marketplace terms show no resale ban on provider data, but grant none either). The owner-run script `Documents\Prism Leads\exa_person_phone_test.py` (dry run by default, `--yes` to send, `--fiber` to attach Fiber) compares the two on the same leads.

**Permission:** Exa's Terms bar reselling the Services to a third party "without our prior consent" and using the Services or Output to build a competing product, but its partner page invites partners to "resell the API, embed it in your customer deployments" with revenue share — so a written OK is one email, unlike the phone vendors.

**Other leads Exa surfaced (terms not yet read; test before relying):** vendors that explicitly allow white-label / agency resale — Datagma (phone about $0.28 on its Expert plan, EU-strong, India unclear, no attribution needed), AgentEnrich (Agency plan $399 a month, "resell to clients (white-label)", free API key, US-leaning); India-first pay-per-lookup APIs — EazyReach (phone 8 credits, CXO phone 10, free trial about 18 phones, no charge on a miss, MCA director phones), Bulkpe (director phone ₹30 + GST, refund if not found, LinkedIn URL -> phone), Instafinancials DirectorConnect and IDSPay (MCA director numbers by DIN); 1Lookup Mobile Finder (about $0.14–0.20 a found number, global). The only independent test found (Outbound Kitchen, 10 mobile-data vendors, about $2,500 spent, mid-2026): no provider is both wide and accurate, about 1 in 4 returned mobiles is the wrong person, and only about 60% of valid mobiles are the right person — so validate line type and name before dialling (about $0.10 a number).

### 4.2c How Prism would fetch numbers from EasyLeadz automatically (read first-hand, 21-Sep-2026)

**Confirmed.** The endpoint is live: a call with a dummy key returns HTTP 200 and `{"data":[],"status":"0","message":"Invalid API
key"}`. The help article words that error differently, so its details are out of date, and **errors travel in the JSON `status`,
not the HTTP code** — the client must test `status == "1"`. The contract (help article + that probe):

* `GET https://app.easyleadz.com/api/prod/` with a **JSON body** `{"data": {"url": <LinkedIn /in/ URL>, "email": <optional>,
  "callbackUrl": <https URL>}}` and headers `Enapi-Key`, `Content-Type: application/json`. If both `url` and `email` are sent only
  the URL is used. **Sales Navigator URLs are rejected.** 10 calls a second.
* The immediate reply only says "accepted" and carries a `request_id`. **The number arrives later, as a POST to our
  `callbackUrl`** (`phone1`, `phone2`, `email[]`, `request_id`, `error`). No way to poll for a result is described.
* A credit is used only if `phone1` came back. "No credits left" comes back as an error reply.
* The key is issued on the EasyLeadz dashboard page `dashboard.easyleadz.com/integerateapi`, and **only after EasyLeadz has
  enabled the API for the account**. The pricing FAQ says the API is "subject to use case approval" and that by default it is
  *not* available to every user — on any plan.

So the card ticking "API" on the Fully Unlimited plans is **not** access. Four places give four answers (FAQ: annual Growth and
up; annual feature list: Hyper Growth and Super Nova; help article: Hyper Growth or a customised plan; the Fully Unlimited and
monthly cards: listed), and all of them end in "ask support".

**The flow in Prism**
1. The customer ticks hot leads → Find phone numbers → sees the estimate → confirms.
2. The licence server checks the licence and the balance and holds the credits (one ledger row, idempotency key = job).
3. A worker sends each lead's LinkedIn URL to EasyLeadz with `callbackUrl` =
   `https://<licence-server>/v1/leads/phones/callback/<one-time token>`, and stores the `request_id`.
4. EasyLeadz posts the result. The server matches token + `request_id`, ignores repeats, saves the number, and **charges only when
   `phone1` is present** (otherwise it releases the hold).
5. The app polls the job and fills the phone column, drawer and export.

**What the server must handle that the vendor's page does not spell out**

| Risk | Why | Handling |
|---|---|---|
| Callback is unsigned | anyone who guesses the URL could post a fake number | random one-time token in the path, match on `request_id`, accept once |
| No retry or poll is described | a callback missed while our server is down means the number is lost | ask if they retry; keep the endpoint tiny and always on; after ~15 minutes mark the item "no answer" and release the hold, but still accept a late callback |
| Daily cap: 20 or 50 a day per account, reset 7 am IST | the cap is the **whole pool's ceiling**, and "No credits left" is not "not found" | count found numbers per account per IST day; queue the overflow to the next morning; never refund it as a miss |
| **A non-+91 number pauses the account for 24 h (10 pauses = blocked, no refund)** | one customer's foreign lead could freeze every customer | send only leads whose person location is India; unknown location → desk lane or skip |
| Public `/in/` URLs only | Sales Navigator exports carry `/sales/lead/...` URLs | skip those (or fall back to the lead's e-mail) and show "needs a LinkedIn profile URL" |
| Errors arrive as HTTP 200 | `status` and `message` are in the body | one small client mapping them to found / not found / retry later / account problem |
| One key, single-user licence | a pool has many customers | the resale question in 4.2b |

**Ways to settle whether the Fully Unlimited API is real, cheapest first**
1. **₹0 — a free EasyLeadz account** (5 free numbers): open the API page above and see whether a key is offered or locked.
   Creating the account is the owner's; I cannot. **Done 21-Sep-2026:** the API page on the free account is locked — it says
   to contact your account manager or e-mail support — so there is no self-serve key, exactly as the FAQ says, and a free
   account cannot show what a paid plan unlocks. The dashboard menu lists My Contacts, My Team, Search Phone numbers, People
   Finder, CSV Enrichment, API Enrichment, CRM Enrichment, EasyProspect, Billing & Invoices.
2. **₹0 — the e-mail in §8 plus the 15-minute demo call** (a booking link sits on their Data Enrichment page): ask them to show
   the API key screen on a Fully Unlimited account, enable a trial key, and confirm in writing.
3. **≈ ₹2,850 with GST — one month of Startup** (₹2,419 + 18 %, 40 numbers; every monthly card lists API): the cheapest real
   end-to-end test, and it doubles as the hit-rate test on 40 real leads. It only works if they switch the API on for the account.
4. **₹50,004 + GST (≈ ₹59,000), non-refundable — Fully Unlimited 20/day, annual:** only after 1–3 have worked.

**Three other routes found on the way**
* **Bulk Upload** is also on the Fully Unlimited cards: a CSV of LinkedIn URLs (up to 3 × the available credits, at most 5,000),
  results viewable and downloadable, an e-mail when the sheet is ready. The help article says Growth and up, the same
  contradiction as the API. A person uploading a file is not a robot, so this is the sound form of the desk lane — **one upload per
  batch instead of one look-up per lead** — still capped by the daily allowance.
* **EasySearch** (help centre): a dashboard search that takes a LinkedIn profile URL, an e-mail or a DIN and returns the number,
  with no Chrome extension and no LinkedIn browsing. The Fully Unlimited cards list it; the ₹9,999 Unlimited card lists only the
  Chrome extension. Whether the Unlimited seat's dashboard also has it (the free account's menu shows "Search Phone numbers") is
  to be checked in the free account.
* **A pay-as-you-go tier on the Data Enrichment page** (product name EasyEnrich): "$0.1 per record" (≈ ₹9.6 at ₹96/$), no expiry
  of credits, paid quarterly, a 500-record free trial, "Request a demo". It is sold as CRM enrichment, and the page does not say
  whether a record includes a mobile number or carries the API. If it does, it would beat EasyLeadz's standard API plans (₹29–61)
  with no annual lock — so it is question 6 in the e-mail.

**How the app behaves (help centre, read 21-Sep-2026).** One credit is one number found; nothing is charged for "not found" or
"opted out"; fetching the same contact twice costs once. A number not found today may be added later — EasyLeadz says it then
notifies the customer by WhatsApp or e-mail (ask whether the API calls back again). Team members share the account's credits,
and per-member caps exist only on annual plans. Its own best-practice page says the Chrome extension on LinkedIn can trigger
LinkedIn's suspicious-activity warnings at high volume and suggests 20–30 contacts a day, recommending EasySearch for more.

**Terms read on the way.** The fair-usage policy defines "Unlimited Credits" as revealing contacts *manually, one by one*, and
says revealing thousands within a week triggers a compliance review; the Fully Unlimited plans are not mentioned in it. The
Product Usage Terms are silent on resale, sharing and API use. Their one data clause says the account's contact data is reset to
zero within 7 days after the subscription ends — so Prism keeps its own copy, and the e-mail asks whether that is allowed. A
Datarade listing of their phone-finder API sits behind a bot check; I did not go around it.

### 4.3 Measure before committing anything annual
No one publishes an India mobile hit rate; the independent figure in the earlier research was **~40–63 % across tools**.
Vendor claims (EasyLeadz's "100 % accuracy assurance", Apollo's coverage) are claims. So run the same ~40 real leads with
LinkedIn URLs through the two you are choosing between, and record hit rate, share that are `+91` mobiles, whether the number
picks up (call a sample) and cost per number actually found:

* **EasyLeadz** — Free (5 numbers), or one month of Startup (₹2,419 + GST for 40, API listed on the card) — and if the
  Unlimited seat is bought, its first month is the real test of the desk lane. If EasyLeadz says its pay-as-you-go
  "record" includes a mobile number, the 500-record trial is a free bake-off.
* **Apollo** — through the **reseller trial key** (step 2 of its program), or the trial's 5 mobile credits; the Basic plan is
  annual-only ($588 up front), too much for a test.
* Optional third opinion: FullEnrich Pro ($55, 100 mobiles ≈ ₹5,300) or Prospeo Starter ($49, 200 mobiles ≈ ₹4,700).

`prospector/phone_bakeoff.py` (to build) prints the results table from a CSV of those outcomes. Cost of the two-vendor test:
about ₹3,000 plus a few calls.

### 4.4 The flow
1. Tick leads → **Find phone numbers** → the app shows the estimate (rate × people, as a maximum).
2. Server checks seat + licence + balance, **charges the maximum up front** (one ledger row, idempotency key = job),
   creates the job, calls the provider.
3. Results arrive (immediately, or by webhook); for every person with no number the server **refunds that person's
   share** (a second ledger row). The customer pays for numbers found, not for tries.
4. The app polls the job, writes `phone` + `extra["phones"]`, shows the column and drawer, and the export carries it.
5. **Desk lane:** the job is created with `provider="desk"` instead of calling an API; the admin console lists open desk jobs,
   a person enters or pastes numbers, and step 3's refund-what-was-not-found runs when the job is closed.

### 4.5 What a phone number may and may not be used for
* **A found number is not consent to message it on WhatsApp.** Meta's policy requires opt-in from the recipient,
  naming WhatsApp and the business, with a timestamp and source; owning or buying a number does not count. So Prism
  must **never** load a Leads phone into a WhatsApp audience as opted-in (the WhatsApp platform's consent ledger,
  WS5, is the gate). A person-to-person "open chat" link for a single lead is a separate, manual action.
* **Calling in India** falls under TRAI's Telecom Commercial Communications rules (as amended 12-Feb-2025): numbers
  on the National Customer Preference Register must be scrubbed, telemarketers use the 140 series, and consent rules
  apply. Leads should therefore store `dnd_status` (unknown by default) and warn before any call/SMS action; wiring a
  DND-scrub service is a follow-up. **This is a summary of published guidance, not legal advice** — confirm with the
  partnership's adviser before promoting a calling workflow.
* **DPDP Act**: keep provenance (source, date) on every number so a person's request to delete or correct can be
  answered. The fields in §4.1 are there for that.

## 5. Data model added

Server: `credit_ledger(id, license_id, delta, kind, action, ref, idem_key UNIQUE per licence, balance_after, note,
created_at)`, `credit_rates(action PK, credits, label, updated_at)`, `licenses.credit_balance`, and (gateway, 24-Sep)
`leads_calls(license_id, op, action, provider, units, credits, provider_cost_usd, tokens_in, tokens_out, ok, error, ms,
idem_key, created_at)`. Next (with phones):
`phone_jobs(id, license_id, provider, state, request_ref, callback_token, items JSON (per lead: url or e-mail, request_id, phone1/phone2, state), credits_charged, credits_refunded, created_at,
updated_at)`. Client: `Lead.extra["phones"]`, `dnd_status`.

## 6. Build order
1. **Ledger + rate card + admin + balance/rates endpoint** — done (tested).
2. **Send the EasyLeadz and Apollo emails (§8).** Nothing below is bought or built against a vendor until EasyLeadz answers.
3. **Desk lane** — `phone_jobs` (`provider="desk"`), an admin page to work the queue (export the pending LinkedIn URLs as a CSV
   for EasyLeadz's Bulk Upload, import the downloaded sheet), charge / refund through the ledger. It needs no vendor API, so it
   can be built and tested now; using it for customers waits on EasyLeadz's consent.
4. **Bake-off script** and the two-vendor test (§4.3) → real hit rates → set the real credit prices.
5. **API lane** — EasyLeadz adapter and callback receiver on the licence server (§4.2c). The contract is documented, so it can be
   built and tested now against a fake EasyLeadz and switched on when a key exists; and, if signed, Apollo's reseller adapter.
6. Gateway for the rest (Exa search, e-mail find/verify, Groq qualify/draft), same charge pattern — **done 24-Sep (§3a)**.
7. Client: balance pill, estimates, remove key boxes/badge — **done 24-Sep**; phone column/drawer/export and bulk
   "Find phone numbers" — not built (they wait on 2–5).
8. Purchase / top-up, allowances, alerts. (Manual top-up exists: the console's Credits tab.)

Nothing in 3–8 has been run against a live provider; each needs a small live smoke test with real keys before it is
called done. Steps 6–7 were tested with fake providers and over real HTTP against a throwaway server.

## 7. Owner decisions still open (recommended default in brackets)
Decided 20-Sep: **pooled credits**, and **EasyLeadz (human Unlimited seat + API) as the phone source, compared with Apollo.**
1. **Send the EasyLeadz email (§8).** It asks what settles the plan (eight questions): does the API really come with the Fully
   Unlimited plans; may you use it for your customers' lookups; will they issue several accounts; will they consent to the
   desk lane. [Do this first — free, and everything else waits on it.]
2. **Send the Apollo reseller enquiry (§8).** Apollo's plan maths (≈ ₹15) beats EasyLeadz's standard API plans (₹29–61), so it
   is the honest comparator and the fallback. [Yes — the reseller trial key also gives a free test.]
3. **If EasyLeadz refuses resale:** Apollo or FullEnrich under a reseller agreement, or customer-held phone accounts (which
   brings back bring-your-own for phones only). [Reseller agreement; decide after the reply.]
4. **What each action costs in credits** [from the bake-off's cost per found number plus your margin; the seeded rates are
   placeholders — set them in the console's Credits tab once the smoke test shows the real provider cost per action].
5. **Top-up path** [manual grants by you first — the console's Credits tab; online purchase after the first customers].
6. **Do AI qualify/draft spend credits?** [yes, at a low rate — they cost real money per call. Built as yes, 1 credit each;
   change it in the price list].
7. **Monthly allowance per plan, and does it roll over?** [start with none; grant by hand].
8. **How much to commit up front** [nothing annual until 1 is answered and §4.3 is done; the ₹50,004-a-year Fully Unlimited
   20/day is small enough to try if approved].
9. **Does bring-your-own-key stay for anyone?** **Decided 24-Sep-2026 (relayed by the WhatsApp-bot session, who asked him):
   dev switch only.** The screen shows no key boxes to a customer, there is no "use my own keys" setting and no Apollo opt-in;
   customers spend credits only. Direct mode survives as `PRISM_LEADS_DIRECT=1`, which is how the owner runs Leads on his own
   Exa / Hunter keys. Apollo is not in the pool at all.

## Sources
* Apollo — [Retrieve mobile phone numbers](https://docs.apollo.io/docs/retrieve-mobile-phone-numbers-for-contacts),
  [People Enrichment](https://docs.apollo.io/reference/people-enrichment),
  [Waterfall enrichment](https://docs.apollo.io/docs/enrich-phone-and-email-using-data-waterfall)
* Apollo (read live 20-Sep-2026) — [Pricing](https://www.apollo.io/pricing) (plan cards, credit costs, the internal-use-only FAQ),
  [Data Reseller Program](https://www.apollo.io/partners/api-reseller)
* Exchange rate — [Trading Economics, USD/INR](https://tradingeconomics.com/india/currency) (96.07 on 18-Sep-2026),
  [Federal Reserve H.10](https://www.federalreserve.gov/releases/h10/hist/dat00_in.htm)
* EasyLeadz — [Pricing page](https://www.easyleadz.com/pricing/) (read live, plan cards and FAQ),
  [API help article](https://intercom.help/easyleadz/en/articles/4536417-how-to-use-api-to-fetch-contacts-automatically),
  [Terms of service](https://www.easyleadz.com/terms-of-service/), [Fair usage policy](https://www.easyleadz.com/fair-usage-policy-limits/),
  [Product usage terms](https://www.easyleadz.com/product-usage-terms), [Data enrichment](https://www.easyleadz.com/data-enrichment),
  [Bulk upload help article](https://intercom.help/easyleadz/en/articles/4218224-how-to-upload-profiles-in-bulk-to-fetch-contacts)
  (all read 21-Sep-2026; plus one live call to the API with a dummy key)
* Prospeo — [Enrich Person API](https://prospeo.io/api-docs/enrich-person), [Pricing](https://prospeo.io/pricing), [Terms of Service](https://prospeo.io/terms-of-service) (§1.1–1.3, read live)
* FullEnrich — [Pricing](https://fullenrich.com/pricing), [API Reseller Program](https://fullenrich.com/partners/resellers), [Terms](https://fullenrich.com/tos)
* Meta — [Get opt-in for WhatsApp](https://developers.facebook.com/documentation/business-messaging/whatsapp/getting-opt-in),
  [WhatsApp Business Messaging Policy](https://whatsappbusiness.com/policy/)
* TRAI — [TCCCPR amendment, 12-Feb-2025](https://www.trai.gov.in/sites/default/files/2025-02/Regulation_12022025.pdf),
  [2026 compliance checklist (Express IVR)](https://expressivr.com/trai-compliance-for-outbound-calls-business-messaging-in-india-your-2026-checklist/)
* Provider comparisons (vendor-authored; used only for the coverage claims marked as such) —
  [Enrich](https://www.enrich.so/blog/best-phone-number-finder-tools),
  [SyncGTM](https://www.syncgtm.com/blog/best-waterfall-phone-finders),
  [ModernInbound on Indian B2B data](https://moderninbound.com/blog/best-easyleadz-alternatives)

## 8. Emails to send (drafts — sending is yours)

**1. EasyLeadz — support@easyleadz.com (do this first)**
> Subject: API access on Fully Unlimited plans, and use for our customers — written confirmation please
> We are Alphakore, an Indian software company. Our product, Prism (Leads & Outreach), helps Indian firms find and qualify
> prospects. We would like to use EasyLeadz as our phone-number source and are choosing between your plans. The API page on our free account
> says to contact your account manager or support, so we are writing to you. Please confirm in writing:
> 1. Your pricing page lists "API" on the Fully Unlimited 20/day (₹4,167) and 50/day (₹6,667) cards and on the monthly plans,
>    while the FAQ says API is on "Annual Growth and higher" and your help article says Hyper Growth or a customised plan. Which
>    plans actually include API access, and at what daily volume?
> 2. Our software would call the API from our server (LinkedIn URL in, `phone1` out, via `callbackUrl`) for lookups requested by
>    our customers, who pay us from a prepaid credit balance. Is that use approved? If a customised or reseller plan is needed,
>    what is the price per number?
> 3. Those plans say "single user licence". May we hold several accounts, and may the numbers be stored in each customer's list?
> 4. We would also like one person on an Unlimited seat to work requests by hand for customers. Is that permitted, and if not,
>    what would be?
> 5. Do the Unlimited plans really return only +91 numbers, and is there any accuracy or refund policy on them?
> 6. Your Data Enrichment page shows pay-as-you-go at $0.1 per record with no expiry and a 500-record trial. Does a record
>    include a mobile number, is the API available on it, and can we use it for our customers' lookups?
> 7. About the API itself: is the `callbackUrl` request signed or carrying a secret, do you retry if our server is down, can a
>    result be fetched again by `request_id`, and do API calls and Bulk Upload count against the same daily 20 / 50?
> 8. Before we buy an annual plan, can you switch the API on for a two-week trial key so we can measure the hit rate on Indian
>    decision-makers? We will also book your 15-minute demo call.

*Short version: send 1, 2, 3 and 6 first, and keep 4, 5, 7 and 8 for the demo call.*

**2. Apollo — the "Talk to our team" form on apollo.io/partners/api-reseller**
> We are Alphakore (Prism, Leads & Outreach). We would like to embed Apollo people search and enrichment, including mobile
> numbers, in our product for Indian customers, who spend prepaid credits. Please share the reseller pricing per e-mail and per
> mobile reveal, the minimum commitment, whether the returned data may be stored in each customer's list, and a trial key so we
> can measure the mobile hit rate on Indian decision-makers before signing.

**3. Fallbacks (only if 1 and 2 stall)**
> *FullEnrich — partner team:* We'd like the API reseller agreement: price per mobile and e-mail at 500, 2,000 and 10,000 credits
> a month, any minimum, whether we may sell credits at our own price, and your measured mobile hit rate on Indian
> decision-makers.
> *Prospeo — privacy@prospeo.io:* Per §1.2 we would like to discuss a resale arrangement: we call your enrichment API from our
> servers for customers' prospect lists paid from prepaid credits. What terms and volume pricing are available?
