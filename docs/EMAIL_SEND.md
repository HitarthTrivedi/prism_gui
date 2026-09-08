# Email (send) — the screen and the window

**What this add-on does.** Sends an email from the owner's own account —
to one person, or one copy each to a list of people — with Prism able to
write the message on request. Not to be confused with **Email automation**
(`docs/EMAIL_WORKFLOW.md`), which *reads* the inbox for inquiries.

**Rebuilt 2026-08-27.** The owner's report: *"if I want to send an email
to only one person I can't even see the input window where I should put
the mail"*. The old window opened on a free-text "What email do you want
to send?" box and hid the address list under *Edit the recipient list
(optional)*; the screen behind it was a brochure. Both are gone.

## The screen (`addons/email/panel.py`)

```
Email                                        [Change account]  [New email]
Send from sales@shakti.one — to one person or to a whole list. You read every word before it goes.

┌ Send an email ──────────────────────────────────────────────────────┐
│ [Write to one person]                 [Send to a list]               │
│ Type the address, the subject…        Attach a CSV of addresses…     │
└─────────────────────────────────────────────────────────────────────┘
┌ Sent from this computer ─────────────────────────── Open the folder ┐
│ DATE            TO                        SUBJECT           RESULT   │
│ 2026-08-27 …    Rajesh <rajesh@acme.in>   Quotation for …   Sent     │
│ 2026-08-27 …    42 people (customers.csv) Introducing …     40 sent, 2 failed │
└─────────────────────────────────────────────────────────────────────┘
┌ Sending account ── sales@shakti.one  through smtp.gmail.com  [Change account] ┐
```

With no account set up the screen is one front door: *No sending account
yet → Set up the sending account*.

## The window (`addons/email/dialog.py::EmailComposeDialog`)

A letter, top to bottom, everything visible from the first moment:

| Row | What |
|---|---|
| **To** | type addresses (any separator) · **Add a list (CSV)** · under it, in words: *Going to 4 people — 3 from customers.csv, the rest typed above* · the list itself as a Name / Email table with *Remove selected* · *Don't know the address? Search the web* |
| **Subject** | one line |
| **Message** | the big box; `{name}` becomes each person's name |
| **Files** | *Attach a file* · what is attached, in words · *Remove files* |
| optional card | *Want Prism to write the message for you?* — one-line brief + **Write it for me**; the draft lands in Message |
| footer | **Send** is off until To, Subject and Message are filled and its tooltip says what is still needed; then it reads **Send to rajesh@acme.in** or **Send to 42 people** |

Sending: a confirmation naming To / Subject / Files / From (default **No**),
progress line by line, Send becomes **Stop sending** while a list goes out.

## Files on disk

`~/Prism Email/sent.json` (`sent_log.py`) — one entry per press of Send:
date, time, every recipient, subject, body, who got it, who failed and why,
attachments, list name. The screen's table is this file; *Open the folder*
opens it. A History run record (`/email …`) is still written as well.
The folder moves with `cfg["email"]["folder"]`.

## Several addresses to send from (2026-09-09)

A firm quotes from `sales@` and chases payment from `accounts@`. Until this
round the whole product sent everything from whichever single address had
been typed in first, because `core/mailer.py` resolves the From header from
one key — `cfg["email"]["address"]` — and every call site handed it the
whole config.

**The engine did not change.** It still takes one account per call and knows
nothing about lists. The app fans out, with the same cfg overlay Email
automation already uses to read several mailboxes through a single-mailbox
engine (`addons/inquiry/dialog.py::_check_account`, which sets
`engine_cfg["inbox"]`). `email_config.cfg_for_sender()` is the send-side
twin.

```
cfg["email"] = {
    address / password / host / port    ← the DEFAULT account, mirrored
    folder                                (where sent.json lives)
    accounts: [ {address, password, host, port, active}, … ]
}
```

  · **The mirror is the default account**, so `mailer.is_configured()` and
    `verify()` — read from five places — keep answering about the account
    that will actually be used, and none of those five gates had to be
    rewritten to understand a list.
  · **The default is the first active account.** Position *is* the default,
    so *Send from this one by default* moves an entry to the top and there
    is no second setting to fall out of step with the visible order.
  · **A missing `active` key means active.** Read the other way, an existing
    customer's mail silently stops going out.
  · **Parking is not deleting**: a switched-off account keeps its password.
  · **The chooser hides at one account.** For a customer with a single
    sending address every one of these screens is unchanged.

Where the address is chosen: the compose window's *From* row; the reminder
draft (`addons/inquiry/dialog.py::_ReminderDialog`); the quotation
(`addons/inquiry/quotation.py`), whose confirmation names it. The unattended
chase has no screen to ask on, so it uses the default.

`email_config.py` is a root module, not part of the Email add-on, for the
same reason `inquiry_config.py` is: Email automation sends from these
accounts too, and no add-on may import another.

## What did not change

`EmailSetupDialog`'s fields (address, app password, host, port, *Test
connection*) and every message it shows, the SMTP sender
(`core/mailer.py`), the drafting stage and its `SUBJECT:/BODY:` contract,
the web search for a public address, the run record. Voice dictation was
dropped from this window — it was the free-text box's, and the box is
gone.

## Tests

`tests/test_email_compose.py` — the To field is first and visible, Send
says who and why not, one person / several typed / a CSV list with names,
removal, the workbench CSV hand-off, a send is written to `sent.json` and
appears on the screen, the launcher's two doors, the no-account front door,
the sent log's words. `tests/test_email_panel.py` — *Change account* is
always offered and opens setup, not a draft.

`tests/test_email_senders.py` — the several-addresses round. Its
load-bearing class is `ALegacyConfigStillSends`: one account saved by the
previous version must read as exactly one account, produce an overlay that
is byte-for-byte the dict the engine already receives, and show no chooser.
The rest pins the mirror following the default past a parked account, a
parked account keeping its password, the readers handing back copies, and
the worker being signed in as the address the confirmation named.
