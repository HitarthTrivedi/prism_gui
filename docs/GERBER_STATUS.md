# Gerber add-on — the ledger

**What this is.** One page that says, for every figure and every feature of
the Gerber add-on: is it built, is it tested, on which customer files, and
who has confirmed the number. Kept current; the date at the top is the day
it was last true.

**Last updated:** 2026-08-26 · engine `prism_terminal/core/gerber.py`,
`gerber_clean.py` · GUI `dialogs/gerber_dialog.py` · pins
`tests/gerber_samples.json`

**How to read "tested".** Three levels, and the difference is the whole
point:

| Level | Meaning |
|---|---|
| **witnessed** | a person or a machine outside Prism agrees — the customer's check sheet, or the CAM report shipped inside the job. If this breaks, Prism is wrong. |
| **cross-checked** | an unrelated implementation (the `gerbonara` library) reads the same file and gets the same number. Catches parser bugs; cannot catch a wrong definition. |
| **locked** | only what Prism reads today, pinned so it cannot drift silently. If it moves, someone must say whether that was an improvement. Not proof of correctness. |

---

## 1. The nine figures

The customer asked for nine numbers from every incoming job. Five were asked
for on 2026-08-19, four more on 2026-08-26.

| # | Figure | Built | How it is measured | Tested on | Level |
|---|---|---|---|---|---|
| 1 | PCB size | 08-19; outline closing rebuilt 08-26 | largest closed shape on the outline layer (strokes noded, then polygonised); drill guide/drawing when no outline layer; copper extents as last resort, flagged | synthetic ×4; all 8 real jobs | **witnessed** on 101942 (60 × 73, check sheet + xlsx) and EI-500DT (90.17 × 90.17, check sheet); locked on 2-547, CT-TT (now 184 × 39), MIE, PCB-2199; **not confident** on 2580043B (see §5) |
| 2 | Array size | **08-26** | several closed faces of one size on the outline layer, not overlapping, covering ≥ 40 % of their frame → the frame is the array | synthetic routed panel (60 × 40, 2 × 2), synthetic V-scored panel (100 × 90, 3 up), real CT-TT (184 × 195) | locked on CT-TT; single-board answer locked on 3 others |
| 3 | PCBs in the array | **08-26** | count of those faces, plus the grid (across × up) | same | locked: CT-TT = 5 (1 × 5) |
| 4 | Min track width | 08-19 | smallest circular aperture used to draw a conductor; lettering and plane layers excluded | synthetic; all 6 pinned jobs | **witnessed** on 101942, EI-500DT; locked on 4 |
| 5 | Min track spacing | 08-19 | nearest copper-edge gap between conductor islands (shapely STRtree); gaps under the snap tolerance treated as touching | same | **witnessed ± 0.06 mm** on 101942, EI-500DT; locked on 4 |
| 6 | Min drill size | 08-19 | smallest tool with ≥ 1 hit, Excellon or drill-as-Gerber | synthetic; all 6 pinned | **witnessed** on all 6 (the jobs' own `.DRR` / drill reports) |
| 7 | Total drills | 08-19 | hits across every drill file, merged by diameter; rout paths excluded | same | **witnessed** on all 6 |
| 8 | Min pad pitch | **08-26** | smallest centre-to-centre distance between two *separate* flashed pads on any copper layer; a pad drawn in overlapping pieces is one pad | synthetic (0.5 mm QFP row; two-circle oval ignored); real 101942, EI-500DT, 2-547, CT-TT | **cross-checked** with gerbonara on 101942; locked on the 4 fast jobs (5.0 / 0.483 / 0.439 / 1.524 mm) |
| 9 | Min SMT pad size | **08-26** | narrow side of the smallest flashed pad on an outer copper layer with no drill hit within its own half-extent; "none" when every pad has a hole; every pad counted (and said so) when the job has no drill positions | synthetic (0.4 × 1.2 chosen; through-hole excluded; no-drill warning; all-holes → none); real ×4 | **cross-checked** with gerbonara on EI-500DT (0.254 mm); locked on 4 fast jobs (none / 0.254 / 0.28 / none) |

**Not yet done for figures 2, 3, 8, 9:** no human has confirmed any of
them. They are pinned as *locked*. The witness to get is one CAM reading
per job from Keyur bhai (§6). The two slow jobs (MIE, PCB-2199) have not
been run for 8 and 9 at all — they are opt-in (`PRISM_SLOW_TESTS=1`).

Where the nine appear: the Gerber window's text, `agent_brief()` (what a
writing tool is given — numbers only), the per-job CSV, and the one-sheet
summary CSV (four new columns after TOTAL DRILL; his original column order
is untouched).

