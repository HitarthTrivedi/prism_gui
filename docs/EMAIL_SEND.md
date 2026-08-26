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

## The screen (`widgets/email_panel.py`)

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

## The window (`dialogs/email_dialog.py::EmailComposeDialog`)

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

## What did not change

`EmailSetupDialog` (account, app password, *Test connection*), the SMTP
sender (`core/mailer.py`), the drafting stage and its `SUBJECT:/BODY:`
contract, the web search for a public address, the run record. Voice
dictation was dropped from this window — it was the free-text box's, and
the box is gone.

## Tests

`tests/test_email_compose.py` — the To field is first and visible, Send
says who and why not, one person / several typed / a CSV list with names,
removal, the workbench CSV hand-off, a send is written to `sent.json` and
appears on the screen, the launcher's two doors, the no-account front door,
the sent log's words. `tests/test_email_panel.py` — *Change account* is
always offered and opens setup, not a draft.
