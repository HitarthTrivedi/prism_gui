"""
Prism GUI — wake-word listener ("Prism")
──────────────────────────────────────────
BEST-EFFORT v0 — read this before relying on it. There is no real local
wake-word engine here (that would mean bundling something like Porcupine or
OpenWakeWord, a separate dependency decision). Instead this loop:
  1. records ~2s chunks continuously
  2. only bothers transcribing a chunk once a crude RMS energy check says
     it wasn't silence (cheap — avoids a network round-trip on every chunk)
  3. sends the loud chunk to Groq Whisper and checks whether "prism" is in
     what it heard

That means real, noticeable delay (up to ~2s of buffering plus a network
round-trip) between saying "Prism" and the GUI noticing — nothing like a
true wake-word engine's near-instant local response, and it burns a Whisper
call for every loud noise near the mic, not just speech. Treat this as a
working demo of the FEATURE, not production always-on listening. If it
turns out to matter for real daily use, swap in Porcupine/OpenWakeWord
(fully local, instant, purpose-built for exactly this) instead of extending
this polling loop further.
"""
from __future__ import annotations
import os
import sys
import io
import wave
from PySide6.QtCore import QThread, Signal

import core_bridge as CB

# audioop was deleted from the stdlib in Python 3.13 (PEP 594), and pyaudio is
# an optional extra that needs PortAudio on the box. Neither may be present —
# and neither is worth refusing to start the whole app over, so they are probed
# here and the feature reports itself unavailable instead of taking the window
# down with an ImportError at launch. audioop-lts is the drop-in replacement.
try:
    import audioop
except ImportError:  # pragma: no cover - depends on interpreter version
    try:
        import audioop_lts as audioop   # noqa: F401
    except ImportError:
        audioop = None

_CHUNK_SECONDS = 2.0
_SILENCE_RMS = 300   # crude energy floor — tune per microphone if it misfires


def install_hint() -> str:
    """The command that actually works on THIS machine.

    Three dialogs used to print 'brew install portaudio' regardless of
    platform, so a Linux or Windows user was told to run a macOS package
    manager they do not have. One place, so they cannot drift again.
    """
    if sys.platform == "darwin":
        return "brew install portaudio && pip install pyaudio"
    if os.name == "nt":
        return "pip install pyaudio"
    return "sudo apt install portaudio19-dev && pip install pyaudio"


def available() -> tuple[bool, str]:
    """(usable, why not). Checked before the listener is started so the reason
    lands in the UI rather than in a traceback nobody sees."""
    if audioop is None:
        return False, ("This build has no audio support (Python 3.13 removed "
                       "the audioop module — install 'audioop-lts').")
    try:
        import pyaudio  # noqa: F401
    except ImportError:
        return False, ("Voice needs PyAudio, which isn't installed:\n\n"
                       f"    {install_hint()}")
    return True, ""


class WakeWordListener(QThread):
    heard = Signal()       # "Prism" was detected — GUI should start a normal take
    error = Signal(str)

    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg
        self._running = True

    def stop(self, wait_ms: int = 3000) -> bool:
        """Ask the loop to finish, and wait for it to actually do so. Returns
        True if the thread has exited by the time this returns.

        This used to only set the flag and return. Callers took that as "the
        thread is gone" and dropped their reference — but the loop was still
        inside a 2s recording pass, or a Whisper request that can run for its
        full 60s timeout. Destroying a running QThread is fatal in Qt:
        "QThread: Destroyed while thread '' is still running", then abort.

        The wait is bounded on purpose. A stuck network call must not freeze
        the GUI for a minute, so this can legitimately return False and the
        caller has to keep the object alive itself rather than assume success.
        """
        self._running = False
        if not self.isRunning():
            return True
        return self.wait(wait_ms)

    def run(self):
        import pyaudio
        try:
            pa = pyaudio.PyAudio()
            stream = pa.open(format=pyaudio.paInt16, channels=1,
                             rate=CB.voice.SAMPLE_RATE, input=True,
                             frames_per_buffer=CB.voice.CHUNK)
        except Exception as e:
            self.error.emit(f"Microphone unavailable: {e}")
            return

        frames_per_chunk = max(1, int(
            CB.voice.SAMPLE_RATE / CB.voice.CHUNK * _CHUNK_SECONDS))
        try:
            while self._running:
                frames, loud = [], False
                for _ in range(frames_per_chunk):
                    if not self._running:
                        break
                    data = stream.read(CB.voice.CHUNK, exception_on_overflow=False)
                    frames.append(data)
                    if audioop.rms(data, 2) > _SILENCE_RMS:
                        loud = True
                if not loud or not frames:
                    continue
                # Re-check before the network call, not just at the top of the
                # loop. Someone who switches the wake word off mid-chunk should
                # not still cost a Whisper round-trip — and it is that call
                # that makes stop() slow enough to matter.
                if not self._running:
                    break
                buf = io.BytesIO()
                with wave.open(buf, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(CB.voice.SAMPLE_RATE)
                    wf.writeframes(b"".join(frames))
                try:
                    text, _lang = CB.voice.transcribe(buf.getvalue(), self.cfg)
                except Exception:
                    continue   # a failed poll shouldn't kill the whole listener
                if "prism" in text.lower():
                    self.heard.emit()
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()
