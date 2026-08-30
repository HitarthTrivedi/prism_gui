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

1. Download this platform's unsigned manifest from the release, and its
   `update-assets-<os>` workflow artifact (`gh run download <run-id> -n
   update-assets-<os>`). Do this on the offline/release machine that holds
   the signing key — not on a laptop that also has CI credentials on it.
2. Sign it:

   ```bash
   python3 devtools/sign_manifest.py manifest.linux-x64.unsigned.json \
     -o manifest.linux-x64.signed \
     --key-hex "$UPDATE_SIGNING_KEY_HEX"
   ```

   This refuses outright if the version isn't newer than the last one this
   machine signed (`devtools/.last_signed_update_version`, gitignored,
   per-machine) — that's the downgrade guard working, not a bug to work
   around with `--allow-downgrade` (that flag is for test fixtures only).
3. Repeat steps 1–2 for every platform in the release (Linux, Windows,
   macOS each get their own manifest and signature — one key, three signed
   files).
4. Publish, by hand, to the same release:

   ```bash
   gh release upload v1.4.0 manifest.linux-x64.signed \
     update-assets-linux-x64/* --clobber
   # repeat for windows-x64 and macos-arm64
   ```

   `--clobber` matters on a re-release (fixing a bad signature) but should
   otherwise never overwrite anything — a version bump means new filenames
   throughout (the flattened names embed the platform tag, not the version,
   so re-running for the SAME version does overwrite; re-running for a NEW
   version does not collide with the old one still sitting there for anyone
   mid-update).

## After that

The next time a Prism client checks for updates (`updater.check_for_update()`,
called from the existing Phase 0 banner path), it fetches
`manifest.<its own platform_tag()>.signed`, verifies it against
`UPDATE_PRODUCTION`, and — if it's genuinely newer — offers the real in-app
"Download → Restart to update" flow instead of the browser-link fallback.

**Before trusting this for a real customer on Windows or macOS**, read the
banner at the top of `apply_update.py`. Two platform assumptions the swap
depends on have never been exercised on real hardware (Windows: does the OS
release Prism's file locks promptly after the process exits; macOS: does a
bundle written by another running app pick up the same quarantine treatment
a browser download gets). Run those two experiments
(`update-plan.md` §9) before the first real customer hits this path on
either platform — Linux is the only one that's been tested end to end.
