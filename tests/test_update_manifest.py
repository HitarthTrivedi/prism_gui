"""Tests for update_manifest.py — the manifest wire format, the actual trust
boundary of the whole in-app updater (update-research-inapp-download.md §4).

Covers the test-matrix cases that section calls non-negotiable: a genuine
manifest verifies; a tampered payload, a wrong key, an expired manifest, and
a manifest signed under an unknown kid must all be REJECTED, not just
"probably rejected" — every negative case here asserts the specific
ManifestError code, not just that *something* was raised, so a future change
that swaps a hard failure for a silent pass-through fails loudly here.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cryptography.hazmat.primitives import serialization as _ser
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import update_manifest as UM


def _keypair():
    priv = Ed25519PrivateKey.generate()
    pub_hex = priv.public_key().public_bytes(
        _ser.Encoding.Raw, _ser.PublicFormat.Raw).hex()
    priv_hex = priv.private_bytes(
        _ser.Encoding.Raw, _ser.PrivateFormat.Raw, _ser.NoEncryption()).hex()
    return priv_hex, pub_hex


class BuildingAManifest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prism-manifest-")

    def test_walks_files_and_hashes_them(self):
        os.makedirs(os.path.join(self.tmp, "sub"))
        with open(os.path.join(self.tmp, "a.txt"), "w") as f:
            f.write("hello")
        with open(os.path.join(self.tmp, "sub", "b.txt"), "w") as f:
            f.write("world")

        manifest = UM.build(self.tmp, "1.0.0")

        self.assertEqual(manifest["version"], "1.0.0")
        paths = {f["path"] for f in manifest["files"]}
        self.assertEqual(paths, {"a.txt", "sub/b.txt"})
        a = next(f for f in manifest["files"] if f["path"] == "a.txt")
        self.assertEqual(a["size"], 5)
        self.assertEqual(a["sha256"], UM.sha256_file(os.path.join(self.tmp, "a.txt")))

    def test_deterministic(self):
        with open(os.path.join(self.tmp, "a.txt"), "w") as f:
            f.write("hello")
        self.assertEqual(UM.build(self.tmp, "1.0.0"), UM.build(self.tmp, "1.0.0"))

    def test_symlinks_recorded_without_hashing(self):
        with open(os.path.join(self.tmp, "real.txt"), "w") as f:
            f.write("x")
        os.symlink("real.txt", os.path.join(self.tmp, "link.txt"))
        manifest = UM.build(self.tmp, "1.0.0")
        link = next(f for f in manifest["files"] if f["path"] == "link.txt")
        self.assertEqual(link["symlink"], "real.txt")
        self.assertNotIn("sha256", link)

    def test_executable_bit_recorded(self):
        exe = os.path.join(self.tmp, "run")
        with open(exe, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(exe, 0o755)
        plain = os.path.join(self.tmp, "data")
        with open(plain, "w") as f:
            f.write("x")
        os.chmod(plain, 0o644)
        manifest = UM.build(self.tmp, "1.0.0")
        modes = {f["path"]: f["mode"] for f in manifest["files"]}
        self.assertTrue(modes["run"] & 0o111)
        self.assertFalse(modes["data"] & 0o111)


class SigningAndVerifying(unittest.TestCase):
    def setUp(self):
        self.priv_hex, self.pub_hex = _keypair()
        self.manifest = {"version": "1.4.0", "files": [
            {"path": "Prism", "size": 3, "sha256": "abc", "mode": 0o111},
        ]}

    def test_roundtrip(self):
        token = UM.sign(self.manifest, self.priv_hex, kid="u1")
        payload = UM.verify(token, public_keys={"u1": self.pub_hex})
        self.assertEqual(payload["version"], "1.4.0")
        self.assertEqual(payload["kid"], "u1")

    def test_tampered_payload_rejected(self):
        token = UM.sign(self.manifest, self.priv_hex, kid="u1")
        prefix, payload_b64, sig_b64 = token.split(".")
        # Flip the manifest's claimed version without re-signing — this is
        # exactly the attack §4 requirement #1 exists to close: the version
        # must never be trusted before the signature over it is checked.
        import json
        from licensing.token import b64u_decode, b64u_encode
        tampered = json.loads(b64u_decode(payload_b64))
        tampered["version"] = "99.0.0"
        tampered_b64 = b64u_encode(json.dumps(tampered).encode("utf-8"))
        forged = f"{prefix}.{tampered_b64}.{sig_b64}"
        with self.assertRaises(UM.ManifestError) as ctx:
            UM.verify(forged, public_keys={"u1": self.pub_hex})
        self.assertEqual(ctx.exception.code, "bad_signature")

    def test_wrong_key_rejected(self):
        token = UM.sign(self.manifest, self.priv_hex, kid="u1")
        _other_priv, other_pub = _keypair()
        with self.assertRaises(UM.ManifestError) as ctx:
            UM.verify(token, public_keys={"u1": other_pub})
        self.assertEqual(ctx.exception.code, "bad_signature")

    def test_unknown_kid_rejected(self):
        token = UM.sign(self.manifest, self.priv_hex, kid="u1")
        with self.assertRaises(UM.ManifestError) as ctx:
            UM.verify(token, public_keys={"u2": self.pub_hex})
        self.assertEqual(ctx.exception.code, "unknown_key")

    def test_expired_manifest_rejected(self):
        token = UM.sign(self.manifest, self.priv_hex, kid="u1", validity_days=1)
        far_future = int(time.time()) + 10 * 86400
        with self.assertRaises(UM.ManifestError) as ctx:
            UM.verify(token, public_keys={"u1": self.pub_hex}, now=far_future)
        self.assertEqual(ctx.exception.code, "expired")

    def test_not_expired_just_inside_window(self):
        token = UM.sign(self.manifest, self.priv_hex, kid="u1", validity_days=90)
        soon = int(time.time()) + 89 * 86400
        payload = UM.verify(token, public_keys={"u1": self.pub_hex}, now=soon)
        self.assertEqual(payload["version"], "1.4.0")

    def test_malformed_token_rejected(self):
        with self.assertRaises(UM.ManifestError) as ctx:
            UM.verify("not-a-real-token", public_keys={"u1": self.pub_hex})
        self.assertEqual(ctx.exception.code, "malformed")

    def test_path_traversal_entry_rejected(self):
        # A signed manifest is still refused if a file entry's path would
        # escape the staged directory — defense in depth, since stage_update()
        # joins this value straight onto a directory it writes into.
        manifest = {"version": "1.4.0", "files": [
            {"path": "../../.bashrc", "size": 3, "sha256": "abc", "mode": 0},
        ]}
        token = UM.sign(manifest, self.priv_hex, kid="u1")
        with self.assertRaises(UM.ManifestError) as ctx:
            UM.verify(token, public_keys={"u1": self.pub_hex})
        self.assertEqual(ctx.exception.code, "malformed")

    def test_absolute_path_entry_rejected(self):
        manifest = {"version": "1.4.0", "files": [
            {"path": "/etc/passwd", "size": 3, "sha256": "abc", "mode": 0},
        ]}
        token = UM.sign(manifest, self.priv_hex, kid="u1")
        with self.assertRaises(UM.ManifestError) as ctx:
            UM.verify(token, public_keys={"u1": self.pub_hex})
        self.assertEqual(ctx.exception.code, "malformed")

    def test_licence_token_cannot_be_replayed_as_a_manifest(self):
        """The whole reason PRSMUv1 is a different prefix from PRSMv1 — a
        signature over one must never verify under the other, even with the
        matching key, even if some future bug made the payload shapes
        overlap."""
        from licensing import token as T
        licence_style = f"{T.PREFIX}.{token_payload_b64(self.manifest)}.sig"
        with self.assertRaises(UM.ManifestError) as ctx:
            UM.verify(licence_style, public_keys={"u1": self.pub_hex})
        self.assertEqual(ctx.exception.code, "version")

    def test_missing_files_list_is_malformed(self):
        token = UM.sign({"version": "1.4.0"}, self.priv_hex, kid="u1")
        with self.assertRaises(UM.ManifestError) as ctx:
            UM.verify(token, public_keys={"u1": self.pub_hex})
        self.assertEqual(ctx.exception.code, "malformed")


def token_payload_b64(manifest: dict) -> str:
    import json
    from licensing.token import b64u_encode
    return b64u_encode(json.dumps(manifest).encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
