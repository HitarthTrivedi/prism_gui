"""A picture as an inquiry: the code printed under a product photo is read
on this machine and quoted like typed text.

The client's case (11 Sep 2026): a customer mails a crop of a brochure --
"SS Locker (8 Comp)  KJP 3" -- and nothing else. Pinned here:

  · core.ocr reads a real rendered picture with whichever backend the
    machine has (RapidOCR in a build; the OS reader from source on a Mac)
    and answers lines top to bottom;
  · a mailbox check OCRs the pictures it files, keeps the text beside them
    in image_text.txt, and fills "Product asked" from it when the mail
    itself said nothing;
  · the code finder reads that file, so "KJP3" in a picture matches the
    catalogue row "KJP 3";
  · the quotation window says what it read from the picture;
  · the Files step of setup says in plain words what each of the three
    files is, and the cost sheet is folded away.

The OCR call in the check test is a fake (no models needed to prove the
plumbing); the one real read is its own test and skips when no backend is
present.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PRISM_LICENSE_OFFLINE_DEV", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication  # noqa: E402

import core_bridge as CB  # noqa: E402
from core import inbox, mailflow, ocr, register  # noqa: E402
from addons.inquiry import autoquote  # noqa: E402
from addons.inquiry import dialog as UI  # noqa: E402
from addons.inquiry.setup import InquirySetupDialog  # noqa: E402
from test_inquiry_ui import _NoSave, ready_cfg  # noqa: E402

_app = QApplication.instance() or QApplication([])
quoting = CB.get_quoting()


def _picture(folder: str, text: str = "SS Locker (8 Comp)   KJP 3") -> str:
    """A rendered label, big and black on white, the way a brochure crop is."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (900, 220), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 64)
    except Exception:                                   # noqa: BLE001
        font = ImageFont.load_default()
    draw.text((30, 70), text, fill="black", font=font)
    path = os.path.join(folder, "catalogue-crop.png")
    img.save(path)
    return path


def _mail_with_picture(folder: str, body: str = ""):
    from email.message import EmailMessage
    path = _picture(folder)
    msg = EmailMessage()
    msg["Subject"] = "Enquiry"
    msg["From"] = "Mr Patel <purchase@shaktiauto.in>"
    msg["To"] = "sales@acme.co.in"
    msg["Date"] = "Mon, 10 Aug 2026 09:14:00 +0530"
    msg["Message-ID"] = "<pic-1@x>"
    msg.set_content(body)
    with open(path, "rb") as f:
        msg.add_attachment(f.read(), maintype="image", subtype="png",
                           filename="catalogue-crop.png")
    return inbox.parse_message(msg.as_bytes(), uid=7)


class ReadingAPicture(unittest.TestCase):

    def test_a_real_read_with_whatever_backend_is_here(self):
        ok, why = ocr.available()
        if not ok:
            self.skipTest(why)
        path = _picture(tempfile.mkdtemp())
        lines = ocr.read(path)
        joined = " ".join(t for t, _ in lines).upper()
        self.assertIn("LOCKER", joined)
        self.assertIn("KJP", joined)
        # Words on one printed line come back as one line, in reading order.
        self.assertEqual(len(lines), 1, lines)
        self.assertLess(joined.index("LOCKER"), joined.index("KJP"))

    def test_read_files_only_looks_at_pictures_and_names_them(self):
        d = tempfile.mkdtemp()
        pdf = os.path.join(d, "drawing.pdf")
        open(pdf, "wb").close()
        with mock.patch.object(ocr, "text_of", return_value="KJP 3"):
            text = ocr.read_files([pdf, os.path.join(d, "crop.png")])
        self.assertIn("[crop.png]", text)
        self.assertNotIn("drawing.pdf", text)

    def test_remember_and_recall(self):
        d = tempfile.mkdtemp()
        self.assertEqual(ocr.recall(d), "")
        ocr.remember(d, "[a.png]\nKJP 3")
        self.assertEqual(ocr.recall(d), "[a.png]\nKJP 3")
        self.assertEqual(ocr.remember(d, "   "), "")


