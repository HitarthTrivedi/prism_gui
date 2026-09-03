"""The terminal must survive what a real terminal does to input.

Seen live: macOS Terminal wraps every paste in bracketed-paste markers
(ESC[200~ … ESC[201~). The speak/type gate reads its first character raw,
so the marker's ESC arrived as "the first typed character" — the pasted
/step-ask command no longer started with "/", fell past the dispatcher
into the task router, and the interpreter hijacked the file path out of
it. In the same session, a garbled Groq routing reply surfaced as
"Expecting ',' delimiter: line 7 column 13" — a parser's sentence, not a
person's.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRISM_PY = os.path.join(ROOT, "prism_terminal", "prism.py")

sys.path.insert(0, os.path.join(ROOT, "prism_terminal"))

_spec = importlib.util.spec_from_file_location("prism_repl", PRISM_PY)
prism = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prism)


class PastedCommandsStayCommands(unittest.TestCase):

    def test_bracketed_paste_markers_are_stripped(self):
        got = prism._strip_paste_markers(
            "\x1b[200~/step-ask plastic file.step question\x1b[201~")
        self.assertEqual(got, "/step-ask plastic file.step question")
        self.assertTrue(got.startswith("/"))

    def test_a_marker_split_across_reads_still_strips(self):
        # The gate consumes the ESC alone; the rest of the marker arrives
        # with the line. Reassembled, the pair must still vanish.
        got = prism._strip_paste_markers("\x1b" + "[200~/help")
        self.assertEqual(got, "/help")

    def test_plain_text_passes_untouched(self):
        self.assertEqual(prism._strip_paste_markers("/gerber ~/job.zip"),
                         "/gerber ~/job.zip")

    def test_every_input_assembly_point_sanitises(self):
        src = open(PRISM_PY, encoding="utf-8").read()
        prompt_body = src[src.index("def _prompt("):src.index("def _confirm_task(")]
        self.assertIn("_strip_paste_markers", prompt_body)
        gate_body = src[src.index("def _get_input("):src.index("def main(")]
        self.assertIn("_strip_paste_markers", gate_body)

    def test_the_main_prompt_reads_canonical_not_widget(self):
        """questionary runs the tty raw and swallows a multi-line paste's
        remaining lines into its own buffer — they then surfaced as
        keystrokes inside the NEXT widget, cutting a /step-ask question in
        half and answering its confirm 'No'. The main prompt must stay on
        plain input() so the drain can merge the whole paste back."""
        src = open(PRISM_PY, encoding="utf-8").read()
        prompt_body = src[src.index("def _prompt("):src.index("def _confirm_task(")]
        self.assertNotIn("questionary.text", prompt_body)
        self.assertNotIn("import questionary", prompt_body)
        self.assertEqual(prompt_body.count("_drain_pending_lines"), 2)

    def test_the_confirm_widget_is_drained_first(self):
        src = open(PRISM_PY, encoding="utf-8").read()
        body = src[src.index("def _ask_yes_no("):src.index("def _prompt(")]
        self.assertLess(body.index("_drain_pending_lines"),
                        body.index("_q_confirm(msg"))

    def test_readline_is_active_so_input_reads_one_line(self):
        """Without readline, input() reads the tty through C stdio, which
        buffers a whole chunk: a paste's second line hides inside libc
        where select()-based draining cannot see it, and leaks out at the
        next Y/n prompt. Watched auto-answer 'No' on two real runs."""
        src = open(PRISM_PY, encoding="utf-8").read()
        self.assertIn("import readline", src)


class RoutingFailuresSpeakEnglish(unittest.TestCase):

    def test_a_garbled_groq_reply_is_retried_then_explained(self):
        src = open(PRISM_PY, encoding="utf-8").read()
        body = src[src.index("asking Groq to split your task"):]
        body = body[:body.index("routing_plan")]
        self.assertIn("json.JSONDecodeError", body)
        self.assertIn("asking once more", body)
        self.assertIn("rewording", body)



@unittest.skipIf(os.name == "nt", "pty is POSIX-only")
class TheVoiceGateLeavesThePasteInTheTty(unittest.TestCase):
    """RawKeys read the first keystroke through the BUFFERED sys.stdin —
    which slurped a whole pasted command into Python's internal buffer to
    hand back one character. The remainder then haunted the session from
    inside Python, invisible to every select()-based drain: a stray 'n'
    from a paste's second line answered a Y/n prompt on two real runs.
    This drives the real RawKeys in a real pty and proves the sequence
    gate → input() → drain → confirm sees every byte in the right place."""

    CHILD = r'''
import os, select, sys
sys.path.insert(0, %r)
import readline  # noqa: F401
from core.voice import RawKeys
with RawKeys() as keys:
    ch = keys.wait()
rest = input()
def drain():
    out = []
    while True:
        r, _, _ = select.select([sys.stdin], [], [], 0.2)
        if not r:
            break
        out.append(sys.stdin.readline().strip())
    return out
extra = drain()
print("CMD=" + repr((ch + rest + " " + " ".join(extra)).strip()), flush=True)
print("CONFIRM=" + repr(input("y/n? ").strip()), flush=True)
''' % (os.path.join(ROOT, "prism_terminal"),)

    def test_a_two_line_paste_survives_gate_input_drain_confirm(self):
        import pty
        import select as sel
        import subprocess
        import time
        master, slave = pty.openpty()
        p = subprocess.Popen([sys.executable, "-c", self.CHILD],
                             stdin=slave, stdout=slave, stderr=slave,
                             close_fds=True)
        os.close(slave)
        out = b""

        def pump(seconds):
            nonlocal out
            end = time.time() + seconds
            while time.time() < end:
                r, _, _ = sel.select([master], [], [], 0.1)
                if r:
                    try:
                        out += os.read(master, 65536)
                    except OSError:
                        return
        pump(0.8)
        os.write(master, b"/step-ask first half\n  second half\n")
        pump(2.0)
        os.write(master, b"y\n")
        pump(1.5)
        p.kill()
        text = out.decode(errors="replace")
        self.assertIn("CMD='/step-ask first half second half'", text)
        self.assertIn("CONFIRM='y'", text)

if __name__ == "__main__":
    unittest.main()
