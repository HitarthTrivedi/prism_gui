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
