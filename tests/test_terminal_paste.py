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


class RoutingFailuresSpeakEnglish(unittest.TestCase):

    def test_a_garbled_groq_reply_is_retried_then_explained(self):
        src = open(PRISM_PY, encoding="utf-8").read()
        body = src[src.index("asking Groq to split your task"):]
        body = body[:body.index("routing_plan")]
        self.assertIn("json.JSONDecodeError", body)
        self.assertIn("asking once more", body)
        self.assertIn("rewording", body)


if __name__ == "__main__":
    unittest.main()
