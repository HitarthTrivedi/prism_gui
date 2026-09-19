"""Off-thread workers for the WhatsApp add-on.

Per-addon workers, like addons/leads/workers.py. Each subclasses the shared
`workers._Worker` (which anchors a running QThread against GC, so a dialog can
close mid-send without a native crash), and imports its client lazily inside
run() so importing this module never reaches for the network or drags anything
heavy onto the UI thread.

Every worker below but WhatsAppSendWorker talks to Prism's own licence server
(addons.whatsapp.license_client), never Supabase or n8n directly — see that
module's docstring. None of them take a base URL or a key any more: the
licence server already knows which seat is calling.
"""
from __future__ import annotations

from PySide6.QtCore import Signal

from workers import _Worker


class WhatsAppSendWorker(_Worker):
    """Send one WhatsApp message off the UI thread.

    A Cloud API call is a network round trip and blocks; `done` carries the
    wamid Meta assigned, so the dialog can show it and, later, match a delivery
    receipt back to the message that earned it."""

    done = Signal(str)          # wamid
    failed = Signal(str)

    def __init__(self, phone_number_id: str, token: str, to: str, body: str,
                 *, api_version: str = "v21.0"):
        super().__init__()
        self.phone_number_id = phone_number_id
        self.token = token
        self.to = to
        self.body = body
        self.api_version = api_version

    def run(self):
        try:
            from addons.whatsapp.cloud_api import send_text
            wamid = send_text(self.phone_number_id, self.token, self.to,
                              self.body, api_version=self.api_version)
            self.done.emit(wamid)
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class ConversationsLoadWorker(_Worker):
    """Load the Inbox list off the UI thread — a licence-server round trip
    per open of the tab, and a slow or unreachable server must not freeze
    the window."""

    done = Signal(list)
    failed = Signal(str)

    def __init__(self, *, limit: int = 50):
        super().__init__()
        self.limit = limit

    def run(self):
        try:
            from addons.whatsapp import license_client as lc
            self.done.emit(lc.list_conversations())
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class ThreadLoadWorker(_Worker):
    """Load one conversation's messages. `conversation_id` rides both signals
    so the dialog can drop a reply that arrives after the person has since
    clicked to a different conversation."""

    done = Signal(object, list)     # conversation_id, messages
    failed = Signal(object, str)    # conversation_id, error

    def __init__(self, conversation_id, *, limit: int = 200):
        super().__init__()
        self.conversation_id, self.limit = conversation_id, limit

    def run(self):
        try:
            from addons.whatsapp import license_client as lc
            messages = lc.get_thread(self.conversation_id)
            self.done.emit(self.conversation_id, messages)
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(self.conversation_id, str(e))


class ContactsLoadWorker(_Worker):
    """Load the Contacts list off the UI thread."""

    done = Signal(list)
    failed = Signal(str)

    def __init__(self, *, search: str = "", limit: int = 200):
        super().__init__()
        self.search, self.limit = search, limit

    def run(self):
        try:
            from addons.whatsapp import license_client as lc
            self.done.emit(lc.list_contacts(search=self.search))
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class ContactOptOutWorker(_Worker):
    """Flip one contact's opt-out flag. The only write Prism ever made to
    Supabase itself, now the same call proxied through the licence server."""

    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, contact_id, opt_out: bool):
        super().__init__()
        self.contact_id, self.opt_out = contact_id, opt_out

    def run(self):
        try:
            from addons.whatsapp import license_client as lc
            row = lc.set_contact_opt_out(self.contact_id, self.opt_out)
            self.done.emit(row or {})
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class ReplySendWorker(_Worker):
    """Ask the licence server to have n8n send and log a reply — never Meta
    directly; see license_client.py for why."""

    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, *, phone: str, text: str, conversation_id="", contact_id=""):
        super().__init__()
        self.phone, self.text = phone, text
        self.conversation_id, self.contact_id = conversation_id, contact_id

    def run(self):
        try:
            from addons.whatsapp import license_client as lc
            data = lc.send_reply(
                phone=self.phone, text=self.text,
                conversation_id=self.conversation_id,
                contact_id=self.contact_id)
            self.done.emit(data)
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class TagsLoadWorker(_Worker):
    """Every distinct tag in use, for the filter picker."""

    done = Signal(list)
    failed = Signal(str)

    def run(self):
        try:
            from addons.whatsapp import license_client as lc
            self.done.emit(lc.list_tags())
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class ContactTagsSaveWorker(_Worker):
    """Save one contact's tags."""

    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, contact_id, tags: list):
        super().__init__()
        self.contact_id, self.tags = contact_id, tags

    def run(self):
        try:
            from addons.whatsapp import license_client as lc
            row = lc.set_contact_tags(self.contact_id, self.tags)
            self.done.emit(row or {})
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class SegmentsLoadWorker(_Worker):
    """Every saved segment."""

    done = Signal(list)
    failed = Signal(str)

    def run(self):
        try:
            from addons.whatsapp import license_client as lc
            self.done.emit(lc.list_segments())
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class SegmentSaveWorker(_Worker):
    """Create or update a saved segment."""

    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, name: str, tags: list):
        super().__init__()
        self.name, self.tags = name, tags

    def run(self):
        try:
            from addons.whatsapp import license_client as lc
            row = lc.save_segment(self.name, self.tags)
            self.done.emit(row)
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class SegmentDeleteWorker(_Worker):
    """Delete a saved segment."""

    done = Signal()
    failed = Signal(str)

    def __init__(self, segment_id):
        super().__init__()
        self.segment_id = segment_id

    def run(self):
        try:
            from addons.whatsapp import license_client as lc
            lc.delete_segment(self.segment_id)
            self.done.emit()
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class AudiencePreviewWorker(_Worker):
    """Resolve who a tag filter would actually reach, before sending."""

    done = Signal(list)
    failed = Signal(str)

    def __init__(self, tags: list):
        super().__init__()
        self.tags = tags

    def run(self):
        try:
            from addons.whatsapp import license_client as lc
            rows = lc.resolve_audience(tags=self.tags)
            self.done.emit(rows)
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class CampaignsLoadWorker(_Worker):
    """Every past broadcast, newest first."""

    done = Signal(list)
    failed = Signal(str)

    def run(self):
        try:
            from addons.whatsapp import license_client as lc
            self.done.emit(lc.list_campaigns())
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class BroadcastSendWorker(_Worker):
    """Ask the licence server to resolve the audience, record the campaign
    and have n8n send it — one call now; the server does what this worker
    used to do in three."""

    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, *, template_name: str, language: str, tags: list,
                 segment_name: str = ""):
        super().__init__()
        self.template_name, self.language = template_name, language
        self.tags, self.segment_name = tags, segment_name

    def run(self):
        try:
            from addons.whatsapp import license_client as lc
            result = lc.send_broadcast(
                template_name=self.template_name, language=self.language,
                tags=self.tags, segment_name=self.segment_name)
            self.done.emit(result)
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))
