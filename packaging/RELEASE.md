# Prism 1.0.0 — Linux (x64)

Built and verified locally. Windows and macOS are not in this release: PyInstaller
cannot cross-compile, so those artifacts have to be produced on those machines
(or by the CI matrix in `.github/workflows/build.yml`).

## Install

```bash
tar xzf Prism-1.0.0-linux-x64.tar.gz
cd Prism
./install.sh              # launcher entry + a `prism` command, all under ~/.local
```

Then launch Prism from your applications menu, or run `prism`.

Prefer not to install? The app is fully portable — `./Prism` from the extracted
folder works on its own. To remove: `./install.sh --uninstall`, then delete the
folder.

## Requirements

- **Google Chrome.** Prism drives your real, logged-in Chrome to operate the AI
  tools. Install it from google.com/chrome first — `install.sh` warns if it
  isn't found.
- **glibc 2.39 or newer** (Ubuntu 24.04+, Fedora 40+, Arch). See the caveat
  below.
- **PortAudio, only for voice.** Wake word and push-to-talk need it:
  `sudo apt install portaudio19-dev`. Everything else works without it — the
  voice buttons say what's missing rather than failing silently.

## Known limitation of this build

It was compiled on Ubuntu 24.04 (glibc 2.39), and glibc is forward-compatible
only. **It will not start on an older distribution** — Ubuntu 22.04, Debian 12,
or anything with glibc < 2.39 will fail with a version error at launch.

For a build that runs on older systems, produce it on the oldest distribution
you intend to support; the CI workflow pins `ubuntu-22.04` for exactly this
reason.

## What was verified

Against the packaged binary, not the sources:

- starts, loads every bundled resource (stylesheet, Barlow fonts, logo, SVG
  icon engine), imports the engine, builds the main window — 12/12 self-test
  checks (`python packaging/smoke_test.py`)
- runs on a real X server with the bundled xcb platform plugin, full UI renders
- runs from a clean `$HOME` with no prior config, silent on stderr
- tarball extracts; `install.sh` creates a valid desktop entry, icon and symlink

Not exercised anywhere yet: a full run driving Chrome from inside the bundle
(the module imports, but no driver has been launched from the packaged app),
and the AppImage variant, which needs `appimagetool` on PATH.

## First run

Prism opens Setup on first launch: Groq API key, a one-line profile, and one
tool per category. Config lands in `~/.prism/config.json`, shared with the
Prism CLI — if you already use the CLI, the app picks up that setup and its run
history immediately.
