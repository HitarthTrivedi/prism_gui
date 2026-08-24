"""Shared test-harness state resets.

Two resets, one autouse fixture, and neither is behaviour: no test may see
`PRISM_LICENSE_OFFLINE_DEV`, and no test may hand the next one a licensing
thread that is still running.

1. The offline-dev hatch
────────────────────────
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

2. Licensing's fire-and-forget threads
──────────────────────────────────────
`licensing.refresh()` and `licensing.report_usage()` hand their work to a
daemon thread and return; nothing the customer does waits on one, which is
correct in the product and poison in a suite. Such a thread re-reads
`licensing.user_dir()` and `keys.public_keys()` at every step, and in tests
those are `mock.patch` globals belonging to whatever test is running *at that
instant* — not the one that started the thread.

What leaked: `test_authorization.py::LocalFirstStartup::
test_k_refresh_returns_immediately_and_never_raises` started one under a
patched `client._post` and let it outlive the patch. It reached the real
licence server, and its answer — a genuine signed token — was written by
`licensing._apply()` into the temp `~/.prism` of whichever test_gates.py test
had the floor eight modules later. Against test_gates' throwaway public key a
genuine token cannot verify, so the licence read TAMPERED, features went
empty, and every add-on padlocked.

Which tests it broke: `test_gates.py::WindowGates::
test_sidebar_padlocks_what_is_not_owned` and `::WindowGates::
test_owned_addon_still_blocked_when_the_server_is_unreachable`, roughly twice
in ten full runs and never in isolation.

That leak is fixed where it was made — the test now joins the thread inside
its patch. This drain is the net under the next one: a leaked thread that
survives its test gets waited for here, so a mistake costs a slow teardown
and a warning naming the test that made it, instead of a 2-in-10 failure in
somebody else's module.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import threading
import warnings

import pytest

_OFFLINE_DEV = "PRISM_LICENSE_OFFLINE_DEV"

# Long enough for a stub-answered thread to finish (microseconds) or a real
# one to time out against the server, short enough that a wedged thread does
# not read as a hung suite.
_THREAD_DRAIN_SECONDS = 10.0


# The licence fields that ARE the licence. `last_seen_utc` and
# `last_refresh_attempt` are heartbeat bookkeeping the app rewrites in normal
# use, so watching them would make this fixture fail on every clean run — and
# a guard that cries wolf is a guard somebody deletes. These five are the ones
# whose loss actually locks a customer out of software they paid for.
_LICENCE_FIELDS = ("token", "license_id", "key", "server", "designation")


def _real_home_files() -> dict[str, str]:
    """Fingerprint the developer's own ~/.prism — what a test must never
    touch: the licence's identity, and every saved run."""
    import json
    home = os.path.join(os.path.expanduser("~"), ".prism")
    out: dict[str, str] = {}
    licence = os.path.join(home, "license.json")
    if os.path.exists(licence):
        try:
            with open(licence, encoding="utf-8") as f:
                data = json.load(f)
            out["licence"] = hashlib.sha256(
                "|".join(str(data.get(k, "")) for k in _LICENCE_FIELDS)
                .encode("utf-8")).hexdigest()
        except (OSError, ValueError):
            out["licence"] = "unreadable"
    runs = os.path.join(home, "runs")
    if os.path.isdir(runs):
        out["runs/"] = ",".join(sorted(n for n in os.listdir(runs)
                                       if n.startswith("run_")))
    return out


@pytest.fixture(scope="session", autouse=True)
def _the_suite_must_not_touch_the_real_home():
    """Fail loudly if a test writes to the developer's own ~/.prism.

    Not hypothetical, and not cheap to find by hand. Two real incidents:

      · A leaked licensing daemon thread (see below) reached the real server
        and wrote its genuine token into whatever `user_dir()` resolved to at
        that instant — sometimes the developer's actual licence file. The
        licence then read TAMPERED on the next real launch, with no clue why.
      · `tests/test_dashboard_data.py` passed `cfg["runs_dir"]` to
        `dashboard_data._run_files` and assumed that isolated it. It does not:
        that key is ignored and the folder is resolved through
        `workspace.runs_dir()`. The test deleted one REAL saved run per suite
        run, and its own "skip if empty" guard never fired — the list was
        non-empty precisely because it was full of the user's data. Fifty-two
        runs of history went that way before anyone noticed.

    Both were invisible until someone opened the app. This makes them a test
    failure instead: a session-scoped before/after fingerprint of the licence
    file and the set of saved runs.
    """
    before = _real_home_files()
    yield
    after = _real_home_files()
    if before == after:
        return
    lost = []
    if before.get("licence") != after.get("licence"):
        lost.append("the real ~/.prism/license.json had its identity "
                    "rewritten (one of " + ", ".join(_LICENCE_FIELDS) + ")")
    if before.get("runs/") != after.get("runs/"):
        was = set(filter(None, (before.get("runs/") or "").split(",")))
        now = set(filter(None, (after.get("runs/") or "").split(",")))
        gone, added = sorted(was - now), sorted(now - was)
        if gone:
            lost.append(f"{len(gone)} saved run(s) DELETED: {gone[:5]}")
        if added:
            lost.append(f"{len(added)} run(s) written into the real folder")
    raise AssertionError(
        "The suite wrote to the developer's own ~/.prism:\n  - "
        + "\n  - ".join(lost)
        + "\nA test must operate on a temp directory. Note that passing "
          "cfg['runs_dir'] does NOT isolate dashboard_data._run_files, and "
          "that a licensing daemon thread outliving its patch will write "
          "wherever user_dir() points when it finishes.")


@pytest.fixture(autouse=True)
def _isolate_ambient_state(request):
    """Close the offline-dev bypass for the duration of every test, then put
    the environment back exactly as it was; and let no licensing thread cross
    the finish line into the next test."""
    previous = os.environ.pop(_OFFLINE_DEV, None)
    try:
        yield
    finally:
        if previous is not None:
            os.environ[_OFFLINE_DEV] = previous

        stragglers = [t for t in threading.enumerate()
                      if t.name.startswith("prism-") and t.is_alive()]
        for t in stragglers:
            t.join(_THREAD_DRAIN_SECONDS)
        still_running = [t.name for t in stragglers if t.is_alive()]
        if still_running:
            warnings.warn(
                f"{request.node.nodeid} left {still_running} running after "
                f"{_THREAD_DRAIN_SECONDS}s. It will read user_dir() and "
                f"public_keys() out of whichever test runs next, and write "
                f"where it is told. Join it in the test that starts it.",
                stacklevel=1)
