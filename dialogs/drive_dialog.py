"""Pick a file out of Google Drive, the same way you'd pick one off the disk.

Three states, and the dialog decides which on open:

  not configured   this build has no OAuth client. Says so, and says what is
                   missing, instead of a click that fails.
  not connected    offers one button. Consent happens in the user's real
                   browser — Google requires that for a desktop app, and it is
                   also the only browser their company SSO will accept.
  connected        a plain folder list: double-click to descend, search to
                   look across the whole Drive, Attach to bring one down.

Everything that touches the network runs on a worker thread. Drive is a
round-trip to Google over whatever the office connection is, and freezing the
window for two seconds every time somebody opens a folder is the difference
between a feature that feels native and one that feels bolted on.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

import i18n
import theme
from dialogs.base import PrismDialog
from integrations import gdrive
from widgets import controls as C
from widgets import icons
from widgets.controls import heading, kicker, meta

_ITEM_ROLE = 1000
MY_DRIVE = "root"


class _Job(QThread):
    """One Drive call, off the GUI thread."""
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn, self._args, self._kwargs = fn, args, kwargs

    def run(self):
        try:
            self.done.emit(self._fn(*self._args, **self._kwargs))
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class DriveDialog(PrismDialog):
    """Returns the local path of the downloaded file in `self.path`."""

    def __init__(self, parent=None):
        super().__init__(
            i18n.t("Google Drive"),
            i18n.t("Pick a file and Prism downloads a copy to work from."),
            icon="globe", parent=parent, closable=False)
        self.setWindowTitle("Google Drive")
        self.resize(760, 580)
        self.setMinimumSize(560, 440)
        self.path = ""
        self._folder = MY_DRIVE
        self._trail: list[dict] = []
        # Held as attributes, not locals: a QThread garbage-collected while
        # its OS thread is still running aborts the process — the same bug
        # the wake-word listener had.
        self._job: _Job | None = None

        # Which Google account is being browsed — a header fact, not a footer
        # one, because it qualifies everything in the list below it.
        self.account = meta("")
        self.header.add_action(self.account)

        # `self.body` is the base class's body column; _clear_body() empties it
        # between the three states this dialog moves through.
        self.body.setSpacing(theme.SPACE_3)

        self.status = meta("")
        self.footer.add_note(self.status)
        self.footer.add_secondary(
            self.button(i18n.t("Cancel"), on_click=self.reject))
        self.attach_btn = self.button(i18n.t("Attach"), "primary",
                                      icon_name="paperclip",
                                      on_click=self._attach)
        self.attach_btn.setEnabled(False)
        self.footer.set_primary(self.attach_btn)

        self._build()

    # ── which of the three states are we in ───────────────────────────────
    def _clear_body(self):
        while self.body.count():
            item = self.body.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._drop_layout(item.layout())

    def _drop_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._drop_layout(item.layout())

    def _build(self):
        self._clear_body()
        ok, why = gdrive.configured()
        if not ok:
            self._show_message(i18n.t("Drive isn't switched on here"), why,
                               connect=False)
            return
        if not gdrive.connected():
            self._show_message(
                i18n.t("Attach straight from your Drive"),
                "Prism asks for read-only access — it can open the files you "
                "pick and nothing else. You sign in with your own account, so "
                "you'll see exactly the files your company already shares "
                "with you.",
                connect=True)
            return
        self._show_browser()

    def _show_message(self, title: str, text: str, *, connect: bool):
        """Two of this dialog's three states have no list to show, and both
        used to render as two grey paragraphs pinned to the top of a 560px
        window — 67% of it bare canvas.

        EmptyState centres itself in whatever height it is given, so the same
        two sentences now sit in the middle of the window with a glyph over
        them and, where there is one, the action underneath. Same words, same
        button, same signal; the difference is that it reads as a state rather
        than as a page that failed to load.
        """
        empty = C.EmptyState(
            "globe", title, text,
            i18n.t("Connect Google Drive") if connect else None)
        if connect:
            empty.clicked.connect(self._connect)
        self.body.addWidget(empty, stretch=1)

    def _show_browser(self):
        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search your Drive, or browse below…")
        self.search.returnPressed.connect(self._search)
        search_row.addWidget(self.search, stretch=1)
        find = QPushButton("Search")
        find.setCursor(Qt.PointingHandCursor)
        find.clicked.connect(self._search)
        search_row.addWidget(find)
        self.body.addLayout(search_row)

        self.crumbs = QLabel("My Drive")
        self.crumbs.setObjectName("meta")
        self.body.addWidget(self.crumbs)

        self.listing = QListWidget()
        self.listing.setFrameShape(QListWidget.NoFrame)
        self.listing.itemDoubleClicked.connect(self._open_item)
        self.listing.currentItemChanged.connect(self._selection_changed)
        self.body.addWidget(self.listing, stretch=1)

        self._run(gdrive.account_email, self._got_email, quiet=True)
        self._open_folder(MY_DRIVE)

    # ── work off the GUI thread ───────────────────────────────────────────
    def _run(self, fn, on_done, *args, quiet: bool = False, **kwargs):
        if self._job is not None and self._job.isRunning():
            return
        if not quiet:
            self.status.setText("Talking to Google Drive…")
        self._job = _Job(fn, *args, **kwargs)
        self._job.done.connect(on_done)
        self._job.done.connect(lambda _=None: self.status.setText(""))
        self._job.failed.connect(self._failed)
        self._job.start()

    def _failed(self, error: str):
        self.status.setText("")
        QMessageBox.warning(self, "Google Drive", error)

    def _got_email(self, email: str):
        if email:
            self.account.setText(email)

    # ── connecting ────────────────────────────────────────────────────────
    def _connect(self):
        self.status.setText("Waiting for you to approve it in your browser…")
        self._run(gdrive.connect, self._connected)

    def _connected(self, email: str):
        self.account.setText(email or "")
        self._build()

    # ── browsing ──────────────────────────────────────────────────────────
    def _open_folder(self, folder_id: str):
        self._folder = folder_id
        self.search.clear()
        self._run(gdrive.list_folder, self._fill, folder_id)
        if folder_id == MY_DRIVE:
            self.crumbs.setText("My Drive")
        else:
            self._run(gdrive.path_of, self._got_trail, folder_id, quiet=True)

    def _got_trail(self, trail: list):
        self.crumbs.setText("My Drive / " + " / ".join(t["name"] for t in trail))

    def _search(self):
        text = self.search.text().strip()
        if not text:
            self._open_folder(MY_DRIVE)
            return
        self.crumbs.setText(f"Search results for “{text}”")
        self._run(gdrive.list_folder, self._fill, MY_DRIVE, query=text)

    def _fill(self, items: list):
        self.listing.clear()
        self.attach_btn.setEnabled(False)
        # A way back out, unless we are already at the top or in a search.
        if self._folder != MY_DRIVE and not self.search.text().strip():
            up = QListWidgetItem(icons.icon("folder", 15, theme.NEUTRAL[600]),
                                 "..  (up one level)")
            up.setData(_ITEM_ROLE, {"mimeType": gdrive.FOLDER_MIME,
                                    "id": MY_DRIVE, "name": ".."})
            self.listing.addItem(up)
        if not items:
            empty = QListWidgetItem("Nothing here.")
            empty.setFlags(Qt.NoItemFlags)
            self.listing.addItem(empty)
            return
        for item in items:
            folder = gdrive.is_folder(item)
            size = gdrive.human_size(item)
            label = item.get("name", "(untitled)")
            if size and not folder:
                label += f"   {size}"
            row = QListWidgetItem(
                icons.icon("folder" if folder else "file", 15,
                           theme.ACCENT if folder else theme.NEUTRAL[600]),
                label)
            row.setData(_ITEM_ROLE, item)
            self.listing.addItem(row)

    def _selection_changed(self, item, _previous=None):
        payload = item.data(_ITEM_ROLE) if item else None
        self.attach_btn.setEnabled(bool(payload)
                                   and not gdrive.is_folder(payload))

    def _open_item(self, item: QListWidgetItem):
        payload = item.data(_ITEM_ROLE)
        if not payload:
            return
        if gdrive.is_folder(payload):
            self._open_folder(payload["id"])
        else:
            self._attach()

    # ── bringing it down ──────────────────────────────────────────────────
    def _attach(self):
        item = self.listing.currentItem()
        payload = item.data(_ITEM_ROLE) if item else None
        if not payload or gdrive.is_folder(payload):
            return
        self.attach_btn.setEnabled(False)
        self.status.setText(f"Downloading {payload.get('name', 'file')}…")
        self._run(gdrive.download, self._downloaded, payload)

    def _downloaded(self, path: str):
        self.path = path
        self.accept()

    # ── lifecycle ─────────────────────────────────────────────────────────
    def closeEvent(self, event):
        """Never let a running Drive call outlive the dialog: a QThread
        collected mid-flight takes the whole process with it."""
        if self._job is not None and self._job.isRunning():
            self._job.wait(3000)
        super().closeEvent(event)
