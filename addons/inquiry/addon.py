"""Email automation — read the mailboxes, register inquiries, quote, chase."""
from __future__ import annotations

from addons import names
from addons.manifest import OK, RAIL, HOME, Addon

MANIFEST = Addon(
    key="inquiry",
    # "Email automation", because that is the phrase the customer says when
    # they describe what they want. The licence feature underneath is still
    # "inbox" and the rail key is still "inquiry" -- the SKU and the wiring
    # did not move, only the name on the shelf.
    label="Email automation",
    feature="inbox",
    tip="Read every mailbox, register the inquiries in one shared file, "
        "quote, chase, and check the PO",
    blurb="Register, quote, chase",
    icon="inbox",
    tone=OK,
    # First on purpose: the only add-on used every day. BOQ is occasional and
    # Email is a task; this one is the reason the app gets opened at all.
    order=10,
    shelves=(RAIL, HOME),
    # A screen, not a dialog: the first thing you want on opening it is the
    # state of the book, not a working modal. The gate still runs first --
    # the screen reads a register the customer may not own.
    screen="inquiry",
    # It hands drawings to whoever measures them, by intent rather than by
    # import -- see addons/boq/contract.py for the other half. Inquiry no
    # longer knows that BOQ exists, only that something might measure a
    # drawing; if nothing does, the button is simply not drawn.
    wants=(names.MEASURE_DRAWING,),
)
