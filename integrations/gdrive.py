"""Google Drive as a place to attach files from.

Prism's job here is small and worth stating precisely: let someone pick a file
that lives in their company's Drive, download it to a temp folder, and hand
the local path to the same attach pipeline a local file goes through. Nothing
downstream knows or cares where a file came from.

────────────────────────────────────────────────────────────────────────────
What you have to set up once, before this can sign anybody in
────────────────────────────────────────────────────────────────────────────
Google will not let an app request an account's files without an OAuth client
that identifies the app. Only you can create it, because it is tied to your
company and your consent screen:

  1. console.cloud.google.com → new project (or an existing one)
  2. APIs & Services → Library → enable "Google Drive API"
  3. APIs & Services → OAuth consent screen → External → fill in the app name,
     support email and logo. Add the scope below. While the screen is in
     "Testing" only accounts you list can sign in, so publish it before you
     ship to customers.
  4. Credentials → Create credentials → OAuth client ID → **Desktop app**
  5. Download the JSON and save it as integrations/google_client.json,
     or set PRISM_GOOGLE_CLIENT to point at it.

Until that file exists every entry point here reports "not configured" and the
UI says so plainly rather than failing at the click.

Scope is drive.readonly, deliberately. Prism reads a file the user picked; it
has no reason to be able to write to, delete from, or reorganise a company's
Drive, and asking for less makes the consent screen an easier sell to an IT
manager. Widening it is a decision to take on purpose, not by copying a
broader scope off a tutorial.

Per-person, not per-company: each member signs in with their own Google
account, so Drive's own sharing rules decide what they can see. That is worth
more than anything Prism could enforce — a salesperson who cannot open the
finance folder in Drive cannot open it here either, and that boundary IS
enforced by the operating system, unlike Prism's own folder split.

Tokens land in ~/.prism/google/<account>.json, owner-readable only, and never
in the shared workspace.
"""
from __future__ import annotations

import os
from typing import Any

import paths

# Read-only. See the note above before widening this.
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# Google Docs/Sheets/Slides are not files with bytes — they must be exported.
# Mapped to the format Prism's readers actually handle: core/files.py extracts
# text from docx/xlsx/pdf, so those are what a native Doc becomes.
EXPORT_AS = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx"),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx"),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx"),
    "application/vnd.google-apps.drawing": ("image/png", ".png"),
}

FOLDER_MIME = "application/vnd.google-apps.folder"


class DriveError(Exception):
    """Anything that stops a Drive operation, already phrased for a human."""


# ── is this build able to talk to Drive at all ─────────────────────────────
def client_config_path() -> str:
    return (os.environ.get("PRISM_GOOGLE_CLIENT")
            or paths.resource("integrations", "google_client.json"))


def deps_available() -> tuple[bool, str]:
    """The Google client libraries are an optional extra, like ezdxf for BOQ:
    a customer who never touches Drive should not carry them."""
    try:
        import google_auth_oauthlib          # noqa: F401
        import googleapiclient.discovery     # noqa: F401
        return True, ""
    except Exception:
        return False, ("Google Drive needs two extra libraries:\n\n"
                       "    pip install google-api-python-client "
                       "google-auth-oauthlib")


def configured() -> tuple[bool, str]:
    """Can this build sign anyone in? Deps AND an OAuth client."""
    ok, why = deps_available()
    if not ok:
        return False, why
    if not os.path.exists(client_config_path()):
        return False, ("Google Drive isn't set up in this build of Prism.\n\n"
                       "It needs an OAuth client ID from Google Cloud, saved "
                       "as integrations/google_client.json. See the notes at "
                       "the top of integrations/gdrive.py.")
    return True, ""


