"""
WhatsApp — the modal shell (compatibility)
──────────────────────────────────────────
The workspace lives full-window in the panel (addons/whatsapp/panel.py). This
thin dialog wraps the same `WhatsAppWorkbench` so the manifest's `dialog=`
reference keeps resolving and any caller that still wants a modal gets one. The
rail no longer opens it — it shows the panel.
"""
from __future__ import annotations

import i18n
from addons.whatsapp.workbench import WhatsAppWorkbench
from dialogs.base import PrismDialog


class WhatsAppDialog(PrismDialog):
    def __init__(self, cfg: dict, parent=None):
        super().__init__(
            i18n.t("WhatsApp"),
            i18n.t("Every conversation, contact and broadcast on your WhatsApp number."),
            icon="message", parent=parent)
        self._workbench = WhatsAppWorkbench(cfg or {}, self)
        self.body.addWidget(self._workbench, stretch=1)
        self.footer.add_secondary(self.button(i18n.t("Close"), on_click=self.reject))
        self.resize(1280, 820)

    def closeEvent(self, event):
        self._workbench.deactivate()
        super().closeEvent(event)
