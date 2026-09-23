"""
Leads & Outreach — Import ▾ (Apollo's "Import a CSV")
─────────────────────────────────────────────────────
In Apollo, bringing a sheet in is its own action at the top of the page —
People > Import > CSV — and it is a MAPPING step, not a guess: "map your CSV
column headers to the corresponding Apollo field… When possible, Apollo
automatically detects and maps fields for you." Then a few settings, then
Import. Nothing is searched: the import becomes a filter value ("Contact CSV
import" / "Account CSV import") the owner applies when he wants to.

This modal is those steps, for one kind at a time:

  1  Choose a file   — CSV or Excel; a workbook with several tabs picks one.
  2  Map columns     — every column to a field (prospector.importing guesses,
                       Apollo's own export headers included), "Keep as a
                       custom field" or "Do not import".
  3  Settings        — contacts: what to do when one already exists (Apollo's
                       "Update the existing record"), add them to a list, find
                       e-mails for the ones without; accounts: a summary.

The dialog only COLLECTS: `result()` hands the parsed people (or companies)
and the settings back, and the workbench writes the stores (contacts.py,
imports.py) — so this stays a plain modal a test can drive without a disk.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

import i18n
import theme
from dialogs.base import PrismDialog
from widgets import controls as C
from prospector import importing as IMP

KINDS = ("contacts", "accounts")
_TITLE = {"contacts": "Import contacts", "accounts": "Import accounts"}
_STEPS = 3
# What makes a row importable — Apollo's rule, as Prism reads it (importing.py).
_NEEDS = {
    "contacts": ({"name", "first_name", "last_name", "email", "linkedin"},
                 "Map at least one column to a name, Email or LinkedIn URL — "
                 "that is what tells people apart."),
    "accounts": ({"name", "website"},
                 "Map at least one column to Account name or Account website."),
}
_EXAMPLES = 3                   # sample values shown per column


def _subtitle(step: int) -> str:
    """"Step 2 of 3 · Map columns" — i18n'd once for each of the three steps,
    so the catalogue holds real sentences."""
    return {
        0: i18n.t("Step 1 of 3 · Choose a file"),
        1: i18n.t("Step 2 of 3 · Map columns"),
        2: i18n.t("Step 3 of 3 · Settings"),
    }[step]


def _example(rows, index: int) -> str:
    """The first few non-empty values of one column, for the mapping table."""
    seen = []
    for row in rows or ():
        value = row[index] if index < len(row) else None
        text = " ".join(str(value).split()) if value is not None else ""
        if text and text not in seen:
            seen.append(text)
            if len(seen) >= _EXAMPLES:
                break
    return " · ".join(seen)


class ImportWizard(PrismDialog):
    """One import, three steps. `choose_file` is the file picker — a test
    replaces it; the real one is QFileDialog."""

    def __init__(self, kind: str, start_dir: str = "", parent=None):
        if kind not in KINDS:
            raise ValueError(f"unknown import kind {kind!r}")
        super().__init__(i18n.t(_TITLE[kind]), _subtitle(0), icon="file",
                         parent=parent)
        self.kind = kind
        self.start_dir = start_dir
        self.path = ""
        self.sheet = ""
        self.columns: list = []
        self.rows: list = []
        self._combos: list = []
        self._step = 0
        self._stack = QStackedWidget()
        self._stack.addWidget(self._file_page())
        self._stack.addWidget(self._map_page())
        self._stack.addWidget(self._settings_page())
        self.body.addWidget(self._stack, 1)

        self._back = self.button(i18n.t("Back"), on_click=self._go_back)
        self.footer.add_secondary(self._back)
        self.footer.add_secondary(self.button(i18n.t("Cancel"), on_click=self.reject))
        self._next = self.button(i18n.t("Next"), "primary", on_click=self._go_next)
        self.footer.set_primary(self._next)
        self.resize(760, 600)
        self._show(0)

    # ── what the caller gets ──────────────────────────────────────────────────
    def result(self) -> dict:
        """{"kind", "path", "name", "sheet", "mapping" ({header: field}),
        "settings", "rows", "skipped", and "leads" or "companies"} — read after
        exec() returns Accepted."""
        mapping = self.mapping()
        out = {"kind": self.kind, "path": self.path,
               "name": os.path.basename(self.path), "sheet": self.sheet,
               "mapping": {str(h) or f"Column {i + 1}": m
                           for i, (h, m) in enumerate(zip(self.columns, mapping))},
               "settings": self.settings(), "rows": len(self.rows)}
        if self.kind == "contacts":
            out["leads"], out["skipped"] = IMP.contacts_from_rows(
                self.columns, self.rows, mapping, self.sheet)
        else:
            out["companies"], out["skipped"] = IMP.accounts_from_rows(
                self.columns, self.rows, mapping)
        return out

    def mapping(self) -> list:
        return [combo.currentData() for combo in self._combos]

    def settings(self) -> dict:
        if self.kind == "accounts":
            return {}
        return {"update_existing": self._existing.currentData() == "update",
                "add_to_list": self._to_list.isChecked(),
                "list_name": self._list_name.text().strip(),
                "find_emails": self._find_emails.isChecked()}

    # ── step 1: the file ──────────────────────────────────────────────────────
    def _file_page(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_3)
        zone = QFrame()
        zone.setObjectName("importZone")
        zone.setAttribute(Qt.WA_StyledBackground, True)
        zone.setStyleSheet(
            f"QFrame#importZone{{background:{theme.WELL};border:1px dashed "
            f"{theme.NEUTRAL[300]};border-radius:{theme.R_CARD}px;}}")
        zl = QVBoxLayout(zone)
        zl.setContentsMargins(theme.SPACE_5, theme.SPACE_6, theme.SPACE_5, theme.SPACE_6)
        zl.setSpacing(theme.SPACE_2)
        zl.addWidget(C.label(i18n.t("Select a CSV or Excel file"), level="CARD_TITLE"),
                     0, Qt.AlignHCenter)
        zl.addWidget(C.label(i18n.t(".csv, .xlsx or .xlsm · up to about 10,000 rows"),
                             level="META"), 0, Qt.AlignHCenter)
        self._pick = C.button(i18n.t("Select file…"), "secondary", icon_name="paperclip",
                              on_click=self._choose)
        zl.addWidget(self._pick, 0, Qt.AlignHCenter)
        col.addWidget(zone)
        self._file_line = QLabel("")
        self._file_line.setStyleSheet(theme.type_css("SUPPORT", theme.TEXT))
        self._file_line.setWordWrap(True)
        col.addWidget(self._file_line)
        tabs = QHBoxLayout()
        tabs.setContentsMargins(0, 0, 0, 0)
        self._tab_label = C.label(i18n.t("Sheet"), level="SUPPORT")
        self._tab = QComboBox()
        self._tab.currentIndexChanged.connect(self._on_tab)
        tabs.addWidget(self._tab_label)
        tabs.addWidget(self._tab, 1)
        col.addLayout(tabs)
        need = (i18n.t("Each row needs a name, an e-mail or a LinkedIn URL. Include "
                       "as many columns as you can — more data makes a person "
                       "easier to recognise.") if self.kind == "contacts" else
                i18n.t("Each row needs a company name or a website. Include both "
                       "if you can. Nothing is searched — the import becomes a "
                       "filter you apply in Find people when you want to."))
        col.addWidget(C.label(need, level="META", wrap=True))
        self._file_error = C.label("", level="META", colour=theme.ERR_INK, wrap=True)
        col.addWidget(self._file_error)
        col.addStretch(1)
        self._tab_label.hide()
        self._tab.hide()
        return page

    def choose_file(self) -> str:
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.t(_TITLE[self.kind]), self.start_dir,
            i18n.t("Sheets") + " (*.csv *.xlsx *.xlsm)")
        return path

    def _choose(self):
        path = self.choose_file()
        if path:
            self.load(path)

    def load(self, path: str, sheet: str = "") -> bool:
        """Read a file (and one of its tabs); False, with the reason on the
        page, when it can't be read or holds no rows."""
        self._file_error.setText("")
        try:
            tabs = IMP.tabs(path)
            name, header, rows = IMP.read_table(path, sheet)
        except Exception as e:                              # noqa: BLE001
            self.path, self.columns, self.rows = "", [], []
            self._file_line.setText("")
            self._file_error.setText(i18n.t("Couldn't read this file: {err}")
                                     .format(err=str(e) or e.__class__.__name__))
            self._sync_next()
            return False
        self.path, self.sheet, self.columns, self.rows = path, name, header, rows
        self._file_line.setText(i18n.t("{file} · {rows} rows · {cols} columns").format(
            file=os.path.basename(path), rows=len(rows), cols=len(header)))
        many = len(tabs) > 1
        self._tab.blockSignals(True)
        self._tab.clear()
        for tab, n in tabs:
            self._tab.addItem(f"{tab} ({n})", tab)
        self._tab.setCurrentIndex(max(0, self._tab.findData(name)))
        self._tab.blockSignals(False)
        self._tab_label.setVisible(many)
        self._tab.setVisible(many)
        self._fill_mapping()
        self._sync_next()
        return True

    def _on_tab(self, _index: int):
        if self.path:
            self.load(self.path, self._tab.currentData() or "")

    # ── step 2: the mapping ───────────────────────────────────────────────────
    def _map_page(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_2)
        self._matched = C.label("", level="SUPPORT", wrap=True)
        col.addWidget(self._matched)
        t = self._table = QTableWidget(0, 3)
        t.setObjectName("importMap")
        # Scoped, like the register's table: the app sheet paints every
        # QTableWidget item WHITE (it was written for the dark glass
        # surfaces), which on this white dialog is no text at all.
        t.setStyleSheet(
            f"QTableWidget#importMap{{background:{theme.CARD};border:1px solid "
            f"{theme.HAIRLINE};border-radius:{theme.R_CONTROL}px;"
            f"gridline-color:transparent;}}"
            f"QTableWidget#importMap::item{{color:{theme.TEXT};padding:0 10px;"
            f"border:none;border-bottom:1px solid {theme.HAIRLINE};}}"
            f"QTableWidget#importMap QHeaderView::section{{background:{theme.CARD};"
            f"color:{theme.NEUTRAL[600]};border:none;border-bottom:1px solid "
            f"{theme.HAIRLINE};padding:8px 10px;font-family:'{theme.FONT_HEADING}';"
            f"font-size:11px;font-weight:600;}}")
        t.verticalHeader().setDefaultSectionSize(40)
        t.setHorizontalHeaderLabels([i18n.t("Column in your file"), i18n.t("Example"),
                                     i18n.t("Import as")])
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        t.setSelectionMode(QTableWidget.NoSelection)
        t.setShowGrid(False)
        t.setWordWrap(False)
        t.setTextElideMode(Qt.ElideRight)
        head = t.horizontalHeader()
        head.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        head.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        head.setSectionResizeMode(1, QHeaderView.Stretch)
        head.setSectionResizeMode(2, QHeaderView.Fixed)
        t.setColumnWidth(2, 220)
        col.addWidget(t, 1)
        self._map_error = C.label("", level="META", colour=theme.ERR_INK, wrap=True)
        col.addWidget(self._map_error)
        return page

    def _fill_mapping(self):
        guess = IMP.guess_mapping(self.columns, self.kind)
        t = self._table
        t.setRowCount(len(self.columns))
        self._combos = []
        choices = [(k, i18n.t(label)) for k, label in IMP.FIELDS[self.kind]] + \
                  [(k, i18n.t(label)) for k, label in IMP.EXTRA_CHOICES]
        for i, name in enumerate(self.columns):
            t.setItem(i, 0, QTableWidgetItem(name or i18n.t("(no header)")))
            example = QTableWidgetItem(_example(self.rows, i))
            example.setForeground(theme.c(theme.NEUTRAL[600]))
            t.setItem(i, 1, example)
            combo = QComboBox()
            for key, label in choices:
                combo.addItem(label, key)
            combo.setCurrentIndex(max(0, combo.findData(guess[i])))
            combo.currentIndexChanged.connect(lambda _i: self._sync_next())
            t.setCellWidget(i, 2, combo)
            self._combos.append(combo)
        fields = {k for k in guess if k not in (IMP.CUSTOM, IMP.SKIP)}
        n = sum(1 for k in guess if k not in (IMP.CUSTOM, IMP.SKIP))
        self._matched.setText(i18n.t(
            "Prism matched {n} of {m} columns to fields automatically. Check "
            "each one — every column is imported as what you pick here; one "
            "Prism has no field for is kept as a custom field.").format(
                n=n, m=len(self.columns)) if fields else i18n.t(
            "Prism couldn't match any column to a field. Pick what each one is."))

    def _mapping_ok(self) -> bool:
        needed, message = _NEEDS[self.kind]
        ok = bool(needed & set(self.mapping()))
        text = "" if ok else i18n.t(message)
        # 22-Sep-2026: a company-research export (Company Name, Industry,
        # City — never a person) went in as people and nothing came of it.
        # Say which import it is instead of only what it lacks.
        if not ok and self.kind == "contacts" and \
                _NEEDS["accounts"][0] & set(IMP.guess_mapping(self.columns, "accounts")):
            text += " " + i18n.t("This file looks like a list of companies — cancel, "
                                 "then use Import ▾ › Accounts.")
        self._map_error.setText(text)
        return ok

    # ── step 3: settings ──────────────────────────────────────────────────────
    def _settings_page(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_3)
        self._summary = C.label("", level="BODY", wrap=True)
        col.addWidget(self._summary)
        self._existing = QComboBox()
        self._to_list = QCheckBox(i18n.t("Add them to a list"))
        self._list_name = QLineEdit()
        self._find_emails = QCheckBox(i18n.t(
            "Find e-mails for the ones that have none (uses verifier credits — "
            "Prism asks before it spends)"))
        if self.kind == "contacts":
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(C.label(i18n.t("If a contact is already in Prism"),
                                  level="SUPPORT"))
            self._existing.addItem(i18n.t("Update the existing record"), "update")
            self._existing.addItem(i18n.t("Keep the existing record as it is"), "keep")
            row.addWidget(self._existing, 1)
            col.addLayout(row)
            col.addWidget(self._to_list)
            self._list_name.setPlaceholderText(i18n.t("List name"))
            self._list_name.setEnabled(False)
            self._to_list.toggled.connect(self._list_name.setEnabled)
            col.addWidget(self._list_name)
            col.addWidget(self._find_emails)
        col.addStretch(1)
        return page

    def _fill_summary(self):
        data = self.result()
        name = os.path.basename(self.path)
        if self.kind == "contacts":
            n, what = len(data["leads"]), i18n.t("contacts")
            why = i18n.t("no name, e-mail or LinkedIn URL")
        else:
            n, what = len(data["companies"]), i18n.t("companies")
            why = i18n.t("no company name or website")
        text = i18n.t("Ready to import {n} {what} from {file}.").format(
            n=n, what=what, file=name)
        if data["skipped"]:
            text += " " + i18n.t("{k} rows will be skipped ({why}).").format(
                k=data["skipped"], why=why)
        self._summary.setText(text)
        if not self._list_name.text().strip():
            self._list_name.setText(os.path.splitext(name)[0])

    # ── moving between steps ──────────────────────────────────────────────────
    def _show(self, step: int):
        self._step = step
        self._stack.setCurrentIndex(step)
        self.header.set_subtitle(_subtitle(step))
        self._back.setVisible(step > 0)
        self._next.setText(i18n.t("Import") if step == _STEPS - 1 else i18n.t("Next"))
        if step == 2:
            self._fill_summary()
        self._sync_next()

    def _sync_next(self):
        if self._step == 0:
            self._next.setEnabled(bool(self.path and self.columns))
        elif self._step == 1:
            self._next.setEnabled(self._mapping_ok())
        else:
            self._next.setEnabled(True)

    def _go_back(self):
        if self._step > 0:
            self._show(self._step - 1)

    def _go_next(self):
        if self._step < _STEPS - 1:
            self._show(self._step + 1)
        else:
            self.accept()
