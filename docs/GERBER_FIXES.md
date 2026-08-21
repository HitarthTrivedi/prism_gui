# Gerber reader — every bug, and the job that found it

A running log, newest last. One entry per bug, with **which customer file
caught it** — because the pattern in that column is the most useful thing in
this document.

**Keep it updated.** Add an entry the day a bug is found, before fixing it.

**Last updated:** 2026-08-21

---

## How to read the severity column

- **Silent** — a wrong number with no error, no crash, no warning. The worst
  kind, and most of these were that.
- **Loud** — it failed visibly. Annoying, not dangerous.
- **Cosmetic** — right answer, wrong presentation.

---

## The jobs

| Short name | What it is | What it caught |
|---|---|---|
| **101942** (`layer 1.zip`) | 2013, single-sided, 60x73mm, 80 holes | 4 bugs |
| **EI-500DT** (`.rar`) | 2018 Altium, 4 layers, 218 holes | 1 bug |
| **2-547-161A** (`.zip`) | 8 layers, 592 holes, 3 drill files | 4 bugs |
| **2580043B** (`.zip`) | 2 layers, 7 holes, carries a `.RUL` | 1 open issue |

---

## 1. Modal D-codes — a third of the file was never read

**Found by:** 101942 · **Severity:** Silent · **Fixed:** `7cef5c4`

In Gerber, a line with no instruction repeats the previous one. This file
writes 4332 of its 4336 region points that way. Prism only acted on lines
that spelled the instruction out, so it read **158 of the layer's 470
objects** — saw zero of the 59 copper pours where there are 59 — and then
reported a clearance for a board it had mostly not read.

**How it was found:** measuring the same board with an unrelated library
(gerbonara) and comparing object counts. Not by tests, not by reading code.

---

## 2. Polarity applied out of order

**Found by:** 101942 · **Severity:** Silent · **Fixed:** `7cef5c4`

Gerber paints in sequence; later marks cover earlier ones. This file goes
copper → erase → copper again. Prism was adding all the copper first, then
doing all the erasing, which wipes out copper the file explicitly puts back.

---

## 3. Lettering counted as tracks

**Found by:** 101942 **and** EI-500DT · **Severity:** Silent · **Fixed:** `aad1c2c`

Boards carry text etched into the copper — part numbers, logos. Prism
measured it as if it were tracks.

On 101942, **94 of the layer's 114 pieces of copper are lettering**, drawn
with a thin 10-mil pen, while every real conductor is a 3mm strip. Prism
reported 10 mil where the truth is 118. EI-500DT had the same fault smaller:
184 tiny segments of vertical text at the board edge, reported as 8 mil on a
board routed to 10.

**How it was found:** the customer's own hand-filled check sheet. Nothing
automated could have caught it — gerbonara agreed with Prism on every object,
because the file was being *read* correctly and the wrong thing *measured*.

**The rule now:** a conductor connects to something; lettering connects to
nothing. Copper only counts if it touches a pad.

---

## 4. Plane layers measured for tracks

**Found by:** EI-500DT · **Severity:** Silent · **Fixed:** `aad1c2c`

An internal ground or power plane is a solid sheet. The only thing in its
Gerber is the clearance punched around each hole, so "minimum track width" on
one is a wrong question, not a small number. The two planes reported 3 mil on
a board routed to 10 and dragged the whole job's answer down.

Planes are now excluded from track measurement and still counted as layers —
the answer reads "4 layers (2 routed + 2 solid plane)", because a 4-layer
board is priced as one.

---

## 5. Three drill files, only one read

**Found by:** 2-547-161A · **Severity:** Silent · **Fixed:** `0790cb2`

Plated holes, non-plated holes and a board-edge rout, each its own file, each
with a tool table starting at T1. Prism read the first one found and stopped:
**592 holes reported as 0.**

All the drilled ones now merge, keyed by diameter because tool numbers restart
per file and a fab orders bits by size. The rout is not a drill file — it is a
milling path with the spindle down — and counting its coordinates would have
invented hundreds of holes nobody drills.

---

## 6. Drill coordinate format read backwards

**Found by:** 2-547-161A · **Severity:** Silent · **Fixed:** `0790cb2`

`LZ` means leading zeros are PRESENT, so the trailing ones were dropped and
the digits pad to the RIGHT. Prism had it the other way, which scales every
coordinate by a power of ten. Also `;FILE_FORMAT=4:4` — a comment, and the
only place some tools state the format at all.

