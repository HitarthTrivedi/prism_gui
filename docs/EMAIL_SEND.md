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

## Pace, limits and sending later (2026-09-09)

The owner's ask: *limit and schedule the mails, and set the difference of
time between the emails*. Until now a list went out to everyone, two
seconds apart, the moment Send was pressed — a metronome a provider can
hear, with no cap and no way to say "not now".

A **Pace and limits** card sits under the letter:

| Control | What it does |
|---|---|
| **Gap between emails** `2.0 s` *plus up to* `0.0 s` *at random* | The fixed pause after each email, plus a random slice on top so the pauses are not identical. Never below half a second. |
| **At most** `all of them` *per send, and* `no limit` *per day* | A per-press cap (the rest stay in the list for the next press) and a per-address daily cap, counted off the sent log across every window and every send from this computer. |
| **When** ☐ *Send later, at* `dd MMM yyyy HH:mm` | Waits until that time, then signs in and sends. The window must stay open; **Stop sending** cancels the wait. A time already past means "now". |

The line under the card says it in words — *"3 to 5 seconds apart. 12 of
100 sent today from this address. 88 of 120 will go on this press (daily
limit 100, 12 already sent today); the rest stay in the list. Starts 09
Sep 14:30 — keep Prism open until then."* — and the Send button counts the
same way: **Send to 88 of 120 people**, **Send to 3 people later**, or
**Daily limit reached** (disabled) when the day is used up.

After a capped send the window stays open with exactly the people who did
not go still in the list, so the next press continues where this one
stopped. The confirmation names the pace and how many are held back.

Where the numbers live: `cfg["email"]["send"]` — `gap_seconds`,
`jitter_seconds`, `max_per_run`, `max_per_day` — read by
`email_config.send_policy()`, written by `with_send_policy()` when Send is
pressed with changed values, and carried across an account save the way
`folder` is. The terminal's `/email` reads the same gap, jitter and
per-send cap; the daily cap is counted off the GUI's sent log and does not
apply there.

The engine side is `core/mailer.py:send_bulk(delay, jitter=, limit=,
start_at=, on_wait=)`: the wait for a scheduled start happens **before**
the SMTP login, so a send set for the morning does not hold a session
open all night, and a stop during the wait sends nothing. Every entry in
`sent.json` now carries `from`, the address it left — what the daily
count is taken against. An entry written before that field existed counts
against every address, on purpose.

Tests: `tests/test_email_pacing.py`.


## A copy in Sent (2026-09-10)

A plain SMTP send reaches the recipient and never touches the sender's own
mailbox, so a Prism-sent email used to be invisible in Outlook and webmail.
The engine now files a copy of every message into the account's Sent
folder over IMAP after each send (Harsh, `core/mailer.py`): best-effort, so
a mailbox that refuses the copy, has IMAP off or has no Sent folder still
sends; providers whose SMTP already files sent mail are skipped.

The window shows it in the **Pace and limits** card — **Keep a copy of
each email in the account's Sent folder**, ticked by default — and the
folded summary says *copy kept in Sent* or *no copy in Sent*. The switch
is handed to the worker as ticked, remembered with the pace when Send is
pressed, and carried across an account save the way `folder` is:
`cfg["email"]["save_to_sent"]`, read by `email_config.save_to_sent()`,
written by `with_save_to_sent()`. Missing means on. The terminal's `/email`
reads the same key.
