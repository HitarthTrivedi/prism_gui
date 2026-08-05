"""Identity of the packaged app — one place, read by the build and the app.

The packaging scripts import this rather than hard-coding strings, so bumping
VERSION here renames every artifact and updates the About text at once.
"""
from __future__ import annotations

NAME = "Prism"
# Reverse-DNS id: macOS uses it for the bundle, Linux for the .desktop file.
BUNDLE_ID = "in.alphakore.prism"
VERSION = "1.0.2"
DESCRIPTION = "One task in, a whole pipeline of AI tools out."
PUBLISHER = "Alphakore"

# Shown on every licence screen — when a trial ends, when an add-on is locked,
# when activation fails. This is the only route a stuck customer has back to
# us, so it must be an address someone actually reads.
# TODO(alphakore): confirm these before the first client build ships.
SUPPORT_EMAIL = "hello@alphakore.in"
WEBSITE = "https://alphakore.in"
