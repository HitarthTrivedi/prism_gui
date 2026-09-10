#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════
#  Prism — install (if needed) and run, on a Mac with nothing on it.
#
#  Double-click this file. The first time it:
#    1. finds a Python 3.11+ on this Mac, or fetches its own standalone one
#       into runtime/ (no admin password, no Homebrew, nothing installed
#       system-wide);
#    2. makes a private virtual environment in .venv/;
#    3. installs Prism's requirements into it;
#    4. fetches the bundled Chromium for Prism Studio / PDF export;
#    5. checks that Google Chrome is installed (Prism drives it for the AI
#       tools) and says so if not;
#    6. starts Prism.
#  Every later double-click goes straight to step 6, unless requirements.txt
#  changed. Everything it writes stays inside this folder and ~/.prism.
#
#  If macOS says the file "cannot be opened because it is from an
#  unidentified developer": right-click it → Open → Open. Once.
#  Interim until the DMG can be signed (see docs/handover/Shipping_the_app_
#  as_a_macOS_DMG.docx).
# ═══════════════════════════════════════════════════════════════════════════
set -u

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR" || exit 1
LOG="$DIR/install.log"
PY_VERSION="3.12.14"
PY_RELEASE="20260901"
MIN_MAJOR=3; MIN_MINOR=11

say()  { printf '%s\n' "$*" | tee -a "$LOG"; }
step() { printf '\n%s\n' "── $* ──────────────────────────────" | tee -a "$LOG"; }
hold() { printf '\n'; read -r -p "Press Enter to close this window." _; }
fail() { say "❌  $*"; say "    The full record is in: $LOG"; hold; exit 1; }

printf '\n🌈  Prism — %s\n' "$(date '+%d %b %Y %H:%M')" | tee -a "$LOG"

# A zip downloaded through a browser carries the quarantine flag on every
# file inside it; macOS then refuses to run the Python it contains. Strip
# it from this folder — it is our own code.
xattr -rd com.apple.quarantine "$DIR" 2>/dev/null || true

# ── 1. a Python ──────────────────────────────────────────────────────────
good_python() {      # $1 = a python; true when it is 3.11+ and has venv
    "$1" -c "import sys, venv; sys.exit(0 if sys.version_info >= ($MIN_MAJOR, $MIN_MINOR) else 1)" \
        >/dev/null 2>&1
}

PY=""
for candidate in \
        "$DIR/runtime/python/bin/python3" \
        python3.12 python3.11 python3.13 \
        /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/3.11/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
        /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
    path="$(command -v "$candidate" 2>/dev/null || true)"
    [ -n "$path" ] && good_python "$path" && { PY="$path"; break; }
done

if [ -z "$PY" ]; then
    step "No Python $MIN_MAJOR.$MIN_MINOR+ on this Mac — fetching a standalone one"
    case "$(uname -m)" in
        arm64)  ARCH="aarch64" ;;
        x86_64) ARCH="x86_64" ;;
        *) fail "Unknown Mac type: $(uname -m)" ;;
    esac
    TARBALL="cpython-${PY_VERSION}+${PY_RELEASE}-${ARCH}-apple-darwin-install_only.tar.gz"
    URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PY_RELEASE}/${TARBALL}"
    mkdir -p "$DIR/runtime"
    if [ -f "$DIR/runtime/downloads/$TARBALL" ]; then
        say "   using the Python that came with this bundle"
        cp "$DIR/runtime/downloads/$TARBALL" "$DIR/runtime/$TARBALL"
    else
        say "   downloading Python $PY_VERSION (about 45 MB)…"
        curl -L --fail --progress-bar -o "$DIR/runtime/$TARBALL" "$URL" 2>&1 | tee -a "$LOG" \
            || fail "Couldn't download Python. Is this Mac online? ($URL)"
    fi
    tar -xzf "$DIR/runtime/$TARBALL" -C "$DIR/runtime" || fail "Couldn't unpack Python."
    rm -f "$DIR/runtime/$TARBALL"
    xattr -rd com.apple.quarantine "$DIR/runtime" 2>/dev/null || true
    PY="$DIR/runtime/python/bin/python3"
    good_python "$PY" || fail "The downloaded Python doesn't run here."
fi
say "🐍  Python: $PY ($("$PY" -c 'import platform; print(platform.python_version())'))"

