# The Gerber add-on — the full workflow, in plain words, and where we are

**Source:** the printed diagram "AI-driven PCB DFM analysis – workflow"
(10 stages), photographed 2026-08-26. This page explains each stage in
ordinary language, says what Prism already does for it, and how much is
left.

**One sentence first.** The diagram describes a complete *DFM* product —
"design for manufacturing" — that reads a customer's PCB job and tells the
factory everything that could go wrong in production. The customer we have
asked for something much smaller: **five numbers** (board size, minimum
track width, minimum track spacing, minimum drill size, number of drills).
Those five are built, tested on real jobs, and verified. The rest of the
diagram is what the add-on could grow into.

---

## The ten stages, in plain language

**1. Input from the customer.** A job arrives as a zip, a folder, or loose
files: the Gerber files (one per layer of the board), the drill file, a fab
drawing (a PDF with the designer's instructions), and sometimes a stack-up,
notes or a bill of materials.

**2. Work out what each file is.** Every file is sorted into its role — top
copper, bottom copper, top/bottom solder mask, drill, board outline,
mechanical, text/legend, or "unknown" — with a confidence score saying how
sure the sorting is.

**3. Read the files into shapes.** The Gerber text is parsed, the tool
shapes ("apertures") interpreted, the actual copper geometry rebuilt as
polygons, the drill file read into hole positions and sizes, and any text
on the drawing read by OCR.

**4. One tidy model of the board.** Everything from step 3 is put into one
common structure — layers, pads, tracks, vias, regions, drill hits,
outline, mechanical features, notes — so every later step works from the
same data.

**5A. The geometry engine (deterministic — pure measurement).** Board
size, track width, track spacing, drill analysis, annular ring, copper to
edge, solder-mask clearance, acid-trap detection, short/open check,
panelisation analysis. No AI — the same input always gives the same number.

**5B. The AI engine (the intelligence layer).** Reads the things that are
written for humans: the fab drawing (OCR + language), the manufacturing
notes, the stack-up; normalises layer names; spots intent and anomalies;
classifies risk and explains it.

**6. The rule engine.** Checks the measurements against rules: electrical,
manufacturing, the customer's own, industry standards (IPC), and the
company's own standards.

**7. Correlate and prioritise.** Merge all results, apply tolerances, mark
each as Pass / Warning / Fail, attach a confidence to each, remove
duplicates and link related violations.

**8. AI report generator.** Turn the results into a plain-language
explanation, pictures of each violation on the board, and recommendations.

**9. Engineer review and approval.** A person reviews, marks up, comments,
accepts or rejects, adds notes. The diagram's own note: low-confidence
results are flagged for manual verification — the human is always in the
loop here.

**10. The final DFM report.** A PDF summary, a detailed PDF/HTML report, a
violation list in CSV/Excel, an annotated board viewer, and a job archive
(JSON / database).

---

## What Prism already does — stage by stage

Legend: ✅ built and tested on real customer jobs · 🟡 partly · ⬜ not started

| Stage | Box on the diagram | Status | What exists today |
|---|---|---|---|
| 1 | Job.zip / folder | ✅ | `gather()` walks zips, rars and nested folders; several jobs in one archive are split apart (`split_jobs`) |
| 1 | Gerber files, drill files | ✅ | read; drill also read when it arrives as a Gerber of pads (old CAM systems) |
| 1 | Fab drawing / PDF | ⬜ | not opened |
| 1 | Stack-up / notes / BOM | ⬜ | not opened |
| 2 | Layer classification | ✅ | `classify()` sorts by name and extension into copper / mask / drill / outline / mechanical / legend / unknown; the designer's own rule file, when the job ships one, is read too |
| 2 | Confidence score per layer | ⬜ | it is a yes/no, not a score |
| 3 | Gerber parser (RS-274X) | ✅ | including modal D-codes, polarity order, macros, rotated pads — all found and fixed on real jobs (docs/GERBER_FIXES.md) |
| 3 | Aperture interpretation | ✅ | |
| 3 | Geometry reconstruction, polygon processing | ✅ | real copper shapes via shapely; lettering and plane layers excluded from track measurement |
| 3 | Drill processing | ✅ | Excellon with and without headers, backwards coordinate formats, several drill files per job, merged |
| 3 | Text / OCR | ⬜ | |
| 4 | One unified board model | 🟡 | `analyse()` returns one job record (layers, answers, warnings) and writes it to CSV; it is not yet the nets/pads/vias model the diagram draws |
| 5A | Board size | ✅ | from the outline layer, not from the ink |
| 5A | Track width, track spacing | ✅ | |
| 5A | Drill analysis | ✅ | count, minimum size, tool table |
| 5A | Annular ring | ⬜ | |
| 5A | Copper to edge | ⬜ | |
| 5A | Solder-mask clearance | ⬜ | |
| 5A | Acid-trap detection | ⬜ | |
| 5A | Short / open check | ⬜ | |
| 5A | Panelisation analysis | 🟡 | several jobs in one archive are told apart; a *panel* of one board is still read as one big board (listed as an open risk) |
| 5B | AI engine — all six boxes | ⬜ | deliberately not started: **no AI ever sees a Gerber file**, only the measured numbers. Reading the fab drawing PDF and notes with AI would be allowed — that is text, not the board — but is not built |
| 6 | Rule engine | 🟡 | the job's own design-rule file is compared against the measurements and a warning raised when a rule is broken; no customer / company / IPC rule sets |
| 7 | Pass / Warning / Fail, confidence | 🟡 | warnings are raised and shown; `crosscheck()` compares the drill count and tool table against the job's own CAM report (`.DRR` / `.REP`), which is the closest thing to a confidence check we have; no Pass/Fail classification, no dedupe |
| 8 | Natural-language explanation | 🟡 | `agent_brief()` hands the five numbers (and only the numbers) to a writing tool to draft the customer reply — the GUI's "Write this up" |
| 8 | Violation snapshots, recommendations | ⬜ | |
| 9 | Engineer review | 🟡 | the Gerber window shows every measurement and its working before anything is written up — a person is in the loop; no markup / accept-reject / notes |
| 10 | CSV report | ✅ | one CSV per job plus a summary CSV, saved to `Desktop/Prism Gerber` |
| 10 | Job archive (JSON) | 🟡 | a run record is kept in History |
| 10 | PDF summary, detailed PDF/HTML, annotated board viewer | ⬜ | |

**By the boxes:** about 20 of the diagram's ~50 boxes are built, 8 are
partly there, and the rest are not started — roughly **a third to 40 %** of
the diagram. **By what the customer asked for:** 100 % — the five figures,
verified on both real sample jobs, with a second independent implementation
(`gerbonara`) agreeing layer for layer.

---

## What is left, in the order it is worth building

1. **More of 5A** — the measurements that are the same *kind* of work as
   the five we have and reuse the geometry we already build: **copper to
   edge**, **annular ring**, **solder-mask clearance**. Each is a few days
   with a real job to test against. These are also the ones a fab actually
   argues with a customer about.
2. **Pass / Warning / Fail against a rule set (6 + 7).** Today a broken
   design rule is a warning line. A short table of the fab's own limits
   (minimum track, spacing, drill, ring, edge clearance) and a green/amber/
   red verdict per measurement is the step that turns "five numbers" into
   "a check". Small.
3. **A readable report (10).** The CSV exists; a one-page PDF with the
   verdicts and the workings is what gets emailed to a customer.
4. **Panel vs board (5A).** Recognise a step-and-repeat panel and report
   the single board — currently an open risk that would give a wrong size
   silently.
5. **Reading the fab drawing and notes (5B).** OCR of the PDF and language
   reading of the notes. This is the first place AI enters, and it is
   allowed — the drawing is instructions, not the board. Medium.
6. **Short / open, acid traps, annotated viewer, markup/approval (5A, 8,
   9).** Real DFM features, each a project of its own. Only worth starting
   once a paying customer names one.

What should **not** be built without a customer's written permission: any
step that sends the Gerber files themselves to an AI. See
`docs/GERBER_FIXES.md` for every bug found so far and what the pattern says
will break next.
