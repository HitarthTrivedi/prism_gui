"""Every question a Prism customer actually asks, and the answer to it.

────────────────────────────────────────────────────────────────────────────
Why this file exists
────────────────────────────────────────────────────────────────────────────
`friendly.py` answers "something just broke, what now?" — it is reactive, keyed
on an error string, and it only ever fires when Prism itself noticed a problem.
That leaves the larger half uncovered: the customer who is not looking at an
error at all. They want to know whether a licence covers two computers, why
their colleague's copy is a different colour, whether the inbox add-on will
touch their real mailbox, or what to type in the box. Nothing is broken, so no
dialog will ever appear, and today the only route to an answer is a phone call.

This is that half, written down. It is the same shape as `friendly.py` on
purpose — plain English, then the numbered things to do — because the customer
should not be able to tell which of the two answered them.

────────────────────────────────────────────────────────────────────────────
Why the answers are gated behind the questions
────────────────────────────────────────────────────────────────────────────
The support screen shows these FIRST and will not offer the routes to us until
one has been read and marked as not having helped. That is deliberate and it
is not about deflecting work: roughly every question in here has been asked
down a phone at least once, and each of those calls cost somebody twenty
minutes to learn something that fits in four lines. Answering it here costs
four seconds.

The gate is honest, though, and that is the part worth protecting: a customer
whose problem genuinely is not in this file types it, gets no match, and the
escalation opens immediately. Nobody is ever made to read six irrelevant
answers to earn the right to talk to us. See `widgets/support_panel.py`.

────────────────────────────────────────────────────────────────────────────
Writing rules — the same ones friendly.py is held to
────────────────────────────────────────────────────────────────────────────
  · `what` is one or two sentences with no jargon in them. The reader runs a
    business; they did not choose Chrome, they do not know what a driver is,
    and they should never meet the word "token".
  · `steps` are instructions to a person, in the order most likely to work.
    Start each with a verb — "Open Settings…", not "The setting is in…".
  · Never state a problem without a next action. An answer with no steps is
    permitted ONLY where the question is a genuine "how does this work?" and
    there is nothing to do about it.
  · Every button, menu and screen named here must exist, under that exact
    name, in the current build. The redesign moved several (Login tabs sits
    behind More settings now; Export diagnostics lives on the sheet that
    Settings' Change buttons open), and an instruction that names a control
    that is not there sends the customer hunting — the one outcome this file
    exists to prevent.
  · `action` names something Prism can do for them, so the answer can carry a
    button instead of directions. The keys are the sidebar command keys that
    `MainWindow._handle_command` understands — anything else silently does
    nothing, which `tests/test_support.py` fails the build over.

`devtools/extract_strings.py` does not walk these strings into the catalogue
(they are data, not literals in a widget), so this file ships English-only for
now — the same trade `plans.py` already makes with its feature blurbs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Answer:
    """What to tell them, and what Prism can do about it."""
    what: str
    steps: tuple[str, ...] = ()
    # A sidebar command key — "config", "key", "login", "licence", "runs"…
    # Rendered as a button, because telling somebody to open Settings is worse
    # than taking them there.
    action: str = ""
    action_label: str = ""
    # The entitlement this question is about, "" if it applies to everyone.
    # Used to tag an answer about an add-on the customer has not bought, so
    # they are told that BEFORE following four steps that cannot work.
    feature: str = ""
    # The honest caveat, when there is one worth printing under the steps.
    note: str = ""


@dataclass(frozen=True)
class Question:
    qid: str
    # Phrased the way the customer would say it out loud, not the way we would
    # file it. "It says my licence has ended" beats "Licence expiry handling".
    text: str
    answer: Answer
    # Extra words that should find this question when typed. The question text
    # is already searched, so only add what it does NOT contain — the customer's
    # vocabulary, our error wording, the thing they call it in the trade.
    keywords: tuple[str, ...] = ()
    related: tuple[str, ...] = ()


@dataclass(frozen=True)
class Topic:
    key: str
    icon: str
    label: str
    # One line, shown under the topic button. Says what is inside so nobody
    # has to open three topics to find the right shelf.
    blurb: str
    questions: tuple[Question, ...]


# ════════════════════════════════════════════════════════════════════════════
#  1 · Getting started
# ════════════════════════════════════════════════════════════════════════════
_START = Topic(
    "start", "home", "Getting started",
    "What Prism is, what you need, and the very first run",
    (
        Question(
            "what-is-prism",
            "What is Prism, and what does it actually do?",
            Answer(
                "You describe a job in your own words — one box, plain "
                "English — and Prism works out which AI websites are needed, "
                "opens them in Chrome signed in as you, asks each one in "
                "turn, and hands you the finished result. You never have to "
                "know which AI is good at what. That is the whole point of "
                "it.",
                ("Press New task in the left sidebar.",
                 "Describe the job in the box, then press Make a plan and "
                 "check the steps it proposes.",
                 "Press Start the work."),
                action="guide", action_label="Show me the full guide"),
            keywords=("what is", "purpose", "explain", "overview", "new",
                      "beginner", "how does it work"),
            related=("what-to-type", "what-do-i-need")),

        Question(
            "what-do-i-need",
            "What do I need before I can use it?",
            Answer(
                "Three things: Google Chrome, accounts on the AI websites you "
                "want used, and a free key from Groq so Prism can work out "
                "the steps. Everything else is already inside the app.",
                ("Install Google Chrome if it isn't on this computer — Prism "
                 "cannot drive Safari, Edge or Firefox.",
                 "Sign in to the AI websites you use, in Chrome, at least "
                 "once.",
                 "Get a free key from console.groq.com and paste it into "
                 "Settings.",
                 "Keep this computer online — Prism needs the internet for "
                 "everything it does."),
                action="config", action_label="Open Settings"),
            keywords=("requirements", "need", "before", "prerequisite",
                      "install", "chrome", "account"),
            related=("groq-key", "other-browser", "offline")),

        Question(
            "first-setup",
            "How do I set it up the first time?",
            Answer(
                "Prism asks for three things the first time it opens, and it "
                "only ever asks once. All three can be changed later from "
                "Settings.",
                ("Paste in your free key from Groq — it begins with gsk_.",
                 "Write one line about what you do, so Prism phrases things "
                 "usefully for your trade.",
                 "Pick one tool per kind of work — research, writing, images "
                 "— choosing only ones you are actually signed in to."),
                action="config", action_label="Open Settings"),
            keywords=("setup", "first run", "onboarding", "configure",
                      "wizard", "start"),
            related=("groq-key", "change-tool")),

        Question(
            "os-warning",
            "My computer warned me the app isn't safe to open",
            Answer(
                "Expected, and it happens once. Prism is not yet registered "
                "with Apple or Microsoft, so both of them warn about it the "
                "first time. It is not a sign that anything is wrong with the "
                "file you downloaded.",
                ("On Windows, click More info, then Run anyway.",
                 "On a Mac, right-click the Prism icon, choose Open, then "
                 "Open again in the box that appears.",
                 "If a Mac says the app is damaged, open Terminal and paste: "
                 "xattr -dr com.apple.quarantine /Applications/Prism.app",
                 "Open Prism normally from then on — the warning does not "
                 "come back.")),
            keywords=("windows protected your pc", "unidentified developer",
                      "damaged", "malicious", "smartscreen", "gatekeeper",
                      "quarantine", "blocked", "security warning"),
            related=("wont-start",)),

        Question(
            "groq-key",
            "Where do I get the key it's asking for, and does it cost anything?",
            Answer(
                "It is free, it takes two minutes, and it is your own account "
                "rather than ours. Groq is the service Prism uses to read "
                "your request and work out the steps — nothing else uses it.",
                ("Go to console.groq.com and sign up.",
                 "Open API Keys, then Create API Key.",
                 "Copy the whole key — it begins with gsk_ — and paste it "
                 "into Settings → Status → Change API key.",
                 "Press Save. Prism checks it there and then, so you find out "
                 "immediately if only half of it was pasted."),
                action="key", action_label="Open the key setting"),
            keywords=("groq", "api key", "gsk", "free", "cost", "sign up",
                      "console.groq.com", "where do i get"),
            related=("key-rejected", "rate-limit")),

        Question(
            "what-to-type",
            "What should I type in the task box?",
            Answer(
                "Write it the way you would explain it to somebody new on "
                "their first day. Say what you want, who it is for, and "
                "anything that has to be in it. Longer is better than "
                "shorter — every detail you give gets used.",
                ("Say what you want made: a proposal, a post, an email, a "
                 "list of companies.",
                 "Say who it is for, and mention anything that must appear in "
                 "it.",
                 "Attach any file that matters with Add file, rather than "
                 "describing what is in it."),
                note="Vague: \"make a post\".  Better: \"make an Instagram "
                     "post for our new CNC machine, aimed at small "
                     "fabrication shops, mentioning the 3-year warranty\".",
                action="guide", action_label="See more examples"),
            keywords=("what to write", "examples", "task", "wording", "how to "
                      "ask", "phrase", "vague"),
            related=("what-is-prism", "attach-file")),
    ))


# ════════════════════════════════════════════════════════════════════════════
#  2 · Running a job
# ════════════════════════════════════════════════════════════════════════════
_RUNNING = Topic(
    "running", "list", "Running a job",
    "Making a plan, changing it, starting and stopping the work",
    (
        Question(
            "make-a-plan-nothing",
            "I pressed Make a plan and nothing happened",
            Answer(
                "Making a plan needs three things to be in place, and Prism "
                "says which one is missing along the bottom of the window — "
                "that message is easy to miss, so check there first.",
                ("Check the status line at the bottom of the window for what "
                 "it said.",
                 "Check your key is saved — Settings → Status says Set or "
                 "Not set beside Groq key.",
                 "Check this computer is online by loading any website.",
                 "Wait a minute and press it again — our licence server "
                 "sometimes takes a moment to wake up first thing in the "
                 "morning."),
                action="key", action_label="Check my key"),
            keywords=("nothing happens", "make a plan", "stuck", "dead "
                      "button", "no plan", "doesn't work"),
            related=("cant-check-licence", "key-rejected")),

        Question(
            "empty-step",
            "A step came back empty",
            Answer(
                "Almost always this means you are not signed in to that "
                "website in Chrome. Prism uses your own accounts, and one of "
                "them has signed you out. Nothing else in the run is lost.",
                ("Click More settings in the left sidebar, then Login tabs.",
                 "Sign in to each tool in the window Prism opens, then close "
                 "it.",
                 "Run the job again — signing in is remembered from then on.",
                 "Press Open in tool beside the step to check whether the "
                 "answer arrived after Prism stopped waiting."),
                action="login", action_label="Open Login tabs"),
            keywords=("no response captured", "empty", "blank", "nothing came "
                      "back", "no answer", "returned nothing"),
            related=("not-signed-in", "worked-yesterday", "robot-check")),

        Question(
            "change-tool",
            "How do I make a different tool do one of the steps?",
            Answer(
                "Every step in the plan carries the name of the tool that "
                "will do it, and that name is a button. Prism's own "
                "suggestion is marked with a star, and a tool you named in "
                "your task yourself is already chosen.",
                ("Click the tool's name beside the step.",
                 "Pick a different one from the list that drops down.",
                 "Press Start the work when the plan looks right."),
                action="agents", action_label="Change my usual tools"),
            keywords=("swap", "different tool", "chatgpt", "claude", "change",
                      "which ai", "pick", "chip"),
            related=("drop-step", "paid-accounts")),

        Question(
            "drop-step",
            "How do I leave a step out?",
            Answer(
                "Click the row. Steps switched off are skipped, and nothing "
                "runs at all until you press Start the work — so the plan can "
                "be rearranged as much as you like first.",
                ("Click any step in the plan to switch it off.",
                 "Click it again to put it back.",
                 "Press Start the work to run whatever is still switched "
                 "on.")),
            keywords=("skip", "remove step", "exclude", "switch off",
                      "unticked", "just one step"),
            related=("change-tool",)),

        Question(
            "several-jobs",
            "Can I line up several jobs at once?",
            Answer(
                "Yes. Prism queues them and works through them one at a time "
                "while you do something else, then shows you everything "
                "together at the end.",
                ("Type the first job and press Add task.",
                 "Type the next one, and keep going.",
                 "Press Make a plan to start the first."),
                note="On a free Groq allowance, a long queue can run into the "
                     "limit — if it does, wait a minute and carry on."),
            keywords=("queue", "batch", "multiple", "several", "add task",
                      "one after another", "list of jobs"),
            related=("rate-limit", "walk-away")),

        Question(
            "stop-run",
            "How do I stop a run that's going wrong?",
            Answer(
                "Press Stop the run. It winds up cleanly at the next safe "
                "point rather than being killed, so every step that had "
                "already finished is kept and stays in History.",
                ("Press Stop the run.",
                 "Wait a second or two for it to wind up.",
                 "Press Back to the steps to change the plan and try again."),
                action="runs", action_label="Open History"),
            keywords=("cancel", "stop", "abort", "kill", "halt", "wrong",
                      "quit run"),
            related=("where-results",)),

        Question(
            "walk-away",
            "Can I walk away while it's running?",
            Answer(
                "Yes — Prism stops the computer going to sleep on its own "
                "while a run is going, and lets go again at the end. The one "
                "thing that will stop it is shutting the lid, and no "
                "application is allowed to override that.",
                ("Leave the computer switched on and leave the lid open.",
                 "Avoid using the Chrome window Prism has opened while it "
                 "works.",
                 "Come back when it's finished — everything is waiting in "
                 "History.")),
            keywords=("lid", "sleep", "idle", "background", "walk away",
                      "leave it", "screensaver", "close laptop"),
            related=("stop-run", "how-long")),

        Question(
            "where-results",
            "Where do my finished results go?",
            Answer(
                "Everything Prism finishes is kept on this computer and shown "
                "in History — what you asked for, which tools ran, and what "
                "each one said. Nothing is ever deleted on its own, and an "
                "ended licence does not lock you out of any of it.",
                ("Click History in the left sidebar.",
                 "Click any past job to read it again.",
                 "Use Copy output on a step to take the text somewhere else."),
                action="runs", action_label="Open History"),
            keywords=("history", "output", "results", "saved", "where", "past",
                      "previous", "find my work"),
            related=("delete-history", "where-data")),

        Question(
            "how-long",
            "How long should a job take?",
            Answer(
                "A few minutes for a short one, and up to half an hour for a "
                "long job with several steps. Prism is typing into real "
                "websites and waiting for them to answer, so it runs at "
                "roughly the speed you would yourself — the gain is that you "
                "are not sitting there doing it.",
                ("Watch the step cards — each one says what it is doing.",
                 "Leave it running and do something else; it does not need "
                 "watching.",
                 "Press Stop the run if a step has clearly hung.")),
            keywords=("slow", "how long", "speed", "time", "minutes",
                      "waiting", "taking ages", "hung")),
    ))


# ════════════════════════════════════════════════════════════════════════════
#  3 · Signing in to the AI tools
# ════════════════════════════════════════════════════════════════════════════
_SIGNIN = Topic(
    "signin", "lock", "Signing in to the AI tools",
    "Your own accounts, the browser, and the checks websites put up",
    (
        Question(
            "not-signed-in",
            "It says I'm not signed in to one of the tools",
            Answer(
                "Prism works through your own accounts rather than an account "
                "of ours, so it needs you signed in — and the websites sign "
                "people out from time to time. Signing in once is remembered "
                "from then on.",
                ("Click More settings in the left sidebar, then Login tabs.",
                 "Sign in to each tool in the window that opens.",
                 "Close that window and run your job again."),
                action="login", action_label="Open Login tabs"),
            keywords=("signed out", "login", "log in", "not signed in",
                      "password", "account", "session"),
            related=("empty-step", "robot-check", "paid-accounts")),

        Question(
            "robot-check",
            "A tool is asking me to prove I'm not a robot",
            Answer(
                "One of the websites has put up a \"confirm you're human\" "
                "box. Prism cannot click those — stopping software doing "
                "exactly that is what they are for. It normally only asks "
                "once.",
                ("Click More settings in the left sidebar, then Login tabs.",
                 "Tick the box on whichever website is asking.",
                 "Run your job again."),
                action="login", action_label="Open Login tabs"),
            keywords=("captcha", "human", "verification", "cloudflare",
                      "robot", "are you a human", "checkbox"),
            related=("not-signed-in", "empty-step")),

        Question(
            "paid-accounts",
            "Do I need to pay for ChatGPT and the rest?",
            Answer(
                "Only where you would have to anyway. Prism uses whatever "
                "accounts you already have, free or paid, exactly as you "
                "would in the browser yourself — it does not buy anything and "
                "it cannot get you past a website's own limits.",
                ("Pick tools you are already signed in to when you set up "
                 "your usual tools.",
                 "Leave out any tool you don't have an account for — a step "
                 "can always be pointed at another one.",
                 "Upgrade a tool's own plan directly with that company if you "
                 "keep hitting its limits."),
                action="agents", action_label="Change my usual tools"),
            keywords=("subscription", "pay", "cost", "free", "plus",
                      "premium", "chatgpt", "claude", "price"),
            related=("change-tool", "which-addons")),

        Question(
            "chrome-wont-open",
            "Prism couldn't open Chrome",
            Answer(
                "Chrome updates itself every few weeks, and for a day or two "
                "after an update Prism's connection to it can stop matching. "
                "This is the most common cause by a distance.",
                ("Open Chrome, click its menu, then About Google Chrome, and "
                 "let it finish updating.",
                 "Close every Chrome window completely, then try again.",
                 "Clear the version box under Settings → Status → Pin Chrome "
                 "version if you ever typed one in by hand, so Prism finds it "
                 "automatically.",
                 "Check Google Chrome is actually installed — Prism cannot "
                 "use another browser."),
                action="chrome", action_label="Open Chrome settings"),
            keywords=("chromedriver", "session not created", "version",
                      "browser", "won't start", "can't find chrome",
                      "update"),
            related=("chrome-in-use", "other-browser")),

        Question(
            "chrome-in-use",
            "It says the browser is already in use",
            Answer(
                "A previous run left a Chrome window running in the "
                "background, and only one at a time can use Prism's browser.",
                ("Close every Chrome window, including any that Prism opened.",
                 "Try the job again.",
                 "Restart the computer if it still complains — that clears it "
                 "for certain.")),
            keywords=("profile appears to be in use", "user data directory",
                      "already running", "locked", "in use"),
            related=("chrome-wont-open",)),

        Question(
            "other-browser",
            "Can I use Edge, Safari or Firefox instead?",
            Answer(
                "No — Prism drives Google Chrome specifically, and there is "
                "no setting for another browser. Chrome can sit alongside "
                "whichever browser you normally use; you do not have to "
                "change anything about how you browse.",
                ("Install Google Chrome from google.com/chrome.",
                 "Sign in to your AI websites inside Chrome once.",
                 "Carry on using your usual browser for everything else.")),
            keywords=("edge", "safari", "firefox", "brave", "browser",
                      "default browser", "opera"),
            related=("chrome-wont-open", "what-do-i-need")),
    ))


# ════════════════════════════════════════════════════════════════════════════
#  4 · Licence and activation
# ════════════════════════════════════════════════════════════════════════════
_LICENCE = Topic(
    "licence", "archive", "Licence and activation",
    "Keys, seats, expiry, padlocks and moving to a new computer",
    (
        Question(
            "enter-key",
            "Where do I type my licence key?",
            Answer(
                "On the very first screen when Prism has never been "
                "activated, and afterwards in Settings, where you can also "
                "see what your licence covers and when it ends.",
                ("Open Settings from the left sidebar.",
                 "Go to the Licence section and press Change licence key.",
                 "Paste the key in and press Activate."),
                action="licence", action_label="Open Licence settings"),
            keywords=("activate", "key", "licence key", "license", "enter",
                      "activation", "code"),
            related=("how-many-computers", "wrong-version")),

        Question(
            "cant-check-licence",
            "It says it couldn't check my licence",
            Answer(
                "Prism asks our server for permission each time you start "
                "work, and it did not answer. This is almost always the "
                "internet, and it usually clears within a minute — the first "
                "run of the morning sometimes catches the server still waking "
                "up.",
                ("Check this computer is online by loading any website.",
                 "Wait about a minute and press Start the work again.",
                 "Try a phone hotspot if you are on office wifi — a firewall "
                 "may be in the way.",
                 "Open History in the meantime; everything you have already "
                 "produced is still there."),
                action="runs", action_label="Open History"),
            keywords=("licence server", "unreachable", "couldn't reach",
                      "permission", "offline", "server", "connection"),
            related=("offline", "licence-ended")),

        Question(
            "licence-ended",
            "My licence has ended — have I lost my work?",
            Answer(
                "No. Nothing has been taken away. New work is paused, but "
                "History and everything you have already produced stay "
                "exactly where they were and stay readable.",
                ("Open History to reach anything you made before.",
                 "Get in touch for a new key when you want to carry on.",
                 "Paste the new key into Settings — everything switches back "
                 "on straight away, with nothing to reinstall."),
                action="licence", action_label="Open Licence settings"),
            keywords=("expired", "ended", "trial over", "renew", "lapsed",
                      "subscription ended", "lost my work"),
            related=("enter-key", "where-results")),

        Question(
            "padlock",
            "Why does one of the add-ons have a padlock on it?",
            Answer(
                "A padlock means one thing only: that part is not in the "
                "licence you hold. Nothing is broken and nothing has stopped "
                "working — it is sold separately from the plan you have.",
                ("Click the padlocked item to read what it does and what it "
                 "costs.",
                 "Carry on using everything else as normal.",
                 "Get in touch if you want it added — a new key switches it "
                 "on immediately, with nothing to reinstall."),
                action="licence", action_label="See what my plan covers"),
            keywords=("locked", "padlock", "greyed out", "disabled", "can't "
                      "click", "not licensed", "upgrade"),
            related=("which-addons", "licence-ended")),

        Question(
            "how-many-computers",
            "How many computers can I use one licence on?",
            Answer(
                "As many as your licence has seats for — one seat is one "
                "computer. The Licence section of Settings shows your plan "
                "and how many seats it holds, so nobody has to guess.",
                ("Open Settings and look at the Licence section.",
                 "Release a seat on a computer you no longer use: press "
                 "Change licence key there, then Deactivate this computer.",
                 "Get in touch if you need more seats added."),
                action="licence", action_label="Open Licence settings"),
            keywords=("seats", "how many", "computers", "machines", "devices",
                      "laptop and desktop", "second computer", "limit"),
            related=("new-computer", "dead-laptop")),

        Question(
            "new-computer",
            "I've got a new computer — how do I move Prism to it?",
            Answer(
                "Release the seat on the old computer first, then activate on "
                "the new one with the same key. Doing it in that order means "
                "you never need us involved at all.",
                ("Open Settings → Licence on the old computer, press Change "
                 "licence key, then Deactivate this computer.",
                 "Install Prism on the new computer.",
                 "Paste the same licence key in when it asks."),
                action="licence", action_label="Open Licence settings"),
            keywords=("move", "new laptop", "transfer", "migrate", "another "
                      "computer", "replace", "deactivate"),
            related=("dead-laptop", "how-many-computers", "where-data")),

        Question(
            "dead-laptop",
            "My old laptop died and it's still using one of my seats",
            Answer(
                "Releasing a seat normally happens on the computer itself, so "
                "a machine that is gone cannot release its own. We free it "
                "from our side instead — same working day.",
                ("Open Settings → Licence on a computer you still have and "
                 "press Change licence key — the device code is on the line "
                 "that says This computer.",
                 "Email us that code and say which machine has gone.",
                 "Carry on — we will free the seat and confirm."),
                action="licence", action_label="Find my device code"),
            keywords=("stolen", "dead", "broken laptop", "lost", "seat stuck",
                      "seat limit reached", "free a seat", "died"),
            related=("how-many-computers", "new-computer")),

        Question(
            "wrong-version",
            "It says my licence was issued for a different version of Prism",
            Answer(
                "The key is real, but this copy of Prism does not recognise "
                "who issued it — normally an older build meeting a newer key. "
                "It is not something you can have caused.",
                ("Check you are on the latest version of Prism and update if "
                 "not.",
                 "Try the key once more after updating.",
                 "Send us the key and the version number if it still refuses "
                 "— we will reissue it."),
                note="Pressing our email address on the activation window "
                     "prepares a message that already includes your version."),
            keywords=("different version", "not recognised", "rejected key",
                      "wrong key", "issued for", "invalid licence"),
            related=("enter-key", "send-diagnostics")),

        Question(
            "clock-wrong",
            "It says this computer's date looks wrong",
            Answer(
                "Prism checks the date to confirm a licence, and this "
                "computer's clock has gone backwards. Correcting the clock "
                "fixes it completely.",
                ("Open your computer's Date & Time settings.",
                 "Turn on the setting that keeps the date and time up to date "
                 "automatically.",
                 "Connect to the internet and restart Prism.")),
            keywords=("clock", "date", "time", "backwards", "tampered",
                      "wrong date", "timezone"),
            related=("cant-check-licence",)),

        Question(
            "offline",
            "Can I use Prism without the internet?",
            Answer(
                "No, and there is no version of it that could be. Prism works "
                "by driving AI websites in a browser — with no internet there "
                "is nothing for it to drive. Working out the steps and "
                "checking your licence also happen online.",
                ("Keep this computer online whenever you want to run "
                 "something.",
                 "Open History offline to read anything you have already "
                 "produced — that part does not need a connection."),
                note="Your licence is only checked at the START of a run, "
                     "never during one, so a brief wobble halfway through "
                     "will not throw away forty minutes of work."),
            keywords=("offline", "no internet", "without internet", "air "
                      "gapped", "disconnected", "wifi", "local"),
            related=("cant-check-licence", "where-data")),
    ))


# ════════════════════════════════════════════════════════════════════════════
#  5 · Files and attachments
# ════════════════════════════════════════════════════════════════════════════
_FILES = Topic(
    "files", "paperclip", "Files and attachments",
    "Attaching documents and drawings, and where they can come from",
    (
        Question(
            "attach-file",
            "How do I attach a file to a job?",
            Answer(
                "Use Add file or Add folder beside the task box. Adding a "
                "folder brings its files in as one group, so the whole lot "
                "can be taken back out again in one go. Prism tells you what "
                "happened every time, so a button that appears to do nothing "
                "is impossible.",
                ("Press Add file, or Add folder for a whole group.",
                 "Check the file appears in Files you mentioned on the "
                 "right.",
                 "Press Detach all to clear them and start again.")),
            keywords=("attach", "upload", "add file", "document", "pdf",
                      "folder", "paperclip", "include"),
            related=("cloud-files", "first-part-only", "favorites")),

        Question(
            "cloud-files",
            "Can I attach something from Google Drive, OneDrive or Dropbox?",
            Answer(
                "Yes, and there is nothing to connect or sign in to. Press "
                "Add file and Prism lists every cloud folder on this "
                "computer, named with the account they belong to. Picking one "
                "opens the file chooser inside it.",
                ("Install Google Drive for Desktop, or the OneDrive or "
                 "Dropbox app, and sign into it once.",
                 "Press Add file in Prism.",
                 "Pick the cloud folder you want and choose the file."),
                note="Because it works through the folder those apps already "
                     "put on your computer, there is no connection to expire "
                     "and nothing to reconnect each week."),
            keywords=("google drive", "onedrive", "dropbox", "icloud",
                      "cloud", "shared drive", "sharepoint", "connect"),
            related=("attach-file",)),

        Question(
            "first-part-only",
            "One of my files says \"(first part only)\"",
            Answer(
                "Prism reads about the first eight pages of a long document "
                "when it puts text into a request. The label is there so you "
                "always know when that has happened rather than finding out "
                "from a thin answer.",
                ("Hover over the label to see the full explanation.",
                 "Split a long document and attach the part that matters if "
                 "the important content is further in.",
                 "Ignore it where the tool accepts attachments — the whole "
                 "file is still uploaded to those.")),
            keywords=("first part only", "truncated", "cut short", "long "
                      "document", "pages", "shortened", "incomplete"),
            related=("attach-file",)),

        Question(
            "cant-open-file",
            "It says it isn't allowed to open my file",
            Answer(
                "The computer refused access. Usually the file is open in "
                "another program, or it is somewhere protected.",
                ("Close the file if it is open in Word, Excel or a PDF "
                 "reader.",
                 "Copy it to your Desktop and attach it from there.",
                 "Check it isn't inside a folder your computer restricts.")),
            keywords=("permission denied", "access", "not allowed", "read "
                      "only", "locked file", "refused"),
            related=("file-gone", "attach-file")),

        Question(
            "file-gone",
            "It says my file isn't there any more",
            Answer(
                "The file has been moved, renamed or deleted since it was "
                "attached. Prism keeps a path to it rather than a copy, so "
                "the original has to stay put until the job runs.",
                ("Remove it from the attached list.",
                 "Add it again from wherever it is now.")),
            keywords=("file not found", "missing", "deleted", "moved",
                      "renamed", "gone"),
            related=("attach-file", "cant-open-file")),

        Question(
            "mentioned-file",
            "I named a file in my typed task but it wasn't picked up",
            Answer(
                "That is on purpose. When you type, Prism does not go hunting "
                "through your sentence for filenames — it would guess wrong "
                "sooner or later, and a real Add file button is right there. "
                "Spoken tasks are different, because there is no button to "
                "press while talking.",
                ("Press Add file and pick it properly.",
                 "Star the ones you use often so they are one click away next "
                 "time.")),
            keywords=("didn't pick up", "mentioned", "filename", "typed",
                      "ignored my file", "not attached"),
            related=("attach-file", "favorites", "speak-nothing")),

        Question(
            "favorites",
            "What is the Favorites list for?",
            Answer(
                "Files and folders you reach for often — your rate list, your "
                "letterhead, the drawings folder. Star it once and it is one "
                "click away from then on, instead of being found through the "
                "file chooser every time.",
                ("Press the + above Favorites in the left sidebar.",
                 "Pick the file or folder you keep needing.",
                 "Double-click it any time afterwards to attach it.")),
            keywords=("favourites", "favorites", "star", "bookmark",
                      "shortcut", "pinned", "often"),
            related=("attach-file",)),
    ))


# ════════════════════════════════════════════════════════════════════════════
#  6 · The add-ons
# ════════════════════════════════════════════════════════════════════════════
_ADDONS = Topic(
    "addons", "grid", "The add-ons",
    "Email automation, BOQ, Email and Reel / Studio",
    (
        Question(
            "which-addons",
            "What add-ons are there, and which ones do I have?",
            Answer(
                "Email automation reads your mailboxes and keeps your "
                "inquiry register. BOQ measures a drawing. Email writes and "
                "sends from your own account. Reel / Studio makes a short "
                "video. Whichever ones your licence covers are in the "
                "sidebar without a padlock.",
                ("Look at the ADD-ONS group in the left sidebar.",
                 "Click any padlocked one to read what it does and what it "
                 "costs.",
                 "Open Settings to see everything your licence covers in one "
                 "list."),
                action="licence", action_label="See what my plan covers"),
            keywords=("add-ons", "addons", "features", "what do i have",
                      "plan", "included", "extras", "modules"),
            related=("padlock", "paid-accounts")),

        Question(
            "inquiry-safe",
            "Will Email automation change anything in my mailbox?",
            Answer(
                "No. It reads and never writes. Nothing is marked as read, "
                "moved, replied to or deleted, and mail stays exactly as you "
                "left it — so whoever owns the mailbox can carry on using "
                "Outlook on the same account and never notice Prism is "
                "there.",
                ("Open Email automation and add the mailbox details it "
                 "asks for.",
                 "Watch the What arrived tab fill up without your mailbox "
                 "changing.",
                 "Switch on Keep everything on this computer if you would "
                 "rather no message text ever left the machine."),
                feature="inbox"),
            keywords=("inbox", "mailbox", "imap", "outlook", "read", "safe",
                      "mark as read", "delete", "gmail"),
            related=("inquiry-stops", "many-mailboxes", "do-you-see")),

        Question(
            "many-mailboxes",
            "Can Prism read more than one mailbox?",
            Answer(
                "Yes — as many as inquiries arrive at. Most firms have "
                "sales@, info@ and the owner's own address all receiving "
                "work, and every one of them feeds the same register, so "
                "nothing has to be forwarded or copied between inboxes any "
                "more.",
                ("Open Email automation and press Setup.",
                 "Press Add another mailbox on the first step and enter each "
                 "address and its password.",
                 "Press Check my mail now — the register fills from all of "
                 "them, and a Mailbox column says which address each inquiry "
                 "came to."),
                feature="inbox",
                note="Passwords stay on this computer, whichever mailbox "
                     "they belong to. One dead mail server never stops the "
                     "other mailboxes being read."),
            keywords=("multiple mailboxes", "two mailboxes", "several "
                      "accounts", "more than one", "sales@", "info@",
                      "second mailbox", "add mailbox", "many emails"),
            related=("inquiry-safe", "shared-register")),

        Question(
            "shared-register",
            "How do several people see the same inquiry register?",
            Answer(
                "The register is one ordinary file — inquiries.csv — in the "
                "folder you chose at setup. Put that folder on your shared "
                "drive and the whole office opens the same sheet, in Prism "
                "or in Excel, exactly like the one you keep by hand today.",
                ("Open Email automation, press Setup, and go to 2 · Files.",
                 "Choose a folder on the shared drive everyone can reach — "
                 "or press Use the team folder if your Prism workspace is "
                 "set up.",
                 "Let ONE computer do the checking — the office PC that "
                 "stays on. Everyone else reads the register; two machines "
                 "writing the same order book is how a row gets lost."),
                feature="inbox",
                note="Mailbox passwords are never kept in the shared folder "
                     "— only the register and the inquiry files live there."),
            keywords=("shared drive", "everyone", "team", "same file",
                      "central", "one sheet", "excel sheet", "google sheet",
                      "whole office", "other computers"),
            related=("many-mailboxes", "where-data", "team-folder")),

        Question(
            "po-arrives",
            "What happens when the purchase order arrives?",
            Answer(
                "The check files it under 5 · The order came, with the PO "
                "saved into that inquiry's folder. Prism reads the PO and "
                "puts it against the quotation you actually sent — every "
                "changed rate, quantity or delivery date is listed before "
                "anything is accepted. Accepting is a button you press; the "
                "register then shows Converted with the PO number and "
                "value.",
                ("Open the 5 · The order came tab after a check.",
                 "Press Read the PO and compare, and look at what differs.",
                 "Press Accept — mark converted when the order is right — "
                 "or ring the customer first when it isn't."),
                feature="inbox",
                note="A scanned PO is a photograph with no text in it — "
                     "Prism says so and you type the PO number, date and "
                     "value instead. Nothing is ever accepted by itself."),
            keywords=("purchase order", "po", "order came", "accept",
                      "compare", "converted", "po number", "work order"),
            related=("inquiry-stops", "boq-file")),

        Question(
            "inquiry-stops",
            "Will it send a price or accept an order without asking me?",
            Answer(
                "Never. It stops at exactly two points on purpose — before a "
                "price goes to a customer, and before a purchase order is "
                "accepted. It also proposes changes to your register rather "
                "than making them, so you are the one who says yes.",
                ("Read the quote it has prepared in the Inquiries tab.",
                 "Change anything you want changed.",
                 "Press send yourself when you are happy with it."),
                feature="inbox",
                note="No AI ever touches a figure. The arithmetic is done by "
                     "the software from your own rate list, and every line of "
                     "the working is shown."),
            keywords=("automatic", "without asking", "send", "quote", "price",
                      "purchase order", "approve", "confirm"),
            related=("inquiry-safe", "email-send")),

        Question(
            "boq-file",
            "What kind of drawing does BOQ need?",
            Answer(
                "A DXF file, which every CAD program can save. It reads the "
                "geometry directly and counts what is actually on the "
                "drawing, so the numbers are measured rather than guessed. No "
                "drawing at all is fine too — it works from a written "
                "description.",
                ("Save your drawing as DXF from your CAD program.",
                 "Open BOQ and attach it.",
                 "Describe the job in words instead if you have no drawing."),
                feature="boq"),
            keywords=("boq", "dxf", "cad", "drawing", "bill of quantities",
                      "takeoff", "measure", "autocad"),
            related=("boq-dwg", "boq-blank-columns")),

        Question(
            "boq-dwg",
            "It can't read my .dwg drawing",
            Answer(
                "Prism reads DXF rather than DWG. Every CAD program can save "
                "one from the other, and it takes a few seconds.",
                ("Open the drawing in your CAD program.",
                 "Save or export it as DXF.",
                 "Attach the DXF instead.",
                 "Describe the job in words if you cannot convert it — BOQ "
                 "works from a written description too."),
                feature="boq"),
            keywords=("dwg", "autocad", "convert", "can't read", "drawing "
                      "format", "unsupported"),
            related=("boq-file",)),

        Question(
            "boq-blank-columns",
            "Why are the Rate and Amount columns empty?",
            Answer(
                "On purpose. Prism counts and measures; you price. Your rates "
                "are yours — they change by customer, by season and by how "
                "much you want the job — and software that guessed at them "
                "would produce a quotation you could not stand behind.",
                ("Open the spreadsheet it produced.",
                 "Put your own rates into the blank column.",
                 "Check the measured quantities against the drawing line by "
                 "line — they are all shown so they can be checked."),
                feature="boq"),
            keywords=("rate", "amount", "blank", "empty", "price", "costing",
                      "not priced", "columns"),
            related=("boq-file",)),

        Question(
            "email-password",
            "My email password was refused",
            Answer(
                "Gmail and most other providers no longer let an application "
                "sign in with your normal password. They need a separate "
                "app password — a one-off code you create for Prism and can "
                "revoke at any time without changing your real one.",
                ("Go to myaccount.google.com/apppasswords and sign in.",
                 "Create an app password, name it Prism, and copy the sixteen "
                 "letters.",
                 "Paste that into Prism's email setup instead of your real "
                 "password."),
                feature="email"),
            keywords=("app password", "smtp", "gmail", "authentication "
                      "failed", "password rejected", "username and password",
                      "email login", "535"),
            related=("email-password-stored", "email-send")),

        Question(
            "email-send",
            "Will it send email without showing me first?",
            Answer(
                "No. Prism writes the draft, shows it to you, and lets you "
                "edit it. Nothing goes out until you press send. Each "
                "recipient then gets their own copy from your own address — "
                "never a bulk-mail service, and never a visible list of "
                "everyone else.",
                ("Read the draft Prism has written.",
                 "Edit anything you want changed.",
                 "Press send when you are happy with it."),
                feature="email"),
            keywords=("send", "automatic", "draft", "review", "bulk", "bcc",
                      "recipients", "without asking"),
            related=("email-password", "inquiry-stops")),

        Question(
            "reel-or-studio",
            "Which video style should I pick — Studio or Quick?",
            Answer(
                "Studio designs the scenes for this client and films them — "
                "it looks custom because it is, and it takes a few minutes. "
                "Quick draws from Prism's own templates and is ready in under "
                "a minute, with the same look every time.",
                ("Pick Studio when the video is for a customer and has a few "
                 "minutes to spend.",
                 "Pick Quick when you need it now, or when Studio is greyed "
                 "out on this computer.",
                 "Attach a logo, business card or brochure either way — the "
                 "brand colours are taken straight from it."),
                feature="reel",
                note="Studio needs a browser part not every computer has. "
                     "When it can't run, Prism says so and offers Quick "
                     "instead — nothing fails silently."),
            keywords=("studio", "quick", "reel", "difference", "template",
                      "custom", "video style", "which video", "greyed"),
            related=("reel-ffmpeg", "which-addons")),

        Question(
            "reel-ffmpeg",
            "It says making a video needs one extra program",
            Answer(
                "Video needs FFmpeg, a free standard program that most builds "
                "already carry. If yours does not, Prism offers to fetch it "
                "the moment it is needed — you do not have to go and find "
                "it.",
                ("Open Reel / Studio and carry on — Prism asks before "
                 "downloading anything.",
                 "Say yes when it offers FFmpeg — it is roughly 30 MB, takes "
                 "about a minute, and only happens once.",
                 "Carry on. Nothing else on this computer changes, and "
                 "everything else in Prism works without it."),
                feature="reel"),
            keywords=("ffmpeg", "video", "reel", "codec", "encode", "missing "
                      "program", "install"),
            related=("reel-or-studio", "disk-full")),
    ))


# ════════════════════════════════════════════════════════════════════════════
#  7 · Speaking to Prism
# ════════════════════════════════════════════════════════════════════════════
_VOICE = Topic(
    "voice", "mic", "Speaking to Prism",
    "The Speak button and the \"Prism\" wake word",
    (
        Question(
            "speak-nothing",
            "The Speak button doesn't do anything",
            Answer(
                "Speaking needs a sound component that is not on every "
                "computer, and Prism cannot install it for you. Everything "
                "else works perfectly without it — this only ever affects the "
                "microphone.",
                ("Check no other program is holding the microphone.",
                 "Allow Prism to use the microphone in your computer's "
                 "privacy settings.",
                 "Type the job instead — nothing else is affected."),
                note="If it has never worked on this computer rather than "
                     "having stopped, the sound component is missing and we "
                     "can send you the one-line install."),
            keywords=("microphone", "speak", "voice", "mic", "portaudio",
                      "pyaudio", "dictate", "talk", "recording"),
            related=("wakeword-slow", "mentioned-file")),

        Question(
            "wakeword-slow",
            "The wake word is slow, or misses me",
            Answer(
                "Expected, and we would rather say so than let you think it "
                "is broken. Listening for \"Prism\" works by checking the "
                "microphone every couple of seconds rather than by a "
                "dedicated listening chip, so there is a lag and it will "
                "occasionally miss you or start on its own.",
                ("Say \"Prism\" clearly and pause for a second afterwards.",
                 "Press Speak directly instead when the room is noisy.",
                 "Switch the listening off in the sidebar if it triggers when "
                 "it shouldn't.")),
            keywords=("wake word", "wakeword", "listen", "hey prism", "lag",
                      "slow", "misses", "false trigger"),
            related=("speak-nothing",)),
    ))


# ════════════════════════════════════════════════════════════════════════════
#  8 · Language, roles and your team
# ════════════════════════════════════════════════════════════════════════════
_TEAM = Topic(
    "team", "globe", "Language, roles and your team",
    "Reading Prism in your own language, and sharing it across a firm",
    (
        Question(
            "change-language",
            "How do I read Prism in Hindi or Gujarati?",
            Answer(
                "Settings has a Language section. Prism's own screens and the "
                "language the AI writes back in are set separately, on "
                "purpose — plenty of people want to read the buttons in "
                "Gujarati and have the proposal come back in English.",
                ("Open Settings and go to Language.",
                 "Press Change language.",
                 "Pick Prism's own language and, separately, what the AI "
                 "should write back in."),
                action="language", action_label="Open Language settings"),
            keywords=("hindi", "gujarati", "language", "translate", "english",
                      "regional", "marathi", "change language"),
            related=("ai-language",)),

        Question(
            "ai-language",
            "Can the AI write back in a different language from the buttons?",
            Answer(
                "Yes, and that is exactly why they are two separate settings. "
                "Reading the interface in your own language and sending a "
                "customer a proposal in English are different needs.",
                ("Open Settings → Language and press Change language.",
                 "Set the second option — what the AI writes back in — to "
                 "whichever you want."),
                action="language", action_label="Open Language settings"),
            keywords=("output language", "reply", "writes back", "different "
                      "language", "translate output"),
            related=("change-language",)),

        Question(
            "different-colour",
            "Why is my colleague's Prism a different colour?",
            Answer(
                "Because the accent colour follows the role the copy is set "
                "up for. In a firm where several people run Prism side by "
                "side, a glance tells you whose screen you are looking at "
                "without reading anything.",
                ("Open Settings and go to Profile to see which role this "
                 "copy is set to.",
                 "Press Your role and team to change it if the wrong one was "
                 "picked."),
                action="team", action_label="Open Your role and team"),
            keywords=("colour", "color", "different", "accent", "blue",
                      "green", "theme", "colleague"),
            related=("designation-key",)),

        Question(
            "designation-key",
            "What is a designation key?",
            Answer(
                "A short code your company gives you that tells Prism which "
                "job this copy is set up for. It sets the colour, and it "
                "gives you your own folders in a shared team workspace. If "
                "nobody has given you one, you do not need one.",
                ("Open Settings → Profile and press Your role and team.",
                 "Paste the code your company gave you.",
                 "Ignore this entirely if you are the only person using "
                 "Prism."),
                action="team", action_label="Open Your role and team"),
            keywords=("designation", "role", "member", "team", "job title",
                      "code", "who am i"),
            related=("different-colour", "team-folder")),

        Question(
            "team-folder",
            "It says my team workspace can't be reached",
            Answer(
                "The shared folder is offline, so today's work is being saved "
                "on this computer only. Nothing is lost — it simply will not "
                "appear for your manager until the folder is back.",
                ("Check the shared drive is connected on this computer.",
                 "Carry on working — everything is saved locally in the "
                 "meantime.",
                 "Ask whoever runs your network if the drive stays "
                 "unreachable.")),
            keywords=("shared drive", "workspace", "network", "team folder",
                      "unreachable", "offline", "manager", "nas"),
            related=("designation-key", "where-data")),
    ))


# ════════════════════════════════════════════════════════════════════════════
#  9 · Privacy and your data
# ════════════════════════════════════════════════════════════════════════════
_PRIVACY = Topic(
    "privacy", "user", "Privacy and your data",
    "Where things are kept, and what does and doesn't leave this computer",
    (
        Question(
            "where-data",
            "Where is my data kept?",
            Answer(
                "On this computer, in a folder called .prism inside your home "
                "folder. Your settings, your key, and every run Prism has "
                "ever finished live there. None of it sits on a server we "
                "control.",
                ("Open History to reach anything Prism has produced.",
                 "Back up the .prism folder along with the rest of your "
                 "documents if you back this computer up.",
                 "Copy that folder across if you are moving to a new "
                 "computer."),
                action="runs", action_label="Open History"),
            keywords=("data", "where", "stored", "folder", "privacy", "local",
                      "server", "cloud", "backup", "~/.prism"),
            related=("do-you-see", "delete-history", "new-computer")),

        Question(
            "do-you-see",
            "Can you see what I type into Prism?",
            Answer(
                "No. Your tasks go from this computer to the AI websites you "
                "chose, in your own browser, under your own accounts. What we "
                "receive is that your licence asked permission to start a "
                "run, and how much of your allowance was used — never the "
                "content.",
                ("Read what a run sent under Behind the scenes on the right "
                 "of the window.",
                 "Switch on Keep everything on this computer in Email "
                 "automation if you would rather no message text left the "
                 "machine at all.")),
            keywords=("privacy", "private", "see", "read", "confidential",
                      "secret", "my data", "data protection", "spy",
                      "telemetry", "gdpr"),
            related=("where-data", "diagnostics-contents", "inquiry-safe")),

        Question(
            "diagnostics-contents",
            "What's in the diagnostics file? Is my key in it?",
            Answer(
                "No. Your key, your passwords, your licence key and email "
                "addresses are all stripped out before the file is written, "
                "and that stripping is tested — because you cannot reasonably "
                "be expected to read the file before sending it. What is left "
                "describes this installation and the recent log.",
                ("Open Settings and press Change licence key — the sheet "
                 "that opens has Export diagnostics along the bottom.",
                 "Send us the file it saves.",
                 "Open it in any text editor first if you would like to see "
                 "for yourself."),
                action="config", action_label="Open Settings"),
            keywords=("diagnostics", "log", "export", "safe to send",
                      "private", "what's in it", "strip", "redact"),
            related=("send-diagnostics", "crash-log")),

        Question(
            "delete-history",
            "Can I delete my history?",
            Answer(
                "Yes — it is an ordinary folder on this computer, and it is "
                "yours. Prism never deletes any of it on its own, which does "
                "mean it grows over time if you run a lot of video work.",
                ("Copy anything you want to keep somewhere else first — "
                 "deleting cannot be undone.",
                 "Delete the runs you no longer want from the .prism folder "
                 "in your home folder."),
                action="runs", action_label="Open History"),
            keywords=("delete", "clear", "history", "space", "disk", "clean "
                      "up", "remove runs", "storage"),
            related=("where-data", "disk-full")),

        Question(
            "email-password-stored",
            "Where is my email password kept?",
            Answer(
                "In the settings file on this computer, and nowhere else. It "
                "is used only to send from your own account. This is also why "
                "an app password is worth using — you can revoke it at any "
                "time without touching your real one.",
                ("Use an app password rather than your real one.",
                 "Revoke that app password with your email provider if you "
                 "ever stop using Prism.")),
            keywords=("password", "email", "smtp", "stored", "saved",
                      "security", "credentials"),
            related=("email-password", "where-data")),
    ))


# ════════════════════════════════════════════════════════════════════════════
#  10 · When something breaks
# ════════════════════════════════════════════════════════════════════════════
_BROKEN = Topic(
    "broken", "alert", "When something breaks",
    "The messages Prism shows, and what each one means",
    (
        Question(
            "wont-start",
            "Prism won't open at all",
            Answer(
                "Work through these in order — the first two account for "
                "almost every case.",
                ("Click through your computer's first-launch warning if this "
                 "is the first time: More info then Run anyway on Windows, or "
                 "right-click then Open on a Mac.",
                 "Restart the computer and try once more.",
                 "Check there is free space on the disk.",
                 "Send us the crash log from the .prism folder if it still "
                 "will not open — it says exactly what happened.")),
            keywords=("won't open", "crash", "closes", "nothing happens",
                      "quits", "start", "launch", "immediately closes"),
            related=("os-warning", "crash-log", "disk-full")),

        Question(
            "rate-limit",
            "It says my allowance is used up",
            Answer(
                "Groq — the free service that works out your steps — only "
                "allows so many requests in a short period, and you have "
                "reached it. Nothing is broken and nothing is lost.",
                ("Wait one minute, then press Make a plan again.",
                 "Run a few at a time rather than queueing several at once.",
                 "Raise your own limits at console.groq.com if you hit this "
                 "often — it is your account, not ours.")),
            keywords=("rate limit", "allowance", "used up", "429", "too many",
                      "quota", "limit reached", "slow down"),
            related=("groq-key", "several-jobs")),

        Question(
            "key-rejected",
            "It says my key was rejected",
            Answer(
                "The key Prism uses to work out your steps was refused. "
                "Usually it was deleted at the other end, or only part of it "
                "was pasted in.",
                ("Go to console.groq.com and sign in.",
                 "Open API Keys and create a new one — it begins with gsk_.",
                 "Copy the whole of it and paste it into Settings → Status → "
                 "Change API key."),
                action="key", action_label="Open the key setting"),
            keywords=("rejected", "invalid key", "401", "unauthorized", "bad "
                      "key", "wrong key", "not working"),
            related=("groq-key", "rate-limit")),

        Question(
            "model-changed",
            "It says the model Prism uses has changed",
            Answer(
                "Groq occasionally retires the models it offers. Prism "
                "normally moves to another one by itself without you noticing, "
                "so seeing this means every one it knows about is unavailable "
                "on your key.",
                ("Press Make a plan once more — Prism will try the next one.",
                 "Get in touch if it keeps failing; this one needs an update "
                 "from us rather than anything at your end.")),
            keywords=("model", "decommissioned", "retired", "deprecated", "no "
                      "longer available", "changed"),
            related=("key-rejected", "send-diagnostics")),

        Question(
            "disk-full",
            "It says the computer has run out of space",
            Answer(
                "The disk is full, so Prism could not save. Video work fills "
                "a disk faster than anything else Prism does.",
                ("Empty the Trash or Recycle Bin.",
                 "Delete or move some large files.",
                 "Clear out old video runs from the .prism folder in your "
                 "home folder — they are the biggest thing Prism keeps.")),
            keywords=("disk full", "no space", "storage", "out of space",
                      "errno 28", "full"),
            related=("delete-history", "reel-ffmpeg")),

        Question(
            "crash-log",
            "It crashed — where's the log?",
            Answer(
                "Prism keeps one in a logs folder inside .prism in your home "
                "folder, because a packaged app has no window to print an "
                "error into. The tidier route is the diagnostics file, which "
                "wraps the log up with everything else we would ask you for.",
                ("Open Settings and press Change licence key — the sheet "
                 "that opens has Export diagnostics along the bottom.",
                 "Email us the file it saves.",
                 "Tell us roughly what you were doing at the time — it makes "
                 "the log far quicker to read."),
                action="config", action_label="Open Settings"),
            keywords=("crash", "log", "logs", "error file", "report",
                      "diagnostics", "where"),
            related=("send-diagnostics", "diagnostics-contents")),

        Question(
            "worked-yesterday",
            "It worked yesterday and today a step comes back empty",
            Answer(
                "The AI companies redesign their websites whenever they like, "
                "and when one does, Prism can lose track of where to type. "
                "Any software that drives a browser has this problem, and we "
                "would rather be straight with you about it than pretend "
                "otherwise. We normally push a fix within a day.",
                ("Check you are still signed in first — click More settings "
                 "in the left sidebar, then Login tabs. That is the more "
                 "common cause by far.",
                 "Point that step at a different tool by clicking the tool's "
                 "name in the plan.",
                 "Press Open in tool beside the step to finish that part by "
                 "hand — the link is always kept.",
                 "Tell us which tool it was so we can push the fix."),
                action="login", action_label="Open Login tabs"),
            keywords=("suddenly", "worked before", "stopped working",
                      "yesterday", "broken", "website changed", "redesign"),
            related=("empty-step", "not-signed-in")),

        Question(
            "send-diagnostics",
            "How do I send you the details of a problem?",
            Answer(
                "Prism writes one file describing this installation, your "
                "licence, and the recent log — with your key, passwords and "
                "email addresses stripped out. That one file usually tells us "
                "everything we need.",
                ("Open Settings and press Change licence key — the sheet "
                 "that opens has Export diagnostics along the bottom.",
                 "Email the file it saves to us.",
                 "Say what you were doing when it happened, and roughly "
                 "when."),
                action="config", action_label="Open Settings"),
            keywords=("send", "support", "report", "diagnostics", "help",
                      "contact", "email us", "problem"),
            related=("diagnostics-contents", "crash-log")),
    ))


TOPICS: tuple[Topic, ...] = (
    _START, _RUNNING, _SIGNIN, _LICENCE, _FILES, _ADDONS, _VOICE, _TEAM,
    _PRIVACY, _BROKEN,
)


# ── lookups ────────────────────────────────────────────────────────────────
_BY_ID: dict[str, Question] = {
    q.qid: q for topic in TOPICS for q in topic.questions}
_BY_KEY: dict[str, Topic] = {topic.key: topic for topic in TOPICS}


def question(qid: str) -> Question | None:
    return _BY_ID.get(qid)


def topic(key: str) -> Topic | None:
    return _BY_KEY.get(key)


def all_questions() -> tuple[Question, ...]:
    return tuple(_BY_ID.values())


def related_to(qid: str) -> list[Question]:
    """The questions worth offering next. Never includes the one just read."""
    q = _BY_ID.get(qid)
    if not q:
        return []
    return [_BY_ID[r] for r in q.related if r in _BY_ID and r != qid]


# ── search ─────────────────────────────────────────────────────────────────
# Deliberately not fuzzy. A customer types four or five words; the job is to
# put the right answer in the top three, and a scoring rule simple enough to
# reason about does that more reliably than an edit-distance measure nobody
# can predict. When it genuinely has nothing, it must return NOTHING — a
# confident wrong answer is what makes people stop trusting the box, and an
# empty result is what opens the route to a person.
_STOPWORDS = frozenset("""
a an and are as at be but by can cant do does doesnt for from get got has have
how i im in is it its me my not of on or our so that the their them then there
these they this to up us was way we were what when where which who why will with
you your prism
""".split())
# NB: "app" is deliberately NOT a stopword. "app password" is the exact term
# Google puts on the screen the customer is stuck on, and dropping the first
# half of it sent that search to the wrong answer.

_WORD_RE = re.compile(r"[a-z0-9]+")


def _words(text: str) -> list[str]:
    return [w for w in _WORD_RE.findall((text or "").lower())
            if w not in _STOPWORDS and len(w) > 1]


def _score(query_words: list[str], q: Question) -> tuple[int, int, int]:
    """How well one question answers this query.

    Returns (score, strong hits, phrase hits). Weighted by where the word was
    found, because the three fields are not equally good evidence: a hit in
    the question text is the customer using our own words back at us, a
    keyword hit is the vocabulary we anticipated and is worth the same, and
    the answer body is the weakest — every answer in here mentions Settings —
    so it scores one.
    """
    heading = set(_words(q.text))
    keys = set()
    for keyword in q.keywords:
        keys.update(_words(keyword))
    body = set(_words(q.answer.what)) | set(
        _words(" ".join(q.answer.steps))) | set(_words(q.answer.note))

    total = strong = 0
    for word in query_words:
        if word in heading or word in keys:
            total += 4
            strong += 1
        elif word in body:
            total += 1

    # A typed phrase that appears verbatim in a keyword ("app password", "no
    # space left") is the strongest signal there is, and splitting it into
    # words throws that away. Cheap enough to check both ways.
    phrases = 0
    joined = " ".join(query_words)
    for keyword in q.keywords:
        if len(keyword) > 4 and keyword in joined:
            total += 3
            phrases += 1
    return total, strong, phrases


def search(text: str, limit: int = 4) -> list[Question]:
    """The questions worth offering for something typed. Best first.

    Returns [] rather than a weak guess, and that emptiness is load-bearing:
    `widgets/support_panel.py` reads it as "we have no answer for this" and
    opens the route to a person on the spot. So the bar is set by what a
    WRONG answer costs — somebody sent to read about purchase orders because
    they typed "refund my order" has been actively obstructed, and would have
    been better served by an honest miss.

    Hence the second condition. One incidental word landing on one keyword is
    not a match when the customer wrote a whole sentence; it is a match when
    they typed one word, because then it is everything they gave us.
    """
    query_words = _words(text)
    if not query_words:
        return []
    hits = []
    for q in all_questions():
        total, strong, phrases = _score(query_words, q)
        if total < 4:
            continue
        convincing = (strong >= 2 or phrases or len(query_words) <= 2)
        if convincing:
            hits.append((total, q))
    hits.sort(key=lambda pair: (-pair[0], pair[1].qid))
    return [q for _s, q in hits[:limit]]


# ── handing the whole thing to the assistant ───────────────────────────────
def as_text(q: Question) -> str:
    """One question and its answer as plain text — for the conversation log,
    the email to support, and the material handed to the assistant. The twin
    of `friendly.as_text`, and the same shape on purpose."""
    lines = [f"Q: {q.text}", f"A: {q.answer.what}"]
    lines += [f"   {i}. {s}" for i, s in enumerate(q.answer.steps, 1)]
    if q.answer.note:
        lines.append(f"   Note: {q.answer.note}")
    return "\n".join(lines)


def as_context(query: str = "", seen: tuple[str, ...] = (),
               limit_chars: int = 9000) -> str:
    """The knowledge base, shaped for one question, to hand to the model.

    The assistant tier (widgets/support_panel.py) answers from THIS rather
    than from whatever it happens to remember about a product it has never
    seen. Without it the model invents menu items — plausible ones, which is
    worse than useless, because the customer goes looking for a Preferences
    window that does not exist.

    Everything at once is 30,000 characters, which is both slow and mostly
    irrelevant to whatever was actually asked. So it sends two things instead:
    every question HEADING, so the model knows the true shape of the product
    and can say "that is covered under Licence" without being told; and the
    FULL answer for the handful that bear on this question — the ones the
    customer has already read (so the model does not repeat them back) and the
    ones their wording matches.
    """
    index = ["EVERY QUESTION PRISM'S HELP CAN ANSWER (headings only):"]
    for t in TOPICS:
        index.append(f"\n[{t.label}]")
        index += [f"  - {q.text}" for q in t.questions]

    wanted: list[str] = []
    for qid in seen:
        if qid not in wanted and qid in _BY_ID:
            wanted.append(qid)
    for hit in search(query, limit=4):
        if hit.qid not in wanted:
            wanted.append(hit.qid)
    for qid in list(wanted):
        for rel in _BY_ID[qid].related:
            if rel in _BY_ID and rel not in wanted:
                wanted.append(rel)

    detail = ["\n\nTHE ANSWERS MOST LIKELY TO BE RELEVANT, IN FULL:"]
    budget = limit_chars - sum(len(line) + 1 for line in index)
    for qid in wanted:
        block = "\n" + as_text(_BY_ID[qid])
        if len(block) > budget:
            break
        detail.append(block)
        budget -= len(block)

    return "\n".join(index) + "\n".join(detail)
