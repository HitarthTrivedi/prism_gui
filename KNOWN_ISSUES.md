# What can go wrong with Prism — in plain words

For you, and for whoever answers the phone when a customer calls.

Everything here is sorted into four buckets:

| Bucket | Meaning |
|---|---|
| **FIXED** | Was a problem. Now handled in the code. Nothing for you to do. |
| **CODE** | We can fix it by writing code. Not done yet. |
| **MONEY** | Code can't fix it. It needs a paid plan, or an account somewhere. |
| **NEVER** | Nobody can fix it. Plan around it and be honest with customers. |

Last reviewed against the working tree with 223 passing tests.

---

## MONEY — things only a subscription or an account can fix

### 1. The licence server falls asleep

**What happens.** Prism asks our licence server for permission every time
someone presses *Start the work*. Free hosting puts a server to sleep after
about 15 minutes of quiet, and it takes 30–60 seconds to wake up. So the first
run of the morning is asking a server that is still getting out of bed.

**What we already did.** Prism now waits 45 seconds instead of 15, and tries a
second time if the first attempt gets nothing. That covers most cold starts.

**What still needs money.** A paid hosting plan so the server never sleeps.
Until then a customer may occasionally wait a minute on their first run of the
day. **Roughly $7/month.** This is the single cheapest reliability improvement
available to us.

**Interim workaround, free:** set up any free uptime monitor (UptimeRobot and
similar) to load the server's `/health` page every 10 minutes. That keeps it
awake without a paid plan. Ten minutes to set up.

**What to tell a customer:** nothing. They should never see this once the
server stays awake.

---

### 2. Google Drive weekly disconnect — *only if we use the OAuth route*

**What happens.** Google expires the connection every 7 days for apps whose
consent screen is still in "Testing" mode. The customer would have to press
*Connect* again every week.

**What we already did.** We stopped needing OAuth at all. Prism now reads
Google Drive as a **normal folder** through Google Drive for Desktop, which
the customer installs once and signs into once. Nothing expires. Nothing to
connect. See *FIXED #1*.

**What still needs an account.** Only if you later want Drive to work for
someone who will *not* install Drive for Desktop. Then you need a Google Cloud
project with a published consent screen. Free, but Google reviews it and that
takes a few days.

**Recommendation:** don't bother. Drive for Desktop is better in every way
that matters here.

---

### 3. Groq's free tier runs out on a busy day

**What happens.** Groq limits how many requests a free key can make per minute
and per day. A customer queueing five tasks in a row can hit it.

**What we already did.** Prism now recognises a rate limit, waits the time
Groq asks for, tries again, and if it still fails says *"Groq is rate-limiting
your API key. Wait a minute and try again, or raise your limits at
console.groq.com."* — instead of a raw error code.

**What needs money.** The customer upgrading their own Groq plan. It is their
key, not ours, so this is a sentence in the setup guide, not a cost to us.

---

### 4. Apollo runs out of email credits

**What happens.** Apollo's free plan only reveals so many verified emails per
month. After that the table comes back empty.

**What we already did.** The message now names credits as one of the three
things that cause an empty table, so nobody wastes an hour checking their
filters.

**What needs money.** The customer's own Apollo plan.

---

### 5. A dead or stolen laptop keeps its seat

**What happens.** Releasing a seat happens on the computer. If the computer is
gone, the customer cannot release it, and they have paid for a seat they
cannot use.

**What needs doing.** Not code in the app — a button on our side, plus a
written promise. Prism already shows the device code in Settings and the
support email next to it, which is the half we control.

**What to tell a customer:** "Email us the device code from Settings and we'll
free the seat the same working day."

---

## NEVER — nobody can fix these

### 6. The websites change their design

**What happens.** Prism types into ChatGPT, Claude and the rest by looking for
specific bits of their page. Those companies redesign whenever they like, and
when they do, a step comes back empty.

**Why it can't be fixed.** We do not control their websites. Any tool that
drives a browser has this problem — there is no version of Prism where this
goes away.

**What we already did.** When a step comes back empty, Prism checks whether
the page is actually a login wall or a "are you a robot" check, and says so
specifically. The link to the tab is always kept, so the work is still
reachable by hand.

