"""Point Inquiry Automation at a demo register, and put it back afterwards.

For trying the Inquiry screen by hand without waiting for real mail to arrive,
and without writing invented inquiries into the register a real customer's
quotes are filed in.

    python3 devtools/demo_register.py on     # use the demo folder
    python3 devtools/demo_register.py off    # restore the real one
    python3 devtools/demo_register.py status

`on` stashes the real folder under inquiry.folder_real, so `off` restores
exactly what was there rather than guessing a default. Only that one key is
touched — the mailbox, terms, rate list and everything else are left alone.
"""
from __future__ import annotations

import json
import os
import sys

CONFIG = os.path.expanduser("~/.prism/config.json")
DEMO = os.path.expanduser("~/Prism Inquiries (demo)")


def load() -> dict:
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


def save(cfg: dict) -> None:
    # Written beside the original and moved into place, so an interrupted
    # write cannot leave someone with half a config and no Groq key.
    tmp = CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    # Before the replace, not after: os.replace carries the TEMP file's mode
    # across, so without this the config lands at 0666 & ~umask — typically
    # 0664, i.e. world-readable. It holds the Groq key and the IMAP password.
    # core/config.py:76 and licensing/store.py:101 both do this; this script
    # reimplemented their atomic-write pattern and dropped the line.
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, CONFIG)


def main(action: str) -> int:
    cfg = load()
    inquiry = dict(cfg.get("inquiry") or {})

    if action == "status":
        print("folder      :", inquiry.get("folder") or "(unset)")
        print("stashed real:", inquiry.get("folder_real") or "(none)")
        print("demo exists :",
              os.path.exists(os.path.join(DEMO, "inquiries.csv")))
        return 0

    if action == "on":
        if inquiry.get("folder") == DEMO:
            print("Already on the demo register.")
            return 0
        if not os.path.exists(os.path.join(DEMO, "inquiries.csv")):
            print(f"No demo register at {DEMO}. Nothing to point at.")
            return 1
        inquiry["folder_real"] = inquiry.get("folder", "")
        inquiry["folder"] = DEMO
        cfg["inquiry"] = inquiry
        save(cfg)
        print(f"Inquiry Automation now reads {DEMO}")
        print("Put it back with:  python3 devtools/demo_register.py off")
        return 0

    if action == "off":
        if "folder_real" not in inquiry:
            print("Not on the demo register — nothing to restore.")
            return 0
        inquiry["folder"] = inquiry.pop("folder_real")
        cfg["inquiry"] = inquiry
        save(cfg)
        print(f"Restored: {inquiry['folder'] or '(unset)'}")
        return 0

    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "status"))
