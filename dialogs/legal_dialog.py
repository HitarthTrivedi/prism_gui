"""Terms of Use / Privacy Policy, read from inside the app — no network
needed, and no risk of the in-app copy drifting from what a customer agreed
to (the bundled file IS the one on paths.resource(), not a link that can
404 or point at whichever version happens to be live on the website today).

QTextBrowser.setMarkdown() is used deliberately instead of
widgets/markdown.py's render_markdown() — that renderer is built for
freeform LLM chat prose and has no table support, and both TERMS_OF_USE.md
and PRIVACY_POLICY.md lean on markdown tables for the data-collected /
seat-limits summaries. Qt's own Markdown-to-rich-text conversion (Qt 5.14+)
handles tables, and this content is fixed, reviewed English — not
translated text — so i18n.install() deliberately leaves setMarkdown()
alone (see i18n.py's own docstring on that).
"""
from __future__ import annotations

from PySide6.QtWidgets import QTextBrowser

import i18n
import paths
from dialogs.base import PrismDialog


class LegalDialog(PrismDialog):
    def __init__(self, title: str, resource_name: str, parent=None):
        super().__init__(title, parent=parent, scrollable=False)

        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.view.setMarkdown(self._load(resource_name))
        self.body.addWidget(self.view, stretch=1)

        self.footer.add_secondary(
            self.button(i18n.t("Close"), on_click=self.accept))

    @staticmethod
    def _load(resource_name: str) -> str:
        path = paths.resource(resource_name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            # A build missing its own legal text is a packaging bug, not a
            # crash the customer should see — degrade to a clear pointer
            # rather than an empty dialog or a traceback.
            return (f"_Could not load `{resource_name}` from this build. "
                    f"See it online instead: alphakore.org_")
