# Prism — Terms of Use

> **Status: DRAFT, not yet reviewed by a lawyer.** The product/licence
> mechanics below are checked against the actual code
> (`license_server/app/models.py`, `licensing/`, `LICENSING.md`) as of
> 2026-08-30, so the *description of how Prism works* is accurate — but
> contract language (liability caps, governing law, dispute resolution) needs
> a lawyer's review before this is presented to a client as binding.
> Bracketed items are placeholders to fill in, not decisions already made.

**Effective date:** [fill in on publish] · **Last updated:** 2026-08-30

These terms govern your use of Prism, a desktop application made by
Alphakore ("we", "us", "our"). By installing, activating a licence for, or
using Prism, you ("you", "the customer") agree to them.

---

## 1. What Prism is

Prism is desktop software that takes a task described in plain English and
runs it as a pipeline across AI tools you already use (e.g. ChatGPT, Claude,
Perplexity, Gamma), driving those tools through your own, already-logged-in
Chrome browser. Prism does not host, resell, or provide access to those AI
tools — you must have your own accounts and, where required, your own
subscriptions and API keys for them. Prism also does not host or transmit
your task content; see the [Privacy Policy](PRIVACY_POLICY.md) for exactly
what is and is not sent to us.

## 2. Licence grant

We grant you a limited, non-exclusive, non-transferable licence to install
and run Prism on the number of devices ("seats") your licence specifies, for
the duration and features it specifies (trial or paid, add-ons purchased,
daily task allowance), subject to these terms and to payment where
applicable. This is a licence to use the software, not a sale of it.

- **Trial licences** run for a fixed period, carry no grace period after
  expiry, and may be limited in features or daily usage.
- **Paid licences** run until their stated expiry, carry a grace period after
  expiry during which the app continues to function while you renew, and may
  include a daily task allowance (unlimited unless your agreement states
  otherwise).
- Your licence enforces its seat count live, each time you use Prism.
  Running it beyond the seats you've paid for, or sharing one licence key
  across more machines than it covers, is a breach of these terms and may
  result in the excess devices being refused access without notice.

## 3. Your responsibilities

- **Your own accounts.** You are responsible for maintaining your own
  subscriptions, accounts, and compliance with the terms of every AI tool
  Prism drives on your behalf. Prism acting through your logged-in session is
  the same, in effect, as you performing those actions yourself — their
  terms apply to you, not to us.
- **Your own credentials.** Your Groq API key, email credentials, and
  licence key are yours to keep secure. We will never ask you for your full
  licence key, your Groq key, or your email password.
- **Lawful and honest use.** You will not use Prism to violate any law, to
  circumvent the licence enforcement described above, or to attempt to
  extract, decompile, or reverse-engineer the software beyond what applicable
  law permits notwithstanding this restriction.

## 4. Fees, trials, and renewal

Fees, if any, are as agreed at the time your licence is issued or renewed.
[Fill in: refund policy, currency, payment method (manual invoicing today,
per `SHIPPING.md` — no automated billing system exists yet as of this
writing) — do not represent an automated refund/renewal process to a client
until one actually exists.] A trial licence converting to paid, or a paid
licence renewing, requires a new key issued by us; nothing in the app
auto-charges you.

## 5. Updates

Prism may check whether a newer version exists and offer it to you. As of
this version, that check tells you a newer version exists; downloading and
installing it may be manual (opening a link) or, where available, handled
by Prism itself after verifying the update's authenticity against a
cryptographic key built into the app — Prism will never install anything
that fails that check. You are not required to accept an update, except
that we may set a minimum supported version below which the licence server
will decline to authorise further use, in which case continuing to use an
unsupported version may not be possible.

## 6. Support

Support is provided on a best-effort basis to active licence holders via the
contact details in the app and in the [User Guide](../docs/client-guide.md). We are
not obligated to support a licence that has expired without renewal, beyond
any grace period stated on that licence.

## 7. Disclaimers

**Prism is provided "as is."** [If this build is a testing/evaluation
release rather than general availability, say so explicitly here and in any
accompanying communication — testing clients should be told plainly this is
a pre-release build, not a finished product, and given a channel to report
issues.] We do not warrant that Prism will be uninterrupted, error-free, or
that any AI tool it drives will produce accurate or fit-for-purpose output —
the AI tools' own output is theirs, not ours, and Prism's role is automating
the interaction with them, not verifying their answers.

## 8. Limitation of liability

[Standard limitation-of-liability language belongs here — e.g. liability
capped at fees paid in the preceding period, exclusion of indirect/
consequential damages — but the specific cap and carve-outs are a business
and legal decision, not something to draft by default. Fill in before
publishing.]

## 9. Termination

We may suspend or revoke a licence for breach of these terms, non-payment
after the grace period, or misuse (including seat-sharing beyond what a
licence covers). You may stop using Prism at any time; fees already paid are
governed by §4's refund terms. On termination, your right to use Prism ends,
though data already on your own machine (per the Privacy Policy) is
naturally unaffected — it was never ours to begin with.

## 10. Changes to these terms

We'll update the "Last updated" date above and, for a material change,
tell existing licence holders directly.

## 11. Governing law

[Fill in: governing law and jurisdiction/venue for disputes — given the
company is India-based (GSTIN/country fields default to India throughout
the licensing system), Indian law is the likely default, but confirm with
counsel rather than assume.]

## 12. Contact

**Alphakore**
Email: contactus@alphakore.org
Phone: 798476995
Website: https://alphakore.org

Related: [Privacy Policy](PRIVACY_POLICY.md) · [User Guide](../docs/client-guide.md)
