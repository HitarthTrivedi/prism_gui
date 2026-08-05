#!/usr/bin/env python3
"""Mint licence keys and tokens — development and test only.

This is the licence server's signing logic, living here until the backend
exists. It moves to the server repo unchanged; the client must never gain the
ability to mint anything.

NOT SHIPPED. devtools/ is absent from packaging/prism.spec, so nothing here can
reach a build. It also holds a private signing key, which is why
devtools/dev-signing-key.hex is gitignored — the key it signs with is only
trusted when Prism runs from source (see licensing/keys.py).

    python3 devtools/mint.py keygen
    python3 devtools/mint.py key
    python3 devtools/mint.py token --days 10 --features core,boq
    python3 devtools/mint.py vector
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cryptography.hazmat.primitives import serialization as _ser
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from licensing import device, keyformat, token as T

HERE = os.path.dirname(os.path.abspath(__file__))
KEY_PATH = os.path.join(HERE, "dev-signing-key.hex")
VECTOR_PATH = os.path.join(os.path.dirname(HERE), "licensing", "testdata",
                           "vector.json")
DAY = 86400


def load_private() -> Ed25519PrivateKey:
    with open(KEY_PATH, "r", encoding="utf-8") as f:
        return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(f.read().strip()))


def public_hex(private: Ed25519PrivateKey) -> str:
    return private.public_key().public_bytes(
        _ser.Encoding.Raw, _ser.PublicFormat.Raw).hex()


def sign(claims: dict, private: Ed25519PrivateKey) -> str:
    """Produce a token. Uses licensing.token's own helpers on purpose: signer
    and verifier sharing one encoder is what stops the two drifting apart."""
    payload_b64 = T.b64u_encode(
        json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = private.sign(T.signing_input(payload_b64))
    return f"{T.PREFIX}.{payload_b64}.{T.b64u_encode(signature)}"


def build_claims(args, device_fp: str) -> dict:
    now = int(args.now or time.time())
    license_end = now + args.days * DAY
    # A token never outlives the licence: the last one of a 10-day trial
    # expires on day 10, not seven days after it was issued.
    token_exp = min(now + args.ttl * DAY, license_end)
    return {
        "kid": args.kid,
        "sub": args.license_id,
        "cust": args.customer,
        "plan": args.plan,
        "kind": args.kind,
        "feat": [f.strip() for f in args.features.split(",") if f.strip()],
        "seats": args.seats,
        "dev": device_fp,
        "iat": now,
        "nbf": now,
        "exp": token_exp,
        "lend": license_end,
        # Trials get no grace: day 10 means day 10, which is the date in the
        # email we sent. Grace absorbs a late bank transfer on a paid account.
        "grace": 0 if args.kind == "trial" else args.grace,
    }


def cmd_keygen(args) -> int:
    if os.path.exists(KEY_PATH) and not args.force:
        print(f"{KEY_PATH} already exists. Pass --force to replace it "
              "(every token signed with the old key stops verifying).")
        return 1
    private = Ed25519PrivateKey.generate()
    raw = private.private_bytes(_ser.Encoding.Raw, _ser.PrivateFormat.Raw,
                                _ser.NoEncryption()).hex()
    with open(KEY_PATH, "w", encoding="utf-8") as f:
        f.write(raw)
    os.chmod(KEY_PATH, 0o600)
    print(f"private key → {KEY_PATH}")
    print(f"public key  → {public_hex(private)}")
    print("\nPaste the public key into licensing/keys.py under DEVELOPMENT.")
    return 0


def cmd_key(args) -> int:
    for _ in range(args.count):
        print(keyformat.generate())
    return 0


def cmd_token(args) -> int:
    private = load_private()
    device_fp = args.device or device.fingerprint(
        os.path.join(os.path.expanduser("~"), ".prism"))[0]
    claims = build_claims(args, device_fp)
    print(sign(claims, private))
    if args.verbose:
        print(json.dumps(claims, indent=2), file=sys.stderr)
    return 0


def cmd_install(args) -> int:
    """Mint a token and write it straight into ~/.prism/license.json, so a dev
    build behaves as though it had been activated."""
    from licensing import store

    private = load_private()
    user_dir = os.path.join(os.path.expanduser("~"), ".prism")
    device_fp = device.fingerprint(user_dir)[0]
    claims = build_claims(args, device_fp)
    data = store.load(user_dir)
    data["token"] = sign(claims, private)
    data["license_id"] = args.license_id
    store.save(user_dir, data)
    store.touch_clock(user_dir)
    print(f"Installed a {args.days}-day {args.kind} licence for "
          f"{claims['feat']} → {store.path(user_dir)}")
    return 0


def cmd_vector(args) -> int:
    """Regenerate the committed test vector.

    The vector is the one thing proving the signer and the verifier agree, on
    every platform and in a frozen build. Regenerating it invalidates that
    proof, so only do it when the token format itself changes.
    """
    private = Ed25519PrivateKey.generate()
    claims = {
        "kid": "vector", "sub": "lic_vector", "cust": "Vector Test Ltd",
        "plan": "business", "kind": "paid",
        "feat": ["core", "boq", "email"], "seats": 5,
        "dev": "0123456789abcdef",
        "iat": 1750000000, "nbf": 1750000000,
        "exp": 1750604800, "lend": 1781536000, "grace": 3,
        "pk": "", "petag": "",
    }
    vector = {
        "_comment": "Committed test vector. Signer and verifier must agree on "
                    "these exact bytes. Regenerate only if the token format "
                    "changes — see devtools/mint.py vector.",
        "public_key": public_hex(private),
        "device_fp": claims["dev"],
        "token": sign(claims, private),
        "claims": claims,
    }
    os.makedirs(os.path.dirname(VECTOR_PATH), exist_ok=True)
    with open(VECTOR_PATH, "w", encoding="utf-8") as f:
        json.dump(vector, f, indent=2)
        f.write("\n")
    print(f"wrote {VECTOR_PATH}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("keygen").add_argument("--force", action="store_true")

    key_parser = sub.add_parser("key", help="generate licence key(s)")
    key_parser.add_argument("--count", type=int, default=1)

    for name, help_text in (("token", "print a signed token"),
                            ("install", "write one into ~/.prism")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--days", type=int, default=10, help="licence length")
        p.add_argument("--ttl", type=int, default=7, help="token lifetime, days")
        p.add_argument("--features", default="core,boq,email,reel")
        p.add_argument("--kind", default="trial", choices=["trial", "paid"])
        p.add_argument("--plan", default="trial")
        p.add_argument("--customer", default="Dev Build")
        p.add_argument("--license-id", default="lic_dev")
        p.add_argument("--seats", type=int, default=1)
        p.add_argument("--grace", type=int, default=3)
        p.add_argument("--kid", default="dev1")
        p.add_argument("--now", type=int, default=0)
        p.add_argument("--device", default="")
        p.add_argument("--verbose", action="store_true")

    sub.add_parser("vector", help="regenerate the committed test vector")

    args = parser.parse_args()
    return {
        "keygen": cmd_keygen, "key": cmd_key, "token": cmd_token,
        "install": cmd_install, "vector": cmd_vector,
    }[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
