#!/usr/bin/env python3
"""Sign and publish every platform's update manifest for one release, in
one run — release-machine tool, not CI, not a build step.

    UPDATE_SIGNING_KEY_HEX=... python3 devtools/release_all.py v1.4.0 33447658517

The `run_id` is the CI run that built the tag — `gh run list --limit 5`
shows it, or `gh run list --workflow "Build desktop apps" -b <tag> -L 1`.

This is the loop RELEASING-UPDATES.md's "Every release" section describes,
run once per platform instead of copy-pasted by hand three times: download
that platform's unsigned manifest and flattened update-assets from the CI
run, sign the manifest, upload both back to the release. devtools/
sign_manifest.py is still the thing that actually signs — this script
never touches the key beyond handing it to that subprocess exactly the way
it already accepts it (--key-hex, defaulting to the environment variable),
and never prints or logs it.

Deliberately NOT shipped (devtools/ is absent from packaging/prism.spec —
see build.py's own comment) and deliberately still a human running it on
their own offline signing machine: this automates the repetitive mechanics,
not the trust decision. UPDATE_SIGNING_KEY_HEX must already be in this
shell's environment before you run it — the script refuses outright if it
isn't, and never accepts it as a command-line argument (a CLI arg is
visible to anyone who can list processes on the machine; an inherited
environment variable isn't).

Idempotent per platform: skips any platform whose `manifest.<platform_tag>.
signed` is already on the release, so a run that fails partway through
(network blip, wrong key, Ctrl-C) can just be re-run rather than needing
you to remember which platforms already made it, and re-running after a
successful release is a fast no-op rather than a slow re-upload of
everything. Pass --force to re-sign and re-upload a platform anyway.

Uploading update-assets is genuinely slow — each platform is roughly a
thousand individual files, and `gh release upload` creates one release
asset per file over the API, not a single bulk transfer. That's real, not
a bug in this script; there's nothing here to speed it up short of the
CI-side flattening scheme changing.
"""
from __future__ import annotations

import argparse
import glob
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

# platform_tag (what manifests and .signed files are named) -> the
# .github/workflows/build.yml matrix's `os` value (what its
# `update-assets-<os>` workflow artifact is actually named). Mirrors that
# workflow's `strategy.matrix.include` — update this table if that matrix
# ever changes runner images.
PLATFORMS = [
    ("linux-x64", "ubuntu-22.04"),
    ("windows-x64", "windows-latest"),
    ("macos-arm64", "macos-14"),
]


def run(cmd: list[str]) -> None:
    print("»", " ".join(cmd))
    subprocess.run(cmd, check=True)


def already_signed(repo: str, tag: str, platform_tag: str) -> bool:
    out = subprocess.run(
        ["gh", "release", "view", tag, "-R", repo, "--json", "assets", "-q",
         f'[.assets[] | select(.name=="manifest.{platform_tag}.signed")] '
         f'| length'],
        check=True, capture_output=True, text=True).stdout.strip()
    return out != "0"


def do_platform(repo: str, tag: str, run_id: str, work: str,
                platform_tag: str, matrix_os: str) -> None:
    unsigned = os.path.join(work, f"manifest.{platform_tag}.unsigned.json")
    signed = os.path.join(work, f"manifest.{platform_tag}.signed")
    assets_dir = os.path.join(work, f"update-assets-{platform_tag}")

    run(["gh", "release", "download", tag, "-R", repo,
        "-p", f"manifest.{platform_tag}.unsigned.json",
        "-D", work, "--clobber"])
    run(["gh", "run", "download", run_id, "-R", repo,
        "-n", f"update-assets-{matrix_os}", "-D", assets_dir])
    # No --key-hex here: sign_manifest.py already defaults it to
    # os.environ["UPDATE_SIGNING_KEY_HEX"], which main() below has already
    # confirmed is set. Passing it explicitly here would work identically
    # but put it on THIS process's command line for no benefit.
    run([sys.executable, os.path.join(HERE, "sign_manifest.py"),
        unsigned, "-o", signed])
    uploads = [signed] + glob.glob(os.path.join(assets_dir, "*"))
    run(["gh", "release", "upload", tag, "-R", repo, "--clobber"] + uploads)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("tag", help="Release tag, e.g. v1.4.0")
    p.add_argument("run_id", help="The CI run id that built this tag")
    p.add_argument("--repo", default="HitarthTrivedi/prism_gui")
    p.add_argument("--work-dir", default=None,
                   help="Where to download/sign into (default: a fresh "
                        "temp dir, left in place so a failure can be "
                        "inspected or resumed by hand)")
    p.add_argument("--force", action="store_true",
                   help="Re-sign and re-upload a platform even if the "
                        "release already has its .signed manifest")
    args = p.parse_args(argv)

    if not os.environ.get("UPDATE_SIGNING_KEY_HEX"):
        p.error("UPDATE_SIGNING_KEY_HEX is not set in this shell. Set it "
                "there (export UPDATE_SIGNING_KEY_HEX=... or read -s "
                "UPDATE_SIGNING_KEY_HEX) before running this script — "
                "never pass it as an argument.")

    work = args.work_dir or tempfile.mkdtemp(prefix="prism-release-")
    os.makedirs(work, exist_ok=True)
    print(f"Working directory: {work}\n")

    done, skipped, failed = [], [], []
    for platform_tag, matrix_os in PLATFORMS:
        print(f"── {platform_tag} " + "─" * max(1, 40 - len(platform_tag)))
        if not args.force and already_signed(args.repo, args.tag, platform_tag):
            print(f"already has manifest.{platform_tag}.signed on the "
                 f"release — skipping (--force to redo it)\n")
            skipped.append(platform_tag)
            continue
        try:
            do_platform(args.repo, args.tag, args.run_id, work,
                       platform_tag, matrix_os)
            done.append(platform_tag)
            print(f"✓ {platform_tag} done\n")
        except subprocess.CalledProcessError as e:
            print(f"✗ {platform_tag} failed: {e}\n", file=sys.stderr)
            failed.append(platform_tag)

    print("── summary " + "─" * 30)
    print(f"done:    {done or '(none)'}")
    print(f"skipped: {skipped or '(none, already signed)'}")
    print(f"failed:  {failed or '(none)'}")
    if failed:
        print(f"\nRe-run the same command to retry — completed platforms "
             f"are skipped automatically, work is kept at {work}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
