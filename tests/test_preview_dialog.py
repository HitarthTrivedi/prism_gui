"""Artifacts now open inside Prism instead of being handed to the OS — see
dialogs/preview_dialog.py. Covers the kind classifier, that each viewer
actually constructs without crashing (a real bug this way: an unknown-icon
KeyError segfaulted the process on first commit of this file, because the
dialog header glyph registry has no "pdf"/"audio"/"text" icon), and that
open_preview() dispatches to the right dialog for a file vs. a folder.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core_bridge  # noqa: F401,E402  (puts prism_terminal/core on sys.path)

from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

_app = QApplication.instance() or QApplication([])


class Classifying(unittest.TestCase):

    def test_kinds_are_recognised_case_insensitively(self):
        from dialogs.preview_dialog import _classify
        self.assertEqual(_classify("a.PNG"), "image")
        self.assertEqual(_classify("a.mp4"), "video")
        self.assertEqual(_classify("a.MP3"), "audio")
        self.assertEqual(_classify("a.pdf"), "pdf")
        self.assertEqual(_classify("a.py"), "text")

    def test_office_and_archive_formats_are_not_renderable(self):
        from dialogs.preview_dialog import _classify
        for ext in (".docx", ".pptx", ".xlsx", ".zip", ".doc"):
            self.assertEqual(_classify(f"a{ext}"), "other")


class EveryViewerActuallyConstructs(unittest.TestCase):
    """Every kind PreviewDialog claims to handle must build without raising —
    a header-icon KeyError here previously crashed the whole process (a Qt
    paint-device abort), not just raised a catchable Python exception."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmp.cleanup()

    def _file(self, name: str, data: bytes) -> str:
        path = os.path.join(self._tmp.name, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def test_image(self):
        from dialogs.preview_dialog import PreviewDialog
        path = self._file("a.png", b"not a real png")
        dlg = PreviewDialog(path, "image")
        dlg.reject()

    def test_text(self):
        from dialogs.preview_dialog import PreviewDialog
        path = self._file("a.py", b"print('hi')")
        dlg = PreviewDialog(path, "text")
        dlg.reject()

    def test_pdf(self):
        from dialogs.preview_dialog import PreviewDialog
        path = self._file("a.pdf", b"%PDF-1.4 not a real pdf")
        dlg = PreviewDialog(path, "pdf")
        dlg.reject()

    def test_video(self):
        from dialogs.preview_dialog import PreviewDialog
        path = self._file("a.mp4", b"not a real mp4")
        dlg = PreviewDialog(path, "video")
        dlg.reject()

    def test_audio(self):
        from dialogs.preview_dialog import PreviewDialog
        path = self._file("a.mp3", b"not a real mp3")
        dlg = PreviewDialog(path, "audio")
        dlg.reject()

    def test_unsupported_offers_the_default_app_instead_of_crashing(self):
        from dialogs.preview_dialog import UnsupportedPreviewDialog
        path = self._file("a.docx", b"not a real docx")
        dlg = UnsupportedPreviewDialog(path)
        dlg.reject()

    def test_folder_lists_a_row_per_entry_including_nested_subfolders(self):
        from dialogs.preview_dialog import FolderPreviewDialog
        os.makedirs(os.path.join(self._tmp.name, "sub"))
        self._file("keep.png", b"x")
        with open(os.path.join(self._tmp.name, "sub", "nested.txt"), "w") as f:
            f.write("x")
        dlg = FolderPreviewDialog(self._tmp.name)
        # One row per top-level entry (the file, the subfolder) plus the
        # trailing stretch — not zero, and not a crash on the mixed file+
        # dir listing.
        self.assertGreaterEqual(dlg.body.count(), 2)
        dlg.reject()

    def test_a_link_sidecar_does_not_get_its_own_row(self):
        from dialogs.preview_dialog import FolderPreviewDialog
        self._file("a.png", b"x")
        self._file("a.png.link.txt", b"https://chatgpt.com/c/abc")
        dlg = FolderPreviewDialog(self._tmp.name)
        # One row for a.png, not two.
        rows = [dlg.body.itemAt(i).widget() for i in range(dlg.body.count())
               if dlg.body.itemAt(i).widget() is not None]
        names = [getattr(w, "_name", None) for w in rows]
        self.assertEqual(names.count("a.png"), 1)
        dlg.reject()


class OpenPreviewDispatch(unittest.TestCase):
    """open_preview() picks the dialog and shows it — exec() is mocked so the
    test doesn't block on a real modal event loop."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_folder_opens_the_folder_dialog(self):
        from dialogs import preview_dialog as PD
        with mock.patch.object(PD.FolderPreviewDialog, "exec",
                               return_value=0) as m:
            PD.open_preview(self._tmp.name)
            m.assert_called_once()

    def test_a_renderable_file_opens_the_preview_dialog(self):
        from dialogs import preview_dialog as PD
        path = os.path.join(self._tmp.name, "a.png")
        with open(path, "wb") as f:
            f.write(b"x")
        with mock.patch.object(PD.PreviewDialog, "exec", return_value=0) as m:
            PD.open_preview(path)
            m.assert_called_once()

    def test_an_unrenderable_file_offers_the_default_app_instead(self):
        from dialogs import preview_dialog as PD
        path = os.path.join(self._tmp.name, "a.docx")
        with open(path, "wb") as f:
            f.write(b"x")
        with mock.patch.object(PD.UnsupportedPreviewDialog, "exec",
                               return_value=0) as m:
            PD.open_preview(path)
            m.assert_called_once()

    def test_a_missing_qtpdf_falls_back_gracefully_not_a_crash(self):
        """packaging/prism.spec deliberately excludes QtMultimedia/QtPdf from
        the shipped build (keeps FFmpeg off the customer's disk) — a real
        build must degrade to "open in default app" here, not crash on the
        customer's click. Simulated by making the dialog's own construction
        raise ImportError, the same exception a stripped build's import
        would actually throw."""
        from dialogs import preview_dialog as PD
        path = os.path.join(self._tmp.name, "a.pdf")
        with open(path, "wb") as f:
            f.write(b"x")
        with mock.patch.object(
                PD, "PreviewDialog",
                side_effect=ImportError("PySide6.QtPdf")), \
             mock.patch.object(PD.UnsupportedPreviewDialog, "exec",
                               return_value=0) as m:
            PD.open_preview(path)
            m.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
