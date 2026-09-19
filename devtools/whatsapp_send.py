"""Manual live test of the WhatsApp Cloud API path — no GUI, no licence.

Run it with YOUR OWN test-number credentials. They stay on your machine — this
script talks only to Meta, and the token is never printed or stored.

    python devtools/whatsapp_send.py --pnid <PHONE_NUMBER_ID> --token <TOKEN> --to <YOUR_MOBILE>

By default it sends the pre-approved `hello_world` template, which is the only
thing that can OPEN a conversation: a plain text message is refused by Meta until
the recipient has written to you inside the last 24 hours. So: run this once,
reply to the template from your phone, then re-run with --text "hello back" to
exercise send_text through the same code Prism uses.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from addons.whatsapp import cloud_api            # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Send one WhatsApp message via Meta Cloud API.")
    ap.add_argument("--pnid", required=True, help="Phone number ID (Meta → API Setup)")
    ap.add_argument("--token", required=True, help="Access token (kept local; not stored)")
    ap.add_argument("--to", help="Recipient, digits with country code e.g. "
                    "919812345678 (quote it if you include spaces or a +). "
                    "Required unless --register.")
    ap.add_argument("--text", default="", help="Send this free-form text instead of a template")
    ap.add_argument("--template", default="hello_world", help="Template name (default hello_world)")
    ap.add_argument("--lang", default="en_US", help="Template language code")
    ap.add_argument("--register", action="store_true",
                    help="Register this number for Cloud API (fixes #133010), then exit")
    ap.add_argument("--pin", default="", help="6-digit registration PIN (with --register)")
    args = ap.parse_args()

    if args.register:
        try:
            cloud_api.register_number(args.pnid, args.token, args.pin)
            print("OK — number registered. Run the send again.")
            return 0
        except cloud_api.WhatsAppError as e:
            print("FAILED: %s  (code=%s, http=%s)" % (e, e.code, e.status))
            return 1

    if not args.to:
        ap.error("--to is required unless --register")
    to = re.sub(r"\D+", "", args.to)          # tolerate "+91 97260 63133"
    if len(to) <= 10:
        print("Note: '%s' has no country code — India numbers look like "
              "91XXXXXXXXXX. Sending as-is." % to)

    try:
        if args.text:
            wamid = cloud_api.send_text(args.pnid, args.token, to, args.text)
            print("OK — text sent. message id:", wamid)
        else:
            wamid = cloud_api.send_template(args.pnid, args.token, to,
                                            args.template, language=args.lang)
            print("OK — template '%s' sent. message id: %s" % (args.template, wamid))
        return 0
    except cloud_api.WhatsAppError as e:
        print("FAILED: %s  (code=%s, http=%s)" % (e, e.code, e.status))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
