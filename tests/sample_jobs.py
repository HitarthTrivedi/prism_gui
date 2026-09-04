"""Where the real customer jobs live on THIS machine.

Five test files measured Prism against actual customer work — Gerber jobs, a
client's quotation form, a STEP assembly — and all five found it by
hardcoding one absolute path:

    /Users/hitarthtrivedi/Documents/PythonProgram/prism-ai-flow/…

That folder exists on exactly one Mac. Everywhere else the guards read
`os.path.isdir(REAL)` as False and skipped, so **22 tests** quietly did not
run: the real-job checks for the most expensive add-on on the price book,
absent from every run on every other machine and from CI, reported as a bare
`s`.

Eleven of Gerber's first thirteen bugs were silent — plausible wrong numbers,
no error, no crash. A skip nobody sees is that same failure one level up, and
it is worse, because the suite still says it passed.

Two changes here. The location is `PRISM_SAMPLE_JOBS` (the old path stays as
the fallback, so nothing breaks for the person who has it), and a skipped
test now says WHICH folder it wanted, so "why is this skipping" is answerable
from the output instead of from reading the source.
"""
from __future__ import annotations

import os

ENV_VAR = "PRISM_SAMPLE_JOBS"

# The original hardcoded root, kept as the default so this is a no-op on the
# machine the samples actually live on.
_LEGACY_ROOT = "/Users/hitarthtrivedi/Documents/PythonProgram/prism-ai-flow"


def root() -> str:
    """The sample-jobs folder this machine should use."""
    return os.path.expanduser(os.environ.get(ENV_VAR, "").strip() or _LEGACY_ROOT)


def path(*parts: str) -> str:
    """A path inside the sample-jobs folder."""
    return os.path.join(root(), *parts)


def missing(*parts: str) -> str:
    """"" when the sample is here, else why it is being skipped.

    Returned as a REASON rather than a bool so the caller can pass it
    straight to skipTest/skipUnless and the output carries the folder. An
    empty string is falsy, so `skipUnless(not missing(...), missing(...))`
    is never needed — see the call sites, which use `skipIf`.
    """
    wanted = path(*parts)
    if os.path.exists(wanted):
        return ""
    if not os.path.isdir(root()):
        return (f"sample jobs folder not on this machine ({root()}) — "
                f"set {ENV_VAR} to point at it")
    return f"sample not on this machine: {wanted}"


# ── symlinks, which Windows treats as a privilege ────────────────────────────

def symlinks_unavailable() -> str:
    """"" if this machine can create a symlink, else why it cannot.

    Windows needs Administrator or Developer Mode for os.symlink; without
    either it raises OSError [WinError 1314] "A required privilege is not
    held by the client". Four test files create one to exercise the
    updater's symlink handling, and on the first Windows CI run of this
    suite all four failed for that reason alone — an environment fact
    reported as four bugs.

    Probed by actually trying it, rather than by checking the OS: the answer
    depends on the machine's settings, not its name, and a developer box
    with Developer Mode on should run these tests.
    """
    import os
    import tempfile

    folder = tempfile.mkdtemp(prefix="prism-symlink-probe-")
    link = os.path.join(folder, "link")
    try:
        os.symlink(os.path.join(folder, "target"), link)
        return ""
    except (OSError, NotImplementedError, AttributeError) as e:
        return (f"this machine cannot create symlinks ({e.__class__.__name__}"
                f": {e}) — on Windows that needs Administrator or Developer "
                "Mode")
    finally:
        try:
            os.remove(link)
        except OSError:
            pass
        try:
            os.rmdir(folder)
        except OSError:
            pass