**Two decimal places, everywhere a figure is shown or written** (the
customer's instruction; their check lists are kept that way). The maths
underneath keeps full precision — only the rendering rounds, and a test
scans every output for a third digit.

---

## 2. The three CAM features

What Keyur bhai does by hand in CAM350 before a job can run, in the order
the customer listed them.

| # | Feature | Status | What exists | Tested on |
|---|---|---|---|---|
| 1 | Filter everything outside the edge cut | **built 08-26** — awaiting his verdict | `gerber_clean.clean_job()`: objects wholly outside the outline removed from copper / mask / silk / paste / pad-master layers, written back through gerbonara; crossing objects kept and listed; outline, mechanical, drill, reports copied through; `cleaning_report.txt/.csv`, before/after SVG per layer, `compare.html`. GUI: **Clean outside the border** button → `~/Desktop/Prism Gerber/<job> cleaned <date>/` | synthetic ×9 cases (inside / outside / crossing / kissing the edge / legend strokes / offset layer / no outline / panel / wrong outline); all 8 real archives (§4) |
| 2 | Polygon management | **not started** | — | needs his list of what he does to polygons by hand |
| 3 | Array and PCB size verification | **built 08-26** — awaiting his readings | `panel()` (figures 2–3 above); the cleaner uses the whole panel, never one board of it | see §1 rows 2–3 |

**Safety rules in the cleaner, each one a real near-miss:**

- A layer is **refused** (copied unchanged, flagged) when nothing on it lands
  on the board, or its extent sits < 10 % over the board, or > 35 % of its
  copper *by area* would be removed. The area rule was added the same day
  after the first sweep showed the cleaner ready to delete 60 % of the
  12-layer board against an outline it had taken from a drill drawing.
- An **array is cleaned against the whole panel**. The first sweep took one
  184 × 39 board as the outline and removed the other four boards' copper
  (3,338 of 4,186 objects). Caught by running every archive, not by a test
  — the test exists now.
- Objects **crossing** the edge are never cut; cutting a stroked track
  rewrites it as a region and is the operator's decision.

---

## 3. What changed on 2026-08-26 (this session)

Engine (`prism_terminal`):

- `b80d208` — `core/gerber_clean.py` (new), `outline_face()` factored out of
  `board_outline()`.
- `d675456` — noded polygonising + 0.15 mm loose-end joining
  (`closed_faces`, `_join_loose_ends`); `panel()`; `pad_pitch()`,
  `smt_pads()`, `_pad_dims()`; Excellon keeps modal X/Y so every hit has a
  position (was 121 of 218 on EI-500DT); `holes` carried through
  `excellon()`, `merge_drills()`, `drill_from_gerber()`; `analyse()` returns
  `array`, `pitch`, `smt` and the new answers; `answers_text()` numbered
  1–9; `agent_brief()`, `write_report_csv()`, `write_summary_csv()`
  extended; cleaner cleans against the panel and refuses by area.

GUI (`prism_gui`):

- `37dd8dc` — **Clean outside the border** button, `GerberCleanWorker`,
  `core_bridge.get_gerber_clean()`, `tests/test_gerber_clean.py`.
- `d719c36` — `tests/test_gerber.py` +5 classes (array, pitch, SMT,
  gappy outline, gerbonara cross-check of pitch and SMT);
  `tests/gerber_samples.json` re-pinned (CT-TT size corrected to 184 × 39;
  new locked keys); `docs/GERBER_FIXES.md` #21 and open items 10–11;
  `docs/GERBER_WORKFLOW.md` updated; this ledger.

One pinned value **moved**: CT-TT-CAP12 `pcb_size_mm` 196 × 195 → 184 × 39.
The old value was the panel plus the 6 mm the score lines overhang it; the
job's own description always said "a PANEL carrying many copies".

---

## 4. Every job we hold, and what each feature did on it

Ground truth lives in `prism-ai-flow/gerber_test/` (outside the repo).

| Job | What | Pinned | Witness for | Cleaning sweep (08-26, after the fixes) |
|---|---|---|---|---|
| `layer 1.zip` — **101942** | 2013 single-sided, drill as Gerber, G36 copper | yes | size, width, spacing±, drill, count — customer's check sheet + xlsx | outline 60 × 73 from drill guide (no outline layer); legend strokes removed on 4 layers (163 / 239 / 252 / 221); 4 frame lines crossing, kept |
| `101942 Gerber Rev01(V2.0)` | the same job as a folder | **no** | — | identical to above |
| `CAM for EI-500DT…rar` — **EI-500DT** | 2018 Altium 4-layer, `.DRR` | yes | size, width, spacing±, drill, count — check sheet + `.DRR` | outline 90.17² from outline layer; 11–14 objects removed per layer, 8–47 crossing kept |
| `2-547-161A_Gerber.zip` | 8 layers, 3 drill files, macro pads | yes | drill, count — `.DRR` | outline 53.2² from outline layer; **nothing outside** on any layer; 1–6 crossing |
| `CT-TT-CAP12…zip` — **the panel** | 5 × (184 × 39) on 184 × 195, V-scored, all through-hole | yes | drill, count — `.DRR` | cleaned against the whole panel; 0 removed on copper (1 silk object), 56 crossing per layer (frame + score lines) |
| `15012021…2580043B.zip` | 2 layers, 7 holes, `.RUL`, outline **open by 3–6 mm** | **no** | — | **refused** every layer: the fallback face was a title-block cell (28.6 × 11.4), 0 % of the copper over it — correct refusal |
| `MIE V2.2…rar` | PADS, 10 copper, `art001.pho` names, **slow** | yes (slow) | drill, count — drill reports | **refused** every layer: 220 × 100 frame from the drill drawing, only 3 % of each layer over it — the drawing and the art do not share an origin |
| `PCB-2199…zip` | PADS, 12 copper, 187k traces, **slow** | yes (slow) | drill, count — drill report | **refused** every layer by the area rule (it would have removed 51,560 of 82,215 objects on `art001.pho` before that rule) — the 383 × 274 "outline" is from a drill drawing and is *not* trustworthy |

---

## 5. Not tested, or known open

- **Figures 2, 3, 8, 9 have no human witness** on any job.
- **Cleaning has never been judged by a person.** It has been run on every
  archive and it is conservative; whether "conservative" is *right* is
  Keyur bhai's call, on the `compare.html` pages.
- **2580043B's true size is unknown.** Its outline is 147 strokes with five
  openings of 3–6 mm; Prism reports 23.49 × 44.06 mm from the ink extents,
  marked not confident. Pinned nowhere.
- **MIE and PCB-2199's sizes (220 × 100, 383.54 × 274.32) come from drill
  drawings**, are locked, unwitnessed, and the cleaner refuses to trust
  them. They need the outline layer from the customer.
- **A panel that draws only its frame** (repetition in `%SR` or in the
  copper only) still reads as one board; `%SR` now raises a warning saying
  so. No such job in hand.
- Not exercised by any job: negative image `%IPNEG`, RS-274-D copper (no
  `%ADD`), Excellon slots `G85`, blind/buried via drill files, mirrored
  bottom layers in the cleaner, 7-zip / tar / password archives.
- The two slow jobs are not in a normal test run.

---

## 6. What we need from Keyur bhai (the customer's CAM operator)

1. **Five before/after job pairs** — the raw job and the job as he cleaned
   it — so the cleaner's output can be diffed against his.
2. For each of the six pinned jobs, **his CAM reading of**: array size and
   count, finest pitch, smallest SMT pad. These become *witnessed* values.
3. **What 2580043B actually measures**, and whether its outline is meant to
   be open.
4. **The outline layers** for MIE and PCB-2199, or his sizes for them.
5. **His list of polygon operations** — feature 2 cannot be specified
   without it.

---

## 7. Test counts (2026-08-26)

`tests/test_gerber.py` + `test_gerber_clean.py` + `test_gerber_dialog.py`:
90 tests (2 skipped — the slow jobs), all green. Full GUI suite: 1,206
passed, 3 skipped, 2 pre-existing deselects. Nothing in the suite writes to
the real Desktop or `~/.prism`.
