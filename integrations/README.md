# Prism integrations

## Google Drive

`gdrive.py` needs an OAuth client ID before it can sign anyone in. Only the
publisher can create one — it is tied to your company and your consent screen.

1. <https://console.cloud.google.com> → create or pick a project
2. **APIs & Services → Library** → enable **Google Drive API**
3. **APIs & Services → OAuth consent screen** → *External*
   - app name, support email, logo
   - add the scope `https://www.googleapis.com/auth/drive.readonly`
   - **publish it** — while it is in *Testing*, only accounts you list by hand
     can sign in, which is the single most common reason a customer's "Connect"
     button fails
4. **Credentials → Create credentials → OAuth client ID → Desktop app**
5. Download the JSON, save it here as `google_client.json`

`google_client.json` is git-ignored. For a packaged build, `prism.spec` ships
the whole `integrations/` folder, so the file has to be present at build time.

Runtime dependencies (optional — Prism runs fine without them, Drive just
reports itself unavailable):

    pip install google-api-python-client google-auth-oauthlib

### Why read-only

Prism reads a file the user picked. It has no reason to write to, delete from
or reorganise a company's Drive, and a narrower scope is a much easier
conversation with an IT manager. Each member signs in with their own Google
account, so Drive's own sharing rules decide what they can see — a boundary
the operating system enforces, unlike Prism's own folder split.
