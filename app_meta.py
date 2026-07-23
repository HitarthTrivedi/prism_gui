"""Identity of the packaged app — one place, read by the build and the app.

The packaging scripts import this rather than hard-coding strings, so bumping
VERSION here renames every artifact and updates the About text at once.
"""
from __future__ import annotations

NAME = "Prism"
# Reverse-DNS id: macOS uses it for the bundle, Linux for the .desktop file.
BUNDLE_ID = "in.alphakore.prism"
VERSION = "1.0.1"
DESCRIPTION = "One task in, a whole pipeline of AI tools out."
PUBLISHER = "Alphakore"
