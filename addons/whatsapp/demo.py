"""Sample WhatsApp data, for building and checking the workspace before a real
number is connected.

Switched on with PRISM_WHATSAPP_DEMO=1 and honoured ONLY when running from
source — in a frozen build enabled() is False whatever the environment says,
the same rule PRISM_LICENSE_OFFLINE_DEV follows. Nothing here is reachable by
a customer.

`handle(endpoint, body)` answers the same paths, in the same envelopes, as the
licence server's /v1/whatsapp/*, so license_client needs exactly one hook and
every screen above it runs unmodified. State lives in memory: a reply sent
here shows up in the thread and moves the conversation to the top, exactly so
the send flow can be exercised end to end.

STDLIB ONLY (paths is the repo's own stdlib-only module).
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

_state: dict = {}


def enabled() -> bool:
    if not os.environ.get("PRISM_WHATSAPP_DEMO"):
        return False
    try:
        import paths
        return not paths.is_frozen()
    except Exception:                                   # noqa: BLE001
        return True


def _iso(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) - delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed() -> dict:
    m, h, d = (lambda n: timedelta(minutes=n)), (lambda n: timedelta(hours=n)), \
        (lambda n: timedelta(days=n))
    contacts = [
        ("k1", "Asha Patel", "919812300001", "asha@patelfab.in", "Patel Fabrication", ["hot lead", "vip"], False),
        ("k2", "Ravi Shah", "919812300002", "ravi@shahtools.in", "Shah Tools", ["customer"], False),
        ("k3", "Meera Joshi", "919812300003", "", "Joshi Castings", ["cold"], True),
        ("k4", "Kunal Desai", "919812300004", "kunal@desaipress.com", "Desai Press Works", ["hot lead"], False),
        ("k5", "Priya Nair", "919812300005", "priya@nairauto.in", "Nair Auto Components", ["customer", "vip"], False),
        ("k6", "Imran Sheikh", "919812300006", "", "Sheikh Engineering", [], False),
        ("k7", "Divya Mehta", "919812300007", "divya@mehtaplast.in", "Mehta Plastics", ["cold"], False),
        ("k8", "Harsh Trivedi", "919812300008", "", "", ["team"], False),
        ("k9", "Sanjay Kulkarni", "919812300009", "sanjay@kulkarnimfg.in", "Kulkarni Mfg", ["customer"], False),
        ("k10", "Neha Gupta", "919812300010", "", "Gupta Sheet Metal", ["hot lead"], False),
    ]
    convos = [
        ("c1", "k1", m(4), [
            ("in", "Asha Patel", "Hi, we saw your sheet-metal work on LinkedIn.", d(0) + m(52)),
            ("out", "bot", "Hello Asha! Happy to help. What are you looking to build?", d(0) + m(51)),
            ("in", "Asha Patel", "We need 40 enclosures, 2mm mild steel, powder coated.", d(0) + m(30)),
            ("out", "Harsh", "Great. Do you have a drawing? DWG or PDF is fine.", d(0) + m(24)),
            ("in", "Asha Patel", "Yes, sending it now.", d(0) + m(9)),
            ("in", "Asha Patel", "Can you share the quote for 40 units by Friday?", m(4)),
        ]),
        ("c2", "k2", h(2), [
            ("in", "Ravi Shah", "Is the revised BOQ ready?", h(3) + m(20)),
            ("out", "Harsh", "Yes — sent it to your email a few minutes ago.", h(3)),
            ("in", "Ravi Shah", "Thanks, sending the PO today.", h(2)),
            ("out", "Harsh", "Perfect, we'll start on receipt.", h(2) - m(1)),
        ]),
        ("c3", "k3", d(1) + h(3), [
            ("out", "bot", "Hi Meera, our Diwali offer is live — 10% off tooling.", d(1) + h(5)),
            ("in", "Meera Joshi", "STOP", d(1) + h(3)),
        ]),
        ("c4", "k4", h(5), [
            ("in", "Kunal Desai", "Do you handle press-brake work above 6mm?", h(5)),
        ]),
        ("c5", "k5", d(1) + h(9), [
            ("in", "Priya Nair", "Please confirm delivery for order #2291.", d(1) + h(10)),
            ("out", "Harsh", "Confirmed — dispatching tomorrow morning.", d(1) + h(9)),
        ]),
        ("c6", "k6", d(2) + h(2), [
            ("in", "Imran Sheikh", "What are your payment terms?", d(2) + h(3)),
            ("out", "bot", "Standard terms are 50% advance, 50% before dispatch.", d(2) + h(2)),
        ]),
        ("c7", "k9", d(4), [
            ("out", "Harsh", "Hi Sanjay, following up on the fixture quote.", d(4) + h(1)),
            ("in", "Sanjay Kulkarni", "Will revert next week.", d(4)),
        ]),
        ("c8", "k10", d(9), [
            ("out", "bot", "Hello Neha, thanks for your enquiry!", d(9) + h(1)),
            ("in", "Neha Gupta", "Can you laser-cut 3mm SS304?", d(9)),
        ]),
    ]
    now = datetime.now(timezone.utc)
    threads, conversations = {}, []
    for cid, kid, last, msgs in convos:
        threads[cid] = [{
            "direction": dr, "sender": sender, "text": text,
            "created_at": (now - when).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "read" if dr == "out" else "",
        } for dr, sender, text, when in msgs]
        conversations.append({"id": cid, "contact_id": kid, "channel": "whatsapp",
                              "status": "open"})
    return {
        "contacts": [{"id": i, "name": n, "phone": p, "email": e, "company": c,
                      "tags": list(t), "opt_out": o} for i, n, p, e, c, t, o in contacts],
        "conversations": conversations, "threads": threads,
        "segments": [{"id": "s1", "name": "Hot leads",
                      "filter": {"tags": ["hot lead"], "match": "any"}}],
        "campaigns": [
            {"id": "b1", "template_name": "diwali_offer", "language": "en_US",
             "segment_name": "Hot leads", "total": 190, "sent": 182, "failed": 8,
             "status": "done", "created_at": _iso(timedelta(days=2))},
            {"id": "b2", "template_name": "order_update", "language": "en_US",
             "segment_name": "", "total": 64, "sent": 64, "failed": 0,
             "status": "done", "created_at": _iso(timedelta(days=11))},
        ],
    }


def _s() -> dict:
    if not _state:
        _state.update(_seed())
    return _state


def _last(cid: str) -> dict:
    thread = _s()["threads"].get(cid) or []
    return thread[-1] if thread else {}


def handle(endpoint: str, body: dict) -> dict:
    """Answer one /v1/whatsapp/<endpoint> call from memory."""
    time.sleep(0.12)                                    # a believable round trip
    s = _s()
    contacts = {c["id"]: c for c in s["contacts"]}

    if endpoint == "/conversations":
        rows = []
        for cv in s["conversations"]:
            last = _last(cv["id"])
            c = contacts.get(cv["contact_id"], {})
            rows.append({
                "id": cv["id"], "contact_id": cv["contact_id"],
                "contact_name": c.get("name", ""), "contact_phone": c.get("phone", ""),
                "opt_out": bool(c.get("opt_out")), "channel": cv["channel"],
                "status": cv["status"], "last_active_at": last.get("created_at", ""),
                "last_text": last.get("text", ""), "last_direction": last.get("direction", ""),
            })
        rows.sort(key=lambda r: r["last_active_at"], reverse=True)
        return {"conversations": rows}

    if endpoint == "/thread":
        return {"messages": list(s["threads"].get(body.get("conversation_id"), []))}

    if endpoint == "/reply":
        cid = body.get("conversation_id")
        if cid in s["threads"]:
            s["threads"][cid].append({
                "direction": "out", "sender": "You", "text": body.get("text", ""),
                "created_at": _iso(timedelta(0)), "status": "delivered"})
        return {"ok": True}

    if endpoint == "/contacts":
        term = (body.get("search") or "").strip().lower()
        rows = [c for c in s["contacts"] if not term or term in (
            c["name"] + " " + c["phone"] + " " + c["email"] + " " + c["company"]).lower()]
        return {"contacts": sorted(rows, key=lambda c: c["name"].lower())}

    if endpoint == "/contacts/opt-out":
        c = contacts.get(body.get("contact_id"))
        if c is not None:
            c["opt_out"] = bool(body.get("opt_out"))
        return {"contact": c or {}}

    if endpoint == "/contacts/tags":
        c = contacts.get(body.get("contact_id"))
        if c is not None:
            c["tags"] = sorted({t.strip() for t in body.get("tags", []) if t.strip()})
        return {"contact": c or {}}

    if endpoint == "/tags":
        return {"tags": sorted({t for c in s["contacts"] for t in c["tags"]})}

    if endpoint == "/segments":
        return {"segments": list(s["segments"])}

    if endpoint == "/segments/save":
        seg = {"id": "s%d" % (len(s["segments"]) + 1), "name": body["name"],
               "filter": {"tags": body.get("tags", []), "match": "any"}}
        s["segments"] = [x for x in s["segments"] if x["name"] != seg["name"]] + [seg]
        return {"segment": seg}

    if endpoint == "/segments/delete":
        s["segments"] = [x for x in s["segments"] if x["id"] != body.get("segment_id")]
        return {"deleted": True}

    if endpoint == "/audience":
        tags = set(body.get("tags") or [])
        rows = [c for c in s["contacts"]
                if not c["opt_out"] and (not tags or tags & set(c["tags"]))]
        return {"audience": rows}

    if endpoint == "/campaigns":
        return {"campaigns": sorted(s["campaigns"], key=lambda c: c["created_at"],
                                    reverse=True)}

    if endpoint == "/broadcast":
        tags = set(body.get("tags") or [])
        n = len([c for c in s["contacts"]
                 if not c["opt_out"] and (not tags or tags & set(c["tags"]))])
        camp = {"id": "b%d" % (len(s["campaigns"]) + 1),
                "template_name": body["template_name"], "language": body.get("language", "en_US"),
                "segment_name": body.get("segment_name", ""), "total": n, "sent": n,
                "failed": 0, "status": "done", "created_at": _iso(timedelta(0))}
        s["campaigns"].append(camp)
        return {"campaign": camp, "audience_size": n}

    raise KeyError(endpoint)
