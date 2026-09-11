# What changed

Written for the person who has to pick this up later — each entry says what it
was, what it is now, and why the change was made, because the "why" is the
part that gets lost.

Tests: **1966 passing** (6 skipped, 8 Sep 2026 after Round 16 landed on main — see
`.claude/agents/prism-test-doctor.md`), plus 148 scenario checks
(`devtools/scenarios.py`).

---

# 1.5.5 — the macOS in-app update produced an app that would not open

Found by the first real macOS in-app update (1.5.2 → 1.5.4, 10 Sep 2026):
the update downloaded, verified, swapped in and relaunched — and Prism.app
never opened again. No window, no log line, no rollback. The backup was
beside it as `Prism.app.old`; restoring it by hand brought 1.5.2 back.

**Was:** `update_manifest.build()` listed the tree with `os.walk()`, whose
`filenames` never include a symlink that points at a *directory* — those
are reported in `dirnames` and, with `followlinks=False`, never descended
into either. So they were never recorded. A PyInstaller macOS bundle is
built on exactly those links: every framework's `Versions/Current → A`,
and `Python.framework/Versions/Current → 3.12`. The *file* links that go
through them (`Python.framework/Python → Versions/Current/Python`, the
seventeen Qt framework binaries) WERE recorded and recreated, so the
staged bundle had every file, every file link, and nothing for the links
to point at. dyld could not load Python.framework, so the process died
before a line of Prism ran — which is also why the two-phase rollback
marker never got its second launch: it needs Python to reach `main.py`.
Linux and Windows bundles have no directory symlinks, which is why the
real frozen-Linux update test in 1.4.2 passed and this waited for a Mac.

**Now:** `build()` records directory symlinks from `dirnames` as the same
`{"path", "symlink"}` entries file symlinks already use; the client's
`stage_update()` has created those since 1.4.1, so a 1.5.2 or 1.5.4 Mac
updating to 1.5.5 gets a complete bundle. And a gate:
`update_manifest.dangling_symlinks()` resolves every link in the manifest
through every other link in it, and `packaging/manifest.py` fails the CI
build if any link points at nothing the manifest carries — run against
the shipped 1.5.4 macOS manifest it reports every broken link that build
had. `tests/test_update_manifest.py` builds a framework-shaped tree and
checks both halves.

**Stated plainly for anyone on a Mac:** a 1.5.2 or 1.5.4 Mac that takes
the in-app update to 1.5.5 is fine — the fix is in the manifest CI builds,
not in the client. A Mac that already took 1.5.4 in-app and will not open:
in Terminal, `mv /Applications/Prism.app /Applications/Prism-broken.app &&
mv /Applications/Prism.app.old /Applications/Prism.app && rm -f
/Applications/Prism.app.prism_update_pending`, then open Prism; it is 1.5.2
again and will offer 1.5.5. The 1.5.4 DMG itself was always fine.

Still open: the rollback can only act once Python runs. A launch that dies
in dyld needs a supervisor (the apply helper waiting on the relaunched PID
for a few seconds) to notice; the next hardening step.

---

# 1.5.4 — a file the tool made is a result, on every step, and it lands in Artifacts

Reported 10 Sep 2026: "the agent gives the document but Prism couldn't
read it" — the card said *Prism couldn't read the response off the page*,
the run recorded a failure, and the DOCX/XLSX the tool had plainly
produced was either never saved or saved and never mentioned. BUGS.md #3.

**Was:**

* Files were harvested on six stages only (development, presentation,
  format, content, write, audio). A tool asked on research, brains, leads
  or summary for "an Excel of this" made one and Prism walked past it.
* The candidate test for "this link is a file" was: extension in the
  href, a `download` attribute, or a `blob:` URL. ChatGPT's generated-file
  chip is none of those — a signed, extension-less URL whose only clue is
  the link text "report.docx" — so it was skipped as a navigational link.
  The click fallback then looked for a control labelled "Download"; the
  chip is labelled with the filename; nothing was found.
* Harvesting ran before the "did the tool answer?" decision but was not
  part of it: a reply that was the file alone, with no prose over fifty
  characters, fell through to `it returned nothing`.
* The saved copy was named `<task> — Content.pdf`; the tool's own filename
  was thrown away.

**Now:**

* `_harvest_stage_files()`: every non-image stage is looked at. The six
  producer stages keep their patient wait; every other stage gets one
  free probe of the page (no sleep) and waits only when a file link is
  already there or the reply's own words say one is coming
  (`_FILE_HINT_RE`). The click-and-wait fallback runs only with such a
  reason (`click_fallback`). The customer's own attachments, which come
  back as identical chips in their turn, are skipped by name.
* `_filename_in_text()`: an anchor whose visible text is a filename counts
  as a file, and that name is kept — the temp file, the attachment record
  (`_site_name`) and the Artifacts copy (`save_artifact(name=…)` →
  `<task> — Research — Product Brief.docx`).
* A step that produced a file and no text is a result: the stage's text
  becomes a short note naming the file (`_files_as_reply`), the run
  records success, the next step receives both the note and the file.
  `stage_done` carries `files`; the card prints "Saved to Prism
  Artifacts: Product Brief.docx · 0.1 MB".

Not changed: image harvesting stays on the visual/media/artwork stages
(on a text step, an `<img>` sized like a picture is as likely to be the
customer's own upload). Claude's side-panel artifact still depends on the
page exposing a download control; the click path is unchanged there.

Tests: `tests/test_cross_platform_browser.py` (+11: the ChatGPT chip, the
customer's upload, the gated click fallback, every-stage probing, the
file-only reply), `tests/test_artifacts_config.py` (+1, the kept name).

## Also in 1.5.4 — "Studio makes artwork on Linux, not on Mac or Windows"

Reported the same day. The artwork step exists only on the Studio path:
the routed run inserts it before Prism Studio's design stage, and the
Reel window inserts it only when the *Studio* renderer is chosen. On a
machine where Studio's browser is not found, the Reel window greyed the
Studio option with a tooltip and quietly ran *Quick*, which has no artwork
step — so the report is accurate and the cause is upstream of artwork.

Checked against the 1.5.2 release manifests: the macOS and Windows
bundles DO ship Playwright's Chromium and node driver (353 and 314 files
under `.local-browsers/`), so a missing browser in the build is not it.
What is left, and what this release does about each:

* **The Artifacts folder could not be written and nothing said so.**
  `~/Desktop/Prism Artifacts` needs the person's permission on macOS
  (a packaged app is asked once; "Don't Allow" made every save a
  PermissionError that `_save_artifacts` swallowed), and on Windows with
  OneDrive's Known Folder Move the Desktop is `…\OneDrive\Desktop` and
  `C:\Users\x\Desktop` may not exist, so Prism made an invisible one.
  Now: `config._desktop_dir()` asks the Windows shell where the Desktop
  is; `config.artifacts_root()` verifies the folder is writable once per
  process and otherwise falls back to `~/Prism Artifacts`, saying so; the
  Artifacts screen and Settings show the folder actually in use;
  `_save_artifacts` warns with the reason instead of `continue`.
* **Studio unavailable was invisible.** The Reel window now says on the
  page why Studio cannot run here, and Export diagnostics gains three
  lines: `Prism Studio yes/no — why`, `Studio browser <path>`, and
  `Artifacts folder <path>` with a note when the Desktop one was refused.
* **Not verifiable from here:** whether the packaged Mac's Chromium and
  node launch on a customer's machine at all. An unsigned, quarantined
  `.app` can have its nested executables refused by Gatekeeper, and the
  build gate runs on a runner that never sees quarantine. The next Mac or
  Windows report should come with Export diagnostics; the three new lines
  answer this in one look.

---

# 1.5.3 — a Mac closes its own leftover Chrome, and never runs an Intel driver without Rosetta

Found by reading the client's M2 failure end to end (10 Sep 2026) instead
of the errno alone. "Chrome opened, no profile, no ChatGPT" was four things
stacked; 1.5.2 removed one of them.

**Was:**

