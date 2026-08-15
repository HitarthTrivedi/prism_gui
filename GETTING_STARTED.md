# Getting started with Prism

Prism is a desktop app that turns one plain-English task into a pipeline
across the AI tools you already use — it drives your logged-in browser the
same way you would, just faster and hands-off.

This guide covers installing it and your first run. No technical background
needed.

---

## Before you install

You need **Google Chrome** — Prism operates the AI tools through it, the same
way you'd click around them yourself. If you don't have it, get it free at
[google.com/chrome](https://www.google.com/chrome/) first.

---

## 1. Download

Go to the [Downloads page](https://github.com/HitarthTrivedi/prism_gui/releases/latest)
and pick the file for your computer:

| Your computer | Get this file |
|---|---|
| **Windows** | the `.zip` file |
| **Mac — 2021 or newer** (M1/M2/M3/M4 chip) | the `.dmg` file ending in `arm64` |
| **Linux** | the `.tar.gz`, or the `.AppImage` if you prefer a single file |

**Not sure which Mac you have?** Click the Apple menu (top-left) → *About
This Mac*. If it says "Chip: Apple M…", take the `arm64` file.

**If it says "Processor: Intel…"**, Prism does not have a build for your Mac
yet — the `arm64` file will not open on it. Ask us rather than trying to make
it work; there is nothing on that page that will run.

## 2. Install

**Windows** — extract the `.zip` (right-click → *Extract All*), then open the
`Prism` folder and double-click `Prism.exe`.

**Mac** — double-click the `.dmg`, then drag the Prism icon onto the
*Applications* shortcut in the window that opens.

**Linux** — extract the `.tar.gz`, then run `./install.sh` inside the
extracted folder. This adds Prism to your applications menu. (Or just run
`./Prism` directly — no install needed.)

## 3. First launch

The very first time you open Prism, your operating system will show a
warning. This is expected — it happens because Prism isn't (yet) registered
with Apple or Microsoft, not because anything is wrong. You only do this once.

**On Mac:**
> *"Prism can't be opened because Apple cannot check it for malicious
> software."*

Right-click (or Control-click) the Prism icon → **Open** → **Open**.

If instead it says the app **"is damaged and can't be opened,"** that's a
security flag macOS puts on downloaded apps, not actual damage. Open
*Terminal* (Spotlight search → type "Terminal") and paste:
```
xattr -dr com.apple.quarantine /Applications/Prism.app
```
Then open Prism normally.

**On Windows:**
> *"Windows protected your PC"*

Click **More info**, then **Run anyway**.

**On Linux:** no warning — it just opens.

After this first time, Prism opens normally like any other app.

---

## 4. First run inside Prism

The first time Prism opens, it walks you through a short setup:

1. **Groq API key** — this is what lets Prism understand your requests. It's
   free: go to [console.groq.com](https://console.groq.com) → *API Keys* →
   *Create API Key*, then paste it in (it starts with `gsk_`).
2. **A one-line description of what you do** — helps Prism phrase things the
   way that's useful to you.
3. **Pick one tool per category** — e.g. which tool handles research, which
   handles writing, which handles images. Only pick the ones you actually use
   and are signed into.

You can change any of this later from **Settings** in the sidebar.

## 5. Using it

Type what you want done in plain English, click **Make a plan**, review the
steps Prism lays out, then **Start the work**. Prism opens each tool in
Chrome, does its part, and hands the result to the next step. When it's done,
you'll see what each tool produced, with a link back to the live tab.

**Important:** Prism uses the tools through *your* logged-in Chrome sessions —
if you've never signed into, say, ChatGPT or Claude in Chrome, sign in there
first (Prism's sidebar has a **Login tabs** button that opens them for you).

---

## Troubleshooting

**A step comes back empty.**
Prism now tells you which of these it is, so read the message rather than
assuming. There are four:

- *"You're not signed in to this tool"* — use **Login tabs** in the sidebar,
  sign in once, and run again. The login is remembered from then on.
- *"This tool has hit its usage limit"* — that tool's free allowance is spent
  for now. Use a different one for that step, or wait for the reset.
- *"Prism could not read the reply off the page"* — the website changed its
  layout. **Signing in again will not help.** Your prompt did go through, so
  the answer is sitting in the open tab and you can copy it from there. Please
  report it: it needs a Prism update.
- *"still writing its answer when Prism stopped waiting"* — give that step
  longer in Settings, or copy the answer from the tab once it finishes.

**Prism says Chrome isn't found.**
Install it from [google.com/chrome](https://www.google.com/chrome/) — Prism
needs the real thing, not a different browser.

**Voice / wake word button doesn't do anything.**
Voice input needs an extra system library (PortAudio) that isn't included by
default on every machine. Every other part of Prism works without it — this
only affects the microphone features.

**A popup says `SSL: CERTIFICATE_VERIFY_FAILED` (Mac only).**
Fixed in builds from v1.0.1 onward — update to the latest release from the
[Downloads page](https://github.com/HitarthTrivedi/prism_gui/releases/latest).
If you're still on v1.0.0, this is a one-time macOS quirk unrelated to your
computer's security; there's nothing to fix on your end except updating.

**Where is my data?**
Everything Prism saves — your settings, run history, API key — lives in a
folder on your own computer (`~/.prism`), never on a server Prism controls.

## Questions or something's not working?

Contact whoever sent you this app, or open an issue at
[github.com/HitarthTrivedi/prism_gui](https://github.com/HitarthTrivedi/prism_gui/issues).
