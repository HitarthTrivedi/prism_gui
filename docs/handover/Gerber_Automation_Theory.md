# How Prism's Gerber automation works


---

## 1. The problem it solves

A PCB fabricator receives a job as a bundle of Gerber files and a drill
file. Before quoting, an estimator has to open the job in CAM software and
find five numbers by hand:

1. Board size
2. Smallest track width
3. Smallest gap between two copper tracks
4. Smallest drill size
5. Total number of drilled holes

That takes a trained person twenty minutes or more, for every job, and
those five numbers drive the whole price. Prism's Gerber automation finds
them in seconds, writes them into the customer's own quotation form, and
optionally has an AI write the reply. The design files themselves never
leave the machine.

---

## 2. The one rule that shapes everything

**No AI ever sees the Gerber files.**

A Gerber set *is* the customer's product. Sending it to an online AI would
be sending someone's design to a third party. It would also be useless:
an AI asked to look at a picture of copper can only guess a track width.
A wrong guess is a scrapped panel.

So the split is fixed:

- **Prism measures.** The geometry is read and measured by Prism's own
  code, deterministically, on the fabricator's machine.
- **The AI only writes.** After the numbers exist, an AI stage may be
  handed those five numbers, as text, to write a quote or a reply. It is
  never handed a file, a path, or an image of the board.

A test asserts that the write-up stage is given an empty attachment list.
If a future edit ever attaches a Gerber to an AI stage, the suite fails.

---

## 3. How a job is understood

### 3.1 Sorting the files

A job arrives as a zip or rar of nine to seventeen files with inconsistent
names. Prism opens the archive and works out what each file is by two
means:

- **The name** gives a hint. Common extensions and naming conventions map
  to a role: top copper, bottom copper, inner layers, solder mask, silk,
  outline, drill.
- **The content** confirms it. Each file is sniffed: a Gerber has aperture
  definitions and coordinate commands; an Excellon drill file has tool
  definitions and hit lists; a CAM report is plain text.

Where names are ambiguous, the numbered inner layers are resolved by
order, and a file whose role is still unknown is resolved from what is
inside it. The result is a list of layers, each with a role.

### 3.2 Reading a Gerber layer

A Gerber file is a drawing program, not an image. Prism's parser reads it
as such:

- **Apertures** are the "pens": circles, rectangles, obrounds, polygons,
  and user-defined macros built from primitives.
- **Draws** are lines made with a pen. **Flashes** are single stamps of a
  pen (pads). **Regions** are filled polygons.
- **Arcs** are expanded into points.
- **State** matters: the file sets a current pen, a current polarity, a
  coordinate format and a unit, and later lines depend on those settings.
  Missing this is where plausible-but-wrong numbers come from.

Every object is converted to real geometry in millimetres.

### 3.3 Separating copper from decoration

A copper layer also contains things that are not conductors: text glyphs,
logos, fiducials. Prism identifies the pens used only for lettering and
excludes them, so that a thin font stroke is not reported as the smallest
track on the board.

The remaining copper is merged into **islands**: sets of shapes that
touch. Each island is one electrically connected net.

---

## 4. How each of the five numbers is measured

**Board size** comes from the outline layer, not from the extents of the
drawing. The outline is turned into closed shapes and the largest closed
face wins. This matters: title blocks, fiducials and tooling holes sit
outside the board edge and would otherwise inflate the size, in one real
job by ten percent of area. If no closed outline exists, the bounding box
is used and the report says so.

**Panels** are detected. If the outline holds several identical boards
with rails, Prism reports the array size and the number of pieces per
array, which is what the fab prices.

**Minimum track width** is the smallest pen actually used to draw a
conductor, after decoration is excluded.

**Minimum track spacing** is the real copper-to-copper clearance between
different islands, measured by geometry. Two points make this hard:

- The smallest gap is usually noise: two shapes meant to touch, rounded
  apart by the file's coordinate resolution, leave a gap of a few
  hundredths of a mil. Gaps below a snap tolerance are treated as touching.
- Checking every pair of shapes is too slow on a big board, so only
  nearest pairs between neighbouring islands are compared.

Spacing is the one figure that needs an optional geometry library. Without
it, the other four numbers still come out and the report says spacing is
unavailable.

**Minimum drill size** and **drill count** come from the Excellon file:
each tool's diameter and the number of hits per tool. Several drill files
are merged. If a job has no drill file, hole data can be recovered from a
drill drawing in Gerber form.

Beyond the five, Prism also reports pad pitch, annular ring and SMT pad
size where the geometry allows, because the customer's form has cells for
them.

---

## 5. Checking the answer

Measurement alone is not enough. Both real parser bugs found during
development produced plausible numbers with no error and no crash. So
there is a ladder of checks, cheapest first:

1. **The job's own CAM report.** Many jobs ship a drill report. Prism
   parses it and compares tool tables and hole counts against its own
   count. Free, exact, no AI.
2. **A second, unrelated implementation.** In the test suite, an
   independent open-source Gerber library reads the same layers and the
   per-layer object counts are compared. This is what found both parser
   bugs.