# ── the signed-in account ──────────────────────────────────────────────────
def _token_dir() -> str:
    """Beside the licence, never in the shared workspace: a Drive refresh
    token is a credential for someone's whole account, and the workspace is
    the one folder we have said other people can read."""
    path = paths.user_dir("google")
    os.makedirs(path, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def _token_path() -> str:
    return os.path.join(_token_dir(), "token.json")


def connected() -> bool:
    return os.path.exists(_token_path())


def disconnect() -> None:
    """Forget the account. Does not revoke at Google's end — the user should
    do that from their Google account page, and the UI says so."""
    try:
        os.unlink(_token_path())
    except OSError:
        pass


def _credentials(interactive: bool):
    """The stored credentials, refreshed, or a fresh consent run.

    `interactive=False` is the "am I already signed in" path and never opens a
    browser, so it is safe to call while drawing a menu.
    """
    ok, why = configured()
    if not ok:
        raise DriveError(why)

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if os.path.exists(_token_path()):
        try:
            creds = Credentials.from_authorized_user_file(_token_path(), SCOPES)
        except Exception:
            creds = None            # corrupt token file: sign in again

    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save(creds)
            return creds
        except Exception:
            # Refresh token revoked or expired. Fall through to consent.
            creds = None

    if not interactive:
        raise DriveError("Not connected to Google Drive yet.")

    flow = InstalledAppFlow.from_client_secrets_file(
        client_config_path(), SCOPES)
    # run_local_server opens the user's real browser and catches the redirect
    # on a loopback port — the flow Google requires for desktop apps, and the
    # reason this cannot be done inside Prism's automation Chrome.
    creds = flow.run_local_server(port=0, prompt="consent",
                                  authorization_prompt_message="",
                                  success_message="Prism is connected to your "
                                                  "Google Drive. You can close "
                                                  "this tab.")
    _save(creds)
    return creds


def _save(creds) -> None:
    with open(_token_path(), "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    try:
        os.chmod(_token_path(), 0o600)
    except OSError:
        pass


def connect() -> str:
    """Run the browser consent flow. Returns the account's email address."""
    _credentials(interactive=True)
    return account_email()


def account_email() -> str:
    try:
        service = _service()
        about = service.about().get(fields="user(emailAddress)").execute()
        return about.get("user", {}).get("emailAddress", "")
    except Exception:
        return ""


def _service():
    from googleapiclient.discovery import build
    creds = _credentials(interactive=False)
    # cache_discovery=False: the default file cache warns noisily under a
    # frozen build and buys nothing for a handful of calls.
    return build("drive", "v3", credentials=creds, cache_discovery=False)


# ── browsing ───────────────────────────────────────────────────────────────
def list_folder(folder_id: str = "root", *, query: str = "",
                limit: int = 200) -> list[dict[str, Any]]:
    """Folders first, then files, both alphabetical.

    `query` searches the whole Drive by name instead of listing one folder —
    which is what people actually do once a Drive is more than a few folders
    deep.
    """
    service = _service()
    if query.strip():
        # The apostrophe is the string delimiter in Drive's query language.
        safe = query.replace("\\", "\\\\").replace("'", "\\'")
        q = f"name contains '{safe}' and trashed = false"
    else:
        q = f"'{folder_id}' in parents and trashed = false"
    try:
        result = service.files().list(
            q=q, pageSize=min(limit, 1000),
            orderBy="folder,name",
            fields="files(id,name,mimeType,size,modifiedTime,iconLink)",
            supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute()
    except Exception as e:
        raise DriveError(f"Couldn't read that folder: {e}") from e
    return result.get("files", [])


def path_of(file_id: str) -> list[dict[str, str]]:
    """Breadcrumbs from My Drive down to `file_id`, for the picker's header."""
    service = _service()
    trail: list[dict[str, str]] = []
    current = file_id
    seen = set()
    while current and current not in seen:
        seen.add(current)
        try:
            meta = service.files().get(
                fileId=current, fields="id,name,parents",
                supportsAllDrives=True).execute()
        except Exception:
            break
        trail.insert(0, {"id": meta["id"], "name": meta.get("name", "…")})
        parents = meta.get("parents") or []
        current = parents[0] if parents else ""
    return trail


def is_folder(item: dict) -> bool:
    return item.get("mimeType") == FOLDER_MIME


# ── downloading ────────────────────────────────────────────────────────────
def download(item: dict, dest_dir: str = "") -> str:
    """Fetch one Drive file to disk and return its local path.

    Native Google formats are exported (a Doc becomes a .docx) because they
    have no bytes to download — asking for the raw content of a Google Doc is
    an error from the API, not an empty file, and that surprises everyone once.
    """
    from googleapiclient.http import MediaIoBaseDownload

    service = _service()
    dest_dir = dest_dir or paths.user_dir("drive-cache")
    os.makedirs(dest_dir, exist_ok=True)

    name = item.get("name") or item.get("id", "drive-file")
    mime = item.get("mimeType", "")

    if mime in EXPORT_AS:
        export_mime, suffix = EXPORT_AS[mime]
        if not name.lower().endswith(suffix):
            name += suffix
        request = service.files().export_media(fileId=item["id"],
                                               mimeType=export_mime)
    elif mime.startswith("application/vnd.google-apps"):
        # A Form, a Site, a Map. Nothing to hand to an AI tool.
        raise DriveError(f"“{name}” is a Google {mime.rsplit('.', 1)[-1]} and "
                         f"can't be downloaded as a file.")
    else:
        request = service.files().get_media(fileId=item["id"],
                                            supportsAllDrives=True)

    target = os.path.join(dest_dir, _safe_name(name))
    import io
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    try:
        while not done:
            _status, done = downloader.next_chunk()
    except Exception as e:
        raise DriveError(f"Couldn't download “{name}”: {e}") from e
    with open(target, "wb") as f:
        f.write(buffer.getvalue())
    return target


def _safe_name(name: str) -> str:
    """A Drive name can contain anything, including a path separator."""
    cleaned = "".join(c for c in name if c not in '/\\:*?"<>|').strip()
    return cleaned or "drive-file"


def human_size(item: dict) -> str:
    try:
        size = int(item.get("size") or 0)
    except (TypeError, ValueError):
        return ""
    if not size:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return ""
