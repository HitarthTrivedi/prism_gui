# WhatsApp / Plan B — B0: the Meta gate (owner checklist)

**Decision (11-Sep-2026):** replace AiSensy's software entirely. Prism becomes a
Meta **Tech Provider** and runs the WhatsApp Business Platform for customers.
This is the one part of Plan B that is **not code and cannot be rushed** — it is
Meta's approval clock. Start it now; the code (B1) is built in parallel.

> The point of B0: Tech-Provider enrolment is now **mandatory** for anyone
> offering WhatsApp messaging, and Meta's **Embedded Signup** is the default way
> customers connect their number. So this is the required front door, not
> gold-plating.

---

## Who does what

| | Owner (you + cofounders) | Claude (me) |
|---|---|---|
| Meta business verification & Tech-Provider enrolment | ✅ only you can | — |
| Alphakore legal docs, Meta Business account, billing | ✅ | — |
| The app code (send, webhook, inbox, templates) | — | ✅ building (B1) |
| Wiring your test number into Prism to prove the loop | hand me the values below | ✅ |

I never handle your access token or passwords — you paste those into Prism (or
Meta's dashboard) yourself. BYO-key, same as every other key in Prism.

---

## The gate, in order

**1. Business Verification** (the long pole — days to weeks on Meta's side)
   - In **Meta Business Settings → Business Info**, fill in, exactly matching
     official documents: **legal business name, registered address, business
     phone, email, and a website/domain** for Alphakore.
   - Start **Security Centre → Business Verification**; upload the supporting
     documents Meta asks for (incorporation / address proof).
   - An incomplete Business Info section gets the WhatsApp account restricted, so
     do this first and completely.

**2. Create the Meta app**
   - **developers.facebook.com → Create App → Business**, add the **WhatsApp**
     use case, and connect the Alphakore business portfolio.
   - Set basic settings: app icon, **privacy-policy URL**, category.

**3. App Review** (unlocks scale — see limits below)
   - Submit a short screen recording showing: (a) sending a message via WhatsApp,
     and (b) creating a message template. (API Setup cURL or WhatsApp Manager
     recordings are accepted.)

**4. Advanced permissions**
   - Request **Advanced access** to `whatsapp_business_messaging` (send on a
     client's behalf) and `whatsapp_business_management` (manage a client's
     WABA). Both are required for Tech-Provider status.

**5. Webhook**
   - Configure the webhook callback URL + verify token. **This is the always-on
     gateway I'm building in B1** — I'll give you the URL and you paste it here.
     Nothing sends or receives until this is set.

---

## The two limits — and why we can start before finishing

- **Before** full App Review, a Tech Provider may onboard **10 new customers per
  rolling 7 days** by default.
- **After** Business Verification + App Review + Access Verification, that rises
  to **200 per rolling 7 days**.

Your pre-sold cohort is ~10 buyers → **the whole first cohort fits inside the
default limit.** We can be live and billing on WhatsApp *before* the full
gauntlet clears; the 200 limit is a later, scale-time concern.

---

## Deadlines to build against

- Build on **Embedded Signup v4**. **v2 is deprecated 15 Oct 2026** — do not
  integrate against it.
- Meta's **per-conversation charge is pass-through** (marketing ≈ ₹1.09, utility
  / auth ≈ ₹0.145, service free in the 24h window). Replacing AiSensy removes
  their *software* fee, never Meta's meter — price WhatsApp as a hosted tier.

---

## Prove it live — no verification wait, and without sharing your token

You do **not** need full verification for a live test — Meta gives a **free test
number** the moment the app exists (step 2), and it ships with the `hello_world`
template pre-approved.

**Keep your access token on your side — never paste it into chat.** BYO-key: you
give it to Prism (or the script below), not to me.

1. Create the app + add WhatsApp (step 2). On **WhatsApp → API Setup** you get a
   **test phone number id**, a **temporary token** (24h) and an **app id**.
2. Add **your own mobile** to the test number's allowed-recipient list.
3. The first message MUST be a **template** — a plain text message is refused by
   Meta until the recipient has written to you in the last 24 hours.
4. Send it, either way:
   - **Meta's own test:** the API Setup page has a Send button / curl that fires
     `hello_world` to your allowed number. Fastest sanity check.
   - **Through Prism's own code (no GUI, no licence needed):**
     `python devtools/whatsapp_send.py --pnid <ID> --token <TOKEN> --to <YOUR_MOBILE>`
     — defaults to the `hello_world` template; after you reply from your phone,
     re-run with `--text "hi"` to exercise free-form send. This runs the exact
     `cloud_api.py` Prism uses.

**What you can share with me (all non-secret) to wire and debug:** the
`phone_number_id`, the **app id**, a **verify token** you invent (for the
gateway), and the text of any error you hit. **Not** the access token.

---

## Sources

- Meta — Become a Tech Provider:
  <https://developers.facebook.com/documentation/business-messaging/whatsapp/solution-providers/get-started-for-tech-providers>
- Meta — Embedded Signup overview:
  <https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/overview/>
- Meta — Onboard business app users:
  <https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users>