**What we should still add (see CODE #9).** A *Check my tools* button, and a
way to fix a broken selector over the phone without shipping an update.

**What to tell a customer:** "The AI tools change their websites; when that
happens we push an update, usually within a day. Your work is never lost —
Prism keeps the link to the tab."

---

### 7. No internet, no Prism

**What happens.** Prism needs the internet for everything: Groq for planning,
the browser for every tool, and our server for the licence.

**Why it can't be fixed.** The product is a pipeline through other people's
websites. There is nothing to run offline.

**What we already did.** The licence is only checked at the *start* of a run,
never in the middle — so a wobble halfway through will not throw away forty
minutes of work. And Prism now says *"Couldn't reach Groq — check your
internet connection"* rather than a technical error.

---

### 8. Closing the laptop lid stops a run

**What happens.** The machine sleeps, the browser session dies.

**Why it can't be fixed.** No application is allowed to override the lid.

**What we already did.** Prism now stops the machine sleeping *on idle* while
a run is going, so walking away is fine. Only the lid matters.

**What to tell a customer:** "Leave it running and walk away — just don't shut
the lid."

---

## CODE — we can fix these, not done yet

### 9. Nothing warns us when a tool's website changes

Add a **Check my tools** button that opens each tool and confirms Prism can
still find the box to type in — a 30-second check before a big job. And read
selector fixes from a small file in `~/.prism` so a broken tool can be fixed
over the phone in two minutes instead of a new release. *About a day's work.*

### 10. The history folder grows forever

Every run and every video is kept, and nothing is ever cleaned up. After a
year of daily use that is gigabytes in a hidden folder. Show the size in
Settings with a "keep the last N runs" option. Never delete without asking —
that history is their work. *A few hours.*

### 11. Chrome profile lock after a crash

If Prism crashes, a leftover browser lock can make every later run fail with
"profile appears to be in use". Clear a stale lock on startup, and add a
"Close Prism's browser" item to the sidebar. *A few hours.*

### 12. Disk full during a video render

Check free space before starting, and say so up front. Settings are already
safe — Prism writes them in a way that survives a power cut. *An hour.*

### 13. A task queue gives up too easily on a slow server

A licence *refusal* should stop the whole queue — that is correct. A licence
*timeout* should retry that one task first. Right now both stop everything.
*An hour.*

### 14. Windows has not been properly tested

The messages about missing FFmpeg and microphone support are written for a
Mac. A customer on a fresh Windows machine hits both and gets Mac
instructions. Needs a real pass on a Windows box before selling one.

---

## FIXED — already handled, nothing to do

### 1. Attaching files from Google Drive

**Add file** now asks where the file is and lists every cloud folder on the
machine — Google Drive (named with the account, e.g. *Google Drive —
ravi@firm.com*), Shared drives, OneDrive, Dropbox and iCloud. Picking one just
opens the file chooser inside that folder.

No sign-in, no connecting, nothing to expire. The customer installs Google
Drive for Desktop once; after that their Drive is simply a folder, under
whichever account they are already signed into.

### 2. Groq retiring a model

Prism used to have one model name written into it. The day Groq retired it,
every customer would have stopped being able to plan anything, at the same
hour. Prism now has a **list** of models: if one is gone it quietly moves to
the next, saves the working one, and carries on. The customer sees nothing.

### 3. Rate limits and bad keys

A rate limit waits and retries once. A rejected key says *"Groq rejected your
API key. Re-enter it in Setup → Groq API key."* No more raw HTTP codes.

### 4. No way to see what went wrong

Prism now keeps a log in `~/.prism/logs`, and **Settings → Export
diagnostics** writes one text file describing the installation, the licence,
what is installed, and the recent log. The customer emails it and support can
see what happened.

**The API key, passwords, licence key and email addresses are stripped out of
it** — tested, because a customer cannot check the file before sending it.

### 5. The machine sleeping mid-run

Prism holds the machine awake for the length of a run and lets go at the end,
including if the window is closed mid-run.

### 6. Chrome won't start

Instead of a wall of technical text, Prism now explains that Chrome has
probably updated, and gives the two things that fix it.

### 7. The clock being wrong

The message now tells them to check the date and time in their computer's
settings, instead of just saying the clock went backwards.

### 8. Long documents being cut short silently

Prism reads the first 12,000 characters of a file — about 8 pages. Attachments
that get cut now say **"(first part only)"** on the row, with the full
explanation on hover. It still uploads the whole file to any tool that accepts
attachments.

### 9. The shared team folder going offline

Work is saved locally so nothing is lost, and a banner now says: *"Your team
workspace can't be reached, so today's work is being saved on this computer
only — it will not appear for your manager until the folder is back."*

### 10. Attaching and un-attaching files

Adding a folder shows one row for the folder with its files underneath, so it
can be removed in one go. There is a **Detach all**. The same file cannot be
attached twice. And every outcome of pressing *Add file* now says what
happened, so a button that appears to do nothing is impossible.

### 11. Apollo being fed a paragraph

Apollo is a search screen, not a chatbot, and its fields reject anything over
200 characters. Prism now tells the previous step to hand over a short filter
block instead of prose, and drives Apollo through its own search URL.

### 12. Canva taking over every image

Connecting Canva to ChatGPT made every post come back as a flat template.
Canva is now only used when the request actually asks for something editable.

---

## The honest summary for a sales conversation

Prism already fails *gracefully* in the places that matter: a stopped run
keeps everything finished so far, a failed step keeps the link so the work is
still reachable, partial results are never thrown away, settings survive a
power cut, and a licence problem still lets someone open their own past work.

The two things worth being straight about:

1. **It drives other people's websites.** When they redesign, a step can break
   until we push an update. Usually a day.
2. **It needs the internet.** All of it. There is no offline mode and there
   was never going to be one.
