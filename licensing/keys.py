"""Public keys that licence tokens are verified against.

Public keys are not secrets — publishing them is harmless. The matching private
keys live only in the licence server's secret store, and nowhere else, ever.

Rotation: tokens carry a `kid`, and this module holds a map rather than a
single key, so a new signing key can be introduced while tokens signed with the
old one still verify. The order is always:

    1. ship a build containing BOTH public keys
    2. wait until customers have updated
    3. only then start signing with the new kid

Signing with a kid that shipped builds do not know locks out every customer who
has not updated, which is the failure this map exists to prevent.
"""
from __future__ import annotations

import paths

# Production keys. Signed tokens issued by api.alphakore.in verify against
# these, in every build.
PRODUCTION: dict[str, str] = {
    # "k1": "…",   ← added at first release, generated on the server
}

# Development and staging keys.
#
# These are trusted ONLY when running from source. A frozen build ignores them
# completely — see public_keys() below. That is not belt-and-braces: the dev
# private key lives in a working tree and gets copied around, so a release
# build that honoured it would ship a universal skeleton key for the whole
# product. The exclusion is the only thing making it safe for this to exist.
DEVELOPMENT: dict[str, str] = {
    "dev1": "dbaf613b980d4590032a03d04591d3f5f3788e7d6ec8d1956e3bfb53fbe6b3cc",
}


def public_keys() -> dict[str, str]:
    """The keys this build will accept tokens from."""
    if paths.is_frozen():
        return dict(PRODUCTION)
    return {**PRODUCTION, **DEVELOPMENT}
