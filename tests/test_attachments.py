"""core/files.py — what an attached file becomes inside a prompt.

The run that prompted this: a 370 KB attendance CSV, attached to "summarise
this in a structured manner". The file went up to the tool as an upload AND
its first 12,000 characters were pasted into the prompt, cut off mid-row.
The analysis stage spent its whole turn on the wall of numbers and produced
nothing usable. Two rules now:

  · a spreadsheet above a few dozen rows is never pasted raw — it gets a
    profile (row count, columns, per-column summary, a few sample rows);
  · a file that has just been uploaded to the tool is not pasted in as
    well, beyond a short excerpt.
"""
from __future__ import annotations

import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge as CB  # noqa: E402

F = CB.files


def _attendance_csv(rows: int) -> str:
    """The shape of the real file: 40 employees, one row per person per day."""
    d = tempfile.mkdtemp(prefix="prism-att-")
    path = os.path.join(d, "employee_attendance_Mar-Aug_2026.csv")
    rng = random.Random(7)
    names = [f"EMP{i:03d},Person {i},{dept}" for i, dept in
             zip(range(1, 41), ["Sales", "Operations", "Finance", "HR", "IT",
                                "Support"] * 7)]
    with open(path, "w", encoding="utf-8") as f:
        f.write("Employee ID,Name,Department,Date,Day,Status,Punch In,Punch Out,"
                "Hours Worked,Late By (min),Late?,Left Early By (min),Overtime (min)\n")
        day = 0
        while day * 40 < rows:
            date = f"2026-03-{(day % 28) + 2:02d}"
            for who in names:
                status = rng.choices(["Present", "Absent", "Leave"], [90, 6, 4])[0]
                if status == "Present":
                    late = rng.choice([0, 0, 0, 12, 35, 43])
                    f.write(f"{who},{date},Mon,{status},09:{rng.randint(5, 59):02d},"
                            f"18:{rng.randint(10, 59):02d},9:01,{late},"
                            f"{'Yes' if late else 'No'},{rng.randint(0, 19)},0\n")
                else:
                    f.write(f"{who},{date},Mon,{status},,,,,,,\n")
            day += 1
    return path


class ASpreadsheetBecomesAProfile(unittest.TestCase):

    def setUp(self):
        self.path = _attendance_csv(rows=5200)
        self.att = F.attach(self.path)

    def test_the_profile_counts_exactly(self):
        profile = self.att["profile"]
        self.assertTrue(profile.startswith("5,200 rows x 13 columns"))
        self.assertIn("Columns: Employee ID, Name, Department, Date", profile)
        self.assertIn("Status: Present", profile)         # distinct values, counted
        self.assertIn("Department: ", profile)
        self.assertIn("First 6 rows, as written:", profile)
        self.assertLess(len(profile), 3600)

    def test_a_big_sheet_is_never_pasted_raw(self):
        for uploaded in (True, False):
            block = F.context_block([self.att], uploaded=uploaded)
            self.assertIn("[spreadsheet:", block)
            self.assertIn("5,200 rows", block)
            self.assertNotIn("[content truncated]", block)
            # At most the sample rows — not a wall of them.
            self.assertLess(block.count("EMP0"), 20, block[:400])
            self.assertLess(len(block), 5000)

    def test_it_says_where_the_rows_are(self):
        self.assertIn("read the rows there", F.context_block([self.att], uploaded=True))
        self.assertIn("only this profile is given",
                      F.context_block([self.att], uploaded=False))


class ASmallSheetStillGoesInWhole(unittest.TestCase):

    def test_forty_rows_or_fewer_are_pasted_as_they_are(self):
        path = _attendance_csv(rows=40)
        att = F.attach(path)
        block = F.context_block([att], uploaded=False)
        self.assertNotIn("[spreadsheet:", block)
        self.assertEqual(block.count("EMP0"), 40)


class AnUploadedFileIsNotPastedTwice(unittest.TestCase):

    def setUp(self):
        d = tempfile.mkdtemp()
        self.path = os.path.join(d, "notes.txt")
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("line of notes\n" * 1500)          # ~21 KB
        self.att = F.attach(self.path)

    def test_uploaded_means_a_pointer_not_the_text(self):
        block = F.context_block([self.att], uploaded=True)
        self.assertIn("read it from the attachment", block)
        self.assertLess(block.count("line of notes"), 2)

    def test_not_uploaded_means_the_old_inline_with_its_cap(self):
        block = F.context_block([self.att], uploaded=False)
        self.assertIn("[content truncated]", block)
        self.assertGreater(block.count("line of notes"), 500)

    def test_a_short_file_is_pasted_either_way(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "brief.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("Three lines of brief.\n" * 3)
        att = F.attach(p)
        self.assertIn("Three lines of brief.", F.context_block([att], uploaded=True))


class ThePipelineBuildsTheBlockAfterTheUpload(unittest.TestCase):
    """A source check: the block used to be built once, before any stage,
    so it could not know whether the upload had happened."""

    def test_every_stage_gets_the_files_not_a_paragraph_about_them(self):
        """The rule that bit the owner twice in one day: attachments went
        only to the first stage, so whether the writer saw the CSV depended
        on whether the analysis stage before it happened to fail."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "prism_terminal", "core", "automation.py"),
                  encoding="utf-8") as f:
            source = f.read()
        self.assertIn("include_attachment = bool(attachments)\n", source)
        self.assertNotIn("stage_idx == 0 or not prior or producer", source)

    def test_context_block_is_asked_per_stage_with_the_upload_result(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "prism_terminal", "core", "automation.py"),
                  encoding="utf-8") as f:
            source = f.read()
        self.assertIn("F.context_block(attachments, uploaded=bool(went_up))", source)
        self.assertNotIn("attach_ctx = F.context_block(attachments)", source)


if __name__ == "__main__":
    unittest.main()
