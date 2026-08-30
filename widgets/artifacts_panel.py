"""Artifacts — every generated file Prism has copied out to a place you can
still find it once the app that made it is closed.

Reel renders, and any pipeline stage that produces a real image, document,
deck or code file, save a copy into config.ARTIFACTS_DIR (see that module) —
named after the prompt that made them, not a run id. When a caller passes
`task=`, everything that one New Task (or BOQ/Gerber/quote job) produced
lands in its own subfolder there instead — one row here, opened in
Finder/Explorer rather than browsed inline. Before this screen, that folder
only existed on disk: the one way to know it was there was to be told, or to
stumble on it in Finder/Explorer. This is Prism saying so.

Read straight off the folder each time the screen is shown — it is plain
files on disk, and the user's own Finder/Explorer can add to or remove from
it between visits just as freely as Prism can. Same LAZY-plus-explicit-
refresh contract History uses: MainWindow._show_screen() calls refresh() on
arrival rather than this class reloading itself, so it stays a passive report
like every other screen here.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QLabel

import core_bridge as CB
import i18n
import theme
from widgets import controls as C
from widgets.files_panel import kind_label, size_label
from widgets.simple_panels import _Page, _bucket

# Extension -> the same "kind" vocabulary core.files.attach() uses, so
# kind_label() (built for attachment chips) reads correctly here too without
# running every file in the folder through the heavier attach() pipeline just
# to list them.
_KINDS = {
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image",
    ".webp": "image",
    ".mp4": "video", ".mov": "video", ".webm": "video",
    ".pdf": "pdf",
    ".doc": "doc", ".docx": "doc", ".odt": "doc",
    ".xls": "sheet", ".xlsx": "sheet", ".csv": "sheet", ".ods": "sheet",
    ".ppt": "presentation", ".pptx": "presentation", ".odp": "presentation",
    ".py": "code", ".js": "code", ".ts": "code", ".tsx": "code",
    ".jsx": "code", ".json": "code", ".html": "code", ".css": "code",
    ".txt": "text", ".md": "text",
}
# kind_label()'s own vocabulary is narrower than the table above (it has no
# "presentation" word yet) — fall back to "file" rather than an untranslated
# label reaching the screen.
_ICON_FOR_KIND = {"image": "image", "video": "video", "code": "code"}

_THUMB = 30   # matches IconPad's own default size — drop-in for the same slot


def _thumbnail(path: str):
    """A real rounded-corner crop of the image itself, for the row's leading
    slot — a generic file glyph can't tell two pictures apart, and in a
    folder that's mostly pictures, telling them apart at a glance is most of
    what looking at the list is for. Returns None (falls back to the usual
    glyph) for anything that isn't a real, decodable image."""
    src = QPixmap(path)
    if src.isNull():
        return None
    src = src.scaled(_THUMB, _THUMB, Qt.KeepAspectRatioByExpanding,
                     Qt.SmoothTransformation)
    x = max(0, (src.width() - _THUMB) // 2)
    y = max(0, (src.height() - _THUMB) // 2)
    src = src.copy(x, y, _THUMB, _THUMB)
    out = QPixmap(_THUMB, _THUMB)
    out.fill(Qt.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.Antialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(0, 0, _THUMB, _THUMB, theme.R_CONTROL, theme.R_CONTROL)
    painter.setClipPath(clip)
    painter.drawPixmap(0, 0, src)
    painter.end()
    label = QLabel()
    label.setFixedSize(_THUMB, _THUMB)
    label.setPixmap(out)
    return label


def _folder_stats(path: str) -> tuple[int, str]:
    """File count and total size of everything under a task subfolder —
    config.artifact_task_dir()'s folders can themselves hold nested folders
    (Gerber's cleaned-copy output keeps its own "previews/" subfolder), so
    this walks rather than assuming one flat level."""
    count, total = 0, 0.0
    for root, _dirs, names in os.walk(path):
        for name in names:
            if name.endswith(".link.txt"):
                continue
            count += 1
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    size = ""
    for unit in ("B", "KB", "MB", "GB"):
        if total < 1024 or unit == "GB":
            size = f"{total:.0f} {unit}" if unit == "B" else f"{total:.1f} {unit}"
            break
        total /= 1024.0
    return count, size


def _chat_link(path: str) -> str:
    """The AI conversation this artifact came from, if save_artifact() had
    one to record — see config.save_artifact's `link` param. Empty for a
    local render (Reel, Motion) that was never a chat to begin with."""
    sidecar = path + ".link.txt"
    if not os.path.isfile(sidecar):
        return ""
    try:
        with open(sidecar, "r", encoding="utf-8") as f:
            return f.readline().strip()
    except OSError:
        return ""


class ArtifactsPanel(_Page):
    TITLE = "Artifacts"
    BLURB = ("Everything Prism has generated for you — reels, images, "
             "documents — kept here even after you close it.")
    LAZY = True

    def header_actions(self) -> list:
        return [C.button(i18n.t("Open the folder"), "secondary",
                         icon_name="folder", small=True,
                         on_click=self._open_folder)]

    def _open_folder(self):
        os.makedirs(CB.config.ARTIFACTS_DIR, exist_ok=True)
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(CB.config.ARTIFACTS_DIR))

    def build(self):
        folder = CB.config.ARTIFACTS_DIR
        paths = []
        if os.path.isdir(folder):
            for name in os.listdir(folder):
                # A ".link.txt" is the sidecar save_artifact() writes next to
                # the file it belongs to (see config.save_artifact) — the
                # chat's URL, not a deliverable of its own, so it rides along
                # on its artifact's row (_row, below) instead of getting one.
                if name.endswith(".link.txt"):
                    continue
                path = os.path.join(folder, name)
                # A directory is one New Task's (or one BOQ/Gerber/quote
                # job's) own subfolder — config.artifact_task_dir() groups
                # everything one run produced there instead of scattering it
                # loose. It gets one row in this same newest-first list,
                # same as a single file would; opening it hands browsing its
                # contents to Finder/Explorer rather than Prism reimplementing
                # a folder tree inline.
                if os.path.isfile(path) or os.path.isdir(path):
                    paths.append(path)
        if not paths:
            self._col.addWidget(C.EmptyState(
                "file", i18n.t("Nothing generated yet"),
                i18n.t("Run Reel/Studio, or any task that produces an "
                       "image, document or code file, and it lands here — "
                       "named after what you asked for.")), stretch=1)
            return
        # Newest first: the thing you just generated is the thing you came
        # here to check. Grouped by day, with the same bucket labels History
        # already uses — a flat mtime-sorted dump was the actual complaint,
        # and this is the app's own established pattern for a date-ordered
        # list, not a second, divergent one invented just for this screen.
        paths.sort(key=os.path.getmtime, reverse=True)
        groups: list[tuple[str, list]] = []
        for path in paths:
            bucket = _bucket("", os.path.getmtime(path))
            if not groups or groups[-1][0] != bucket:
                groups.append((bucket, []))
            groups[-1][1].append(path)

        for bucket, items in groups:
            self._col.addWidget(C.SectionHeader(
                i18n.t(bucket),
                i18n.t("1 file") if len(items) == 1
                else i18n.t("{n} files").format(n=len(items))))
            for path in items:
                self._col.addWidget(self._row(path))
        self._col.addStretch(1)

    def _row(self, path: str) -> C.FileItem:
        if os.path.isdir(path):
            return self._folder_row(path)
        name = os.path.basename(path)
        ext = os.path.splitext(name)[1].lower()
        kind = _KINDS.get(ext, "")
        # `name` too, not just `kind` — kind_label() falls back to the
        # extension for a kind it has no word for yet (e.g. "presentation"),
        # and that fallback reads the name/path itself, not the kind we
        # already tried to derive from it.
        detail = " · ".join(p for p in (kind_label({"kind": kind, "name": name}),
                                        size_label(path)) if p)
        actions = [C.icon_button(
            "external", i18n.t("Open"),
            lambda _=False, p=path: self._open_file(p))]
        link = _chat_link(path)
        if link:
            actions.append(C.icon_button(
                "globe", i18n.t("Open the chat that made this"),
                lambda _=False, u=link: self._open_link(u)))
        leading = _thumbnail(path) if kind == "image" else None
        row = C.FileItem(name, detail, _ICON_FOR_KIND.get(kind, "file"),
                         actions, leading=leading)
        row.setToolTip(path)
        row.activated.connect(lambda p=path: self._open_file(p))
        return row

    def _folder_row(self, path: str) -> C.FileItem:
        name = os.path.basename(path)
        count, size = _folder_stats(path)
        files_word = (i18n.t("1 file") if count == 1
                     else i18n.t("{n} files").format(n=count))
        detail = " · ".join(p for p in (files_word, size) if p)
        actions = [C.icon_button(
            "external", i18n.t("Open the folder"),
            lambda _=False, p=path: self._open_file(p))]
        row = C.FileItem(name, detail, "folder", actions)
        row.setToolTip(path)
        row.activated.connect(lambda p=path: self._open_file(p))
        return row

    @staticmethod
    def _open_file(path: str):
        # Qt's own cross-platform "open with the OS default app" — already
        # proven by _open_folder() above; opening one file used to reimplement
        # the same platform dispatch by hand with subprocess/os.startfile
        # instead of the mechanism already sitting right here.
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    @staticmethod
    def _open_link(url: str):
        QDesktopServices.openUrl(QUrl(url))