3. **An AI sanity check on a rendered image plus the numbers.** Planned,
   not built. A picture is not a manufacturable design, so it does not
   break the rule.
4. **The raw files to an AI, only with the customer's written permission.**
   Never by default.

The customer also returned their own filled check sheet for two sample
jobs. Prism matched size, track width, smallest drill and hole count
exactly, and spacing within one mil.

---

## 6. Cleaning a job

A second job the CAM operator does by hand is removing what lies outside
the board: title blocks, stray text, copper left past the edge. Prism does
this from the same outline it measured, so the size it quotes and the
copper it keeps cannot disagree.

The rules are deliberately cautious, because a wrongly cut production
file is a scrapped panel:

- Fully outside: removed.
- Fully inside: kept untouched.
- Crossing the edge: kept and listed for the operator to decide.
- A small margin around the edge counts as inside.
- A panel is cleaned against the whole panel, not one board of it.
- If a layer would lose more than a third of its copper, nothing is
  removed and the layer is flagged, because that means the outline and
  the layer disagree about where the board is.

Before-and-after previews and a comparison report are written beside the
cleaned files.

---

## 7. Filling the customer's own form

The customer does not want a new report. They want their existing Excel
quotation sheet with the numbers already in it.

Prism fills it by **labels, not coordinates**. The sheet is scanned for
cells whose text matches a known label ("Board X", "Min Line", "Smallest
Hole"…) and the measured value is written into the cell to the label's
right. Labels survive the customer inserting a row, and the same logic
fills the next customer's differently-drawn form.

Two rules keep the form theirs:

- A cell holding a formula is never overwritten. Their totals stay their
  totals.
- A label Prism has no measurement for is left blank. A blank is a
  question for the estimator, not a place for a guess.

The drill table is the one structural fill: one row per measured tool,
diameter and hits, and leftover placeholder rows are zeroed so the form's
own sum counts only real drills.

Every figure is written to two decimal places.

---

## 8. How it reaches the user

**The terminal** has a command that takes an archive, measures it, prints
the four panels (what is in the job, the five numbers, the workings, the
cross-check) and saves the run.

**The desktop app** has a Gerber add-on with a front-door screen and a
working window. Drop the archive and measuring starts at once, before
anything is typed. The window shows the same four panels, offers Clean,
offers Fill form, and offers an optional write-up. Measuring runs on a
background thread with per-layer progress, because a twelve-layer board
with hundreds of thousands of traces takes minutes.

**The write-up**, if asked for, goes through Prism's normal browser
automation: the user's own logged-in AI tool is opened in their own
Chrome, given the five numbers as text and the user's instruction, and
the reply is captured. No API keys, no new subscriptions, no file upload.

---

## 9. The modules, and what each is for

### Engine (shared with the terminal)

| Module | Job |
|---|---|
| Gerber reader | Classify files, parse Gerber and Excellon, build geometry, measure the five numbers, detect panels, cross-check against the CAM report, apply design-rule notes, and produce the numbers-only brief for an AI. |
| Gerber cleaner | Keep what is on the board, remove what is not, write cleaned layers and a before/after report. |
| Form filler | Fill the customer's Excel quotation form by label, protect formulas, write the drill table. |
| Terminal command | The command-line entry point that runs measure, prints the panels and saves the run. |
| Automation runner | Drives the user's browser AI for the optional write-up. |

### Desktop app

| Module | Job |
|---|---|
| Add-on manifest | Declares the add-on as data: name, icon, licence feature, screen, run prefixes, engine modules it needs. |
| Front-door panel | The add-on's screen: what it does, recent runs, the way in. |
| Working dialog | Drop target, the four panels, Clean, Fill form, write-up. |
| Contract | What Gerber will do for another add-on, asked for by intent. |
| Workers | Measure and Clean on background threads, so the window never freezes. |
| Engine bridge | The one door from the app to the engine; also answers "is Gerber available". |

### Libraries

| Library | Used for |
|---|---|
| Standard regular expressions and maths | Parsing commands and coordinates, arc expansion. |
| Archive readers | Opening zip and rar jobs. |
| A geometry library, optional | Copper-to-copper spacing. Everything else works without it. |
| An independent Gerber library, tests only | The second-implementation check. |
| Qt | The desktop window and threads. |

### Tests

Unit tests for the parser and each measurement, two real customer jobs as
ground truth, the cross-check against their CAM reports, the
second-implementation comparison, dialog tests that intercept the AI
stage and assert no file is attached, and a slow-test flag for the large
jobs.

---

## 10. What is deliberately not built yet

- Capability check: measured numbers against the fab's own limits.
  Needs the fab's one-page capability sheet.
- Panel utilisation: how many boards fit a production panel. Real
  geometry, not AI, but needs the fab's panel sizes and rules.
- Costing: needs the fab's rate structure, which is their margin.
- Sending: needs mail credentials, asked for last, never first.

Each step is built only when it is finishable, checkable against a real
job, and useful on its own.

---


