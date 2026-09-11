"""Quote by code: an inquiry that names catalogue codes, priced off the rate
list and, when the owner has switched it on, sent without a person.

The client's ask (11 Sep 2026): "our customers write the product code and
the pieces; the code is in our price list; quote them straight away".
core.quoting.find_requests reads every code the mail names and the
quantity beside it. This module turns those into a quotation the same way
the quotation window does -- same terms, same numbering, same covering
mail -- and decides whether it may go out on its own:

    every code matched exactly  AND  every line has a written quantity

Anything less is held for the quotation window with the reason written
into the register row's Notes, so the person opening it sees why.

Pure functions over config, register rows and the engine; the sending
itself stays in the inquiry window (it owns the worker and the register).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import core_bridge as CB
import i18n
from addons.inquiry.setup import settings_of


@dataclass
class Plan:
    requests: list = field(default_factory=list)    # quoting.Request, in order
    lines: list = field(default_factory=list)       # quoting.QuoteLine
    reason: str = ""                                # why it is held, if it is

    @property
    def ok(self) -> bool:
        return bool(self.lines) and not self.reason


def inquiry_text(row: dict, message=None) -> str:
    """Everything the customer wrote that a code could be in: the mail
    itself when the check has it, else the register row's fields and the
    inquiry folder's history (the check writes the mail body there)."""
    parts = []
    if message is not None:
        parts += [getattr(message, "subject", "") or "", getattr(message, "body", "") or ""]
    parts += [row.get("Product asked", "") or "", row.get("Quantity", "") or "",
              row.get("Notes", "") or ""]
    folder = row.get("Folder", "")
    if folder and message is None:
        try:
            parts.append(CB.get_history().read(folder) or "")
        except Exception:                               # noqa: BLE001
            pass
    return "\n".join(p for p in parts if p)


def plan(row: dict, items: list, message=None) -> Plan:
    """What would be quoted, and whether it may go without a person."""
    quoting = CB.get_quoting()
    text = inquiry_text(row, message)
    requests = quoting.find_requests(text, items)
    out = Plan(requests=requests)
    if not requests:
        out.reason = i18n.t("no product code from the rate list in the mail")
        return out
    for r in requests:
        if not r.confident:
            out.reason = i18n.t("no quantity written next to {code}").format(code=r.item.code)
        qty = r.quantity if r.confident else quoting.to_decimal(1)
        out.lines.append(quoting.QuoteLine(
            r.item.description or r.item.code, qty, r.item.unit,
            r.item.rate_for(qty), r.item.hsn, basis="rate list"))
    return out


def terms_of(cfg: dict):
    quoting = CB.get_quoting()
    terms_cfg = settings_of(cfg).get("terms") or {}
    from decimal import Decimal
    return quoting.Terms(
        gst_percent=Decimal(str(terms_cfg.get("gst_percent", 18))),
        validity_days=int(terms_cfg.get("validity_days", 15) or 15),
        payment=terms_cfg.get("payment", "") or "",
        delivery=terms_cfg.get("delivery", "") or "")


def build_quotation(cfg: dict, row: dict, register_rows: list, lines: list):
    """The Quotation object the window and the automatic path both send:
    numbered off the register, dated today, under the saved terms."""
    quoting = CB.get_quoting()
    return quoting.Quotation(
        number=quoting.next_quote_number(register_rows or []), date=date.today(),
        customer=row.get("Customer", "") or row.get("Email", ""),
        contact=row.get("Contact person", ""),
        email=row.get("Email", ""),
        inquiry_no=row.get("Inquiry no", ""),
        lines=list(lines), terms=terms_of(cfg))


def default_body(quote, settings: dict) -> str:
    return i18n.t(
        "Dear Sir,\n\nThank you for your enquiry. Our quotation "
        "{number} is attached, valid for {days} days.\n\n"
        "Delivery: {delivery}\nPayment: {payment}\n\n"
        "Please let us know if you need anything clarified.\n\n"
        "Regards,\n{signature}"
    ).replace("{number}", quote.number).replace(
        "{days}", str(quote.terms.validity_days)).replace(
        "{delivery}", quote.terms.delivery).replace(
        "{payment}", quote.terms.payment).replace(
        "{signature}", settings.get("signature", "") or
        settings.get("company", ""))


def covering_mail(quote, settings: dict) -> tuple[str, str]:
    """Subject and body for an automatic send -- the same defaults the
    quotation window fills in, plus the priced lines in the body so the
    customer sees the figures without opening the attachment."""
    quoting = CB.get_quoting()
    first = quote.lines[0].description if quote.lines else ""
    subject = f"{i18n.t('Quotation')} {quote.number} — {first[:50]}"
    body = default_body(quote, settings)
    body += "\n\n" + quoting.render_text(quote, settings.get("company", ""))
    return subject, body


def held_note(reason: str) -> str:
    return i18n.t("auto-quote held: {why}").format(why=reason)


def enabled(cfg: dict) -> bool:
    return bool(settings_of(cfg).get("auto_quote", False))
