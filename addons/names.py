"""The shared vocabulary add-ons use to ask each other for work.

No add-on may import another. But real work crosses them: an order comes in
through Email automation and somebody has to measure the drawing that came
with it.

That used to be done by Inquiry importing BOQ's dialog and constructing it,
which made Inquiry know BOQ's module path, its class name, its constructor
signature, how its attachments are shaped, and implicitly that the customer
is entitled to it. Five couplings for one button, and five reasons the two
files could not move independently.

An intent replaces all five. Inquiry asks the host for MEASURE_DRAWING;
whichever add-on offers it answers, gated by the same licence check every
other route goes through. If nothing offers it -- not installed, not built,
not bought -- the button is simply not drawn, which is strictly better than
today, where it is drawn and then paywalls after the click.

These are wire identifiers, not copy. They are never shown to a user and
never translated. STDLIB ONLY -- this module is imported by the manifest
layer, which packaging/prism.spec imports in a bare interpreter.

Naming rule: an intent is named after the JOB, not the add-on that happens
to do it today -- the same rule plans.FEATURES follows, and for the same
reason. "MEASURE_DRAWING" survives BOQ being renamed, replaced, or split in
two; "OPEN_BOQ_DIALOG" would not.
"""
from __future__ import annotations

# Take a CAD drawing (or a written spec) and return quantities.
# Offered by: boq.  Wanted by: inquiry.
MEASURE_DRAWING = "measure.drawing"

# Take Gerber files and return board size, track width, spacing, drill
# counts. Offered by: gerber. Wanted by: nobody yet -- Inquiry is the
# obvious consumer and the day it wants this it is one `wants=` entry and
# one button, not an import.
MEASURE_PCB = "measure.pcb"

# Take a STEP model and return every part's size, thickness, holes and
# weight -- measured on this machine, the model never shown to an AI.
# Offered by: step. Wanted by: nobody yet -- Inquiry is the obvious
# consumer, and the day it wants this it is one `wants=` entry and one
# button, not an import.
MEASURE_MODEL = "measure.model"

# Take a parts list off a drawing or spec.
# Offered by: bom (as a mode of the BOQ dialog, which is exactly the kind of
# implementation detail an intent is supposed to hide).
LIST_PARTS = "list.parts"

# Compose and send mail with the given files attached.
# Offered by: email.  Wanted by: inquiry (quotes, chasers, PO confirmation).
SEND_MAIL = "send.mail"

# Every intent this build knows about. The contract test checks that each
# one is offered by at most one add-on, and that nothing `wants` a name that
# does not appear here -- a typo'd intent is otherwise indistinguishable
# from a feature the customer has not bought, because both draw no button.
ALL = (
    MEASURE_DRAWING,
    MEASURE_PCB,
    MEASURE_MODEL,
    LIST_PARTS,
    SEND_MAIL,
)