* `_posix_chrome_pids()` took the first whitespace-separated token of the
  `ps` line as the program. On a Mac that is `/Applications/Google` (the
  binary is `…/Google Chrome.app/Contents/MacOS/Google Chrome`), basename
  "Google", so no Mac Chrome ever matched and `_release_profile()` was a
  silent no-op on every Mac. The Chrome left running by Login tabs (closing
  a Mac app's windows does not quit it) and the browser undetected-
  chromedriver launches *before* it starts the driver were never closed;
  the next launch handed itself to them and chromedriver said "cannot
  connect to chrome". That is also why the 1.5.1/1.5.2 errno-86 retry
  could not work on a Mac: the retry's Chrome handed off to the first
  attempt's orphan.
* undetected-chromedriver 3.5.5 has no `mac-arm64` in its platform table
  (`win32`, `linux64`, `mac-x64`), so on *every* Mac it downloads the Intel
  driver. Whenever Prism's own arm64 download failed — offline, a proxy,
  Chrome for Testing not yet listing a just-updated major — the fallback
  was a certain errno 86, shown as "Chrome updated itself, update Chrome".
  The reason every Mac at Alphakore worked: Rosetta was already on them,
  pulled in long ago by some Intel app, so the Intel driver ran. macOS
  never offers to install Rosetta for a binary a program executes; that
  just fails.
* `friendly.py`'s version-mismatch rule (pattern "chromedriver") rewrote
  the engine's Intel/Rosetta explanation; the true text sat under
  Technical detail.
* uc's browser finder looks in `/Applications` only. Prism's own finder
  knows `~/Applications` (a no-admin install), but never told uc — so
  Login tabs worked and every run said Chrome was not installed.
* The source-zip hand-off (`Install and Run Prism.command`) ran a Python
  with no CA bundle; the certifi patch lived only in the PyInstaller hook.

**Now:**

* The program is everything before the first ` --`; five Mac `ps` lines in
  `tests/test_cross_platform_browser.py`, helper process included, the
  everyday Mac Chrome and a script that names the path still left alone.
* `_refuse_intel_fallback()`: on Apple silicon with no arm64 driver and no
  Rosetta (`_rosetta_installed()` — two files, then a real `arch -x86_64`
  exec), Prism stops with "needs its Apple silicon browser driver … check
  this Mac is online and press Start again" and never calls uc. With
  Rosetta, uc chooses as before. `_apple_silicon_driver()` now tries the
  exact major, then `STABLE`, then any arm64 driver already in
  `~/.prism/chromedriver/` (newest first) before giving up.
* `browser_executable_path` is passed to uc from Prism's own finder.
* `friendly.py`: rules for errno 86 / "built for Intel Macs" and for the
  missing arm64 driver, placed before the version-mismatch rule; the
  "cannot connect" and "profile in use" rules tell a Mac user to quit
  Chrome with ⌘Q. The engine's own "cannot connect" text says the same on
  Darwin.
* `main.py` `_ensure_tls_trust()`: the same certifi patch as the runtime
  hook, applied when running from source on macOS.
* Export diagnostics gains a "Browser driver" section
  (`automation.driver_report()`): CPU, Rosetta, Chrome path and version,
  every driver file with the CPU it was built for, and whether a Chrome is
  sitting on Prism's profile right now.

Tests: `tests/test_chrome_driver_arch.py` (+9, incl. `NoRosettaNoIntelDriver`
and `TheDriverReport`; `test_without_an_own_driver_uc_chooses_as_before`
is now conditional on Rosetta, and says why), `tests/test_cross_platform_browser.py`
(+5 Mac lines), `tests/test_friendly_mac.py` (new, 6). Windows and Linux
paths are untouched except that uc is now told the browser path Prism
already found. Full read-through: `artifacts/mac-chrome-driver-cases-2026-09-10.html`
in the parent folder.

---

# 1.5.2 — Prism brings its own Apple silicon driver

The client's M2 updated to 1.5.1 and still stopped with errno 86 on the
retry. The reason is inside undetected-chromedriver: it unlinks and
re-downloads the driver on every launch, and when the unlink is refused
(the migrated folder was not writable) it silently reuses the file that
is there — the Intel one. So Prism's cleanup and purge could both fail
and the same driver ran again.

**Now:** on Apple silicon Prism fetches the `mac-arm64` chromedriver
itself from Chrome for Testing into `~/.prism/chromedriver/<major>/`,
checks the Mach-O header says arm64, and hands that path to
undetected-chromedriver, which only patches it. Its own cache no longer
decides anything. A driver folder that cannot be emptied is moved aside.
The message now says: press Start again; if it comes back, the one
`rm -rf` line; then Export diagnostics. Intel Macs, Windows and Linux are
untouched, and a failed download falls back to the old behaviour.

---

# 1.5.1 — an Intel driver on an M2 is found, removed and explained

Found by the first client install of the Apple silicon DMG (10 Sep 2026):
the first run died with `[Errno 86] Bad CPU type in executable`. Chrome
was universal and fine. The cached browser driver in
`~/Library/Application Support/undetected_chromedriver` was x86_64 —
carried over from an older Intel Mac by Migration Assistant — and the M2
had no Rosetta to run it.

**Was:** the cleanup that should have removed it shelled out to `file`
and swallowed every failure, so it did nothing and said nothing, and the
raw errno reached the customer.

**Now:** the engine reads the Mach-O header itself (thin x86_64, thin
arm64, universal), removes an Intel driver on Apple silicon before Chrome
starts and says so, an errno 86 out of the launch purges the cache and
retries once with a fresh download, and a second errno 86 becomes plain
words that name the folder. Linux and Windows are untouched: the check
only decides on Darwin/arm64. Tests: `tests/test_chrome_driver_arch.py`.

Client-side, until they update: delete that folder and start Prism again.

---

# 1.5.0 — the rules and fallbacks of 9–10 Sep, in a build

1.4.3 was built on 8 Sep, before any of Rounds 17–28 existed, so every
installed copy still sends a list two seconds apart with no cap, still
has no "Use fallback" button, still hands Canva a page of prompt, and
still attaches the customer's drawing to the BOQ writer. This build is
those rounds, plus what the team landed on `main` since:

* **Email** — Pace and limits (gap, jitter, per-press and per-day caps,
  send later), the Sent-folder copy with its switch, het's multi-account
  sending (Round 17, Round 28; `docs/EMAIL_SEND.md`).
* **Running a task** — "Use fallback" beside "Skip step"; an empty
  ChatGPT answer caught in seconds and regenerated once; Canva builds the
  deck through its own AI page; short, human-sized prompts; makers are
  briefed to build; the prompts are written only for the plan you
  confirmed (Rounds 18–22).
* **BOQ** — the drawing never reaches an AI; a sample BOQ defines the
  document; the measurement is a table with the unit inferred from the
  coordinates, look-alike layers and remote blocks flagged; and now
  pricing from your own rate list to an Excel with live formulas (Rounds
  23–28).
* **Landed by the team** — Leads & Outreach add-on and the BOQ pricing
  engine (Harsh); Motion Studio, the continuity compiler, materials,
  review and the cinematic lab (Beastburner); the add-on architecture and
  its guard tests (`CONTRIBUTING.md`).
* **Hand-off without a certificate** — `devtools/make_bundle.py` and the
  double-click installer for a Mac with nothing on it.

Nine add-ons register. The update manifests for this version are signed
with the production key `u1` as before; a 1.4.1+ install updates in-app.

---

# 1.4.3 — the Windows update helper never swapped

Found by a real customer update on Windows: the 1.4.2 tree downloaded and
verified into `%USERPROFILE%\.prism\updates\1.4.2`, Prism quit for the
restart, and never came back; reopening the exe gave the old version.

**Was:** `apply_update.pid_alive()`'s Windows branch did `import ctypes`
and then used `ctypes.wintypes.DWORD()`. `ctypes.wintypes` is a submodule
that only exists as an attribute once something imports it by name. The
`--prism-apply-update` helper is a bare process — no Qt, no licensing,
no keyring — so nothing had, `wait_for_exit()` raised `AttributeError`,
`perform_apply_and_relaunch()`'s catch-all returned 3, and the swap and
relaunch never happened. Under pytest some other import had already
loaded the submodule, which is why the Windows test lane was green.

**Now:** `import ctypes.wintypes`, and a test that runs `pid_alive()` in
a fresh `python -I` interpreter with only `apply_update` imported — the
way the helper actually runs.

**Consequence, stated plainly:** the helper runs in the OLD binary, so a
Windows 1.4.1 or 1.4.2 install cannot finish any in-app update. Windows
customers make one browser download to 1.4.3; from then on they
self-update. Linux and macOS clients on 1.4.1+ update to 1.4.3 in-app.

# 1.4.2 — the in-app update finally sticks

Found by actually running one: a real frozen 1.4.0 Linux build, the signed
1.4.1 manifest, real assets, the real swap — and then the new build rolled
itself back on its first launch. Every in-app update through 1.4.1 did.

**Was:** `apply_update.mark_pending_confirm()` wrote a marker after the
swap and `check_and_rollback_if_pending()` treated ANY marker at startup as
"the previous launch never confirmed". The very first launch of the
swapped-in build is the one that finds the marker — so it restored the
backup, noted a rollback, and relaunched the old version before a single
window opened. Nothing in the tests exercised swap-then-first-launch;
`test_pending_marker_at_next_launch_triggers_rollback` codified the bug.

**Now:** the marker is two-phase. The first launch appends `launched` and
carries on; `confirm_startup_success()` removes the marker once the window
is up; only a SECOND launch that still finds it rolls back. Because the
decision runs in the NEW binary, 1.4.0 and 1.4.1 clients updating to 1.4.2
get the fix — their own code only stages and swaps.
`tests/test_apply_update.py::ConfirmAndRollback`.

**Also from that run:**

* `updater._get()` opened a fresh connection to github.com, followed its
  redirect to the asset CDN, and closed it — for every one of ~1000 files.
  GitHub throttles that pattern: 3 s per tiny file from the long-running
  process, 0.3 s from a fresh one; an 80 MB update took 25 minutes and
  looked hung. One keep-alive `requests.Session` (`updater._http()`): the
  same update now stages and verifies in 52 s.
* GitHub allows 1000 assets per release and the 1.4.1 Linux build had
  1022, so its assets release could never be complete (only the files that
  differ from 1.4.0 were published, which is all a 1.4.0 client asks for).
  `packaging/prism.spec` now trims licence texts inside `*.dist-info/` and
  `.pyi` stubs — nothing reads them at runtime — and
  `packaging/manifest.py` fails the build over 1000 rather than letting
  `release_all.py` discover it an hour later.

# Round 29 — quote by product code, and send it yourself if you say so

A client's ask (11 Sep): their customers write the catalogue code and the
pieces ("chair 1128K x 40"), the code is on their price list, and they
want the quotation to go straight back. The Rate list under Email
automation → Setup → Files was already that price list; three things were
missing.

* **Any file.** The rate list reads from PDF, Word and plain text as well
  as Excel and CSV (`quoting.load_rates` → `_rows_from_document`, over the
  same text extraction attachments use). A scanned PDF is refused with a
  reason; the picker and the help text say which formats work.
* **Every code in the mail.** `quoting.find_requests(text, items)` reads
  each rate-list code the mail names, in order, with the quantity written
  beside it ("1128K x 40", "40 pcs of chair 1128K", "1129K: 12 pieces").
  A code is exact, never fuzzy. A code with no quantity comes back
  unconfident. The quotation window shows a lines table when a mail names
  more than one code, prefills the single form when it names one, and the
  quotation itself carries every line.
* **Auto-send, opt-in.** A switch in the same setup group: "Quote
  automatically when the mail names product codes from this list with
  quantities". Off by default. After every mailbox check, each new inquiry
  is planned (`addons/inquiry/autoquote.py`): if every code matched and
  every line has a quantity, the quotation is numbered, saved, and sent
  from the default account under the saved terms, and the row is marked
  Quoted like a hand-sent one; otherwise the row stays in "To quote" with
  `auto-quote held: <why>` in its Notes. Sends run one at a time.

Tests: `tests/test_autoquote.py`.

# Round 28 — Harsh's BOQ pricing and Sent-copy get their windows

Harsh's 10 Sep landing (engine `de4ed63`) brought two things the GUI could
not show: `core/boq_price.py`, which prices a measured take-off into a
tender-ready BOQ, and a Sent-folder copy of every email the mailer sends.
Both were live in the engine and invisible in the app — the pricing had no
caller at all, and the copy was on with nothing to say so or switch it off.

**BOQ — "Price it (optional)"** (`addons/boq/pricing.py`, shown under the
measured table once a drawing is measured, BOQ mode only — a BOM is a parts
list):

* one grid row per measured line, in the measurement's order; Qty is the
  measurement and Amount is arithmetic, so neither takes typing; Section,
  Description, Unit and Rate do;
* **Attach your rate list…** (CSV / XLSX, read by the same `core.quoting`
  loader Inquiry's quotations use; the price list already given to Inquiry
  is picked up automatically), or **Use starter rates**, marked indicative;
* a library rate is applied only when the match is confident AND the units
  agree — a per-cum rate never prices a wall measured in metres; the row
  stays unpriced and says why;
* contingency %, GST % and inter-state (IGST vs CGST+SGST); the totals
  line with the grand total in Indian words; unpriced lines counted and
  kept out of the total;
* **Save as Excel…** (live `=Qty*Rate` / `=SUM` formulas, Abstract of Cost
  sheet), **CSV**, **PDF** (needs the bundled Chromium).

No AI touches a number here, and the write-up prompt is unchanged: pricing
sits beside the writing stage, never inside it. `core_bridge.get_boq_price()`
is the one door. Tests: `tests/test_boq_pricing.py`.

**Email — "Keep a copy of each email in the account's Sent folder"** in
the Pace and limits card, on by default as the engine has it, named in the
folded summary ("copy kept in Sent" / "no copy in Sent"), handed to the
worker as ticked, remembered with the pace, and carried across an account
save like `folder` (`email_config.save_to_sent` / `with_save_to_sent`).
The terminal's `/email` reads the same key. Tests: `ACopyInSent` in
`tests/test_email_pacing.py`.

**Shipping to a Mac with nothing on it** (`devtools/make_bundle.py`,
`packaging/Install and Run Prism.command`): a zip of the tracked source of
both repos plus one double-click launcher that finds or fetches a
standalone Python (no admin password, no Homebrew), makes the venv,
installs the requirements, fetches Chromium, checks for Google Chrome and
starts Prism — and on the next double-click just starts it. Interim until
the Developer ID certificate lets the DMG be signed. See
`packaging/README-INSTALL.txt`.

# Round 27 — the measurement says what the coordinates say

Reading the same site survey by hand settled three things no BOQ written
from its totals had: the unit (a projected survey grid in metres, and a
7 m gate block placed at scale ~0.001), the two boundary-wall layers (one
wall on two layers — together they close the footprint), and six of seven
pump houses sitting 1 – 4 km away on a pipeline. `core.boq.measure()` now
walks the same coordinates once more and reports `site`: the inferred
unit with its evidence, look-alike layers with a verdict (one run on two
layers / drawn twice / check), the main cluster's extent, and any block
farther than a kilometre from the rest with its distances. The summary
the AI reads carries them; the measured table on screen shows the unit as
inferred and the look-alikes and remote blocks in its warning band. All
local; nothing leaves the machine.

*Files:* `prism_terminal/core/boq.py`, `addons/boq/measured.py`,
`tests/test_site_facts.py`

---

# Round 26 — the measurement is a table

The owner's screenshot: "Measured from your drawing" showed the prompt
text — "LENGTHS BY LAYER:" and a wall of "layer: 498.44 unspecified"
lines in a 120 px box. That text is written for the AI, not for a person.
The box is now a table (`addons/boq/measured.py`): one row per measured
item in the CSV's own order — Item, Measured as (Length / Area / Count),
Layer, Value right-aligned with thousands separators, Unit — sortable by
any column, ten rows on screen and the rest scrolling, a header line with
units, entity and layer counts, the warnings (unit unconfirmed, scope
filter, conversion notes) in a warning band, and the full layer list one
click away. The prompt text is untouched; it is still what the AI gets.

*Files:* `addons/boq/measured.py`, `addons/boq/dialog.py`,
`tests/test_boq_dialog.py`

---

# Round 25 — the writer keeps the estimator's habits

Comparing two BOQs of the same site — one written locally from the
numbers with the firm's sample attached, one written by Claude with the
whole DWG — showed the template did its job (the local one is the
document the firm would send) and the drawing added no measurement (the
tool said so itself). What the drawing-fed one did better was habit, not
data: a reference table of the measured figures, a stated decision on a
duplicate wall layer, storage and power sized from the counts with the
arithmetic shown, existing poles reused as mounts. Those habits are now
asked of the local writer on every drawing-based BOQ.

*Files:* `prism_terminal/core/boq.py`, `tests/test_boq_dialog.py`

---

# Round 24 — a sample BOQ tells the writer what it is making

The owner's idea, after comparing a numbers-only BOQ with one written
from the drawing: do not give the AI the drawing, give it one of the
firm's own BOQs. The plumbing already existed — a `.docx`/`.xlsx`/`.pdf`
attached to the BOQ window was classed as a template and handed to the
Interpret and Format stages — but the screen never said so, and the
writer was told to treat it as a "style guide, take inspiration". Now the
BOQ front door offers it as a step, and the writer is told the sample
defines the document: its sections, columns, numbering, level of detail,
wording, units and boilerplate, and its design decisions for comparable
items, filled with this drawing's measured numbers, never its rows.

*Files:* `prism_terminal/core/boq.py`, `addons/boq/panel.py`,
`tests/test_boq_dialog.py`

---

# Round 23 — the BOQ drawing never reaches an AI either

The owner walked the BOQ flow and found the one gap in the rule every
measuring add-on keeps: the drawing was measured here, the Standards and
Interpret stages never saw it — but the Format stage attached the CAD
file to the writing tool "so it could analyse the drawing itself".

Now no stage receives the drawing, in the window and in the terminal's
`/boq` alike; the writer is handed the measured summary (every layer,
every block and count, the lengths and areas) and told plainly that the
file is not attached, to build every line from those figures, and to
flag anything only the layout could decide rather than invent it. BOM
mode, which shares the writer, says the same. Templates and notes still
travel.

*Files:* `addons/boq/dialog.py`, `prism_terminal/prism.py`,
`prism_terminal/core/boq.py`, `prism_terminal/core/bom.py`,
`tests/test_boq_dialog.py`

---

# Round 22 — the prompts are written for the plan you confirmed

The flaw behind the Canva run, named by the owner: the router wrote every
step's prompt when it made the plan — before anyone looked at it. Drop a
step, add one, move one, or switch its tool on the Plan screen and the
prompts did not follow: the presentation step was switched from Gamma to
Canva and Canva was handed Gamma's brief.

**Now Start the work checks whether the plan changed** (`router.plan_changed`
against `router.planned_steps`: membership, order, tools, and any step with
no prompt) and, if it did, **writes the prompts again for exactly the steps
you confirmed, in that order, on those tools** — one Groq call off the
thread (`PlanBriefWorker` → `router.brief_confirmed_plan`) before the
licence check. The drafts keep their substance; the tool and the order are
the truth; makers get the maker rule; the last step is told it is last.
The rewritten prompts are put back on the rows (`AgentsPanel.apply_prompts`)
so Prompt shows what will actually be sent. An unchanged plan keeps its
prompts and starts as before. If Groq cannot be reached the drafts stand,
and a step with no prompt gets a real floor (`passthrough_prompt`).

*Files:* `prism_terminal/core/router.py`, `workers.py`, `main_window.py`,
`widgets/agents_panel.py`, `tests/test_confirmed_plan.py`

---

# Round 21 — a tool that builds the thing is briefed to build it, and every stage is briefed like a colleague

The owner's second Canva run, from the prompt Canva received: *"Produce the
final deck in plain-text slide format ready for import into Gamma.app …
Do NOT generate actual PPT files."* Canva did as it was told and typed the
outline back. The stage prompt had been written for a chat tool, and it
named the wrong tool.

**Makers.** The registry now says what each tool builds (`makes`: Canva an
editable design, Gamma and Tome a presentation, Midjourney images, Runway
a video, ElevenLabs audio, v0 an app…). The router is told, per tool, and
when a maker is in the plan it gets a rule to brief it the way a senior
person briefs a designer: build this, with this content verbatim, this
look, this count — never "plain text", never "do not generate files", and
never a different tool's name. At run time the engine opens a maker's
stage with a plain brief — *"You are Canva, and what I need from you is an
editable Canva design … build it here … if anything below asks for plain
text or says not to create files, that was written for a chat tool and
does not apply to you"* — reads the context to it the human way, and never
asks it for a handoff section.

**Every other stage, in the same voice.** The numbered "STRICT PIPELINE
RULES" block that closed each chat prompt now reads as a colleague's
note — what the answer is for, who reads it next, the one section that
has to be there (`HANDOFF FOR <NEXT>`, unchanged, because the relay parses
it) — and the final stage is told it is the last step and the answer goes
to the person. Machine-read stages (JSON specs, image batches, Apollo's
filter block) keep their strict wording on purpose.

Engine only. Tests in `tests/test_makers.py`.

---

# Round 20 — an empty ChatGPT answer is caught in seconds, and Canva builds the deck

From the owner's run log of 10 Sep, two faults.

**ChatGPT finished with nothing, and Prism waited 300 s for it.** The tab
showed a new assistant turn with no text and no Stop button — the toolbar
under a blank bubble — and `_smart_wait`, which watches text grow, ran out
the whole cap. Now a tool can say which element means "still generating"
(`busy_selector`) and which means "a reply" (`turn_selector`); when a new
turn has sat idle and empty for a short while the wait ends, the tool's
own regenerate control is pressed once (`_regenerate_once`, hover-only but
in the DOM), and if it is empty again the stage fails at once and the
fallback tool takes it. ChatGPT's selectors were read off the live page.
The user can also press **Use fallback** (Round 19) the moment they see it.

**Canva never received the prompt, then never pressed Generate.** The
registry pointed at `/magic-design/`, a marketing page with no composer.
Probed live with Playwright: Canva AI lives at `canva.com/ai`, opens under
a promo dialog whose video swallows clicks (Escape closes it), takes the
prompt in the one labelled textarea, sends with `button[aria-label='Submit']`
— and answers with an *outline* first, needing "View outline" → "Generate
design" before a deck exists. `_run_canva` makes those moves; the thread
URL is the saved link (the deck opens from its card there and lands in
Projects). Verified end to end: a 3-slide deck built through both paths.

**The prompt header is shorter.** The block that carries the customer's
own words to every tool now says its rule in one sentence — summaries lose
things, the words above win, specific facts must survive — instead of a
paragraph. The stall was not the prompt's length, but every tool reads it.

Engine only. Tests in `tests/test_empty_answer.py`.

---

# Round 19 — Use fallback: hand a stuck step to its fallback tool now

The owner's ask: Prism waits a fixed time for a tool and only then hands
the step to the next tool in its category — but the person watching can
often see the tool has errored, and does not want to sit out 600 seconds
for Prism to notice.

**Use fallback**, beside Skip this step on the run screen. Pressing it
stops the wait on the running step and runs the failover pass for that
one step immediately — the next tool in the same category, the same
`_retry_failed_stages` the end-of-run pass uses — so the stages after it
get its answer instead of running on thinner context. What the stuck tool
had on the page is not kept; the person pressed the button because they
could see it was not going to answer. Pressed again during the retry, it
abandons that tool too and moves to the next one. Not latched; the engine
clears the flag per press, like Skip.

Wiring, in the same shape as Skip: `OutputPanel.fallback_requested` →
`MainWindow._use_fallback` → `AutomationWorker.use_fallback()` →
`run(fallback_signal=)`. The engine's per-stage waits (text and image)
poll it through `stage_halt()`; a nested retry run never fails over again.

*Files:* `prism_terminal/core/automation.py`, `workers.py`,
`widgets/output_panel.py`, `main_window.py`, `tests/test_use_fallback.py`

---

# Round 18 — the Canva hand-off, verified live, and the two reasons Prism skipped it

The owner's report: ask Prism for an Instagram post *"and make it editable /
in Canva"* and ChatGPT should draw the picture and then hand it to its
Canva app — and it no longer did.

**Verified with Playwright first** (`devtools/canva_probe.py`, on a copy of
Prism's own Chrome profile). The hand-off itself works: ChatGPT drew the
post, the follow-up `@canva …` was answered by the Canva app with a card and
`CANVA LINK: https://www.canva.com/d/…`, and that link opens a real editable
1254×1254 design in the owner's Canva. ChatGPT still routes a plain
`@canva` in the message text to the app; the response selector still finds
the text turn. So the engine's plan was right and the run was failing
around it.

**Reason one — a picture has no words.** ChatGPT answers an image request
with the image and no prose: the assistant turn is an `<img>` and an
"Edit" button. `_capture()` therefore came back empty, and
`_make_editable()` read an empty capture as "nothing was made" and skipped
Canva — while the picture sat on screen. `run()` now tells the step whether
a picture rendered (`made_image=bool(got)` off `_wait_for_images`), and a
rendered image counts as something to convert.

**Reason two — a short answer was thrown away.** `_capture()` drops
anything under fifty characters, to lose buttons and chips. `CANVA LINK:
none` is sixteen; a real link can be under fifty. So the one reply the
step most needs to read was the one discarded, and "not connected" read
as "did not answer". `_capture(keep=)` keeps a reply carrying the marker a
caller is waiting for, and `_reask()` passes its `expect` through.

Engine only (`core/automation.py`); no add-on, no shell, no registry
touched. Tests in `tests/test_canva.py`.
# Round 17 — a list is not a blast: pace, limits and sending later

The owner's ask, in two lines: *limit and schedule the mails*, and *the
difference of time between the emails*. A list used to go out to everyone,
two seconds apart, the moment Send was pressed.

**Pace and limits**, a card under the letter in the Email window: the gap
between emails plus a random extra on top (so the pauses are not a
metronome), a per-press cap and a per-address daily cap (counted off the
sent log, across windows and days), and *Send later, at* a chosen time.
The note under the card and the Send button both say what will happen in
words — *Send to 88 of 120 people*, *Daily limit reached*. After a capped
send the window stays open with exactly the people who did not go, so the
next press continues. The numbers persist in `cfg["email"]["send"]`.

**Folded by default (10 Sep).** On the owner's screen the open card pushed
the Message box down to one line, the date picker drew unstyled and the
note was clipped. The card is now a title, the setting in words (*2 s
apart · everyone at once · no daily limit · sends now*) and **Change**; it
opens to a proper form and opens on its own when a saved setting is not
the default. The window scrolls; `QDateTimeEdit` joined the stepper rules
in `style.qss`.

**Engine:** `core/mailer.py:send_bulk()` grew `jitter`, `limit`, `start_at`
and `on_wait`; the scheduled wait happens before the SMTP login and a stop
during it sends nothing. `pause_after_send()` is the one place the gap is
computed. The terminal's `/email` reads the same gap, jitter and per-send
cap out of the config.

**Kept inside the Email add-on and its own data module**, per the
architecture: `addons/email/dialog.py`, `addons/email/sent_log.py` (each
entry now records `from`, and `sent_today()` counts it), root-level
stdlib-only `email_config.py` (`send_policy`, `with_send_policy`,
`plan_send`; the policy survives `account_block` and `cfg_for_sender`),
`workers.py:SendWorker` (the parameters pass through; a `waiting` signal
counts down). No other add-on touched; Email automation's own sends are
single messages and are unchanged.

*Files:* `prism_terminal/core/mailer.py`, `prism_terminal/prism.py`,
`email_config.py`, `addons/email/dialog.py`, `addons/email/sent_log.py`,
`workers.py`, `docs/EMAIL_SEND.md`, `tests/test_email_pacing.py`,
`lang/_catalogue.json`

---

# 1.4.1 — a Mac can install, update and re-seat itself; Studio V2 is whole

Three threads, one release. The first two came out of reading the macOS
install and licensing path end to end for the first time
(`prism+gui/artifacts/macos-install-and-licensing-2026-09-08.html`); the
third finishes the Studio V2 / Motion work that had been sitting
uncommitted.

## The macOS updater swapped the wrong folder

**Was:** `updater.install_dir()` returned the executable's parent —
correct for a PyInstaller onedir on Linux and Windows, but on a Mac that is
`Prism.app/Contents/MacOS`. `apply_update.perform_swap()` renamed *that*
aside and dropped a whole staged tree in its place, so the first in-app
update left a bundle with no `Info.plist`, no `Frameworks/` and a broken
signature seal. Finder then refused to open it. CI compounded it by
hashing `dist/Prism` (the COLLECT folder) for the macOS manifest, a tree no
installed Mac has.

**Now:** `updater.bundle_root()` walks up to the `.app` and the whole
bundle is the swap unit; the pending-confirm marker is written *beside* it
(a stray file inside a bundle also breaks the seal); CI hashes
`dist/Prism.app`. And because every 1.4.0 Mac still carries the old swap
code, macOS moved to a new update channel name, `macos-arm64-app`: a 1.4.0
Mac fetches `manifest.macos-arm64.signed`, gets a 404, and takes the
browser-download fallback — the only safe path for it. Never publish under
the old name again. `tests/test_apply_update.py::MacBundle`,
`tests/test_updater.py::PlatformChannel`.

## Signing is wired, waiting on an Apple account

`packaging/codesign.py` already did Developer ID + hardened runtime +
notarytool + stapler; nothing ever set `MACOS_SIGN_IDENTITY`. The workflow
now imports a `.p12` into a throwaway keychain and passes the six secrets
through — all optional, so an unset secret still builds unsigned exactly as
before. The `.dmg` itself is now signed, notarised and stapled too
(`codesign.sign_macos_archive`); before, only the bundle inside it was.
BUILD.md and the release notes gained the macOS 15 "Open Anyway" path,
which replaced right-click → Open.

## SEAT_LIMIT_REACHED is a choice, not a ticket

**Was:** the server answered "every seat is in use" *with the list of
machines*, and the client showed only the sentence. A customer whose old Mac
was reimaged, repaired or migrated (a new IOPlatformUUID) sat at the one
machine that could not activate, and the only way out was an admin release.
`device.py` had predicted this as the most common support ticket.

**Now:** the licence dialog lists the machines with when they were last
used, and one click frees the chosen seat and activates here, through a
new `POST /v1/release` that takes the licence key as proof — the same proof
activation takes to grab a seat, so it grants nothing the key did not.
`tests/test_license_seats.py`; server `tests/test_api.py` (+2).

## Smaller licensing changes

* `keyring` is on. Every build before this wrote the reusable licence key
  in the clear to `~/.prism/license.json` because the line was commented
  out "for later". On macOS an updated (re-signed) Prism gets one keychain
  prompt; Deny is survivable — the customer retypes the key once.
* Server `offline_hours` default 1 → 24, matching what `issue-key.sh`,
  `trial.sh` and `grant.py` always passed. Only a licence minted through
  the raw API differed, and it stopped authorising an hour into a train
  journey.

## Studio V2, finished

The uncommitted rewrite had the right bones — durable `data-prism-id`
layers instead of child-index paths, browser modules as real files under
`core/studio_assets/`, a `/refine` endpoint back into the design
conversation — and three things that made it unusable as it stood:

* **The canvas did not fit its column.** `editor.css` fixed `#stage`'s
  edges but never overrode the harness's 1080×1920, so the reel drew near
  full size under the right panel and below the fold; the workspace test
  timed out on a click the transport intercepted. The stage now sits in its
  own viewport and is scaled *as one unit*, the way V1 did it.
* **`fit()` wrote an inline `transform` on every scene**, which is exactly
  the property the cut library drives — so no push, squeeze or zoom ever
  showed in the preview. Scaling the stage instead leaves scene transforms
  alone; scrub across a cut and it plays.
* **The editor had lost V1's tools** while the Python still accepted every
  record: add text / picture / shape, colour, background, font, size,
  weight, align, front/back, delete/reset, scene length and background,
  palette and typeface swap. All back, inside the V2 inspector, one undo
  step per control.

Also: a reel the AI router filmed never got `_studio` (the design
conversation), so Refine was dead for every reel opened from Artifacts —
`automation._studio_conversation()` finds the nearest earlier stage with a
chat URL and `_run_studio` stores it. `build_html()` stamps ids on every
page it builds, so an edit made in the editor finds its layer on the render
page for a spec that predates stamping. The V1 `#__ed-bar`/`#__ed-side`
stubs are gone; the two browser tests that waited on them now drive the V2
ids. `tests/test_studio_v2.py` (+2), the browser lane in
`tests/test_reel_edit.py` and `tests/test_reel_editor_tools.py`.

## Motion is back, with the check its kill-switch asked for

The switch-off comment said: re-enable only after "a real attached-image
render". `tests/test_motion_assets.py::AttachedImageReachesTheFilm` films a
spec with an attached red PNG and reads the pixel out of the MP4. The
packaged self-test gained `Studio editor + Motion runtime files`, because
both are data files a bundle can lose without any import failing.
# Round 16 — STEP moves into `addons/step/`, on top of the add-ons migration

**Landed 8 Sep 2026.** Rebased onto `origin/main` after PR #8 (the
migration) and the 1.4.1 / Reel Studio round had merged; the engine commit
was rebased onto the engine's `origin/main` (Studio V2) — one conflict in
`core/automation.py`, resolved by keeping the upstream no-prompt guard and
folding the Studio hand-off into `_run_local_stage`. `workers.py` keeps
both sides' new `AutomationWorker` parameters. Engine pushed first, then
the app, per `CONTRIBUTING.md`. A `CLAUDE.md` at the root now points every
Claude session at the architecture and landing rules.

`origin/chore/addons-migration` (het-vaghela-21, ~24 commits) restructures
the app: every add-on is a folder under `addons/<key>/` declared by a
stdlib-only manifest, `addons/registry.py` is the one shared file an
add-on touches, `widgets/simple_panels.py` is gone, and eight rules are
enforced by guard tests (`CONTRIBUTING.md`, `docs/architecture/`). It is
NOT on `main` yet. Rounds 12–15 were built on the old layout, so this round
rebuilds the STEP add-on the way the new rules say, on a local branch
`step-addon` cut from the migration branch. Nothing is merged into `main`
and nothing is pushed.

**What STEP is now.** `addons/step/addon.py` (`MANIFEST`: key `step`,
feature `boq` like Gerber and BOM, order 35 so the three measuring add-ons
sit together, screen `step`, probe `core_bridge:step_available`, remedy
`cadquery`, run prefixes `"STEP — "` and `"/step"`, engine `stepfile`,
offers `names.MEASURE_MODEL`), `contract.py` (`open_with_files` — plain
paths in, the dialog shapes them), `panel.py` (`StepPanel(AddonFrontDoor)`),
`dialog.py` (the Round 13–14 dialog, unchanged apart from where its workers
come from), and `workers.py` (the three STEP workers, each a
`workers._Worker`). One import line in `addons/registry.py`; one intent in
`addons/names.py`.

**What the shell needed.** The rail, Home, History and the licence gate
now read the manifest, so `widgets/sidebar.py` and `widgets/panel_base.py`
were not touched. `main_window.py` still builds each screen by hand, so it
gained the `"step"` entry in `SCREENS` (appended last), the panel, the
`opened` wiring, the `_handle_command` branch and `_open_step` /
`_open_step_dialog`. `core_bridge.py` gained `step_available()` and
`get_stepfile()` (rule 2: only the bridge imports the engine).
`workers.py` keeps only the `AutomationWorker` additions from Round 13
(`files_out`, `image_stages`, `failover`).

**The guard tests learned about STEP in the same commit**, as
`CONTRIBUTING.md` asks: `GOLDEN_RAIL` / `GOLDEN_HOME` in
`tests/test_addon_contract.py`, `PANELS` in `tests/test_screen_registry.py`,
`ADDON_FEATURES` in `tests/test_addon_gates.py`. `tests/test_step_dialog.py`
was re-pointed at `addons.step` and its shelf/routing checks rewritten
against the registry and a real window — the old version grepped
`main_window.py`, which the new rules forbid. `lang/_catalogue.json`
regenerated (56 strings added, none removed).

**The engine is unchanged by the migration** and its pin on the branch is
the same commit `main` pins, so the Round 12–15 engine work (`stepfile.py`
naming and drawing sheets, `automation.py` skip-during-retry and deferred
local stages, `config.py`'s `step_out_dir`, `prism.py`'s `/step-folder`)
carries over as-is. It sits on a local branch `wip/step-engine` in
`prism_terminal/`.

**Local branches, none pushed.** `wip/step-old-layout` (prism_gui) holds
Rounds 12–15 exactly as they were on the old layout; `wip/step-engine`
(prism_terminal) holds the engine work; `step-addon` (prism_gui) is this
round. `main` in both repos is untouched.

*Files:* `addons/step/*`, `addons/registry.py`, `addons/names.py`,
`main_window.py`, `core_bridge.py`, `workers.py`, `tests/test_step_dialog.py`,
`tests/test_addon_contract.py`, `tests/test_screen_registry.py`,
`tests/test_addon_gates.py`, `lang/_catalogue.json`

---

# Round 15 — a reel run that failed three ways, from one screenshot

A live reel run: "Make the images" failed on ChatGPT and was being retried
with Canva; **Skip this step** did nothing; and "Make the video" already
read FAILED underneath, before the images had a second chance. Three
faults, one fix each.

**Skip works during a retry.** `_retry_failed_stages` started its nested
`run()` without the skip flag, so a press during a retry — the one place a
customer is most likely to press it — was ignored. The flag now reaches
the nested run's waits (as a stop, so it winds up and keeps what landed),
a press abandons the remaining alternatives for that stage instead of
trying the next tool anyway, and the screen gets a `stage_skipped` saying
so. A promised image stage keeps its full budget through a retry too.

**The video waits for its images.** A local renderer (Reel, Studio,
Motion) ran in its turn regardless of what came before. Now, when a stage
before it produced nothing and failover is about to retry that stage, the
renderer is held back and run after the retry pass — with the pictures if
they came, honestly without them if not, but never before the retry that
could have supplied them. Its card stays queued meanwhile instead of
turning red.

**The script example is a placeholder.** Step 2's Claude reply began "A
quick flag: the tail end of your prompt demands a JSON schema about Bombay
Super Hybrid Seeds" — the OUTPUT FORMAT block's example was a realistic
sample about a named seed company, and the model read it as a smuggled
second brief and refused. No JSON, so the video stage had nothing to
build from. The example is now `<Example Company Name>` with placeholder
figures and says so.

*Files:* `core/automation.py`, `core/reel_web.py`, `tests/test_skip_step.py`

---

# Round 14 — the drawing sheet is drawn by Prism, and the AI one waits properly

`/step-auto` asked an image model for the dimension sheet and got back a
blurred preview, because a generic `visual` stage waits 60 seconds for a
picture and gives up after 12 if none has shown — while ChatGPT's image
model takes one to three minutes and shows a progressive preview that
counted as "an image, unchanged for 20s, done".

**Two changes, the second the one that matters.**

**1. The wait.** `automation.run(image_stages=…)` lets a caller promise
that a stage's deliverable IS a picture; such a stage gets a seven-minute
cap (the loop still returns the moment the picture settles). And
`_wait_for_images` now watches each image's source and size, not just the
count — a preview replaced in place by the finished picture is a change —
and keeps waiting while the page itself says it is still creating the
image. `/step-auto` and the STEP dialog's Draft both make the promise.

**2. The sheet, without an AI.** `core.stepfile.sheet_svg()` draws the
dimension sheet itself from the geometry: for every part, front, top and
side views by OpenCascade hidden-line projection (hidden edges dashed), the
overall sizes on real dimension lines in millimetres to two decimals, the
isometric, a hole table, notes and a title block — the layout of the
hand-made sheet this whole add-on replaces. It takes about a second and
every figure on it is the measured one. `/step` writes it every time as
`<model> - drawing sheet.svg` / `.html` / `.png`; `/step-auto` and Draft are
now the optional styled extra, not the only way to get a dimensioned sheet.

**3. ChatGPT only, and the file first.** The styled sheet is ChatGPT's job:
not whichever visual tool Agents names, and no hand-off to another image
model if ChatGPT stumbles (`failover=False`) — a second, differently-wrong
sheet is not a rescue. And the STEP dialog now asks for the model before
anything else: the question box and the Draft / Ask / Edit choice only
appear once a `.step` is attached.

*Files:* `core/stepfile.py`, `core/automation.py`, `workers.py`,
`prism.py`, `dialogs/step_dialog.py`, `widgets/simple_panels.py`,
`tests/test_stepfile.py`, `tests/test_step_dialog.py`

---

# Round 13 — the STEP add-on has a screen

The terminal had `/step`, `/step-auto` and `/step-ask` for a fortnight; the
GUI had nothing. Now it is an add-on like Gerber: a rail entry, a front-door
screen and a dialog.

**How it works.** Attach one or more `.step` / `.stp` models. The first
time, Prism asks where the files for your models should live (choose a
folder, or the Desktop) and keeps the answer; a folder named after each
model is made inside it, every file carrying the model's name (Round 12).
Pick the material (metal or plastic) and one of three actions:

- **Draft** — measure, then the image tool draws a dimensioned drawing
  sheet from the numbers; the sheet it returns is saved beside the rest.
- **Ask** — measure, then Groq suggests improvements from the numbers and
  your question, and the reasoning tool reviews them into an exact change
  plan on a review page. Nothing is changed.
- **Edit** — Ask, then — after you confirm against the review page — the
  plan is applied to a COPY of the model, here, and the copy is re-measured
  so the After column is real.

**The rule.** The STEP file never leaves the machine. Every AI stage is
given the measured numbers and Prism's own plain render of the parts, and
`tests/test_step_dialog.py` intercepts the worker calls to prove it — the
same tests Gerber has, for the same reason.

**The rail.** This is the thirteenth control on a rail the header of
`widgets/sidebar.py` holds at twelve. The scroll floor carries it; the day
one measuring add-on is folded into another, this is the row to fold.

*Files:* `dialogs/step_dialog.py`, `workers.py` (three STEP workers, and
`files_out` on AutomationWorker), `core_bridge.py`, `widgets/sidebar.py`,
`widgets/simple_panels.py`, `main_window.py`, `tests/test_step_dialog.py`

---

# Round 12 — STEP files are named after the model, and go where you say

An estimator keeps ten jobs' sheets in one place, and `/step` wrote
`dimensions.xlsx`, `drawing.png` and `modified.step` for every one of them
— ten files nobody could tell apart — into a folder called
`Assem1_1757000000` on the Desktop.

**Now:** every file starts with the customer's own file name. For
`Assem1.STEP`:

    Assem1 - dimensions.xlsx
    Assem1 - drawing sheet.html / .png
    Assem1 - view top.svg, Assem1 - view side.svg …
    Assem1 - AI drawing sheet 1.png          (/step-auto)
    Assem1 - change review.html              (/step-ask)
    Assem1 - modified.step
    Assem1 - dimensions after change.xlsx
    Assem1 - drawing sheet after change.png

They live in a folder named after the model, `<root>/Assem1`, and a
second run of the same model gets `Assem1 (2)` rather than overwriting the
first. `root` is the person's choice: the new config key `step_out_dir`,
set from the terminal with `/step-folder <path>` (the GUI will ask the
same question in a dialog when its STEP screen is built) and defaulting to
`~/Desktop/Prism Step` as before.

All the names come from one place, `core.stepfile.names()`, so the
terminal, the review page and a future GUI cannot disagree about what a
file is called. Spaces in the names are URL-quoted in the HTML.

*Files:* `core/stepfile.py`, `core/config.py`, `prism.py`,
`tests/test_stepfile.py`

---

# Round 11 — the Apollo prompt lands in the box that reads prose

A live run with Apollo as the first stage ended with the pipeline prompt
sitting in Apollo's small "Search people" keyword box and a table of zero
rows. That box is a plain keyword match; a sentence in it finds nobody.

**Was:** with no `HANDOFF FOR APOLLO` block to build a URL from,
`_run_apollo()` typed six words of the brief into whatever the first
`input[placeholder*='Search']` on the page was — the toolbar keyword box.

**Now:** the brief goes into the "Use Apollo AI to find the right prospects"
field (`input[role='combobox'][placeholder^='Example:']`). Enter hands it to
Apollo's AI Assistant, which opens as a side panel, thinks for 30–60 seconds
and applies Titles / company keywords / Location to the People grid — the
same grid `_capture()` already reads. Prism waits for the **Total** tile to
move off the unfiltered count (or for rows) before capturing. The keyword
box is now the last resort, reached only when the AI box is missing or the
account shows `0 CHATS LEFT`; a filtered URL search that matches nobody also
gets one try through the AI box.

**One trap, found the expensive way:** the box only renders while no
search is applied, and a restored Prism session brings the People page back
with last run's keywords still set. The button labelled **Search with AI**
does not bring the box back — it opens an assistant chat about the current
search and spends a chat doing it. **Reset filters** does, and so does the
bare `#/people` route; `_apollo_ai_box()` tries those and never touches
the other button.

**Why these selectors:** found with Playwright on the live app, not guessed.
Apollo's `zp_*` classes are hashed per deploy; the role and the rotating
"Example: …" placeholder are stable. The box kept a 4,000-character paste
with no `maxlength`, so `ai_prompt_max_chars` is a measured figure. The
probe is kept as `devtools/apollo_probe.py` for the next time Apollo moves
things around.

**Cost to the user:** one assistant chat per prompt. The free plan allows
five a month, which is why the URL route stays first whenever a filter block
exists.

*Files:* `core/agents.py`, `core/automation.py`, `tests/test_apollo.py`,
`devtools/apollo_probe.py`, `KNOWN_ISSUES.md`

---

# Round 10 — Prism knows when a newer Prism exists (1.3.1)

The licence server has sent `latest_version` and `min_supported_version` on
every lease since the authorisation-lease round, and every client dropped
both on the floor. Customers learned about a release from an email and then
went looking for the download. This round is Phase 0 of `../update-plan.md`:
read the two values, say so, and ship that as **1.3.1** — because every later
phase of the updater needs customers on a build that can *see* an update.

## The advice reaches the state

**Was:** `_store_lease()` kept the lease and nothing else. The two version
strings beside it were never read.

**Is:** `LicenseState.latest_version` / `.min_supported_version`, persisted in
`license.json` off every lease and authorize response — and off the `detail`
of a `CLIENT_TOO_OLD` refusal, which is the only lease answer a retired build
ever gets, so it can say "update" rather than "can't reach the server". Drawn
at launch with no network. A field the server stops sending is left alone; one
it sends EMPTY is cleared, which is how a banner is withdrawn without a client
release. Neither string is signed, so neither can do more than change wording
— `updater.py`'s docstring is the trust statement.

## The banner, and where it sits

Third in the pecking order, behind a licence problem and an unreachable
shared folder: "Prism 1.4.0 is available. You have 1.3.1." with **Download**
(opens `app_meta.DOWNLOAD_URL`, a fixed address, never one from the response)
and **Not now**, remembered per version in `~/.prism/update_state.json` — so
the next release brings it back. A build below the server's floor gets "can
no longer start new work — update to continue" with no Not-now, and that one
outranks the shared-folder banner because new work is already refused.

## Settings › Diagnostics › This installation

The Version row grew **Check for updates**. `licensing.refresh()` gained
`on_done`, called on its worker thread once both round trips have landed; the
panel hands it a Signal's `emit`, Qt queues that back to the UI thread, and
both the page and the window's banner redraw. It says "You have the latest
version" only after a check — never as a standing pat on the back.

## Release runbook

`SHIPPING.md` §1.3: once the Release is up, set `LATEST_CLIENT_VERSION` in
Render. `render.yaml` now declares it `sync: false`; `MIN_CLIENT_VERSION`
stays the enforcing lever and stays unset.

Tests: `tests/test_updater.py` (version compare, state, `on_done`, Not-now)
and `tests/test_gates.py::UpdateBanner` (pecking order, dismiss, Download,
the Check-now round trip).

---

# Round 9 — the help screen learns to talk, and the way to a person is real

Round 7 shipped Help & support with tiers two and three as placeholders, on
instruction. The instruction changed after a day of real use, and so did a
verdict on the first version's feel: a chat screen that posted every menu
into the thread and left it there read as a form that kept growing.

## The transcript behaves like a conversation now

**Was:** ten full-width topic cards in the thread, then ten question rows,
then ten more topic cards when somebody went back — all of them still
pressable for ever, which is both a wall to scroll and a fork waiting to be
clicked.

**Is:** three rules. Topics are CHIPS — their names are two words, so ten of
them take three short rows and the whole opening fits above the fold
(questions stay full-width rows, because a truncated question cannot be
chosen). A menu is RETIRED the moment the conversation moves past it — the
pick already survives as the customer's own bubble, so nothing readable is
lost. And Prism's messages carry its mark, because two voices in one column
need telling apart faster than reading them. Plus a Start over button — the
screen keeps its thread across visits by design, which made "begin again"
impossible without one.

## The assistant is real — the customer's own Groq key, on a leash

The button now starts a conversation with a model, and everything about the
wiring is about keeping it honest:

* It answers **from the written help, not from its imagination**: every
  question heading (so it knows the true shape of the product), the full
  text of the answers matching this question, and the ones already read —
  marked *do not repeat these*. The first rule of its instructions is to say
  "I don't have that one, press Contact the team" rather than guess, because
  a made-up menu item costs the customer more than an admitted unknown.
* It starts knowing the four facts half of every support call is spent
  establishing: version, whether a key is saved, the platform, the licence
  state.
* Temperature 0.15 — support answers are quotations from the manual, and a
  model feeling creative about which menu an option lives in is the one
  failure this tier cannot afford. A test pins it.
* Its failures go through `friendly.explain()`, so the assistant breaking
  reads exactly like the rest of the app breaking — a sentence and steps,
  never a code. No key saved: it says so and offers the Settings button,
  because the customer least likely to have a key is the one who has not
  finished setting up.
* An animated Thinking bubble while it works, and the window's own shutdown
  now winds the assistant's thread up — a running QThread destroyed with its
  owner aborts the process, and Prism vanishing mid-question is a memorably
  bad way to end a support session.

## Contact the team hands the whole story to a person

The sheet arrives pre-filled with what a support thread spends its first
three replies asking for: version, platform, licence state, the device code
(seat problems are unanswerable without it), and the full conversation —
editable, with the promise printed on it that keys and passwords are never
included (true by construction, and tested). Three ways out, because
`mailto:` silently does nothing on a machine with no mail client: open the
email app (with the full text put on the clipboard FIRST, so a truncating
mail client cannot lose it), copy it all, or save it as a file that also
carries the redacted diagnostics report.

## Tests

52 in `tests/test_support.py` now: the retire-the-menus rules, Start over
forgetting everything including the gate, the assistant's grounding (whole
product shape, full answers for the question at hand, already-read marked),
the refuse-don't-guess instruction pinned by string, the no-key path, the
cautious temperature, failure-through-friendly, and the contact draft's
contents and its no-secrets guarantee.

