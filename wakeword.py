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
import io
import wave
import audioop
from PySide6.QtCore import QThread, Signal

import core_bridge as CB

_CHUNK_SECONDS = 2.0
_SILENCE_RMS = 300   # crude energy floor — tune per microphone if it misfires


class WakeWordListener(QThread):
    heard = Signal()       # "Prism" was detected — GUI should start a normal take
    error = Signal(str)

    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg
        self._running = True

    def stop(self):
        self._running = False

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
