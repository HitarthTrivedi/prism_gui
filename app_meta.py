"""Identity of the packaged app — one place, read by the build and the app.

The packaging scripts import this rather than hard-coding strings, so bumping
VERSION here renames every artifact and updates the About text at once.
"""
from __future__ import annotations

NAME = "Prism"
# Reverse-DNS id: macOS uses it for the bundle, Linux for the .desktop file.
BUNDLE_ID = "in.alphakore.prism"
VERSION = "1.3.1"
DESCRIPTION = "One task in, a whole pipeline of AI tools out."
PUBLISHER = "Alphakore"

# Where the "Download" button on the update banner sends people. A fixed
# vendor address baked into the build — never a URL the licence server hands
# us, so nothing that can talk to the client can redirect it (updater.py).
# The GitHub Releases page always shows the newest build; the CI workflow
# publishes every tag there.
# TODO(alphakore): point at WEBSITE + "/prism/download" once that page exists.
DOWNLOAD_URL = "https://github.com/HitarthTrivedi/prism_gui/releases/latest"

# Shown on every licence screen — when a trial ends, when an add-on is locked,
# when activation fails. This is the only route a stuck customer has back to
# us, so it must be an address someone actually reads.
# TODO(alphakore): confirm these before the first client build ships.
SUPPORT_EMAIL = "hello@alphakore.in"
WEBSITE = "https://alphakore.in"

# Where a person downloads a newer Prism. Fixed, and opened in the browser —
# Prism never fetches or runs an update itself (see updater.py). The
# releases page, so the same address serves every version that follows.
DOWNLOAD_URL = "https://github.com/HitarthTrivedi/prism_gui/releases/latest"
