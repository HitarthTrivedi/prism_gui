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
| **2580043B** (`.zip`) | 2 layers, 7 holes, carries a `.RUL` | 2 bugs |
| **CT-TT-CAP12** (`.zip`) | a PANEL — 196x195mm, 2855 holes | clean first time |
| **MIE V2.2** (`.rar`) | PADS export, 10 copper layers, `art001.pho` names | 4 bugs |
| **PCB-2199…** (`.zip`) | PADS export, 12 copper layers, 187k traces a layer | 3 bugs |

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

## 14. The designer's rulebook was ignored

**Found by:** 2580043B · **Severity:** Low for correctness, **HIGH for
arguments** · **Fixed:** `dae4f2b`

This job carries a `.RUL` file — the designer's own rulebook — which the
earlier three did not. It states:

```
Width      Minimum = 3.94 mil
Clearance  Minimum = 7.87 mil
```

Prism measures **11.8 mil** and **8.1 mil**.

Both are true and they answer different questions — a speed limit and a radar
reading. The rules say *"tracks may go as thin as 3.94"*; the copper says
*"the thinnest actually drawn is 11.8"*. But a fabricator who opens the `.RUL`
and quotes 3.94 against our 11.8 sees a number three times out and concludes
the software is broken.

Both now print side by side, and both go in the CSV:

```
2. Min track width    0.300 mm (11.8 mil)   (design rule allows 3.94 mil)
3. Min track spacing  0.205 mm (8.1 mil)    (design rule allows 7.87 mil)
```

The measured figure never moves — it is what limits manufacture. Only the
board-wide rules are taken: a `.RUL` carries dozens of local exceptions, and
the tightest of those is not what the board was routed to.

---

## 15. "I do not recognise this" threw away a role the extension had settled

**Found by:** 2580043B · **Severity:** Silent · **Fixed:** `dae4f2b`

The `.RUL` reader was written and returned nothing. The extension had
correctly marked the file as rules, and then the content sniffer — which
reads plain prose as "other" — overwrote it. A one-line fix, and a reminder
that a recogniser saying "unknown" must never outrank one that already said
"known".

---

## 16. Twelve copper layers read as none

**Found by:** MIE V2.2 **and** PCB-2199 · **Severity:** Silent · **Fixed:** `c87ad4d`

Two jobs arrived from PADS, where every file is called `art001.pho`,
`art002.pho` … `art012.pho`. The extension says only "a photoplot" and every
file has it, so nothing was identified and **both jobs measured nothing at
all** — no size, no track width, no drills, no error.

The role and the layer number are in the NAME, and it is a real convention:

```
art001 … art012   copper, layer 1 to 12
sm001121          solder mask on layer 1 (top)
sm010128          solder mask on layer 10 (bottom)
sst / ssb         silkscreen top / bottom
smd               paste
dd                drill drawing
drl_pt / drl_np   drill, plated / non-plated
adt / adb         assembly drawing top / bottom
```

Which side a layer is on is only knowable from its position in the run — the
lowest number is the component side, the highest the solder side. So that is
resolved across the whole job, not per file.

---

## 17. A drill file with no header

**Found by:** PCB-2199 · **Severity:** Silent · **Fixed:** `c87ad4d`

`drl001.drl` has no `M48` and no `METRIC`/`INCH` line — it opens with `%` and
then `T1C.008F0S0`. The sniffer read the header, found nothing, and called it
"not a fabrication file" on a board with thousands of holes.

---

## 18. Slow enough to look broken

**Found by:** PCB-2199 · **Severity:** Loud · **Fixed:** `c87ad4d`

The first job big enough to matter: **187,674 segments on a single copper
layer**, twelve of them. Measuring took minutes per layer with nothing
printed, which reads as a hang — the user kills it and reports the tool as
broken.

Three changes, none of which move a number:

- **Chain traces before unioning.** Those 187,674 segments are 69,885 actual
  traces. Buffering the polyline instead of each segment took a layer from 22
  seconds to 9 — and is more correct, because separately buffered segments
  can fail to overlap at a joint by a rounding error and split one trace into
  two islands.
- **One bulk neighbour query** instead of a Python loop, over islands
  simplified to two microns first. Same minimum, a quarter of the time. Two
  microns is two orders below any fabrication tolerance.
- **Progress per layer**, so a long run looks like work rather than a hang.

**All six earlier jobs still return their pinned answers** — that is the
regression harness doing exactly what it was built for.

---

## 19. A tool select is not always a bare `T1`

**Found by:** MIE V2.2 · **Severity:** Silent · **Fixed:** `8e0d9e6`

This job writes every tool select as `T1C.01969F095S3` — the diameter and the
feed and speed repeated on each one. Only a bare `T1` was matched, so every
hole was attributed to no tool at all and **a 1,177-hole board reported
zero**.

No error, and this is why it is worth writing down: the tool TABLE at the top
of the file parsed perfectly. Everything about the file looked read.

---

## 20. One report is not the job

**Found by:** MIE V2.2 · **Severity:** Loud · **Fixed:** `8e0d9e6`

The check that should have caught #19 made the same mistake in reverse. This
job ships a **Drill Sizes Report per drill file** — 8 holes non-plated, 1,169
plated — and each was compared against the job total. A perfect
`8 + 1169 = 1177` was reported as two failures.

They are summed and compared once now. That report format is also a new
witness in its own right: machine-written and independent, the same role the
`.DRR` plays on the Altium jobs.

---

# Open — not fixed

## A. Still never tested

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
