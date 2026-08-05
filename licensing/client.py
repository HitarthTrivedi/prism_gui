"""HTTP to the licence server.

Every call here is short, blocking and failure-tolerant, and the caller is
responsible for keeping it off the UI thread. A slow DNS lookup on a corporate
network must never add seconds to Prism's launch, and the licence server being
unreachable must never produce a dialog — the app already holds a token good
for days, which is the entire reason tokens are signed rather than checked
live.

There is no /v1/trial/start. Trials are keys we issue by hand; the client
cannot mint one. See docs/licensing/02-api-and-data.md.
"""
from __future__ import annotations

import os
from typing import Any

import paths

# Where a shipped build talks to. Baked in at build time and NOT overridable
# at runtime in a frozen app — an env var that could redirect a release build
# to a licence server someone else controls would defeat the whole system.
#
# packaging/build.py writes this from PRISM_SERVER_URL so a test build can be
# pointed at a laptop or a LAN address without editing source. Leave it unset
# for real releases and this default ships.
DEFAULT_SERVER = "https://api.alphakore.in"

# Short on purpose. This runs at launch; if the server has not answered in five
# seconds we would rather carry on with the cached token than make the customer
# wait for a timeout they cannot act on.
# Background calls — refresh, deactivate, usage. Failing one of these is
# harmless: the cached token covers it and nothing is shown to the customer.
TIMEOUT = 8

# Authorising a run happens with the customer watching, right after they
# pressed Start the work. They will wait a few seconds for an answer; what
# they will not forgive is being told no because we gave up too early.
AUTHORIZE_TIMEOUT = 15

# Activation is the most expensive call we make — look up the licence, count
# seats, insert the device, commit — and the one the customer least forgives
# failing, because it is their first impression and they cannot get past it.
#
# Sized for a database that is nowhere near the server: a Supabase project in
# Sydney answers in ~300ms per query, so six queries plus a cold connection
# handshake is comfortably past five seconds. That combination produced a
# "couldn't reach the licence server" on a server that was up and answering.
ACTIVATE_TIMEOUT = 30


class ServerError(Exception):
    """The server answered, and said no.

    `message` is the server's own customer-facing wording — it is written as
    copy, not as a log line, so it goes straight to the user.
    """

    def __init__(self, code: str, message: str, detail: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}


class Unreachable(Exception):
    """Could not talk to the server at all. Almost never worth showing."""


def server_url() -> str:
    """Where to talk to.

    The override exists for staging and is honoured ONLY when running from
    source. An environment variable that redirected a release build would let
    anyone point Prism at a licence server they control, which is precisely the
    backdoor this whole design is meant not to have.
    """
    if not paths.is_frozen():
        override = os.environ.get("PRISM_LICENSE_SERVER")
        if override:
            return override.rstrip("/")
    return DEFAULT_SERVER


def _post(endpoint: str, body: dict[str, Any], *, app_version: str,
          timeout: int | None = None) -> dict[str, Any]:
    import requests  # local import: keeps `import licensing` cheap at startup
    import sys

    url = f"{server_url()}{endpoint}"
    headers = {
        "X-Prism-Version": app_version,
        "X-Prism-Platform": sys.platform,
    }
    try:
        response = requests.post(url, json=body, headers=headers,
                                 timeout=timeout or TIMEOUT)
    except Exception as e:                      # noqa: BLE001 — requests raises broadly
        raise Unreachable(str(e)) from e

    try:
        data = response.json()
    except ValueError:
        data = {}

    if response.status_code >= 400:
        error = data.get("error") or {}
        raise ServerError(
            str(error.get("code") or f"http_{response.status_code}"),
            str(error.get("message")
                or "The licence server rejected this request."),
            error.get("detail") if isinstance(error.get("detail"), dict) else {})
    return data


def activate(key: str, device_fp: str, *, app_version: str,
             hostname_label: str = "") -> dict[str, Any]:
    return _post("/v1/activate", {
        "key": key,
        "device_fp": device_fp,
        "app_version": app_version,
        "hostname_label": hostname_label,
    }, app_version=app_version, timeout=ACTIVATE_TIMEOUT)


def refresh(license_id: str, device_fp: str, *, app_version: str,
            payload_etag: str = "") -> dict[str, Any]:
    return _post("/v1/refresh", {
        "license_id": license_id,
        "device_fp": device_fp,
        "app_version": app_version,
        "payload_etag": payload_etag,
    }, app_version=app_version)


def deactivate(license_id: str, device_fp: str, *, app_version: str) -> dict[str, Any]:
    return _post("/v1/deactivate", {
        "license_id": license_id,
        "device_fp": device_fp,
    }, app_version=app_version)


def authorize(license_id: str, device_fp: str, *, app_version: str,
              action: str = "run", feature: str = "core") -> dict[str, Any]:
    """Ask permission for one run, or for one add-on being opened.

    Uses a longer timeout than the launch calls: this one the customer is
    knowingly waiting on, having just pressed a button, so a slow answer beats
    a wrong one.
    """
    return _post("/v1/authorize", {
        "license_id": license_id,
        "device_fp": device_fp,
        "action": action,
        "feature": feature,
        "app_version": app_version,
    }, app_version=app_version, timeout=AUTHORIZE_TIMEOUT)


def usage(license_id: str, device_fp: str, *, app_version: str,
          run_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    return _post("/v1/usage", {
        "license_id": license_id,
        "device_fp": device_fp,
        "run_id": run_id,
        "app_version": app_version,
        "events": events,
    }, app_version=app_version)


def payload(license_id: str, device_fp: str, *, app_version: str) -> dict[str, Any]:
    return _post("/v1/payload", {
        "license_id": license_id,
        "device_fp": device_fp,
        "app_version": app_version,
    }, app_version=app_version)