class TheCheckReadsWhatItFiles(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.cfg = ready_cfg(self.folder)
        self.paths = mailflow.Paths(self.folder)

    def _check(self, body=""):
        msg = _mail_with_picture(self.folder, body)
        from core import triage

        def sorter(messages, *a, **k):
            return [triage.Verdict(category=triage.INQUIRY, source="rule")
                    for _ in messages]
        with mock.patch.object(ocr, "text_of", return_value="SS Locker (8 Comp)\nKJP3"), \
                mock.patch.object(mailflow.inbox, "fetch_new",
                                  return_value=([msg], inbox.State(), "")), \
                mock.patch.object(mailflow.triage, "classify", side_effect=sorter):
            # The check's own fetch is patched at the point it reads mail;
            # everything after -- sorting, filing, OCR, the register -- runs.
            result = mailflow.check(self.cfg, self.paths, state=inbox.State(),
                                    local_only=True)
        return result

    def test_the_picture_text_lands_beside_the_picture_and_in_the_row(self):
        result = self._check()
        self.assertEqual(len(result.new_inquiries), 1, result.error)
        item = result.new_inquiries[0]
        kept = ocr.recall(item.folder)
        self.assertIn("KJP3", kept)
        self.assertIn("[catalogue-crop.png]", kept)
        row = register.load(self.paths.register_csv)[0]
        self.assertIn("KJP3", row["Product asked"])
        self.assertIn("read from the picture", row["Product asked"])

    def test_typed_words_are_not_overwritten_by_the_picture(self):
        result = self._check(body="Please quote 4 nos of the locker in the picture.")
        row = register.load(self.paths.register_csv)[0]
        self.assertNotIn("read from the picture", row["Product asked"])
        self.assertIn("KJP3", ocr.recall(result.new_inquiries[0].folder))


class ThePictureReachesTheQuote(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.cfg = ready_cfg(self.folder)
        rates = os.path.join(self.folder, "rates.csv")
        with open(rates, "w", encoding="utf-8") as f:
            f.write("Code,Description,Unit,Rate\nKJP 3,SS Locker 8 compartment,nos,18500\n")
        self.cfg["inquiry"]["rate_list"] = rates
        self.items = quoting.load_rates(rates)
        self.inquiry_folder = os.path.join(self.folder, "INQ-1")
        os.makedirs(self.inquiry_folder)
        ocr.remember(self.inquiry_folder, "[crop.png]\nSS Locker (8 Comp)\nKJP3")

    def _row(self, body):
        from test_inquiry_ui import message
        row = register.from_message(message(body=body))
        row["Folder"] = self.inquiry_folder
        row["Product asked"] = body or "SS Locker (8 Comp) KJP3 (read from the picture)"
        return row

    def test_the_code_in_the_picture_is_found_with_the_quantity_from_the_mail(self):
        row = self._row("4 nos of the locker in the picture please")
        plan = autoquote.plan(row, self.items)
        self.assertEqual([(r.item.code, r.quantity) for r in plan.requests],
                         [("KJP 3", quoting.to_decimal(4))])
        self.assertTrue(plan.ok, plan.reason)

    def test_a_picture_alone_is_held_for_a_quantity(self):
        plan = autoquote.plan(self._row(""), self.items)
        self.assertEqual(plan.requests[0].item.code, "KJP 3")
        self.assertFalse(plan.ok)
        self.assertIn("KJP 3", plan.reason)

    def test_the_quotation_window_shows_what_it_read(self):
        row = self._row("4 nos please")
        register.save([row], mailflow.Paths(self.folder).register_csv)
        with _NoSave():
            dialog = UI.InquiryDialog(self.cfg)
            dialog._refresh_register()
            q = UI.QuotationDialog(self.cfg, dialog._register_rows[0], self.items, dialog)
        self.assertTrue(q.picture_label.isVisibleTo(q))
        self.assertIn("KJP3", q.picture_label.text())
        self.assertEqual(q.item_picker.currentData().code, "KJP 3")
        self.assertEqual(q.quantity.text(), "4")


class TheFilesStepSpeaksPlainly(unittest.TestCase):

    def test_each_file_says_what_it_is_and_the_cost_sheet_is_folded(self):
        from PySide6.QtWidgets import QLabel
        with _NoSave():
            d = InquirySetupDialog(ready_cfg(tempfile.mkdtemp()))
        d.tabs.setCurrentIndex(1)                       # 2 · Files
        texts = " ".join(lbl.text() for lbl in d.findChildren(QLabel))
        self.assertIn("Price list (catalogue):", texts)
        self.assertIn("one row per product", texts)
        self.assertIn("Old inquiry sheet:", texts)
        self.assertIn("NOT your price list", texts)
        self.assertFalse(d.cost_file.isVisibleTo(d), "folded until asked for")
        d.cost_disclosure.button.setChecked(True)
        self.assertTrue(d.cost_file.isVisibleTo(d))
        self.assertEqual(d.cost_disclosure.button.text(),
                         "I don't have fixed prices — I work each price out")

    def test_a_saved_cost_sheet_keeps_its_fold_open(self):
        cfg = ready_cfg(tempfile.mkdtemp())
        cfg["inquiry"]["cost_sheet"] = "/x/costs.csv"
        with _NoSave():
            d = InquirySetupDialog(cfg)
        d.tabs.setCurrentIndex(1)
        self.assertTrue(d.cost_file.isVisibleTo(d))


if __name__ == "__main__":
    unittest.main()
