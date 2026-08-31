# Tier 3 — server-side execution (deferred)

**Status: not being built. Recorded so the decision and its costs survive.**

Tiers 1 and 2 are the plan of record, and both are built — see
[`00-overview.md`](00-overview.md).
This document exists so that when someone asks *"can we make it completely
uncrackable?"* in a year, the answer and its price are already written down.

---

## What T3 is

Move the routing *call itself* onto the licence server. The client sends the
user's task and their agent configuration; the server builds the prompt, calls
Groq, and returns the finished plan.

```
      TIER 2 (building this)              TIER 3 (deferred)
   ┌──────────────────────┐            ┌──────────────────────┐
   │ client               │            │ client               │
   │  · assembles prompt  │            │  · sends task        │
   │  · calls Groq        │            │  · renders the plan  │
   │  · has the strings   │            │  · has nothing       │
   └──────────┬───────────┘            └──────────┬───────────┘
              │ payload (data)                    │ task in
              ▼                                   ▼ plan out
   ┌──────────────────────┐            ┌──────────────────────┐
   │ server               │            │ server               │
   │  · sends strings     │            │  · builds the prompt │
   │                      │            │  · calls Groq        │
   └──────────────────────┘            └──────────────────────┘
```

T2 withholds the *strings*. T3 withholds the *logic*.

## What it would close

T2's one honest gap: a client who takes a legitimate trial, patches the binary,
and keeps the payload they were legitimately given. T2 makes that copy perish
on its own (see the perishability argument in
[`02-api-and-data.md`](02-api-and-data.md)) — T3 makes it impossible, because
the machinery was never on their disk to begin with.

There is nothing to patch. `plan()` is an HTTP call to us or it is nothing.

## What it costs

Four things, and none of them are small.

**Every run needs the internet.** T2's design lets a site engineer activate in
the office and work all month from a basement. T3 ends that. The offline
tolerance argued for throughout [`LICENSING.md`](../../LICENSING.md) — long
Chrome pipelines that must not die on a network blip — is spent here.

**Customer data transits our servers.** The user's task text, their profile,
their file names. For BOQ it would eventually mean drawing geometry. Construction
and engineering clients have confidentiality obligations to *their* clients;
some will need a DPA, and some will simply say no. This is a sales objection,
not just an engineering cost.

**Our uptime becomes their uptime.** Today, our server dying is invisible for a
week. Under T3 it is a total outage for every customer simultaneously. That
implies real on-call, monitoring, and redundancy — an operational burden far
larger than the code.

**We pay for inference.** Today customers bring their own Groq key. Under T3 the
bill is ours, per customer, forever, and it has to be inside the subscription
price. That is a pricing decision before it is a technical one.

## When it would be worth it

Any one of these:

- **A customer we do not trust.** Reselling risk, a competitor's subsidiary, or
  a territory where enforcement is impractical.
- **Volume past roughly 50 seats**, where one cracked copy circulating stops
  being a rounding error.
- **We move to usage-based pricing**, which needs server-side metering anyway —
  at which point T3 is nearly free, because the call is already ours.
- **We stop asking customers for a Groq key.** Proxying inference is the same
  architecture; if that ships for onboarding reasons, T3 comes with it.

That last one is the realistic trigger. The "paste your own Groq API key" step
in [`onboarding.py`](../../prism_terminal/core/onboarding.py) is a conversion
problem for a paid product, and fixing it lands us in T3 territory regardless of
licensing. **If that change is ever scheduled, do T3 at the same time** — doing
them separately means building the same plumbing twice.

## Rough shape, if built

- `POST /v1/route` — `{task, profile, agents, premium, attachments_meta}` →
  the same routing dict `core/router.py` returns today.
- The client keeps its rendering, its guardrails, and its stage-name copy; only
  prompt construction and the Groq call move.
- Keep the local path behind a flag for development, and never ship it enabled.
- Cache aggressively: identical task + config should not pay twice.
- Rate-limit per licence, or one runaway loop becomes an unbounded bill.

Estimated **1–2 weeks** on top of T2, plus ongoing operational load that does
not end.

## What not to do instead

**Obfuscation.** Every few months someone suggests PyArmor or similar as a
cheaper T3. It is not — it raises the effort of a crack by hours, not by
category, and it complicates every build and every crash report permanently.

**PyInstaller bytecode encryption.** Removed in PyInstaller 6.0. The
`block_cipher` lines still sitting in
[`packaging/prism.spec`](../../packaging/prism.spec) are inert; delete them
rather than trusting them.

**Nuitka.** Compiling to C is a genuine improvement over shipping `.pyc`, and it
stacks with any tier. But it is orthogonal to T3 and carries its own cost:
PySide6 under Nuitka across four CI targets is fragile, and this project's build
pipeline has already been expensive to keep green. Worth revisiting only if a
specific adversarial customer appears.
