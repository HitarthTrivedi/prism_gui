"""Shared test-harness state resets.

There is exactly one thing in here, and it is a reset, not behaviour: the
suite must not be able to see `PRISM_LICENSE_OFFLINE_DEV`.

Why it matters
──────────────
`licensing._offline_dev()` is a developer escape hatch. When the variable is
set and the build is not frozen, `licensing._unreachable_answer()` answers
"allowed" for anything the local token is entitled to, instead of refusing.
It is consulted *after* the network call has already raised `Unreachable`, so
it changes the ANSWER, never the round trip — it cannot make a hanging test
finish, and stripping it cannot make one hang.

That makes it ambient global state that silently rewrites a production
decision path, and the suite had no reset for it. Two ways it got set:

  · the operator exporting it on the command line (the documented invocation
    for this suite does exactly that), and
  · `tests/test_inquiry_screen.py` doing `os.environ.setdefault(...)` at
    module scope, which pytest executes during *collection* — so every other
    module ran with the hatch open even when the variable was unset in the
    environment. That line has been removed; this fixture is what stops the
    next one from mattering.

The victim was
`test_authorization.py::AuthorizeFlow::test_h_a_revoked_licence_gets_no_lease_and_loses_its_cache`,
which asserts that a revoked licence cannot fall back on its cached lease
once the server is unreachable. With the hatch open the fallback is granted,
and the revocation test fails — the one assertion that must never be
unreliable, because a genuine regression in it looks identical.

This is the same class of insulation `LeaseHarness.setUp` already applies to
`licensing.secretstore._keyring`: the answer a test gets must not depend on
what the developer has in their environment.
"""
from __future__ import annotations

import os

import pytest

_OFFLINE_DEV = "PRISM_LICENSE_OFFLINE_DEV"


@pytest.fixture(autouse=True)
def _no_offline_dev_hatch():
    """Run every test with the offline-dev bypass closed, then put the
    environment back exactly as it was."""
    previous = os.environ.pop(_OFFLINE_DEV, None)
    try:
        yield
    finally:
        if previous is not None:
            os.environ[_OFFLINE_DEV] = previous