# ── 2 + 3. the venv and the requirements ─────────────────────────────────
VENV="$DIR/.venv"
STAMP="$VENV/.prism-installed"
WANT="$(shasum -a 256 "$DIR/requirements.txt" | cut -c1-16)-$("$PY" -c 'import platform; print(platform.python_version())')"
HAVE="$(cat "$STAMP" 2>/dev/null || true)"

if [ ! -x "$VENV/bin/python" ]; then
    step "First run — making Prism's private environment"
    "$PY" -m venv "$VENV" || fail "Couldn't create the virtual environment."
fi
VPY="$VENV/bin/python"

if [ "$WANT" != "$HAVE" ]; then
    step "Installing what Prism needs (a few minutes the first time)"
    "$VPY" -m pip install --quiet --upgrade pip setuptools wheel packaging >>"$LOG" 2>&1 \
        || fail "pip couldn't update itself. Is this Mac online?"
    # pyaudio (voice input) needs PortAudio, which a clean Mac doesn't have;
    # it is tried on its own afterwards so it can never block the rest.
    grep -v -E '^\s*pyaudio' "$DIR/requirements.txt" > "$VENV/requirements.core.txt"
    "$VPY" -m pip install --quiet -r "$VENV/requirements.core.txt" 2>&1 | tee -a "$LOG" \
        | grep -v '^$' || true
    "$VPY" -c "import PySide6, requests, selenium, ezdxf, openpyxl, playwright" 2>>"$LOG" \
        || fail "The requirements didn't install. Look at the end of $LOG."
    say "   ✅  core requirements"
    # Python 3.13 dropped the audioop module the voice input reads with;
    # the drop-in replacement is best-effort like pyaudio itself.
    "$VPY" -c "import sys; sys.exit(0 if sys.version_info >= (3, 13) else 1)" 2>/dev/null \
        && "$VPY" -m pip install --quiet audioop-lts >>"$LOG" 2>&1 || true
    if "$VPY" -m pip install --quiet pyaudio >>"$LOG" 2>&1; then
        say "   ✅  voice input (pyaudio)"
    else
        say "   ◦   voice input skipped — needs PortAudio (brew install portaudio); typing works as normal"
    fi
    # The STEP add-on's CAD kernel. Large (hundreds of MB) and optional at
    # runtime — the STEP window says 'needs cadquery' without it.
    if [ "${PRISM_SKIP_CADQUERY:-0}" != "1" ]; then
        say "   installing the STEP add-on's CAD kernel (cadquery, large)…"
        if "$VPY" -m pip install --quiet cadquery >>"$LOG" 2>&1; then
            say "   ✅  STEP add-on (cadquery)"
        else
            say "   ◦   cadquery skipped — STEP files will say 'needs cadquery'"
        fi
    fi
    # ── 4. Chromium for Studio / PDF export ──
    say "   fetching the bundled Chromium for Prism Studio (about 150 MB)…"
    if "$VPY" -m playwright install chromium >>"$LOG" 2>&1; then
        say "   ✅  Chromium"
    else
        say "   ◦   Chromium skipped — Studio falls back to Reel; PDF export off"
    fi
    printf '%s' "$WANT" > "$STAMP"
fi

# ── 5. Google Chrome ─────────────────────────────────────────────────────
if [ ! -d "/Applications/Google Chrome.app" ] && [ ! -d "$HOME/Applications/Google Chrome.app" ]; then
    step "Google Chrome is not installed"
    say "   Prism drives your own logged-in Chrome to run the AI tools."
    say "   Install it from https://www.google.com/chrome/ and sign in to"
    say "   ChatGPT, Claude, Canva, Perplexity … in it once, then run Prism."
    read -r -p "   Open the Chrome download page now? [y/N] " yn
    case "$yn" in [Yy]*) open "https://www.google.com/chrome/" ;; esac
fi

# ── 6. run ───────────────────────────────────────────────────────────────
step "Starting Prism"
say "   (keep this window open while Prism runs; closing it closes Prism)"
"$VPY" "$DIR/main.py" "$@" 2>&1 | tee -a "$LOG"
STATUS=${PIPESTATUS[0]}
if [ "$STATUS" -ne 0 ]; then
    say ""
    say "Prism stopped with code $STATUS. The record is in $LOG."
    hold
fi
exit "$STATUS"
