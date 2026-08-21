"""Turning what went wrong into what to do about it.

The person using Prism runs a business. They have not used an AI tool before,
they did not choose Selenium, and "HTTP 429" is not a sentence. Every message
they can possibly see goes through here first and comes out as three things:

    title    what happened, in five words
    what     one or two sentences of plain English, no jargon
    steps    the numbered things to try, most likely fix first

The rule this module exists to enforce: **never show someone a problem without
showing them the next action.** A message with no action is a phone call.

How it works
────────────
A list of patterns, most specific first. Each knows one real failure — the
ones in KNOWN_ISSUES.md, because those are the ones that actually happen — and
carries the words for it. Anything unmatched still gets a useful answer: the
generic entry ends with "send us the diagnostics file", which is the honest
next step when we genuinely do not know.

Write the steps as instructions to a person, not a description of a system.
"Open Settings → Chrome and clear the version box" beats "the pinned Chrome
version is inconsistent with the detected one".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Problem:
    title: str
    what: str
    steps: tuple[str, ...] = ()
    # True when the honest next step is to contact support, which is the only
    # case where the dialog offers to save the diagnostics file.
    ask_support: bool = False
    # Something Prism can do for them, named so the dialog can offer a button:
    # "settings:chrome", "settings:key", "login", "guide", "support".
    action: str = ""
    action_label: str = ""


# Each entry is (regex over the error text, Problem). First match wins, so the
# specific ones come before the general ones.
_RULES: list[tuple[re.Pattern, Problem]] = []


def _rule(pattern: str, problem: Problem) -> None:
    _RULES.append((re.compile(pattern, re.I | re.S), problem))


# ── the internet, and our own server ──────────────────────────────────────
_rule(r"couldn't reach the licence server|licence server|unreachable",
      Problem(
          "Prism couldn't check your licence",
          "Prism asks our server for permission each time you start work, and "
          "it didn't answer. This is almost always the internet, and it "
          "usually clears on its own within a minute.",
          ("Check this computer is online — try loading any website.",
           "Wait about a minute and press Start the work again. Our server "
           "sometimes takes a moment to wake up.",
           "If you are on office wifi, a firewall may be blocking it — try a "
           "phone hotspot to check."),
          ask_support=True))

_rule(r"check your internet|connection|network is unreachable|getaddrinfo|"
      r"name or service not known|timed out",
      Problem(
          "No internet connection",
          "Prism needs the internet for everything it does — it plans your "
          "task online and drives the AI tools in a browser.",
          ("Try loading any website to confirm you're online.",
           "If you're connected but it still fails, turn wifi off and on "
           "again.",
           "On a company network, ask whoever runs IT whether the AI websites "
           "are blocked.")))

# ── Groq: the planning brain ──────────────────────────────────────────────
_rule(r"rate.?limit",
      Problem(
          "Your AI allowance is used up for now",
          "Groq — the free service Prism uses to plan your work — only allows "
          "so many requests in a short period, and you've reached it. Nothing "
          "is broken and nothing is lost.",
          ("Wait one minute, then press Make a plan again.",
           "If you're running several tasks at once, do them a few at a time.",
           "To remove the limit, upgrade your plan at console.groq.com — it "
           "is your own account, not ours.")))

_rule(r"rejected your api key|invalid api key|401",
      Problem(
          "Your Groq key isn't working",
          "The key Prism uses to plan your work was refused. Usually the key "
          "was deleted, or only part of it was pasted in.",
          ("Go to console.groq.com and sign in.",
           "Open API Keys and create a new key. It starts with gsk_.",
           "Copy the WHOLE key, then paste it into Settings → Groq API key."),
          action="settings:key", action_label="Open Settings"))

_rule(r"none of the models|model.*(not found|decommission|deprecat|no longer)",
      Problem(
          "The AI model Prism uses has changed",
          "Groq has retired the model Prism was using. Prism normally switches "
          "to another one by itself, so seeing this means all of the ones it "
          "knows about are unavailable on your key.",
          ("Press Make a plan once more — Prism will try the next model.",
           "If it keeps failing, this needs an update from us."),
          ask_support=True))

_rule(r"no groq api key|set your groq api key",
      Problem(
          "Prism needs your Groq key first",
          "Groq is the free service Prism uses to work out the steps for your "
          "task. It takes two minutes to get a key.",
          ("Go to console.groq.com and sign up — it's free.",
           "Open API Keys → Create API Key.",
           "Copy it and paste it into Settings → Groq API key."),
          action="settings:key", action_label="Open Settings"))

# ── the browser ───────────────────────────────────────────────────────────
# BEFORE the version-mismatch rule below, and the order is the whole point.
#
# A "no such window" error arrives with a Selenium stack trace, and every
# frame of that trace says "undetected_chromedriver" — which matches the
# chromedriver pattern below. So a closed tab was diagnosed as a driver
# version mismatch, and the customer was sent to update a browser that was
# working perfectly. A wrong answer given confidently is worse than the
# generic "something went wrong" it replaced.
_rule(r"no such window|target window already closed|web view not found|"
      r"invalid session id|session deleted because of page crash|"
      r"disconnected: not connected to devtools|chrome not reachable|"
      r"browser has closed",
      Problem(
          "The browser window was closed",
          "Prism was working in a Chrome window and that window went away — "
          "usually because it was closed by hand while the run was going, or "
          "because Chrome itself quit. Nothing is wrong with your computer or "
          "your setup.",
          ("Everything finished before this point was kept — check History.",
           "Start the run again, and leave Prism's Chrome window alone while "
           "it works. You can use a different Chrome window in the meantime.",
           "If you did not close it, Chrome may have run out of memory — "
           "close some other tabs and try again.")))

_rule(r"couldn't start chrome|chromedriver|session not created|"
      r"this version of chrome|webdriver",
      Problem(
          "Prism couldn't open Chrome",
          "Chrome updates itself every few weeks, and for a day or two after "
          "an update Prism's browser connection can stop matching it.",
          ("Open Chrome, click the Chrome menu → About Google Chrome, let it "
           "update, then close Chrome completely and try again.",
           "If you set a Chrome version by hand in Settings → Chrome, clear "
           "that box so Prism finds it automatically.",
           "Make sure Google Chrome is actually installed — Prism cannot use "
           "Safari or Edge."),
          action="settings:chrome", action_label="Open Chrome settings"))

_rule(r"profile appears to be in use|user data directory is already",
      Problem(
          "Prism's browser is still open somewhere",
          "A previous run left a Chrome window running in the background, and "
          "only one can use Prism's browser at a time.",
          ("Close every Chrome window, including any Prism opened.",
           "If that doesn't help, restart the computer — it clears it for "
           "certain.")))

_rule(r"not signed in|sign in to this tool|signed out",
      Problem(
          "You're not signed in to one of the AI tools",
          "Prism uses your own accounts — ChatGPT, Claude and the rest — and "
          "one of them has signed you out. Signing in once is remembered from "
          "then on.",
          ("Click Login tabs in the left sidebar.",
           "Sign in to each tool in the window Prism opens.",
           "Close that window and run your task again."),
          action="login", action_label="Open Login tabs"))

_rule(r"human.?verification|are you a robot|captcha",
      Problem(
          "A tool is asking to check you're human",
          "One of the AI websites showed a 'confirm you're human' box. Prism "
          "cannot click those — they exist to stop software doing exactly "
          "that.",
          ("Click Login tabs in the sidebar.",
           "Tick the box on whichever site is asking.",
           "Run your task again. It usually only asks once."),
          action="login", action_label="Open Login tabs"))

# ── licence and add-ons ───────────────────────────────────────────────────
_rule(r"isn't in your licence|feature_not_licensed|not licensed",
      Problem(
          "That's not part of your plan",
          "This part of Prism is sold separately from the one you have. "
          "Nothing is broken — it simply isn't switched on for your licence.",
          ("Everything else keeps working as normal.",
           "If you'd like it added, get in touch and we'll send an updated "
           "key — it takes effect immediately, with nothing to reinstall.")))

_rule(r"licence has ended|expired|licence is over",
      Problem(
          "Your licence has ended",
          "New work is paused, but nothing has been taken away — your history "
          "and everything you've already produced are still here.",
          ("Open History to reach anything you made before.",
           "Contact us to renew. Entering the new key switches everything "
           "back on straight away.")))

_rule(r"clock|date and time",
      Problem(
          "This computer's date looks wrong",
          "Prism checks the date to confirm your licence, and this computer's "
          "clock has gone backwards.",
          ("Open your computer's Date & Time settings.",
           "Turn on 'Set date and time automatically'.",
           "Connect to the internet and restart Prism.")))

# ── email ─────────────────────────────────────────────────────────────────
_rule(r"app password|smtpauth|authentication failed|username and password",
      Problem(
          "Your email password was refused",
          "Gmail and most other providers no longer let apps use your normal "
          "password. They need a separate 'app password' — a one-off code you "
          "create for Prism.",
          ("Go to myaccount.google.com/apppasswords and sign in.",
           "Create an app password, name it Prism, and copy the 16 letters.",
           "Paste that into Prism's email setup instead of your real "
           "password.")))

# ── files and disk ────────────────────────────────────────────────────────
_rule(r"no space left|disk full|errno 28",
      Problem(
          "This computer has run out of space",
          "Prism couldn't save because the hard disk is full.",
          ("Empty the Trash.",
           "Delete or move some large files, then try again.",
           "In Settings you can see how much space Prism's own history is "
           "using.")))

_rule(r"permission denied|errno 13|read-only file system",
      Problem(
          "Prism isn't allowed to open that file",
          "The computer refused access. Usually the file is somewhere "
          "protected, or it's open in another program.",
          ("Close the file if it's open in Word, Excel or a PDF reader.",
           "Try copying it to your Desktop and attaching it from there.")))

_rule(r"file not found|no such file|filenotfound",
      Problem(
          "That file isn't there any more",
          "The file has been moved, renamed or deleted since it was attached.",
          ("Remove it from the attached list and add it again.",)))

# ── optional extras ───────────────────────────────────────────────────────
_rule(r"ezdxf|libredwg|\.dwg",
      Problem(
          "Prism can't read that drawing yet",
          "Reading CAD drawings needs an extra component that isn't installed "
          "on this computer.",
          ("Send us this message and we'll send you the one-line install.",
           "In the meantime, save the drawing as DXF from your CAD program — "
           "Prism reads that directly.",
           "Or describe the job in words instead of attaching a drawing; the "
           "BOQ add-on works from a written spec too."),
          ask_support=True))

_rule(r"ffmpeg",
      Problem(
          "Video needs one extra program",
          "Making a reel needs FFmpeg, a free video tool that isn't part of "
          "Prism. Prism can fetch it for you.",
          # No longer "send us this message". Prism downloads and installs it
          # itself now, so telling a customer to contact support for a job the
          # software does in a minute would be an odd thing to do.
          ("Open Reel and press Get FFmpeg. It's about 30 MB and takes a "
           "minute; it only happens once.",
           "Nothing else changes on this computer, and everything else in "
           "Prism works without it.")))

_rule(r"pyaudio|portaudio|microphone",
      Problem(
          "The microphone isn't available",
          "Prism couldn't reach the microphone, so speaking your task isn't "
          "available on this computer.",
          ("Check that no other program is using the microphone.",
           "On a Mac, look in System Settings → Privacy & Security → "
           "Microphone and make sure Prism is allowed.",
           "Everything else works — just type the task instead.")))

# ── the tools themselves ──────────────────────────────────────────────────
_rule(r"returned nothing|no response|couldn't read the response|empty",
      Problem(
          "One of the AI tools didn't answer",
          "The tool was asked, but nothing came back in time. This is usually "
          "the website being slow or having changed its page.",
          ("Your other steps still ran — check the results above.",
           "Click the link next to that step to open the tool and see whether "
           "the answer arrived after Prism stopped waiting.",
           "Run just that step again by unticking the others."),
          ask_support=True))

_rule(r"apollo",
      Problem(
          "Apollo didn't return any leads",
          "Three things cause this: the search was too narrow, the Apollo "
          "account is signed out, or it has run out of email credits for the "
          "month.",
          ("Click Login tabs and check you can see Apollo's People table.",
           "Look at the credit balance at the top of Apollo.",
           "Try a broader search — a wider area, or more job titles.")))

# ── the catch-all ─────────────────────────────────────────────────────────
_GENERIC = Problem(
    "Something went wrong",
    "Prism hit a problem it doesn't recognise. Nothing you have already "
    "produced has been lost.",
    ("Try the same thing once more — many problems are momentary.",
     "Open Help & support if it happens again — it has a written answer for "
     "most things, and opens the way to us when none of them fits.",
     "Everything already finished is still in History."),
    ask_support=True,
    # The one entry where we genuinely do not know what went wrong, so it is
    # the one that most needs a route onwards rather than a shrug. Saving the
    # diagnostics file is still offered beside it; this is the faster half.
    action="support", action_label="Open Help & support")


def explain(error: object, context: str = "") -> Problem:
    """Any error → something a person can act on.

    `context` is a hint from the caller ("attach", "run", "email") used only
    when the text itself is not distinctive enough to match.
    """
    text = f"{context} {error}".strip()
    for pattern, problem in _RULES:
        if pattern.search(text):
            return problem
    return _GENERIC


def as_text(problem: Problem) -> str:
    """The whole thing as plain text, for a status bar or a log line."""
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(problem.steps, 1))
    return f"{problem.title}\n\n{problem.what}\n\n{steps}".strip()
