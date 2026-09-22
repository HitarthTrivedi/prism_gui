"""
Leads & Outreach — the modal shell (compatibility)
──────────────────────────────────────────────────
The workbench lives full-window in the panel (addons/leads/panel.py). This thin
dialog wraps the same `LeadsWorkbench` so the manifest's `dialog=` reference
keeps resolving and any caller that still wants a modal gets one. The rail no
longer opens it — it shows the panel.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget, QListWidgetItem

import i18n
from dialogs.base import PrismDialog
from addons.leads.workbench import LeadsWorkbench


class CompanyPickDialog(PrismDialog):
    """"Check the companies where you want to find prospects. Then, click
    Find People." -- Apollo's own words for this exact step (Import a CSV
    of Accounts, knowledge.apollo.io, read 22-Sep-2026): importing a sheet
    of companies and searching with it are two separate, deliberate
    actions there, with a review in between -- Apollo's own Companies
    screen, ticked one by one, not every imported row going into a search
    unasked. Prism has no persistent Companies screen to put that tick-list
    on (Leads is a search tool, not an accounts CRM), so this dialog is the
    same choice in the one place it can live: right where a sheet's batch
    is about to become Find people's own filters. Every company starts
    ticked -- the common case is "search the ones I gave you" -- and
    unticking one here is exactly the same as removing its chip from the
    filter panel afterwards would have been, just before it is added
    rather than after."""

    def __init__(self, companies: list, parent=None):
        super().__init__(
            i18n.t("Choose which companies to search"),
            i18n.t("{n} companies from your sheet. Untick any you don't "
                   "want — the rest go into Find people's own filters as "
                   "soon as you press the button below; nothing is "
                   "searched until you press Find people itself."
                   ).format(n=len(companies)),
            icon="list", parent=parent)
        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.NoSelection)
        for name in companies:
            item = QListWidgetItem(name)
            item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            item.setCheckState(Qt.Checked)
            self._list.addItem(item)
        self.body.addWidget(self._list, stretch=1)
        self.resize(520, 580)
        self.footer.add_secondary(
            self.button(i18n.t("Cancel"), on_click=self.reject))
        self.footer.set_primary(self.button(
            i18n.t("Add checked to Find people"), "primary",
            on_click=self.accept))

    def checked(self) -> list:
        """The company names still ticked, in their original order."""
        return [self._list.item(i).text() for i in range(self._list.count())
                if self._list.item(i).checkState() == Qt.Checked]


class LeadsDialog(PrismDialog):
    def __init__(self, cfg: dict, parent=None):
        super().__init__(
            i18n.t("Leads & Outreach"),
            i18n.t("Find, qualify and reach the right people — Prism drafts, "
                   "you send."),
            icon="user", parent=parent)
        self._workbench = LeadsWorkbench(cfg or {}, self)
        self.body.addWidget(self._workbench, stretch=1)
        export_btn, send_btn = self._workbench.action_buttons()
        self.footer.add_utility(export_btn)
        self.footer.add_secondary(self.button(i18n.t("Close"),
                                              on_click=self.reject))
        self.footer.set_primary(send_btn)
        self.resize(1280, 820)
