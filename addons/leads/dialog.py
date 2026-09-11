"""
Leads & Outreach — the modal shell (compatibility)
──────────────────────────────────────────────────
The workbench lives full-window in the panel (addons/leads/panel.py). This thin
dialog wraps the same `LeadsWorkbench` so the manifest's `dialog=` reference
keeps resolving and any caller that still wants a modal gets one. The rail no
longer opens it — it shows the panel.
"""
from __future__ import annotations

import i18n
from dialogs.base import PrismDialog
from addons.leads.workbench import LeadsWorkbench


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
