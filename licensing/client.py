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

DEFAULT_SERVER = "https://api.alphakore.in"

# Short on purpose. This runs at launch; if the server has not answered in five
# seconds we would rather carry on with the cached token than make the customer
# wait for a timeout they cannot act on.
TIMEOUT = 5


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


def _post(endpoint: str, body: dict[str, Any], *, app_version: str) -> dict[str, Any]:
    import requests  # local import: keeps `import licensing` cheap at startup
    import sys

    url = f"{server_url()}{endpoint}"
    headers = {
        "X-Prism-Version": app_version,
        "X-Prism-Platform": sys.platform,
    }
    try:
        response = requests.post(url, json=body, headers=headers, timeout=TIMEOUT)
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
    }, app_version=app_version)


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


def payload(license_id: str, device_fp: str, *, app_version: str) -> dict[str, Any]:
    return _post("/v1/payload", {
        "license_id": license_id,
        "device_fp": device_fp,
        "app_version": app_version,
    }, app_version=app_version)
