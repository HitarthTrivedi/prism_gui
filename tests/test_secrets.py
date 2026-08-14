"""Nothing that unlocks anything may be in the build.

A standing check, not a one-off audit. The failure this prevents is mundane
and permanent: somebody adds a convenience default — a fallback Groq key so a
demo works without setup, a signing key pasted in "temporarily" to test
minting, a staging admin token in a config file — and it ships. Every one of
those is a single commit, and none of them look wrong in review.

Three separate properties, because they fail separately:

  1. No PROVIDER credential owned by Alphakore is in the tree. Groq is BYOK:
     the customer's own key, in their own ~/.prism/config.json, used from
     their own machine. If Prism ever proxies model calls, the credential
     belongs on the backend behind a lease-checked endpoint — never here.
  2. No PRIVATE signing key can reach a build. The client verifies; it must
     never be able to mint.
  3. BYOK still works. The single most likely way to "fix" (1) is to delete
     the plumbing that lets a customer supply their own key, which would take
     the product with it.
"""
from __future__ import annotations

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

GUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Directories that never reach a customer. devtools/ is excluded from
# packaging/prism.spec by design and holds the minting logic; build output is
# generated; tests are these files.
SKIP_DIRS = {"__pycache__", ".git", ".venv", "venv", "build", "dist",
             "release", "node_modules", "devtools", "tests", ".pytest_cache"}

# Extensions worth reading. A .py, a .json config or a shell script is where a
# credential actually gets left; a .png is not.
TEXT_SUFFIXES = (".py", ".json", ".sh", ".cfg", ".ini", ".toml", ".env",
                 ".yml", ".yaml", ".spec", ".txt", ".qss")

# Live credential shapes. Each needs enough trailing entropy that the literal
# prefix in help text ("it starts with gsk_") does not match.
CREDENTIAL_PATTERNS = (
    ("Groq API key", re.compile(r"gsk_[A-Za-z0-9]{20,}")),
    ("OpenAI key", re.compile(r"\bsk-[A-Za-z0-9]{32,}")),
    ("xAI / Grok key", re.compile(r"\bxai-[A-Za-z0-9]{20,}")),
    ("Anthropic key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("GitHub token", re.compile(r"\b(ghp|gho|ghs|ghu)_[A-Za-z0-9]{30,}")),
    ("PEM private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)


def shipped_files():
    """Every text file that could end up in a build."""
    for folder, dirs, names in os.walk(GUI):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in names:
            if name.endswith(TEXT_SUFFIXES):
                yield os.path.join(folder, name)


def read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return ""


class NoEmbeddedCredentials(unittest.TestCase):

    def test_no_provider_api_key_is_in_the_tree(self):
        """The failure message names the FILE and the KIND, never the value —
        a test that prints the secret it found puts it in CI logs forever."""
        found: list[str] = []
        for path in shipped_files():
            body = read(path)
            for label, pattern in CREDENTIAL_PATTERNS:
                if pattern.search(body):
                    found.append(f"{label} in {os.path.relpath(path, GUI)}")
        self.assertFalse(found, "credential-shaped values found (values "
                                "deliberately not printed): " + "; ".join(found))

    def test_no_signing_key_file_can_reach_a_build(self):
        """A private key in the tree is only safe while it is unreachable.
        gitignore covers the repo; this covers the working tree a build runs
        against."""
        for folder, dirs, names in os.walk(GUI):
            dirs[:] = [d for d in dirs if d in ("devtools",)
                       or d not in SKIP_DIRS]
            for name in names:
                if not name.endswith("-signing-key.hex"):
                    continue
                rel = os.path.relpath(os.path.join(folder, name), GUI)
                # Only devtools/, which packaging/prism.spec never collects.
                self.assertTrue(
                    rel.startswith("devtools" + os.sep),
                    f"{rel} is a private signing key outside devtools/")

    def test_packaging_does_not_bundle_devtools(self):
        """devtools/ holds the minting logic and the dev private key. If it
        were ever added to the spec's datas, every build would ship the
        ability to forge a licence."""
        spec = read(os.path.join(GUI, "packaging", "prism.spec"))
        self.assertNotIn("'devtools'", spec)
        self.assertNotIn('"devtools"', spec)

    def test_the_shipped_public_keys_are_public_keys(self):
        from licensing import keys
        for group in (keys.PRODUCTION, keys.DEVELOPMENT):
            for kid, hexed in group.items():
                self.assertEqual(len(bytes.fromhex(hexed)), 32,
                                 f"{kid} is not a 32-byte Ed25519 public key")


class ByokIsPreserved(unittest.TestCase):
    """Groq is the customer's own key, and must stay that way until there is a
    backend gateway to move it behind."""

    def test_the_config_still_has_a_user_supplied_key_field(self):
        import core_bridge as CB
        self.assertIn("api_key", CB.config.DEFAULT)
        # Empty by default. A non-empty default would BE the embedded
        # credential this whole file exists to prevent.
        self.assertEqual(CB.config.DEFAULT["api_key"], "")

    def test_setup_is_not_considered_done_without_the_user_s_own_key(self):
        import core_bridge as CB
        self.assertFalse(CB.config.is_configured({"api_key": "",
                                                  "onboarded": True}))
        self.assertTrue(CB.config.is_configured({"api_key": "gsk_x",
                                                 "onboarded": True}))

    def test_groq_calls_take_the_key_as_an_argument(self):
        """Not read from a module constant, not from a bundled file. The
        signature is the guarantee: there is nowhere for a Prism-owned key to
        live in this call path."""
        import inspect

        import core_bridge as CB
        params = list(inspect.signature(CB.router.groq_chat).parameters)
        self.assertEqual(params[0], "api_key")

    def test_no_provider_url_is_called_without_a_caller_supplied_key(self):
        """Every Groq endpoint in the engine is reached through a function
        that was handed a key. A default-argument key would be an embedded
        credential wearing a disguise."""
        import inspect

        import core_bridge as CB
        for module in (CB.router, CB.pathfinder, CB.voice):
            for name, fn in vars(module).items():
                if not inspect.isfunction(fn):
                    continue
                for param in inspect.signature(fn).parameters.values():
                    # `api_key` only. `stop_key` in core.voice is a keyboard
                    # key, and a broader match turns this into a test about
                    # parameter naming rather than about credentials.
                    if param.name.lower() not in ("api_key", "apikey", "key"):
                        continue
                    if param.default is inspect.Parameter.empty:
                        continue
                    self.assertIn(
                        param.default, ("", None),
                        f"{module.__name__}.{name} has a non-empty default "
                        f"for {param.name}")


if __name__ == "__main__":
    unittest.main()
