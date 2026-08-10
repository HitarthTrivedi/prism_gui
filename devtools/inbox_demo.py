#!/usr/bin/env python3
"""Try Inbox to Order before it has a screen.

    python3 devtools/inbox_demo.py              # sample inbox, no network
    python3 devtools/inbox_demo.py --connect    # your real mailbox, read-only

The engine is finished; the window is not. This runs the whole daily loop from
the terminal so the feature can be seen — and demonstrated to a customer —
while the screens are being built.

What --connect does and does not do, stated plainly because it asks for a mail
password:

    · reads only. The folder is opened read-only and every fetch uses
      BODY.PEEK, so nothing is marked read, moved or deleted.
    · sends nothing. No mail goes out. There is no code path here that can.
    · keeps the password in memory for the length of the run. Nothing is
      written to disk except the inquiry register and the attachments.
    · sorts locally. Nothing is sent to any AI unless you pass --ai.
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from datetime import date, timedelta
from decimal import Decimal
from email.message import EmailMessage

GUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, GUI)
sys.path.insert(0, os.path.join(GUI, "prism_terminal"))

from core import inbox, mailflow, quoting, register, triage  # noqa: E402

DEMO_HOME = os.path.join(os.path.expanduser("~"), "prism-inbox-demo")

BOLD, DIM, OFF = "\033[1m", "\033[2m", "\033[0m"


def head(text: str) -> None:
    print(f"\n{BOLD}{text}{OFF}\n" + "─" * min(len(text), 70))


# ── the sample inbox ──────────────────────────────────────────────────────────

SAMPLE = [
    ("Enquiry for compression springs", "Mr Patel <purchase@shaktiauto.in>",
     "Dear Sir,\n\nKindly quote your best rate for 5000 nos compression "
     "spring, 2mm wire, 25mm OD, as per attached drawing.\n\nDelivery needed "
     "in 3 weeks.\n\nRegards\nMr Patel\nShakti Auto Components\n98250 xxxxx",
     [("SPRING-DWG-441.pdf", b"%PDF-1.4 sample drawing")], {}),
    ("Requirement", "Nikhil <buyer@gujaratmotors.in>",
     "Sir,\nWe need 800 nos tension spring 3mm. Please send rate and "
     "delivery.\nThanks", [], {}),
    ("50% OFF industrial tools this week!", "offers@toolmart.example",
     "Biggest sale of the year. Shop now.", [],
     {"List-Unsubscribe": "<https://toolmart.example/u>"}),
    ("Your NEFT transaction", "noreply@bank.example",
     "Your account is credited with INR 1,38,000 by SHAKTI AUTO. UTR N4471.",
     [], {}),
    ("Quotation for MS wire 2mm", "sales@steelsupply.co.in",
     "Our rate is Rs 95/kg ex-works, GST extra.", [], {}),
    ("Out of Office", "someone@bigco.example", "I am on leave until Monday.",
     [], {"Auto-Submitted": "auto-replied"}),
    ("August newsletter", "news@engineeringtoday.example",
     "This month in manufacturing...", [],
     {"List-Unsubscribe": "<https://et.example/u>"}),
    ("Please share your process documents", "qa@gujaratmotors.in",
     "Kindly share your heat treatment SOP for our vendor file.", [], {}),
]

SAMPLE_RATES = (
    "ACME SPRINGS PVT LTD\nGIDC Vatva, Ahmedabad\n\n"
    "Code,Description,Unit,Rate,Rate @ 1000,Rate @ 5000\n"
    "CS-201,Compression spring 2mm wire 25 OD,nos,32.00,29.00,28.50\n"
    "CS-202,Compression spring 3mm wire 30 OD,nos,38.00,35.00,33.50\n"
    "TS-100,Tension spring 3mm wire,nos,44.00,41.00,39.00\n"
    "WS-050,Washer flat mild steel 10mm,nos,3.00,2.60,2.40\n"
)


def build_sample() -> list:
    messages = []
    for i, (subject, sender, body, attachments, headers) in enumerate(SAMPLE, 1):
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = "sales@acmesprings.co.in"
        msg["Date"] = "Mon, 11 Aug 2026 09:14:00 +0530"
        msg["Message-ID"] = f"<sample{i}@demo>"
        for key, value in headers.items():
            msg[key] = value
        msg.set_content(body)
        for name, data in attachments:
            msg.add_attachment(data, maintype="application", subtype="pdf",
                               filename=name)
        messages.append(inbox.parse_message(msg.as_bytes(), uid=i))
    return messages


# ── the run ───────────────────────────────────────────────────────────────────

def show(result, paths: mailflow.Paths) -> None:
    head("1 · What arrived, and what Prism made of it")
    print(f"  {result.headline()}\n")
    print(f"  {DIM}Everything below was sorted on this computer. Newsletters "
          f"carry an\n  unsubscribe header, auto-replies say so in their "
          f"headers, and known\n  senders are on your own list — none of it "
          f"went anywhere.{OFF}")

    head("2 · The inquiry register")
    print(f"  {paths.register_csv}\n")
    rows = register.load(paths.register_csv)
    if not rows:
        print("  (nothing registered — no inquiries in this batch)")
    for row in rows:
        print(f"  {BOLD}{row['Inquiry no']}{OFF}  {row['Date received']}  "
              f"{row['Customer'] or row['Email']}")
        print(f"      wants   : {row['Product asked'][:70]}")
        print(f"      status  : {row['Status']}")
        if row.get("Drawing") and row["Drawing"] != "No":
            print(f"      files   : {row['Drawing']}")
        print(f"      folder  : {row['Folder']}")

    if result.orders:
        head("3 · Purchase orders needing a look")
        for item in result.orders:
            print(f"  {item.message.subject}  — {item.note}")

    head("4 · Quotations due a reminder")
    if result.followups:
        for row in result.followups:
            print(f"  {row['Inquiry no']}  {row['Customer']}  "
                  f"quoted {row['Quotation date']}  "
                  f"reminders sent: {row['Reminders sent']}")
    else:
        print(f"  {DIM}none yet — nothing has been quoted in this run{OFF}")

    head("5 · The month so far")
    print("  " + mailflow.day_summary(paths).replace("\n", "\n  "))


def demo_quote(paths: mailflow.Paths) -> None:
    """Price the first inquiry off a sample rate list, showing the working."""
    rows = register.load(paths.register_csv)
    if not rows:
        return
    row = rows[0]
    rates_path = os.path.join(paths.root, "rate-list.csv")
    if not os.path.exists(rates_path):
        with open(rates_path, "w", encoding="utf-8") as f:
            f.write(SAMPLE_RATES)

    head("6 · Making the quotation from your own rate list")
    print(f"  rate list: {rates_path}\n")
    items = quoting.load_rates(rates_path)
    matches = quoting.match_item(row["Product asked"], items)
    if not matches:
        print("  No row on the rate list matched. Prism would ask you to pick.")
        return

    print(f"  Asked for : {row['Product asked'][:66]}\n")
    print("  Prism suggests, best first:")
    for m in matches[:3]:
        print(f"     {m.item.code:<8} {m.item.description[:44]:<44} "
              f"₹{quoting.indian_currency(m.item.rate):>9}   {DIM}{m.reason}{OFF}")
    confident = quoting.is_confident(matches)
    print(f"\n  {'Clear enough to quote without asking.' if confident else 'Too close to call — Prism would ask you to pick.'}")

    quantity = Decimal("5000")
    item = matches[0].item
    quote = quoting.Quotation(
        number=quoting.next_quote_number(rows), date=date.today(),
        customer=row["Customer"] or row["Email"], inquiry_no=row["Inquiry no"],
        lines=[quoting.QuoteLine(item.description, quantity, item.unit,
                                 item.rate_for(quantity), item.hsn,
                                 basis="rate list")])
    print(f"\n  Slab rate at {quantity} nos: "
          f"₹{quoting.indian_currency(item.rate_for(quantity))} "
          f"{DIM}(list ₹{quoting.indian_currency(item.rate)}){OFF}\n")
    print("  " + quoting.render_text(quote, "ACME SPRINGS PVT LTD").replace("\n", "\n  "))

    written = quoting.write_csv(quote, os.path.join(
        row["Folder"], f"{quote.number.replace('/', '-')}.csv"))
    print(f"\n  saved → {written}")
    print(f"\n  {DIM}Nothing was sent. In the finished product this is the "
          f"point where\n  Prism says \"going out in 10 minutes\" and you do "
          f"nothing, or tap Hold.{OFF}")


def run(messages, cfg, paths, *, local_only: bool) -> None:
    known = triage.Knowledge(
        own_domains={"acmesprings.co.in"},
        customers={"shaktiauto.in", "gujaratmotors.in"},
        vendors={"steelsupply.co.in"})
    original = inbox.fetch_new
    if messages is not None:
        inbox.fetch_new = lambda c, s, **k: (messages, inbox.State(1, 99), "")
    try:
        result = mailflow.check(cfg, paths, knowledge=known,
                                local_only=local_only)
    finally:
        inbox.fetch_new = original

    if result.error:
        print(f"\n  {result.error}\n")
        return
    show(result, paths)
    demo_quote(paths)

    head("Where everything is")
    print(f"  {paths.root}")
    print(f"\n  {DIM}Open that folder. The register is a plain CSV that opens "
          f"in Excel,\n  and every inquiry has its own folder with the mail "
          f"and the drawings.{OFF}\n")


def connect(args) -> dict:
    print("\nProviders like Gmail and Outlook need an app password rather than\n"
          "your normal one. A company mailbox usually just takes the password.\n")
    address = input("  email address : ").strip()
    password = getpass.getpass("  password      : ")
    print("\n  looking for your mail server…")
    settings, error = inbox.discover(address, password)
    if error:
        print(f"\n  {error}\n")
        sys.exit(1)
    print(f"  found: {settings['host']}\n")
    return {"api_key": args.key or "", "inbox": settings}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--connect", action="store_true",
                        help="read your real mailbox instead of the sample")
    parser.add_argument("--ai", action="store_true",
                        help="let Groq sort the mail the local rules cannot place")
    parser.add_argument("--key", default=os.environ.get("GROQ_API_KEY", ""),
                        help="Groq API key, for --ai")
    parser.add_argument("--folder", default=DEMO_HOME,
                        help=f"where to put everything (default {DEMO_HOME})")
    args = parser.parse_args()

    paths = mailflow.Paths(args.folder)
    paths.ensure()

    if args.connect:
        cfg = connect(args)
        messages = None
        print(f"  reading your inbox, read-only. Nothing will be marked as "
              f"read.\n")
    else:
        cfg = {"api_key": args.key or "", "inbox": {
            "address": "sales@acmesprings.co.in", "password": "x",
            "host": "mail.acmesprings.co.in"}}
        messages = build_sample()
        print(f"\n  {DIM}Sample inbox — eight messages, no network. "
              f"Use --connect for your own.{OFF}")

    run(messages, cfg, paths, local_only=not args.ai)
    return 0


if __name__ == "__main__":
    sys.exit(main())
