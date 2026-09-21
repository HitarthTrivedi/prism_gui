"""History must tolerate records written by older Prism versions."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402
from dialogs.history_dialog import HistoryDialog  # noqa: E402


class ReadingOlderRunRecords(unittest.TestCase):

    def test_a_string_routing_prompt_does_not_crash_history(self):
        """Older records stored routing[stage] as text, not a mapping."""
        renderer = HistoryDialog.__new__(HistoryDialog)
        html = renderer._render({
            "query": "Research EV incentives",
            "routing": {"research": "Research the current EV incentives."},
            "responses": {"research": ["The subsidy changed in 2026."]},
            "links": {},
        }, "run_1.json")
        self.assertIn("Research the current EV incentives.", html)
        self.assertIn("The subsidy changed in 2026.", html)


if __name__ == "__main__":
    unittest.main()
