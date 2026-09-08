"""Saving a copy of every send into the account's own Sent folder.

A plain SMTP send reaches the recipient but never writes to the sender's
mailbox, so Prism-sent mail used to be invisible in Outlook/webmail. The mailer
now IMAP-APPENDs each sent message to the account's Sent folder — best-effort,
so a mailbox that won't take the copy never breaks the actual send.

Nothing here reaches the network: the Sent-folder detection is a pure function,
and the two skip paths (a provider that auto-files, and the off switch) both
return before any IMAP connection is attempted. The append itself is exercised
against a fake connection so the mailbox-quoting is covered without a server.
"""
from __future__ import annotations

import os
import sys
import unittest
from email.message import EmailMessage

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402  (puts prism_terminal/core on sys.path)
from core import mailer  # noqa: E402


class FindingTheSentFolder(unittest.TestCase):
    """sent_folder_from_list() reads raw IMAP LIST output the way imaplib
    hands it back — a list of bytes lines — and names the Sent folder."""

    def test_the_special_use_flag_wins_over_any_name(self):
        lines = [
            b'(\\HasNoChildren) "/" "INBOX"',
            b'(\\HasNoChildren) "/" "Drafts"',
            b'(\\HasNoChildren \\Sent) "/" "Sent Items"',
        ]
        self.assertEqual(mailer.sent_folder_from_list(lines), "Sent Items")

    def test_gmails_nested_sent_mail_is_found_by_flag(self):
        lines = [
            b'(\\HasChildren \\Noselect) "/" "[Gmail]"',
            b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Sent Mail"',
        ]
        self.assertEqual(mailer.sent_folder_from_list(lines), "[Gmail]/Sent Mail")

    def test_a_cpanel_delimiter_and_prefix_are_handled(self):
        # Dovecot/cPanel: dotted names, no special-use flag → matched by name.
        lines = [
            b'(\\HasNoChildren) "." "INBOX"',
            b'(\\HasNoChildren) "." "INBOX.Sent"',
        ]
        self.assertEqual(mailer.sent_folder_from_list(lines), "INBOX.Sent")

    def test_the_well_known_name_is_the_fallback_without_a_flag(self):
        lines = [
            b'(\\HasNoChildren) "/" "INBOX"',
            b'(\\HasNoChildren) "/" "Sent"',
        ]
        self.assertEqual(mailer.sent_folder_from_list(lines), "Sent")

    def test_no_sent_folder_at_all_is_an_empty_string(self):
        lines = [b'(\\HasNoChildren) "/" "INBOX"',
                 b'(\\HasNoChildren) "/" "Archive"']
        self.assertEqual(mailer.sent_folder_from_list(lines), "")

    def test_string_lines_are_accepted_too(self):
        self.assertEqual(
            mailer.sent_folder_from_list(['(\\Sent) "/" "Sent"']), "Sent")


class WhenTheCopyIsSkippedEntirely(unittest.TestCase):
    """Two cases must not even open an IMAP connection."""

    def test_a_gmail_account_is_left_to_file_its_own_copy(self):
        # Gmail's SMTP already drops sent mail into Sent Mail — a second append
        # would duplicate it, so we skip and say so, without connecting.
        saver = mailer._SentSaver(
            {"email": {"address": "me@gmail.com", "password": "x"}})
        self.assertFalse(saver.active)
        self.assertIn("automatically", saver.note)
        self.assertIsNone(saver._conn)

    def test_the_off_switch_skips_before_any_connection(self):
        saver = mailer._SentSaver({"email": {
            "address": "me@alphakore.org", "password": "x",
            "save_to_sent": False}})
        self.assertFalse(saver.active)
        self.assertEqual(saver.note, "")        # not even a failed-to-reach note
        self.assertIsNone(saver._conn)

    def test_a_blank_account_is_a_no_op(self):
        saver = mailer._SentSaver({"email": {}})
        self.assertFalse(saver.active)
        self.assertIsNone(saver._conn)


class TheAppendItself(unittest.TestCase):
    """Exercised against a fake connection — no server, but the exact APPEND
    arguments are asserted, because a mailbox name with a space that isn't
    quoted is silently dropped by the server."""

    def _saver_with(self, folder, conn):
        # Bypass __init__ so no IMAP connection is ever attempted.
        s = mailer._SentSaver.__new__(mailer._SentSaver)
        s._conn, s._folder, s.active, s.note = conn, folder, True, ""
        return s

    def _message(self):
        m = EmailMessage()
        m["From"] = "me@alphakore.org"
        m["To"] = "chris@piperfire.com"
        m["Subject"] = "Hello Chris"
        m.set_content("A short body.")
        return m

    def test_a_folder_with_a_space_is_quoted(self):
        calls = []

        class Conn:
            def append(self, box, flags, when, payload):
                calls.append((box, flags, when, payload))
                return ("OK", [b"done"])

        saver = self._saver_with("Sent Items", Conn())
        saver.save(self._message())
        self.assertEqual(len(calls), 1)
        box, flags, _when, payload = calls[0]
        self.assertEqual(box, '"Sent Items"')          # quoted, or the server drops it
        self.assertEqual(flags, r"(\Seen)")            # filed as already-read
        self.assertIn(b"Hello Chris", payload)         # the real message went up

    def test_an_inactive_saver_never_touches_the_connection(self):
        class Boom:
            def append(self, *a, **k):
                raise AssertionError("must not append when inactive")

        s = mailer._SentSaver.__new__(mailer._SentSaver)
        s._conn, s._folder, s.active, s.note = Boom(), "Sent", False, ""
        s.save(self._message())                        # no exception, no call

    def test_a_server_that_rejects_the_append_does_not_raise(self):
        class Angry:
            def append(self, *a, **k):
                raise OSError("mailbox is full")

        saver = self._saver_with("Sent", Angry())
        saver.save(self._message())                    # swallowed — send survives


if __name__ == "__main__":
    unittest.main()
