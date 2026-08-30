"""Open an Artifact inside Prism itself, not by handing it to the OS.

Artifacts used to open the same way every attachment chip in the app always
has — QDesktopServices.openUrl(), the system's own default app — see
widgets/files_panel.py's "Open" action and its docstring on why that is the
right call for an attachment a person is only checking. An Artifact is
different: it is the thing Prism itself made, in the window Prism itself
put it in, and the customer asked for it to stay that way rather than
bouncing out to whatever program the OS happens to have registered for a
.png today. `open_preview()` is the one entry point every row in
artifacts_panel.py calls instead.

Only a real remote URL — the "open the chat that made this" globe button —
keeps leaving the app; that one has nowhere to render TO inside Prism.

What actually renders in-app: images, plain-text/code, PDF, video and audio,
and a folder's own contents (as a list, not a raw OS file-manager window).
Everything else (.docx/.xlsx/.pptx and the rest of Office's formats, plus
archives) has no renderer here or anywhere else in the app, and building one
is its own project — those get an explicit "Open in the default app" button
instead of a silent, surprise hand-off, and it's built as a normal PrismDialog
button, not a fallback smuggled into what looks like a working preview.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPlainTextEdit, QSizePolicy, QSlider,
)

import i18n
import theme
from dialogs.base import PrismDialog
from widgets import controls as C

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
_VIDEO_EXTS = (".mp4", ".mov", ".webm", ".avi", ".mkv")
_AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac")
_TEXT_EXTS = (".txt", ".md", ".json", ".py", ".js", ".ts", ".tsx", ".jsx",
             ".html", ".css", ".java", ".c", ".cpp", ".h", ".go", ".rb",
             ".php", ".sh", ".sql", ".csv", ".ipynb", ".yaml", ".yml")


def _classify(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in _IMAGE_EXTS:
        return "image"
    if ext in _VIDEO_EXTS:
        return "video"
    if ext in _AUDIO_EXTS:
        return "audio"
    if ext == ".pdf":
        return "pdf"
    if ext in _TEXT_EXTS:
        return "text"
    return "other"


def open_preview(path: str, parent=None):
    """Show `path` inside Prism. A folder gets a navigable list of its own
    contents; a file gets the viewer matching its kind, or — for a kind
    nothing here can render — a small dialog offering to open it externally
    instead of doing that automatically.

    video/audio/pdf fall back the same way if their Qt module is missing.
    That is not hypothetical: packaging/prism.spec EXCLUDES QtMultimedia and
    QtPdf from the shipped build on purpose, to keep it off the customer's
    disk (they pull in an FFmpeg backend). A dev checkout has them; a real
    build of Prism does not, and must not crash a customer's click over it —
    it gets the same "open in the default app" a .docx already gets.
    """
    if os.path.isdir(path):
        FolderPreviewDialog(path, parent).exec()
        return
    kind = _classify(path)
    if kind == "other":
        UnsupportedPreviewDialog(path, parent).exec()
        return
    try:
        dlg = PreviewDialog(path, kind, parent)
    except ImportError:
        UnsupportedPreviewDialog(path, parent).exec()
        return
    dlg.exec()


# The dialog-header glyph registry (widgets/icons.py) only has "image",
# "video", "code" and "file" — not one for every kind this dialog renders.
_HEADER_ICON = {"image": "image", "video": "video", "audio": "video",
               "pdf": "file", "text": "code"}


class PreviewDialog(PrismDialog):
    """One file, rendered in-app. `kind` picks the body; the chrome (title,
    close, an explicit escape hatch to the OS app) is the same for all four."""

    def __init__(self, path: str, kind: str, parent=None):
        super().__init__(os.path.basename(path),
                         icon=_HEADER_ICON.get(kind, "file"), parent=parent,
                         scrollable=(kind == "text"))
        self.path = path
        self._player = None   # keeps QMediaPlayer/QAudioOutput alive
        self.resize(860, 640)
        self.setMinimumSize(480, 360)

        body = {
            "image": self._build_image,
            "video": self._build_video,
            "audio": self._build_audio,
            "pdf": self._build_pdf,
            "text": self._build_text,
        }[kind]
        body()

        self.footer.add_utility(self.button(
            i18n.t("Open in default app"), on_click=self._open_externally))
        self.footer.set_primary(self.button(
            i18n.t("Close"), "primary", on_click=self.accept))

    def _open_externally(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.path))

    # -- image --------------------------------------------------------------
    def _build_image(self):
        pix = QPixmap(self.path)
        label = QLabel()
        label.setAlignment(Qt.AlignCenter)
        if pix.isNull():
            label.setText(i18n.t("This image could not be read."))
        else:
            label.setPixmap(pix.scaled(
                800, 560, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.body.addWidget(label, stretch=1)

    # -- text/code ------------------------------------------------------------
    def _build_text(self):
        edit = QPlainTextEdit()
        edit.setReadOnly(True)
        edit.setStyleSheet(theme.type_css("MONO", theme.TEXT))
        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                edit.setPlainText(f.read())
        except OSError as e:
            edit.setPlainText(f"({e})")
        self.body.addWidget(edit, stretch=1)

    # -- pdf ------------------------------------------------------------------
    def _build_pdf(self):
        from PySide6.QtPdf import QPdfDocument
        from PySide6.QtPdfWidgets import QPdfView
        self._pdf_doc = QPdfDocument(self)
        self._pdf_doc.load(self.path)
        view = QPdfView()
        view.setDocument(self._pdf_doc)
        view.setPageMode(QPdfView.PageMode.MultiPage)
        view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self.body.addWidget(view, stretch=1)

    # -- video ------------------------------------------------------------------
    def _build_video(self):
        from PySide6.QtMultimediaWidgets import QVideoWidget
        video = QVideoWidget()
        video.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.body.addWidget(video, stretch=1)
        self._wire_player(video)

    # -- audio ------------------------------------------------------------------
    def _build_audio(self):
        label = QLabel(os.path.basename(self.path))
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        self.body.addWidget(label, stretch=1)
        self._wire_player(None)

    def _wire_player(self, video_widget):
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        player = QMediaPlayer(self)
        audio = QAudioOutput(self)
        player.setAudioOutput(audio)
        if video_widget is not None:
            player.setVideoOutput(video_widget)
        player.setSource(QUrl.fromLocalFile(self.path))
        self._player = (player, audio)   # kept alive for the dialog's life

        self.body.addLayout(self._transport_row(player))
        player.play()

    def _transport_row(self, player):
        row = QHBoxLayout()
        play_btn = self.button(i18n.t("Pause"), on_click=lambda: (
            player.pause() if player.isPlaying() else player.play()))

        def _sync(_state=None):
            play_btn.setText(i18n.t("Pause") if player.isPlaying()
                             else i18n.t("Play"))
        player.playbackStateChanged.connect(_sync)
        row.addWidget(play_btn)

        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 0)

        def _duration(ms):
            slider.setRange(0, ms)
        def _position(ms):
            if not slider.isSliderDown():
                slider.setValue(ms)
        player.durationChanged.connect(_duration)
        player.positionChanged.connect(_position)
        slider.sliderMoved.connect(player.setPosition)
        row.addWidget(slider, stretch=1)
        return row

    def reject(self):
        self._stop_playback()
        super().reject()

    def accept(self):
        self._stop_playback()
        super().accept()

    def _stop_playback(self):
        if self._player is not None:
            self._player[0].stop()


class UnsupportedPreviewDialog(PrismDialog):
    """A file kind nothing in Prism can render — Office documents, archives.
    Says so plainly rather than silently doing what the row used to do."""

    def __init__(self, path: str, parent=None):
        super().__init__(os.path.basename(path),
                         i18n.t("Prism can't show this file type inline yet."),
                         icon="file", parent=parent)
        self.path = path
        self.resize(440, 200)
        self.body.addWidget(QLabel(
            i18n.t("It will open in whatever app your computer already "
                   "uses for this kind of file.")))
        self.footer.add_secondary(self.button(
            i18n.t("Close"), on_click=self.reject))
        self.footer.set_primary(self.button(
            i18n.t("Open in default app"), "primary",
            on_click=self._open_externally))

    def _open_externally(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.path))
        self.accept()


class FolderPreviewDialog(PrismDialog):
    """A task subfolder's contents, as a Prism list — same FileItem rows the
    Artifacts screen itself uses — rather than handing the whole folder to
    the OS file manager. Clicking a row opens that file/folder the same way,
    recursively, so a nested folder (Gerber's cleaned-copy output keeps its
    own previews/ subfolder) is just another row rather than a dead end."""

    def __init__(self, path: str, parent=None):
        super().__init__(os.path.basename(path), icon="folder",
                         parent=parent, scrollable=True)
        self.path = path
        self.resize(560, 640)
        self.setMinimumSize(420, 360)

        entries = sorted(
            (os.path.join(path, name) for name in os.listdir(path)
             if not name.endswith(".link.txt")),
            key=lambda p: (os.path.isfile(p), os.path.basename(p).lower()))
        if not entries:
            self.body.addWidget(C.EmptyState(
                "folder", i18n.t("Empty"), i18n.t("Nothing in this folder.")),
                stretch=1)
        for entry in entries:
            self.body.addWidget(self._row(entry))
        self.body.addStretch(1)

        self.footer.add_utility(self.button(
            i18n.t("Open the folder"), on_click=self._open_externally))
        self.footer.set_primary(self.button(
            i18n.t("Close"), "primary", on_click=self.accept))

    def _row(self, path: str) -> C.FileItem:
        from widgets.files_panel import kind_label, size_label
        name = os.path.basename(path)
        if os.path.isdir(path):
            n = sum(len(f) for _r, _d, f in os.walk(path))
            detail = (i18n.t("1 file") if n == 1
                     else i18n.t("{n} files").format(n=n))
            icon = "folder"
        else:
            classified = _classify(path)
            kind = classified if classified != "other" else ""
            detail = " · ".join(p for p in (
                kind_label({"kind": kind, "name": name}), size_label(path))
                if p)
            icon = {"image": "image", "video": "video", "audio": "video",
                   "text": "code"}.get(kind, "file")
        row = C.FileItem(name, detail, icon, [C.icon_button(
            "external", i18n.t("Open"),
            lambda _=False, p=path: open_preview(p, self))])
        row.setToolTip(path)
        row.activated.connect(lambda p=path: open_preview(p, self))
        return row

    def _open_externally(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.path))