---

# Round 8 — Email automation: every inbox, one register, and the order's own screen

A second firm described their whole operation in one sentence: everything —
inquiries, quotations, follow-ups, purchase orders — arrives by email, on
several addresses, and several people retype it all into one shared Excel
sheet. That is the workflow the engine has run since Round 3, asked for at
the scale of an office instead of a desk. `docs/EMAIL_AUTOMATION.md` is the
full design and the business case, with sources; this is what changed.

## The mailbox step takes a list now

**Was:** one account under `cfg["inquiry"]["account"]`, one read bookmark
beside it.

**Is:** `cfg["inquiry"]["accounts"]` — each entry with its own bookmark,
because two mailboxes sharing one last-UID would skip or re-import each
other's mail, and either failure is indistinguishable from a quiet week.
The old keys are still written, mirroring the first entry, so a config saved
by this version opens in the previous one; `accounts_of()` is the one reader
that understands both, and an existing customer's first check after updating
carries on from exactly where their last one stopped.

**The walk is one account at a time, never parallel.** The engine's own rule
— two fetches racing on one bookmark registers the same inquiry twice — is
"N fetches racing on one order book" the moment there are N accounts. One
dead mail server is skipped and named ("sales@… — the mail server didn't
answer" is a whole sentence; without the address it is half of one); one
locked register stops the walk, because the same lock would refuse every
account after it and none of their bookmarks have moved. A password being
refused three times sidelines that mailbox — the provider would throttle and
then lock it, and "Prism locked me out of my email" is the support call that
ends a deployment — while the healthy ones keep being read.

**The register says where each inquiry arrived.** One new column, `Mailbox`,
stamped when the row is born and never rewritten — a PO landing on a
different address later is not the inquiry moving. With sales@, info@ and
the owner's own address feeding one file, "who is this customer talking to"
is the first question the sheet gets asked.

**The centralised sheet was always one file; Setup now says so.** The
register lives in one folder, so the folder picker now carries the sentence
("choose a folder on your shared drive and everyone opens the same
register") and a one-click **Use the team folder** when the Prism workspace
is set up. One machine does the writing — the office PC that stays on;
everyone else reads. Several machines writing one register is deliberately
deferred, with its trigger, in `docs/DEFERRED.md`.

## The purchase order finally has its screen

`core/po.py` — read the PO, compare it to the quotation, flag every
difference — has been built and tested since Round 3, and no screen ever
called it. The runtime doc has named "the PO confirmation" as the missing
screen the whole time. Tab **5 · The order came** is that screen:

* The comparison is against the quotation **actually sent**, read back from
  the CSV written at send time — today's rate list could quote something the
  customer never saw. The reader mirrors `quoting.write_csv` and is checked
  against the file's own Total row to the paisa; a file that does not add up
  produces NO comparison rather than a wrong one.
* Accepting is a button, and it only writes the register — `Converted`, the
  PO number, the order value. The second of the two money stops, exactly
  where every doc has always promised it.
* The typed-in boxes are not a failure mode, they are the design: half of
  real POs are scans with no text in them, and the privacy switch means a PO
  — which is mail content — is never sent out to be read when *Keep
  everything on this computer* is on. Reading by machine is the convenience;
  the person holding the printed order is never blocked. (OCR: deferred,
  with a measured trigger, in `docs/DEFERRED.md`.)

## The shelf says "Email automation" now

Both prospect firms said "email", not "inquiries", when they described what
they wanted — so the shelf item, the screen and the setup say **Email
automation**. The rail key (`inquiry`), the licence feature (`inbox`), the
register format and every file on disk are unchanged: the SKU and the wiring
did not move, only the name on the shelf. The support screen's answers grew
three questions to match (several mailboxes, the shared register, what
happens when the PO arrives).

## Tests

27 new (`tests/test_email_automation.py`): per-mailbox bookmarks banked
against the right account, the dead-server skip and the locked-register
stop, learned senders chaining from one mailbox's check to the next, the
Mailbox stamp (and that it never rewrites), per-address password back-off,
the quotation round-trip to the paisa with the tampered-file refusal, the
₹4,500-on-ninety-paise comparison catch, the privacy switch keeping a PO's
text on the machine, and the review sheet refusing an empty accept. The
five-tab order test in `test_inquiry_ui.py` was updated deliberately: the
tab order is still the explanation of the feature, and the fifth tab is the
end the workflow was sold on.

---

# Round 7 — Help & support: the written answer first, then us

`friendly.py` speaks when Prism itself notices a problem. Nobody was there
for the larger half — the customer who is not looking at an error at all:
does one licence cover two computers, will the inbox add-on touch my real
mail, what do I type in the box. Nothing is broken, so no dialog ever
appears, and every one of those questions was a phone call.

## A new rail destination, and the shape of it

**Help & support** sits in the rail next to How to use Prism — they are not
the same thing: the guide is for somebody who does not yet know what Prism
does, this is for somebody who knew exactly what they wanted and did not get
it. It is a screen, not a dialog, like every other destination the rail
switches to, and it keeps its conversation for the life of the window — you
can follow an answer's button to Settings and come back to the thread.

Three tiers, in an order that is the whole design:

1. **The written answers** (`support_kb.py`) — 61 questions in 10 topics,
   the ones actually asked down a phone, phrased the way the customer says
   them. Same writing rules `friendly.py` is held to: plain English, then
   numbered steps that start with a verb, never a problem without a next
   action. Every button and menu an answer names was checked against this
   build — the redesign moved several (Login tabs sits behind More settings
   now; "Back to the plan" became "Back to the steps"; Export diagnostics
   lives on the sheet Settings' Change buttons open) and an instruction that
   names a control that is not there sends the customer hunting.
   A typed box searches them; the scoring deliberately returns NOTHING
   rather than a weak guess, because the empty result is what opens the
   route to a person.
2. **The assistant** and 3. **Contact the team** — placeholders, by
   decision, not omission. The plan is an assistant that talks the problem
   through, and a direct line that has us call the customer; both are their
   own change. The buttons are already in place so the screen's shape does
   not shift under people later, and each one, pressed today, answers
   honestly in the transcript — the contact one hands over the address that
   is read today. A placeholder may postpone the feature, never the person.

**The gate.** Tiers 2 and 3 stay shut until a written answer has actually
been tried — the pattern every government service site uses, because a
button marked contact-us gets pressed instead of the four-line answer that
was faster. But it opens on the FIRST honest miss: one answer marked "No,
still stuck", or one typed question with no match. Nobody is made to read
six irrelevant answers to earn a person, and the shut buttons carry the
sentence that says what opens them.

**The ways in.** friendly's catch-all — the one entry where we genuinely do
not know what went wrong — now carries an "Open Help & support" button, and
the guide's "when something goes wrong" topic points the same way.

## What it took elsewhere

* `devtools/extract_strings.py` had not learned the redesign's copy tables
  (`sidebar.MORE`, `settings_panel.SECTIONS`, `GuidePanel.CARDS`, …), so the
  new screens' labels were quietly untranslatable; registered them, and
  normalised catalogue paths to forward slashes so a regeneration on Windows
  stops rewriting every entry. Catalogue regenerated: 373 → 768 strings.
  Sixteen keys whose English no longer exists anywhere were pruned from the
  Hindi and Gujarati packs.
* Two transcript bugs found by measuring rather than looking: the scroll
  range ran hundreds of pixels past the last message (a word-wrapped label's
  *minimum* size is its height when wrapped at its widest word, and the
  layout sums those width-blind), and the scroll-to-newest landed one layout
  pass short every time. The column now sizes by height-for-width and rides
  the range while a message settles.
* 36 tests (`tests/test_support.py`): the jargon and verbs-first rules the
  answers are held to, every action key against the window's dispatcher,
  the search phrasings, both halves of the gate, and that the placeholders
  answer honestly and end somewhere real.

---

# Round 6 — the reels were slides, and it was arithmetic

One change, and it came from a measurement rather than an opinion.

A reel built by hand with a coding agent was compared against a reel Prism
generated. Same renderer, same CSS, same browser. The difference was not taste:

|                        | Built by hand | Prism |
| ---------------------- | ------------- | ----- |
| markup + motion per scene | **20,300 chars** | **278 chars** |
| elements per scene     | 25–77         | 3–5   |
| animations inside scenes | 150         | 0     |
| planning written first | ~50,000 chars | none  |

**278 characters is a headline and a subhead.** That is a slide. There is
nothing in it to move, so no instruction about motion could ever have fixed it
— which is exactly why the previous attempt, which added motion rules to the
prompt, made the output worse rather than better.

The cause was structural. The art director was asked for the whole reel in one
JSON object, and a model writing one JSON object budgets a few thousand
characters and divides them by seven.

## The design stage is a conversation now

**Was:** one prompt, one reply, the whole reel.

**Is:** turn one is the LOOK and a STORYBOARD — the palette, the type, the
shared stylesheet, and one row per scene giving it a distinct job, composition
and motion. Then one turn per scene, in the same tab, each with a whole reply
to spend on one scene. Each is laid out in the real browser and corrected
before the next is asked for.

Measured on the same four-scene script, rendered both ways:

```
OLD   4 scenes |   271 chars/scene |  7 elements/scene |  0 animations
NEW   4 scenes | 2,339 chars/scene | 34 elements/scene | 30 animations
```

**Why the correction loop is better too.** A layout fault used to come back as
"scene 3's headline is off the frame" against a reply the model had long since
moved past. Now it is simply "this one", while the scene is still the subject.

**Why more turns cost the customer nothing.** Prism drives the customer's own
browser on their own subscription. Ten prompts in a chat window instead of two
is slower, not more expensive — which is the opposite of the economics a
coding agent faces, and the reason this approach was available to us and not
to them. The design stage now takes minutes rather than seconds, and says
which scene it is on while it works.

## Per-scene CSS is confined to its scene

`scope_css()` in `core/reel_web.py`. A model naming things in reply four
cannot see what it called them in reply two — everybody writes `.title`,
everybody writes `@keyframes rise`. Left alone they collide and whichever
scene loses the cascade silently inherits another scene's type size and
another scene's motion.

Every selector is rewritten to that scene's layer and every `@keyframes`
renamed, with the `animation:` declarations that point at them following the
rename. Three details that took real care:

- **`.leaving` is the scene element itself**, not something inside it.
  Prefixed as a descendant, every hand-written cut would have silently
  stopped working.
- **A class may share a keyframes name.** `.rise` and `@keyframes rise` are
  both idiomatic; only the animation references are rewritten, never the
  class.
- **`url()` contents are not CSS.** A brace in a path or a data: URI used to
  be read as structure and cut the stylesheet in half.

It is worth more than the collisions it prevents: because a scene *cannot*
reach outside itself, the prompt never has to ask it to be careful. It is told
so, in as many words — a scene free to name things clearly writes better CSS
than one hedging against a collision it cannot see.

## A failed turn costs one scene, not the reel

More turns means more chances to fail. A reply that is prose rather than JSON
is asked again, more bluntly. A scene that still will not come back is
replaced by a plain one built from the script's own words — modest, legible by
construction, in the design's own colours. One dull scene ships; a hole does
not.

---

# Round 5 — a week of real runs, and what they broke

Nothing in this round came from planning. Every entry is something that went
wrong while the product was being used to make an actual reel for an actual
prospect, and several of them had been quietly wrong for a long time.

The theme, if there is one: **Prism was losing information at the seams.** Not
crashing — losing. The customer's own words on the way into a prompt, the
customer's CSS on the way out of a browser, the evidence on the way into an
error message. Every one of those failures reads as "the AI did a bad job".

## The customer's own words now reach the tool doing the work

The most expensive bug here, and the hardest to see.

Prism expands a request into a professional task brief, and the router writes
each stage prompt FROM that brief. The router is handed the raw request and
told it wins on scope — but the stage prompts it produces were only as good as
what it chose to carry across, and **the agents never saw the original at
all.**

A customer asked for a reel about *"Consiz, a mouse with a middle button that
summarises whatever you have selected and lets you ask questions about it"*.
The brief came back as *"showcase the mouse, demonstrate its features, explain
its benefits"*. The button, the selecting, the summarising, the asking — every
mechanical fact, gone. Claude then wrote a genuinely good script about a
generic productivity mouse, because a generic productivity mouse was all it
had ever been told about.

Nothing downstream can catch that. A summary that drops the one fact the whole
video is about still reads perfectly well, so every later stage compounds it
confidently — and the handoff chain means stage four works from stage three's
summary of stage two's summary.

The raw request now rides at the top of every stage prompt, verbatim, before
the attachments and before the previous stage's handoff. It is labelled as the
human speaking, and says outright that what follows is a summary, that
summaries lose things, and that specific facts above must survive even if the
brief below does not repeat them. Capped at 2500 characters and marked when
truncated — generous on purpose, because the Consiz mechanism sat in the last
third of that sentence.

*Suggested by the customer, who diagnosed it from the two briefs side by side.*

## The chat window was corrupting the design on its way out

Two bugs, one saved file, and the model was innocent of both.

A reel's art direction is a JSON document containing a full stylesheet.
Repeatedly it came back as **"No JSON found in the agent's reply"** while the
customer could see JSON sitting on the ChatGPT page. Unanswerable — until the
failed reply started being kept (below). One look at it settled both:

- **A soft-wrapped URL became a real newline inside a JSON string.** The chat
  window wrapped a very long Google Fonts `@import`, and the scrape turned that
  visual wrap into an actual line break inside the value. JSON forbids an
  unescaped control character in a string, so an entire design was thrown away
  over a line break that only ever existed on screen. `_escape_control_chars()`
  now escapes exactly those, tracking string state so ordinary
  pretty-printing between members is untouched. Run against the real saved
  failure, the design comes back whole — 6 scenes, both fonts, 3550 characters
  of CSS.

- **Markdown ate every asterisk, and that was our own instruction's fault.**
  Both prompts said "no fences". Outside a code block the reply renders as
  prose, prose is markdown, and markdown treats `*` as an emphasis marker — so
  `*{box-sizing:border-box}` arrived as ` {box-sizing:border-box}` and the
  whole CSS reset was silently dropped. The saved file contained **zero
  asterisks in 17KB**. Fences are now required, and the prompt says why so a
  model does not helpfully strip them again. The parser has always skipped
  fences — its own docstring says scrapes carry them — so forbidding them
  bought nothing and cost entire designs.

## Evidence is kept instead of discarded

The reason the above took three attempts to diagnose: the scraped text lived in
a local variable, the run moved on, and the error said only "No JSON found".

A design that will not parse is now written to
`~/.prism/logs/design-that-would-not-parse-<ts>.txt`, and the error names the
file. It answered a fortnight-old mystery on its first use.

The same failure of nerve appeared elsewhere: **a planning failure discarded
the customer's prompt entirely.** Planning is where runs fail most often — a
rate limit, a dead connection, an expired key — and it fails before anything is
written down, so their own words were the only casualty. Somebody who spent
five minutes describing a job had to remember it and type it again. Saved now,
error and all.

## A reel with no pictures is designed on purpose

Image generation fails for ordinary reasons — a quota, a content refusal, a
render that never finished. On one run ChatGPT thought for 185 seconds and
produced nothing.

Prism noticed. The design stage did not, and **silence is not neutral**: an
empty asset list produced an empty listing, so the prompt simply did not
mention pictures, and a model asked for a premium product reel assumed the
usual ones existed and wrote `src='asset:art1'`.

The renderer already strips unresolved assets, so nothing showed a broken-image
glyph. But a layout DESIGNED around pictures that never arrive is worse than
that: the holes are stripped and what remains is a composition with gaps in it,
which reads as broken rather than as spare.

`assets.manifest({})` now says there are no images, that this is not an
oversight, that nothing is coming later, and — the part that matters — what to
do instead: carry it on typography, hierarchy, negative space, rules, colour
fields and CSS shapes. A prohibition alone produces a timid design, so it also
says outright that a spare type-led reel is a legitimate and often superior
one.

## Canva: make the picture first, then make it editable

Asking for an editable Canva design and a good image in the same prompt made
the customer choose between them. Canva COMPOSES a template — stock layouts,
its own type — where DALL·E renders the scene described. For "da Vinci sipping
Wagh Bakri chai" the render is the whole job.

Now the two asks stop competing. The first prompt asks only for the best
picture the tool can draw; once it exists, a second prompt goes into the same
conversation — `@canva can you make this design editable` — pointing at the
artwork directly above it. Best picture *and* an editable file, which was not
previously on offer. *The customer's idea.*

Four failure modes have defined answers rather than surprises: nothing
generated → skip it entirely; Canva not connected → the fixed reply is dropped
rather than appended; Canva silent → keep the image; wrong kind of stage →
never asked.

That last one shipped wrong and was caught on the first real run: `artwork` and
`design` were included, and the Studio pipeline's design stage emits JSON for
Prism's own renderer — so the follow-up asked Canva to "import the image above"
when the message above was a CSS blob. The editable stages are now exactly the
registry's Canva-configured ones, with a test asserting the two lists match,
because they drifted apart once and **that drift was the bug**.

## Closing the browser no longer kills Prism

Reported as *"python stopped working and prism ended"*, with a real macOS crash
report behind it: SIGABRT, `QThread::~QThread`, `_Py_Finalize`.

Qt calls `qFatal()` when a thread object is destroyed while still running, and
PySide destroys every QThread during interpreter shutdown. So closing Prism
mid-run did not leak quietly — it killed the process. The app's own log signed
off with an ordinary "Prism closed" and no traceback, which is why it looked
like a mystery: the crash happens after the last thing anyone logs.

Every live worker is now stopped and joined on close. Stop-all before wait-all,
so three stuck workers cost ten seconds between them rather than thirty.
Inquiry Automation had the same hole and more workers than anywhere else.

Separately: **a closed browser window was diagnosed as a Chrome version
problem.** Every frame of a Selenium stack trace says
`undetected_chromedriver`, which matched the version-mismatch rule, so a closed
tab sent the customer off to update a browser that was working perfectly. A
confident wrong answer is worse than the generic one it replaced, because they
act on it. And the run kept going against the dead session — every later stage
opening it, timing out, and reporting the same error. It stops on the first one
now and says so once.

## When a tool runs out, another one finishes the job

A run is twenty to forty minutes and the heaviest stage is usually the last, so
the free tier that runs out runs out at the END — leaving a pipeline that did
nine tenths of the work and produced nothing usable.

Prism now reads the page for "you've reached your limit", "out of free
messages", "upgrade to continue" and the rest, kept deliberately apart from the
signed-out check because the two need opposite responses: an exhausted quota is
something Prism can route around by itself, whereas signing in is something
only the customer can do.

The replacement comes from the same category, so it can do the same job — a
failed image stage handed to a research tool produces an essay about pictures.
Tools the customer already configured go first, because they are probably
signed in to those. Capped at two attempts; each one is minutes of browser
time.

**Limitation, stated rather than left to be discovered:** the retry runs after
the pipeline, not inside it. A stage that failed in the middle has already
handed nothing to the stages behind it, and those are not re-run. The last
stage is fully recovered. Doing better means restructuring a 500-line loop
whose index-keyed maps all shift if the stage list changes underneath it.

## The test suite was writing into the customer's own data

Twice, found twice, and the second one was found by a customer asking a
completely different question.

- **`~/.prism/config.json`** — a test called `_checked()`, which calls
  `_remember()`, which calls `config.save()`. It wrote a bare fixture over a
  real config: Groq key, profile, agent choices, Chrome pin, gone. The only
  symptom was Prism asking to be set up again on every launch, which reads like
  a Prism bug rather than a test one.
- **`~/.prism/runs/`** — tests proving "a broken run is still recorded" were
  recording into the real History. **56 of 128 files** were fake "Chrome would
  not launch" failures. Worse than clutter: they carried no query, so they
  looked exactly like real runs whose prompt had been lost — the bug
  manufactured evidence for a bug that did not exist.

Both now refuse at module level rather than relying on the next person to
remember. The runs one needed two doors shut, not one: `config.RUNS_DIR` is
only the CLI's default, and the window passes its own folder. Verified by
counting the directory before and after the suite.

## Documentation

- **`docs/FUTURE_INDUSTRY_TARGETS.md`** — where Prism goes after springs and
  plastics. PCB fabricators (Fine Circuits / Fineline, Manjusar GIDC — the
  first real prospect, with what was proven against their actual 4-layer
  board), and EMS/assembly houses, which is the larger prize because they
  receive a Gerber AND a BOM AND a pick-and-place file. Includes the rule that
  matters: **the Gerber files never leave the machine** — Prism measures
  locally and only the measurements, the template and the company details go to
  the AI tools to be formatted. Their customers are aerospace and medical firms
  whose board geometry arrives under NDA.
- **`README.md`** — rewritten. It still said "v0" and described a July build,
  and one line in it was not merely stale but wrong: it claimed a sibling
  `../prism_terminal` checkout takes priority over the submodule. It does not,
  and never did. The same sentence had already been removed from
  `core_bridge.py`; this copy survived, and it cost an afternoon of editing a
  file that is never loaded — twice.

## Also in this round

The licence lease and secret store, macOS codesigning, and the UI pass that
lifted content onto cards and folded the seven CONFIGURE rows behind a
disclosure, all by the second developer on the project.

### Still open
The send path and the PO → BOQ hand-off remain written, unit-tested, and never
run against a real mailbox. `plans.py` feature names are still not in the
translation catalogue.

---

# Round 4 — the screens, and the rest of the loop

Round 3 built the engine and said plainly that the screens did not exist. They
do now, and the workflow runs end to end: read the mail, register it, quote it,
read the answer, chase the silence, argue with the no.

## The screen

Four tabs, in the order the work happens — **What arrived → Inquiries → What
they said back → Waiting on a reply.** The tab order is the explanation of the
feature, so it has a test of its own.

- **Colour.** Categories, statuses and reply intents are tinted so a
  hundred-row register reads at arm's length. The word is always there as well
  as the colour: roughly one man in twelve cannot tell the red from the green,
  and a register printed on the office laser comes out grey. Tests assert every
  category and every status has a colour, because an uncoloured cell in a
  coloured column reads as a rendering bug.
- **Checks on a timer.** Off by default; interval set in Setup. It only ever
  READS. A tick is skipped while a check is already running — two IMAP fetches
  racing on one bookmark is how the same inquiry gets registered twice — and
  skipped while a quotation is open on top. Failures on a tick go to the status
  line, not a dialog: a modal appearing over somebody's work every ten minutes
  because the mail server had a bad afternoon is how the feature gets switched
  off for good. For the same reason a tick never moves the tab.
- **Time as well as date** in the register. Two inquiries from one customer on
  the same morning were indistinguishable before. Converted to local time — a
  mail header carries the *sender's* offset, so a 09:00 enquiry from Germany
  was filing itself at 09:00 in a Gujarat register.
- **Editing a row by hand.** They can always edit the CSV in Excel, but a
  register that can only be corrected by closing the app is one they stop
  correcting. The bookkeeping fields are deliberately not editable — letting
  the inquiry number be retyped is how two rows end up sharing one.
- **Starting from a register they already keep.** Setup imports it: their own
  columns survive untouched, numbering carries on from theirs rather than
  reissuing a number already on a quotation, and an existing register is never
  overwritten. Columns Prism did not recognise are reported, not guessed.

## Replies, which is the part it is bought for

The engine already worked out what each reply meant. The GUI threw it away.

Tab 3 now shows the reply, what Prism makes of it, what the register *would*
say, and the customer's actual words underneath. **Nothing applies itself** — a
machine silently rewriting a sales record on the strength of a sentence it
might have misread is not something a business can check.

`register.mark_reply()` is careful about three things:

- **"Accepted" does not mean Converted.** Going ahead is a promise; Converted
  is a fact with a PO number behind it. Collapsing them makes the month-end
  conversion figure optimistic by exactly the orders that never arrived — the
  one number an owner would repeat to a bank.
- **An unreadable reply changes nothing but the date.** A wrong status is worse
  than a stale one: the owner acts on the register without re-reading the mail,
  and a quotation wrongly marked Not converted is never chased again.
- **Haggling is not a refusal.** "Send your best price" is the commonest reply
  there is, and reading it as a no closes a row that is still winnable.

## Chasing, unattended

Every two days, three times, then it stops. The schedule lives in the register
— `Reminders sent` and `Last contact`, the same two columns the owner can see
and edit — so there is no hidden second queue to drift out of step with it.

One reminder per check, never a batch: three leaving in the same second, to
three customers who talk to each other, reads as a machine. Each is worded
differently — the first is a light touch, the third asks straight out whether
to close the file. A failed send is not counted, or Prism gives up after three
reminders that never left the building. Off until switched on.

## Winning back a no — and less Groq

**`core/drafting.py` is new.** Writing a page of persuasion that knows what was
quoted, what they objected to, and how far this owner will move on price is a
different job from labelling an inbox. It goes through the AI tools in the
customer's own Chrome, on their own subscription — no API key, no per-token
cost.

The risk is a tool that offers 15% because it sounded persuasive. So: no figure
may appear that is not in the owner's own policy file, **no policy file means
no discount is offered at all**, and the customer's email is marked as
information rather than instruction — a buyer cannot write "ignore your pricing
policy" and negotiate with the tool directly.

Two things deliberately did **not** move to the browser, with the reasoning in
the module docstring: sorting the inbox (a browser round trip is most of a
minute; two hundred emails is a working day with their Chrome held hostage) and
writing the register (Python writes it atomically, gets the money right to the
paisa, and cannot hallucinate a row — and it is the customer's order book, not
something to post to a website).

**Reading a reply now usually needs no AI at all.** `mailflow.local_intent()`
settles the formulaic ones — 13 of 13 test phrases, zero calls. Only genuinely
vague replies reach the model. The rules run first even when a key is
configured, or they would be dead code.

## Pricing from the owner's own formulas

The engine could always run a cost sheet; the GUI only read rate lists, which
locked out every shop quoting made-to-drawing work. Either source works now,
and every line of the working is shown — this is the number they will be asked
to justify on the phone.

Two defects the testing found:

- **The quotation totals the *rounded* per-piece rate**, so it does not equal
  the cost. Reading ₹31,556 on screen and sending ₹31,550 is how an owner stops
  believing the whole calculation. The gap is now stated in words.
- **A blank weight quoted the labour alone** — an under-quote that looked like
  a finished quotation. It refuses now.

## FFmpeg

A Windows customer met a codec install guide on pressing Reel. FFmpeg is now
**bundled** (`imageio-ffmpeg` in the wheel), with a verified download as the
fallback: the same wheel, checked against the SHA-256 PyPI publishes for that
exact file, verified before it is unpacked. `reel.py` and `reel_web.py` each
had their own `shutil.which("ffmpeg")`; both delegate to one resolver now, and
a test parses the AST to keep it that way.

The self-test line that read "optional — needs FFmpeg on the machine" *was* the
belief that caused the bug. It names which FFmpeg is in use now.

## The licence server

- **`DEFAULT_SERVER` now ships the Render address.** `api.alphakore.in` has no
  DNS record, and a build pointed at a name that does not resolve cannot
  activate anybody. This is a temporary pin with a real cost — see
  **SHIPPING.md §3.2**, which is now the only place that says how to undo it,
  and which `tests/test_licensing_endpoint.py` fails if anyone deletes.
- **`ACTIVATE_TIMEOUT` 30s → 75s.** A cold `/health` on that host measured
  **42.6 seconds**; activation was giving up 13 seconds early against a server
  that was up and healthy. Activation is the one call a new customer cannot go
  around — no cached token, no way into the app.
- Deliberately **no retry** on activation, unlike authorize. A timeout there is
  ambiguous: the request may have counted a seat before the socket gave up, and
  burning the second seat of a two-seat licence is worse than the failure the
  retry would fix.

### Not done
`plans.py` feature names and blurbs are still not in the translation catalogue
— unchanged from Round 3, still a pre-existing gap.

The send path and the PO → BOQ hand-off are written and unit-tested but have
never run against a real mailbox. Reading is the well-covered half.

---

# Round 3 — Inbox to Order

Asked for in person by a spring manufacturer at GIDC: *let Prism read my mail,
sort it, keep my inquiries in one file, quote from my own rate list, track
whether the customer said yes or no, and when the PO comes, make the production
sheet.* They also asked for SOPs to be sent to customers automatically.

The engine for all of it is built and tested. **The screens are not** — see the
end of this section.

Two documents cover it: [`docs/EMAIL_WORKFLOW.md`](docs/EMAIL_WORKFLOW.md) is
what happens, in plain language, with the flowcharts;
[`docs/EMAIL_WORKFLOW_RUNTIME.md`](docs/EMAIL_WORKFLOW_RUNTIME.md) is how —
which AI does which job, his day hour by hour, and every point a person is
needed.

### Reading the inbox — `core/inbox.py`
The other half of `mailer.py`, which could already send. IMAP over the standard
library, no new dependency. Works with any company-domain mailbox; `discover()`
tries `imap.`, `mail.` and the bare domain so nobody has to know what their
server is called.

**Two rules it will not break.** The folder is opened read-only and every fetch
uses `BODY.PEEK`, so Prism never marks anything read, moved or deleted — the
owner still uses Outlook on the same account, and a tool that silently cleared
unread flags would make them miss a real order. And nothing in the file talks
to an AI; fetching is plumbing.

Handles the things that bite in year two: a server that renumbers the mailbox
(UIDVALIDITY), the `UID n:*` search that always returns the newest message even
when it is older than asked for, attachment filenames containing `../`, and
four customers all attaching `drawing.pdf`.

### Sorting it — `core/triage.py`
Local rules first, AI only for what is left. A newsletter is caught by its own
`List-Unsubscribe` header, an out-of-office by `Auto-Submitted`, a known
customer or supplier by a list the company already has. Only genuinely new
correspondents are ever put in a prompt, and only a 1,200-character snippet of
them.

That ordering is what makes "most of your mail never leaves this computer" a
testable claim rather than a hopeful one — and it is tested: a suite check
fails the build if locally-sorted mail ever reaches a prompt. `local_only`
turns off the AI pass entirely and the feature still works.

Corrections are learned per exact address, so a sender is never asked about
twice. They outrank every rule except machine post — one mistaken tap must not
put a robot's auto-reply in the register for ever.

### The register — `core/register.py`
One growing CSV, one row per inquiry, opens in Excel. Financial-year numbering
(`INQ/25-26/0087`, April to March, like every quotation book in the country).
Written atomically, because a crash mid-write must not truncate somebody's
order book. Columns they add by hand survive. When the file is open in Excel it
says *"close the inquiry register in Excel"* rather than failing silently.

Replies find their own row by Message-Id, falling back to an open inquiry from
the same address — which catches the customer who replies from their phone and
breaks the thread. A closed row never swallows new business.

Also here: `awaiting_followup()`, the most valuable list in the file, and the
month-end figures. Conversion is counted against quotations sent, not inquiries
received — an inquiry nobody quoted was never a chance, and counting it makes
the number flattering and useless.

### Pricing — `core/quoting.py`
Reads their rate list (CSV, or Excel via openpyxl) and finds the header row
rather than assuming row 1, because real price lists open with a letterhead.
Understands quantity slabs from `Rate @ 1000` columns. Matches free text to a
row by rare-word weighting with the digits weighted up again, because in this
trade the numbers are the specification — and returns *candidates with reasons*,
never a decision.

For made-to-drawing work there is no rate to look up, so there is a cost sheet:
their own lines, their own rates, charged per kg, per piece, per lot or as a
percentage. Plus wire and coil weight from a drawing's dimensions — geometry,
checkable against a scale.

**No AI touches a number in this file, and a test enforces it.** Every figure
is Decimal, rounded half-up the way Indian accounting does — Python's default
turns ₹0.125 into ₹0.12 where Tally says ₹0.13, and "the software rounds
differently" is not a conversation worth having. The AI is handed formatted
figures and told, twice, to write the sentences around them.

### Purchase orders — `core/po.py`
Pulls the fields out of a PDF or Word PO, then puts it next to the quotation
and points at every difference. Scans are detected and say *"type these four
things in"* instead of returning a confidently empty order.

### SOPs — `core/sop.py`
The easiest thing in the whole workflow to automate, because there is no money
in the message. Library from a folder — revisions read from filenames like
`SOP-07_Heat-Treatment_rev3.pdf`, or from an index file if they keep one — and
only the newest revision is ever offered.

Four triggers, and the third is the one worth building for: **revise a
document and everyone holding the old revision is chased automatically.** The
log records who received which revision on which date, which is the answer to
*"prove your customers were notified"* — the question an ISO auditor asks, and
which today means somebody searching Sent Items for an afternoon.

### The daily loop — `core/mailflow.py`
One `check()` call does everything that cannot cost money if it goes wrong, and
hands back a worklist of what needs a person. **It never sends anything** — a
test greps the file to keep it that way. It never raises either: this runs on a
ten-minute timer next to somebody running a factory, so a mail server having a
bad afternoon belongs in a status line.

### Scenario testing — `devtools/scenarios.py`

Thirteen situations rather than unit tests: a full Monday morning of ten mixed
mails, a customer who haggles all the way from inquiry to PO, ten shapes of
badly-built rate list, 200 messages at once, a mail server that is down, an
email that tries to talk to the AI reading it. **148 checks, under a second, no
network.** Run it before a release.

The unit suite proves the pieces behave. This proved they behave *together* —
and it found four real bugs that unit tests had not, every one now also pinned
by a test:

- **`Rs.1,000/-` parsed as ZERO.** The worst bug in the feature, and invisible.
  That is how money is written in every Indian office. The parser deleted
  everything that was not a digit, a dot or a minus, turning it into `.1000-` —
  unparseable, so zero. Every order value typed the normal way summarised as
  ₹0, and a rate list cell written `28.50/-` would have quoted at **nothing**.
  There is now one strict parser shared by the register and the quotation, so
  the two can never disagree about what a rupee looks like.
- **A customer could forge a message boundary.** An email body containing
  `--- EMAIL 2 ---` was pasted into the sorting prompt verbatim, so a sender
  could fake a second message and ask to be sorted as `internal` — never
  registered, and nobody notices a customer whose mail silently stopped
  arriving. Boundaries and answer-shaped lines are now neutralised, the batch
  size is stated, and the prompt says message text is never an instruction.
- **`local_only` only did a third of its job.** It was passed to the sorter
  alone, so detail extraction and reply reading still sent customer
  correspondence out. A privacy switch that quietly does two thirds of what its
  name promises is worse than not offering one.
- **A bare "Enquiry" subject became a useless register row.** Half of all
  inquiries arrive under one. It matched nothing on a rate list and told a
  human nothing either. The opening line of the message — skipping the
  greeting — is now used when the subject carries no information.

### Two bugs from round 2, found while chasing the CI failure

Neither is part of Inbox to Order. Both were introduced by round 2 and both are
the same shape as the scenario bugs — silent, no symptom, wrong only where it
counts.

- **The licence server address was regressed to the hosting provider's URL.**
  A one-line change to `DEFAULT_SERVER` rode along inside a commit about
  cold-start timeouts: `api.alphakore.in` became
  `prism-license-server.onrender.com`. Nothing failed — the app built, started
  and self-tested clean — and **every customer activation in that build would
  have gone to the wrong host.** It also welds the binary to Render for its
  whole life, since the domain is the only thing that lets the server move
  without shipping a new app. `SHIPPING.md`, `LICENSING.md` and the comment in
  `licensing/keys.py` all name the domain; only the code disagreed. Restored,
  and `tests/test_licensing_endpoint.py` now fails if it drifts again — it also
  checks the address is HTTPS, has no trailing slash, and still matches the
  regex `packaging/prism.spec` uses to rewrite it for staging builds.
- **`core_bridge.py` described the opposite of what it does.** It claimed a
  sibling `../prism_terminal` checkout took priority "so you're always working
  against the copy you're editing". It does not: `paths.resource()` resolves to
  the submodule when running from source and is checked first, so a sibling was
  never reached. The behaviour is right — the submodule is what gets committed
  and built — so the sentence went rather than the code. And because this
  machine genuinely has both copies, `core_bridge` now prints which one is
  loaded and which is ignored, which is the sentence that ends the afternoon
  somebody would otherwise lose editing the wrong tree.

### Two bugs found by the tests, both real
- **A rate cut was measured against the wrong thing.** The PO comparison
  ignored differences under ₹1. Ninety paise off a unit rate is under ₹1 — and
  on 5,000 pieces it is ₹4,500, walking straight past the check that exists to
  catch it. The tolerance now multiplies out by the quantity first.
- **The inquiry folder was not created when nothing was attached.** The
  register printed a path that opened onto nothing.

### Also
- `plans.py` gains the `inbox` feature. Inclusive in **Works** — it is the
  piece they use every day, and it is what makes them open Prism at all.
  An add-on for **Studio**.
- **The BOQ paywall copy was lying.** It promised "a priced BOQ"; the engine
  deliberately leaves Rate and Amount blank. Now it says the customer's rates
  go in the blank columns — Prism counts, you price. Same correction already
  made in the business documents.
- `openpyxl` added to `requirements.txt`. Optional at runtime, bundled in every
  build.

### Not done — the screens
The engine runs the whole loop. The window he clicks in does not exist yet:
mail-account setup, the worklist, the quotation review with its Hold button,
and the PO confirmation. That is the next piece of work, and it is what he will
judge the product by.

Also still English-only: `plans.py` feature names and blurbs are not in the
translation catalogue — the new `inbox` feature is in exactly the same state as
every existing one, so this is a pre-existing gap rather than a new one.

---

# Round 2 — roles, languages, cloud attach, plain-English errors

---

## Bugs fixed

### Apollo was being sent a paragraph and refusing it
A live run failed with `Value too long: 'Context from the previous pipeline
stage (RESEA…' exceeds 200 characters`. Apollo is a filter screen, not a chat
box, and its API rejects any single value over 200 characters — the pipeline
was handing it the whole inter-stage brief.

Two halves. The stage before Apollo is now told to emit a fixed filter block
(`TITLES / INDUSTRIES / LOCATIONS / HEADCOUNT / KEYWORDS`) instead of prose,
and Apollo is driven by **its own search URL** rather than by typing into the
page — Apollo mirrors its whole search state into the address bar, so this
sets the same filters without touching the left rail's class names. Values are
hard-capped in code, not just asked for in the prompt.

*Files:* `core/agents.py`, `core/automation.py`, `tests/test_apollo.py`

### Canva took over every image
With the Canva app connected to ChatGPT, every visual and presentation turn
came back as a flat template — including jobs that needed a rendered
illustration. Canva composes a stock layout; DALL·E renders the scene actually
described.

Canva is now **opt-in**: it engages only when the user's own words ask for
something editable (`canva`, `editable`, `template`, `edit later`…). And when
they have not asked, the prompt says so explicitly — silence is not enough,
because a connected Canva app gets reached for unless told otherwise.

*Files:* `core/agents.py`, `core/automation.py`, `tests/test_canva.py`

### Add file stopped working
Caused by the i18n work below. To translate a window caption, `QFileDialog`'s
**static** methods were wrapped — but those are the entry point to a *native
OS panel*, not a Qt widget, and every attachment in the app goes through them.
macOS does not even draw a title on an open panel, so the patch bought nothing
and cost the most load-bearing path in the UI.

Statics are stock again; captions are translated at the call sites instead. A
test now fails the build if they are ever wrapped again, and a second test
greps every call site for a bare literal caption.

*Files:* `i18n.py`, `main_window.py`, `widgets/*.py`, `tests/test_i18n.py`

### LAZYCOOK was being talked down to
It runs its own Generate → Analyze → Optimize → Validate loop and scrapes the
web itself — which is the entire reason to route to it over Perplexity. Prism's
house style (`Your ONLY task is:`, a fixed section list, `STRICT PIPELINE
RULES: 1. Perform ONLY the task above — nothing more`) reads to it as "stop
after the first pass", so it answered in one shot and came back weaker than
the tool it was chosen over.

Agents can now declare `prompt_style="natural"` and get asked the way a person
asks. The handoff is still requested — the pipeline cannot work without it —
but as a request at the end rather than as rule 3 of 4. The router also gets a
carve-out rule, **only when such a tool is actually in the plan**.

*Files:* `core/agents.py`, `core/automation.py`, `core/router.py`

---

## New features

### Multilingual — Hindi and Gujarati, 100%
Prism translates **by value**, not by call site: `t()` takes the English string
and returns the local one, and `install()` patches the Qt methods that put text
on screen so no widget code changed.

The safety property: a string is only swapped if it is in
`lang/_catalogue.json`. The same `setText()` also draws customer names, file
paths and whole paragraphs written by Claude — none of those are in the
catalogue, so none can be touched. Run `devtools/extract_strings.py` after
adding UI copy.

Also handles: script-appropriate font fallbacks (Barlow has no Devanagari),
right-to-left layout, and a **separate** setting for what language the AI
tools write back in — plenty of people want the app in Gujarati and the client
deliverable in English.

*Files:* `i18n.py`, `lang/`, `devtools/extract_strings.py`, `core/lang.py`

### Roles, per-member folders and a manager view
A company activates with one **company key**; each person then pastes a
**designation key** (`PRSD1.…`) that we mint. The role is Ed25519-signed, so it
cannot be forged by editing a settings file — tests cover self-promotion,
another company's key, and replay as a licence token.

Eight roles (Owner, Manager, Sales, Marketing, Operations, Engineering,
Accounts, HR), each with its own workspace folder, default tools and **accent
colour** — the hue rotates while every swatch keeps its exact lightness, so
contrast is identical in all nine (measured drift: 0.000000).

`workspace.readable_members()` is the single access rule: a working role sees
one folder, an admin sees all. Every screen goes through it.

> Enforced by Prism, not by the OS. On a shared drive a member can open Finder
> and read another folder. The signed role is the part that is solid.

*Files:* `roles.py`, `identity.py`, `workspace.py`, `plans.py`,
`licensing/designation.py`, `theme.py`

### Cloud file attach — no OAuth
Add file now lists every cloud folder mounted on the machine — Google Drive
(named by account), Shared drives, OneDrive, Dropbox, iCloud — and opens the
chooser inside it.

Google Drive for Desktop mounts Drive as an ordinary folder, so there is no
token, no consent screen, and nothing that expires. The OAuth path in
`integrations/gdrive.py` still exists for anyone without Drive for Desktop,
but it is no longer the way in.

*Files:* `cloud.py`, `integrations/`, `dialogs/drive_dialog.py`

### Plain-English errors
Every failure goes through one translator and comes out as **what happened**,
**what to do** as numbered steps, and where possible a button that does it.

`session not created: This version of ChromeDriver only supports Chrome 131`
becomes *"Prism couldn't open Chrome"* with three steps and a button to the
Chrome setting.

Tests fail the build if "webdriver", "selector", "traceback", "HTTP" or
"OAuth" reaches the screen, or if any message lacks a next action — a message
without one is a phone call.

*Files:* `friendly.py`, `dialogs/problem_dialog.py`

### A guide, and a welcome
"How to use Prism" is second in the sidebar: 13 topics in plain language with
copyable examples. Locked add-ons appear greyed with what they do — it is the
only place a customer discovers what else we sell. First-timers get a welcome
offering the tour before Setup.

*Files:* `dialogs/guide_dialog.py`, `main_window.py`

### Attachments
Folders now show as one row with their files indented, so a whole "Add folder"
can be removed in one go. Plus **Detach all**, a duplicate guard, and a status
message for every outcome — so a button that appears to do nothing is
impossible.

*Files:* `widgets/files_panel.py`, `main_window.py`

---

## Reliability

Audited the whole path a daily user walks. See `KNOWN_ISSUES.md` for the
plain-language version sorted into *fixed / code / needs money / nobody can
fix*.

| | |
|---|---|
| **Groq retires a model** | `MODEL_FALLBACKS` is a list. A dead model falls through, the working one is saved, the customer sees nothing. This one would have taken every install down on the same day. |
| **Rate limits** | Waits the `retry-after`, retries once, then says what to do. |
| **Cold-start refusals** | Authorize timeout 15s → **45s** plus one retry — transport failures only, never on a real answer, so a metered run cannot be double-counted. |
| **No way to debug** | Rolling log in `~/.prism/logs` + **Export diagnostics**. Credentials and email addresses are stripped, and that is tested. |
| **Sleeping mid-run** | Wake lock held for the run, released even if the window closes mid-run. |
| **Silent truncation** | Long attachments show "(first part only)". |
| **Workspace offline** | Banner saying today's work will not reach the manager. |

*Files:* `diagnostics.py`, `awake.py`, `core/router.py`, `licensing/client.py`

---

## Things deliberately NOT done

- **Licence server hosting.** The 45s timeout absorbs most cold starts, but a
  host that sleeps needs a paid plan. Free interim: point an uptime monitor at
  `/health` every 10 minutes.
- **Publishing the Google OAuth consent screen.** Only matters if we ever use
  the API route instead of Drive for Desktop. While it is in Testing, refresh
  tokens expire every 7 days.
- **The guide's own text is English only.** The UI is 373/373 in Hindi and
  Gujarati; the 13 guide topics are not in the catalogue yet.
- **Rate cards.** The BOQ engine leaves Rate/Amount blank on purpose. Letting
  a customer attach their own price list is the single feature that would open
  the dealer and manufacturer markets — see `docs/BUSINESS_NOTES.docx`.

---

## If something here breaks

1. `Settings → Export diagnostics` — one file, credentials stripped.
2. `~/.prism/logs/prism.log` — the rolling log.
3. `python3 -m unittest discover -s tests` — 263 tests.
4. `QT_QPA_PLATFORM=offscreen PRISM_SELFTEST=1 python3 main.py` — proves a
   build is whole.
