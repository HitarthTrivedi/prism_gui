"""Artifacts — every generated file Prism has copied out to a place you can
still find it once the app that made it is closed.

Reel renders, and any pipeline stage that produces a real image, document,
deck or code file, save a copy into config.ARTIFACTS_DIR (see that module) —
named after the prompt that made them, not a run id. Before this screen, that
folder only existed on disk: the one way to know it was there was to be told,
or to stumble on it in Finder/Explorer. This is Prism saying so.

Read straight off the folder each time the screen is shown — it is plain
files on disk, and the user's own Finder/Explorer can add to or remove from
it between visits just as freely as Prism can. Same LAZY-plus-explicit-
refresh contract History uses: MainWindow._show_screen() calls refresh() on
arrival rather than this class reloading itself, so it stays a passive report
like every other screen here.
"""
from __future__ import annotations

import os
import subprocess
import sys

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

import core_bridge as CB
import i18n
from widgets import controls as C
from widgets.files_panel import kind_label, size_label
from widgets.simple_panels import _Page

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
                path = os.path.join(folder, name)
                if os.path.isfile(path):
                    paths.append(path)
        if not paths:
            self._col.addWidget(C.EmptyState(
                "file", i18n.t("Nothing generated yet"),
                i18n.t("Run Reel/Studio, or any task that produces an "
                       "image, document or code file, and it lands here — "
                       "named after what you asked for.")), stretch=1)
            return
        # Newest first: the thing you just generated is the thing you came
        # here to check.
        paths.sort(key=os.path.getmtime, reverse=True)
        for path in paths:
            self._col.addWidget(self._row(path))
        self._col.addStretch(1)

    def _row(self, path: str) -> C.FileItem:
        name = os.path.basename(path)
        ext = os.path.splitext(name)[1].lower()
        kind = _KINDS.get(ext, "")
        # `name` too, not just `kind` — kind_label() falls back to the
        # extension for a kind it has no word for yet (e.g. "presentation"),
        # and that fallback reads the name/path itself, not the kind we
        # already tried to derive from it.
        detail = " · ".join(p for p in (kind_label({"kind": kind, "name": name}),
                                        size_label(path)) if p)
        open_btn = C.icon_button(
            "external", i18n.t("Open"),
            lambda _=False, p=path: self._open_file(p))
        row = C.FileItem(name, detail, _ICON_FOR_KIND.get(kind, "file"),
                         [open_btn])
        row.setToolTip(path)
        row.activated.connect(lambda p=path: self._open_file(p))
        return row

    @staticmethod
    def _open_file(path: str):
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif os.name == "nt":
            os.startfile(path)  # noqa: F821
        else:
            subprocess.Popen(["xdg-open", path])
