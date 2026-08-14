"""Usage metering — what the customer consumed, never what they wrote.

Records shapes and counts: how many runs, how many stages, which tool ran
each, and the Groq token counts. Never the brief, never a prompt, never
output. A BOQ query names a real project on a real site; sending that to a
licence server would turn billing infrastructure into something needing a
data-processing agreement, for data we have no use for.

Token counts are honest only for Groq. Those come back in the API response.
The Claude / ChatGPT / Perplexity stages are driven through a browser — there
is no usage figure to read — so they are counted as stages run per tool.
Quoting a "total tokens" number at a customer as though it covered everything
would be wrong, and the admin summary says so.

Nothing here may ever raise into the caller. A metering failure must not cost
a customer their run.
"""
from __future__ import annotations

import threading
import time
from typing import Any

_lock = threading.Lock()
_buffer: list[dict[str, Any]] = []

# A generous ceiling. If the app has been running for days without reaching
# the server, drop the oldest rather than growing without bound — this is
# billing telemetry, not an audit trail, and losing the tail of it is
# preferable to a client's memory creeping.
MAX_BUFFERED = 2000


def record(kind: str, *, tool: str = "", stage: str = "",
           prompt_tokens: int = 0, completion_tokens: int = 0,
           ok: bool = True, ms: int = 0) -> None:
    """Buffer one event. `kind` is plan | run | stage | groq | addon.

    `plan` is recorded by licensing.authorize() when it takes the lease fast
    path — on a metered licence the server writes that row itself, so this is
    the unmetered case only. It is reporting, never enforcement: a client that
    simply never sent it would change the admin console's numbers and nothing
    else, which is precisely why a daily allowance is counted server-side
    instead.
    """
    try:
        with _lock:
            _buffer.append({
                "kind": kind, "tool": tool[:40], "stage": stage[:40],
                "prompt_tokens": int(prompt_tokens or 0),
                "completion_tokens": int(completion_tokens or 0),
                "ok": bool(ok), "ms": int(ms or 0),
            })
            if len(_buffer) > MAX_BUFFERED:
                del _buffer[:len(_buffer) - MAX_BUFFERED]
    except Exception:                               # noqa: BLE001
        pass


def drain() -> list[dict[str, Any]]:
    """Take everything buffered so far, leaving the buffer empty."""
    with _lock:
        events, _buffer[:] = list(_buffer), []
    return events


def restore(events: list[dict[str, Any]]) -> None:
    """Put events back after a failed send, so a flaky network loses nothing."""
    if not events:
        return
    with _lock:
        _buffer[:0] = events
        if len(_buffer) > MAX_BUFFERED:
            del _buffer[:len(_buffer) - MAX_BUFFERED]


def pending() -> int:
    with _lock:
        return len(_buffer)


def install_groq_meter(router_module) -> bool:
    """Count Groq tokens by wrapping the module's `requests` handle.

    Done here rather than in `core/router.py` on purpose: prism_terminal is a
    submodule shared with the CLI, which is not licensed and must keep working
    standalone. Wrapping the name the module already looks up catches every
    call site — there are three — without editing a line of it.

    Returns False if the shape it expects is not there, so a future refactor
    of the engine degrades to "no token counts" rather than to a crash.
    """
    try:
        import requests as real_requests

        groq_url = getattr(router_module, "GROQ_URL", "")
        if not groq_url or getattr(router_module, "_prism_metered", False):
            return False

        class _MeteredRequests:
            """Proxies `requests`, tallying Groq responses on the way past."""

            def post(self, url, *args, **kwargs):
                started = time.time()
                response = real_requests.post(url, *args, **kwargs)
                if isinstance(url, str) and url.startswith(groq_url):
                    self._tally(response, started)
                return response

            @staticmethod
            def _tally(response, started):
                usage = {}
                try:
                    usage = (response.json() or {}).get("usage") or {}
                except Exception:                   # noqa: BLE001
                    pass    # a non-JSON error body is not a metering problem
                record("groq",
                       prompt_tokens=usage.get("prompt_tokens", 0),
                       completion_tokens=usage.get("completion_tokens", 0),
                       ok=getattr(response, "status_code", 0) == 200,
                       ms=int((time.time() - started) * 1000))

            def __getattr__(self, name):
                return getattr(real_requests, name)

        router_module.requests = _MeteredRequests()
        router_module._prism_metered = True
        return True
    except Exception:                               # noqa: BLE001
        return False