---

## 7. Rotated pads had no shape

**Found by:** 2-547-161A · **Severity:** Silent · **Fixed:** `0790cb2`

185 of the top layer's pads are drawn with an aperture macro. Macro flashes
were given no geometry at all, so **the pads took no part in the spacing
measurement** on a board where pads are most of the copper.

Circle, outline, polygon and the three line primitives are now built — every
macro on every real job so far. Anything using arithmetic still returns
nothing, and says so.

---

## 8. Five jobs measured as one board

**Found by:** the folder itself · **Severity:** Silent · **Fixed:** `0790cb2`

Pointing at a folder of several jobs measured them all as one board: one
job's outline, everyone's drill count, and no error.

---

## 9. …then one job split into five

**Found by:** 2-547-161A · **Severity:** Silent · **Fixed:** `d14e355`

The fix for #8 split by folder, and this export arrives as `Gerber/`,
`NC Drill/`, `__Previews/`. The copper went in one job and the drills in
another, so a 592-hole board reported no drill file at all. Same failure
wearing the other hat.

Jobs are now grouped by the board's name, not the folder.

---

## 10. Archives inside a folder were walked past

**Found by:** the folder itself · **Severity:** Loud · **Fixed:** `d14e355`

A folder holding `job1.zip` beside `job2.rar` measured neither. Also: the same
job present twice — an archive and the folder someone extracted it into —
counted every hole twice.

---

## 11. Board size taken from the ink, not the outline

**Found by:** EI-500DT · **Severity:** Silent · **Fixed:** `36a35da`

Fiducials and a legend block sitting outside the board edge inflated the size:
3.600 x 3.750 in measured, 3.550 x 3.550 in actual. **10% of the area,
straight into the price.**

101942 added a second version of the same trap: its board rectangle's fourth
side starts at Y = -0.0000003 mm instead of 0, so the shape would not close
and Prism reported the title block as the board — 98 x 13 mm instead of
60 x 73.

---

## 12. Drill supplied as a Gerber, and 4-digit D-codes

**Found by:** 101942 · **Severity:** Silent · **Fixed:** `36a35da`

The drill arrives as a Gerber of flashed pads, not an Excellon file — a
parser that reads only Excellon reports no holes rather than an unread file.
The same job selects apertures D9500/D9501, which a 2-3 digit pattern matches
nowhere, so every hole vanished with no error.

---

## 13. The one-sheet output deleted by an edit

**Found by:** a live run · **Severity:** Loud · **Fixed:** `902411e`

Rewriting the two functions on either side of it took it with them. Nothing
failed until the last line, because the per-job report had already been
written and saved — so the run looked like it worked. Now pinned by tests.

---

# Open — not fixed

## A. Design rules vs measured reality

**Found by:** 2580043B · **Severity:** Low for correctness, **HIGH for
arguments**

This job carries a `.RUL` file — the designer's own rulebook — which the
earlier three did not. It states:

```
Width      Minimum = 3.94 mil
Clearance  Minimum = 7.87 mil
```

Prism measures **11.8 mil** and **8.1 mil**.

Both are true and they answer different questions. The rules say *"you may go
as thin as 3.94"*; Prism says *"the thinnest actually drawn is 11.8"*. But if
the customer reads the `.RUL` and Prism reads the copper, the two disagree by
three times and it looks broken.

**Fix:** read the `.RUL` and print both side by side, so there is nothing to
argue about.

## B. Still never tested

- **Curved tracks.** No job so far has a single arc.
- **Panelised jobs** — one file holding many copies of a board.
- **Negative inner planes** drawn inverted.

---

# What the pattern says

**Eleven of thirteen bugs were silent** — a plausible wrong number, no error,
no crash. That is what makes this domain dangerous: nothing tells you.

**Where they were caught:**

| Caught by | Count |
|---|---|
| A new customer file | 8 |
| An unrelated library measuring the same board | 2 |
| The customer's own check sheet | 2 |
| A live run | 1 |
| **Our own tests, before a real file** | **0** |

Tests protect what is already known. **Every single bug came from outside** —
a new file, another tool, or the customer. That is why the sample set in
`tests/gerber_samples.json` matters more than the test count, and why each new
job is worth asking for.
