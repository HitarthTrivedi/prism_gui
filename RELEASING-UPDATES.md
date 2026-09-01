# Releasing an in-app update

How a tagged build turns into something Prism's own in-app updater will
actually offer a customer. Related: [`SHIPPING.md`](SHIPPING.md) for the
three shipping stages this sits inside · [`BUILD.md`](BUILD.md) for what
`packaging/build.py` produces · `update-research-inapp-download.md` for why
this is shaped the way it is.

## The one thing to understand first

Pushing a tag (`v1.4.0`) makes CI build, smoke-test, and publish a normal
GitHub Release — exactly as it always has. It ALSO makes CI generate an
**unsigned** update manifest per platform (`manifest.<platform>.unsigned.json`,
attached to that release) and a matching pile of flattened per-file assets
(`update-assets-<os>`, a workflow artifact — deliberately **not** attached to
the release).

That's it. CI stops there on purpose. Nothing CI touches can sign a manifest
— the signing key never goes near a CI secret, per
`update-research-inapp-download.md` §5.2 requirement #2, because a CI/token
compromise must not be able to push a malicious "update" to every customer.
**Prism's in-app updater will not fetch anything from this release until a
human does the two steps below.** Until then, the "Download" button just
falls back to the old browser-link behaviour — that is the safe default, not
a bug.

## What you need, once

- The offline `UPDATE_SIGNING_KEY_HEX` — generated once, kept in a password
  manager plus a sealed paper copy, **never** pasted into a CI secret, a repo
  variable, or anything Render can read. See `licensing/keys.py`'s
  `UPDATE_PRODUCTION` comment. If this doesn't exist yet, generate it now:

  ```bash
  python3 -c "
  from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
  from cryptography.hazmat.primitives import serialization as s
  k = Ed25519PrivateKey.generate()
  priv = k.private_bytes(s.Encoding.Raw, s.PrivateFormat.Raw, s.NoEncryption()).hex()
  pub = k.public_key().public_bytes(s.Encoding.Raw, s.PublicFormat.Raw).hex()
  print('private (keep offline):', priv)
  print('public  (ship in the build):', pub)
  "
  ```

  Add the public half to `licensing/keys.py`'s `UPDATE_PRODUCTION` dict under
  kid `u1`, commit that (public keys are not secrets), and cut a build
  containing it **before** you ever sign a manifest with the matching
  private key — a build that doesn't know the key yet will reject the
  manifest as `unknown_key`, safely, but there's no point signing for
  nobody.
- `gh`, the GitHub CLI, authenticated against this repo.

## Every release, after CI finishes for a tag

**One command does all three platforms:**

```bash
UPDATE_SIGNING_KEY_HEX=... python3 devtools/release_all.py v1.4.0 <run-id>
```

Run it on the offline/release machine that holds the signing key — not a
laptop that also has CI credentials on it. `<run-id>` is the CI run that
built the tag (`gh run list --limit 5`). It downloads each platform's
unsigned manifest and `update-assets-<os>` artifact, signs it
(`devtools/sign_manifest.py` — see its own downgrade-guard note below),
and uploads everything to the right place (see "Two releases" below). It's
idempotent per platform and safe to re-run if it fails partway through —
see the script's own docstring for the full explanation, including why
this exists instead of the four-commands-times-three-platforms this
section used to be.

Signing refuses outright if the version isn't newer than the last one this
machine signed **for that platform**
(`devtools/.last_signed_update_version.<platform>`, gitignored, one file
per platform, per-machine) — the downgrade guard working, not a bug to
route around with `--allow-downgrade` (test fixtures only). It's scoped
per platform deliberately: one release signs the SAME version three times
over, once per platform, and a guard that couldn't tell that apart from a
real downgrade refused the second and third signs — it did, on the first
real 3-platform release, until that got fixed.

**Two releases per version, not one.** GitHub caps a release at 1000
assets, and three platforms' flattened per-file update assets sharing one
release with the archives and manifests needs ~2600 once Playwright's
Chromium is in the bundle — found the hard way shipping v1.4.0, where
most of those files silently never made it onto the release and `gh
release upload` still exited 0. So:

  - `<tag>` — the human-facing release: archives, unsigned manifests
    (from CI), signed manifests (from `release_all.py`). Unchanged from
    before; `updater.py`'s `_manifest_url()` still reads it via
    `releases/latest/download/`.
  - `<tag>-assets-<platform>` — one per platform, holding that platform's
    ~1000 flattened per-file assets. Created `--prerelease` so it can
    never become GitHub's "latest" release out from under the real one.
    `updater.py`'s `_file_url()` reads these via an explicit tag (built
    from the manifest's own `version` field), never "latest" — three
    releases can't all be "latest" at once.

If you need to redo just one platform's asset upload by hand (a partial
`release_all.py` failure, say), `devtools/verify_upload.py` does the
verify-then-upload-missing step alone, against files already downloaded
locally — see its own docstring.

## After that

The next time a Prism client checks for updates (`updater.check_for_update()`,
called from the existing Phase 0 banner path), it fetches
`manifest.<its own platform_tag()>.signed` from `<tag>` (still "latest"),
verifies it against `UPDATE_PRODUCTION`, and — if it's genuinely newer —
stages the update by fetching only the files that changed from
`<tag>-assets-<its own platform_tag()>`, then offers the real in-app
"Download → Restart to update" flow instead of the browser-link fallback.

**A client's own `updater.py` has to already contain the fix to use it.**
The very first time a client updates from a version older than whichever
release introduced a fix here, that old client's baked-in code runs the
OLD logic and falls back to the browser — server-side correctness alone
can't reach into a binary that was already built. From that point forward
(once they're on a version whose `updater.py` has the fix), every
subsequent update uses the real in-app flow. Confirmed exactly this way
shipping v1.4.0: 1.3.2 clients fall back to the browser for THIS one
update, and every update after 1.4.0 will not.

**Before trusting this for a real customer on Windows or macOS**, read the
banner at the top of `apply_update.py`. Two platform assumptions the swap
depends on have never been exercised on real hardware (Windows: does the OS
release Prism's file locks promptly after the process exits; macOS: does a
bundle written by another running app pick up the same quarantine treatment
a browser download gets). Run those two experiments
(`update-plan.md` §9) before the first real customer hits this path on
either platform — Linux is the only one that's been tested end to end.
