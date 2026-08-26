"""The Email add-on, rebuilt as a letter: To, Subject, Message, Send.

The report that started this, in the owner's words: "if I want to send an
email to only one person I can't even see the input window where I should
put the mail". So the first thing these tests pin is geometry — the To
field is the first field on the window, visible, above Subject, above
Message — and the second is that the Send button says, in words, who it
will send to and refuses (with a reason) until it can.

Nothing here runs the event loop against a modal, and nothing touches the
real ~/Prism Email: every dialog is built with cfg["email"]["folder"] set
to a temp directory.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PRISM_LICENSE_OFFLINE_DEV", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Signal, QObject  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import sent_log  # noqa: E402
from dialogs import email_dialog as ED  # noqa: E402
from dialogs.email_dialog import EmailComposeDialog  # noqa: E402
from widgets.email_panel import EmailPanel, LIST_LABEL, ONE_LABEL  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _cfg(folder: str) -> dict:
    return {"email": {"address": "sales@shakti.one", "password": "x",
                      "host": "smtp.gmail.com", "port": 465, "folder": folder},
            "agents": {"content": "ChatGPT"}}


def _dialog(folder: str = "", attachments=None, mode="one") -> EmailComposeDialog:
    folder = folder or tempfile.mkdtemp(prefix="prism-email-")
    dlg = EmailComposeDialog(_cfg(folder), attachments or [], None, mode=mode)
    dlg.resize(820, 760)
    # show() lays the nested grid out; nothing modal is queued behind it.
    dlg.show()
    dlg.layout().activate()
    return dlg


def _csv(rows) -> str:
    d = tempfile.mkdtemp()
    p = os.path.join(d, "customers.csv")
    with open(p, "w", encoding="utf-8") as f:
        f.write("name,email\n")
        for name, email in rows:
            f.write(f"{name},{email}\n")
    return p


class TheToFieldIsTheFirstThingYouSee(unittest.TestCase):

    def setUp(self):
        self.dlg = _dialog()

    def test_to_subject_and_message_are_visible_in_that_order(self):
        d = self.dlg
        for w in (d.to_edit, d.subject_edit, d.body_edit, d.send_btn):
            self.assertTrue(w.isVisibleTo(d), w)
        self.assertLess(d.to_edit.y(), d.subject_edit.y())
        self.assertLess(d.subject_edit.y(), d.body_edit.y())

    def test_the_list_table_stays_out_of_the_way_until_there_is_a_list(self):
        self.assertFalse(self.dlg.list_box.isVisibleTo(self.dlg))

    def test_send_is_off_and_says_why_while_the_letter_is_empty(self):
        self.assertFalse(self.dlg.send_btn.isEnabled())
        tip = self.dlg.send_btn.toolTip()
        for need in ("address", "subject", "message"):
            self.assertIn(need, tip)

    def test_the_window_says_which_account_it_sends_from(self):
        self.assertIn("sales@shakti.one", self.dlg.header.subtitle.text())


class WritingToOnePerson(unittest.TestCase):

    def setUp(self):
        self.dlg = _dialog()

    def test_one_typed_address_is_one_recipient(self):
        self.dlg.to_edit.setText("Rajesh <rajesh@acme.in>")
        self.assertEqual([r["email"] for r in self.dlg.recipients], ["rajesh@acme.in"])
        self.assertIn("rajesh@acme.in", self.dlg.who_label.text())

    def test_send_names_the_person_once_the_letter_is_complete(self):
        d = self.dlg
        d.to_edit.setText("rajesh@acme.in")
        d.subject_edit.setText("Quotation for springs")
        d.body_edit.setPlainText("Dear {name}, please find our rates.")
        self.assertTrue(d.send_btn.isEnabled())
        self.assertEqual(d.send_btn.text(), "Send to rajesh@acme.in")

    def test_several_typed_addresses_are_counted(self):
        d = self.dlg
        d.to_edit.setText("a@x.com, B@y.com; a@x.com c@z.com")
        self.assertEqual(len(d.recipients), 3)
        d.subject_edit.setText("s")
        d.body_edit.setPlainText("b")
        self.assertEqual(d.send_btn.text(), "Send to 3 people")


class SendingToAList(unittest.TestCase):

    def setUp(self):
        self.dlg = _dialog()
        self.path = _csv([("Rajesh", "rajesh@acme.in"), ("Priya", "priya@xyz.com"),
                          ("", "info@abc.co.in")])

    def test_a_csv_fills_the_visible_table_with_names(self):
        d = self.dlg
        d._load_list(self.path)
        self.assertTrue(d.list_box.isVisibleTo(d))
        self.assertEqual(d.list_table.rowCount(), 3)
        self.assertEqual(d.list_table.item(0, 0).text(), "Rajesh")
        self.assertEqual(d.list_table.item(0, 1).text(), "rajesh@acme.in")
        self.assertIn("3 people", d.who_label.text())
        self.assertIn("customers.csv", d.who_label.text())

    def test_the_list_keeps_its_names_when_the_same_address_is_typed(self):
        d = self.dlg
        d._load_list(self.path)
        d.to_edit.setText("rajesh@acme.in, new@one.com")
        emails = [r["email"] for r in d.recipients]
        self.assertEqual(emails, ["rajesh@acme.in", "priya@xyz.com",
                                  "info@abc.co.in", "new@one.com"])
        self.assertEqual(d.recipients[0]["name"], "Rajesh")

    def test_a_row_can_be_removed_from_the_list(self):
        d = self.dlg
        d._load_list(self.path)
        d.list_table.selectRow(1)
        d._remove_selected()
        self.assertEqual(d.list_table.rowCount(), 2)
        self.assertNotIn("priya@xyz.com", [r["email"] for r in d.recipients])

    def test_a_csv_handed_over_by_the_workbench_is_the_list(self):
        att = {"name": "customers.csv", "path": self.path, "mime": "text/csv"}
        d = _dialog(attachments=[att])
        self.assertEqual(d.list_table.rowCount(), 3)
        self.assertEqual(d.source_files, [])


class _FakeSendWorker(QObject):
    """Emits done at once — a send that never touches a mail server."""
    progress = Signal(int, int, str, bool, str)
    done = Signal(list, list)
    failed = Signal(str)
    stopped = False

    def __init__(self, cfg, recipients, subject, body, files):
        super().__init__()
        self.recipients = recipients
        _FakeSendWorker.last = self

    def start(self):
        self.done.emit([r["email"] for r in self.recipients], [])

    def isRunning(self):
        return False


class EverySendIsWrittenDown(unittest.TestCase):

    def test_the_send_lands_in_the_folder_and_on_the_launcher(self):
        folder = tempfile.mkdtemp(prefix="prism-email-")
        d = _dialog(folder)
        d.to_edit.setText("rajesh@acme.in")
        d.subject_edit.setText("Quotation for springs")
        d.body_edit.setPlainText("Dear {name}, rates attached.")
        with mock.patch.object(ED, "SendWorker", _FakeSendWorker), \
                mock.patch.object(QMessageBox, "question",
                                  return_value=QMessageBox.Yes), \
                mock.patch.object(QMessageBox, "information"), \
                mock.patch.object(ED.CB.config, "save_run"):
            d._send()
        entries = sent_log.load(_cfg(folder))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["subject"], "Quotation for springs")
        self.assertEqual(entries[0]["sent"], ["rajesh@acme.in"])
        self.assertEqual(sent_log.describe_to(entries[0]), "rajesh@acme.in")
        self.assertEqual(sent_log.describe_result(entries[0]), "Sent")
        with open(os.path.join(folder, "sent.json"), encoding="utf-8") as f:
            self.assertEqual(len(json.load(f)), 1)

        panel = EmailPanel(_cfg(folder))
        self.assertIsNotNone(panel.sent_table)
        self.assertEqual(panel.sent_table.rowCount(), 1)
        self.assertEqual(panel.sent_table.item(0, 1).text(), "rajesh@acme.in")
        self.assertEqual(panel.sent_table.item(0, 3).text(), "Sent")


class TheLauncher(unittest.TestCase):

    def test_two_ways_to_start_and_each_opens_the_right_way(self):
        panel = EmailPanel(_cfg(tempfile.mkdtemp()))
        seen = []
        panel.open_compose.connect(seen.append)
        panel.one_btn.click()
        panel.list_btn.click()
        self.assertEqual(seen, ["one", "list"])
        self.assertEqual(panel.one_btn.text(), ONE_LABEL)
        self.assertEqual(panel.list_btn.text(), LIST_LABEL)

    def test_with_no_account_it_offers_setup_and_nothing_else(self):
        panel = EmailPanel({})
        seen = []
        panel.change_account.connect(lambda: seen.append("setup"))
        self.assertFalse(hasattr(panel, "one_btn"))
        door = panel.findChild(type(panel._col.itemAt(0).widget()))
        door.clicked.emit()
        self.assertEqual(seen, ["setup"])

    def test_the_header_still_offers_change_account_and_a_primary(self):
        panel = EmailPanel(_cfg(tempfile.mkdtemp()))
        labels = [a.text() for a in panel.header_actions()]
        self.assertIn("Change account", labels)
        self.assertIn("New email", labels)


class TheSentLog(unittest.TestCase):

    def test_newest_first_and_words_for_a_list(self):
        cfg = _cfg(tempfile.mkdtemp())
        to = [{"email": f"p{i}@x.com", "name": ""} for i in range(4)]
        sent_log.record(cfg, to=to[:1], subject="first", body="b",
                        sent=["p0@x.com"], failed=[], attachments=[])
        sent_log.record(cfg, to=to, subject="second", body="b",
                        sent=["p0@x.com", "p1@x.com"],
                        failed=[("p2@x.com", "bounced"), ("p3@x.com", "bounced")],
                        attachments=["brochure.pdf"], list_name="customers.csv")
        entries = sent_log.load(cfg)
        self.assertEqual([e["subject"] for e in entries], ["second", "first"])
        self.assertEqual(sent_log.describe_to(entries[0]), "4 people (customers.csv)")
        self.assertEqual(sent_log.describe_result(entries[0]), "2 sent, 2 failed")

    def test_a_missing_file_is_an_empty_list(self):
        self.assertEqual(sent_log.load(_cfg(tempfile.mkdtemp())), [])


if __name__ == "__main__":
    unittest.main()
