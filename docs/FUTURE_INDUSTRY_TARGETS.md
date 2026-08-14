# Future industries to target

Where Prism goes after springs and plastics, why, and what has to be built for
each. Written so that whoever picks this up later knows not just the plan but
the reasoning — and the parts we are not sure about.

**Where we are today.** Prism sells to manufacturers whose output is a quoted,
measured job. Inquiry Automation reads their mail, keeps their inquiry
register, prices from their own rate list, chases the quiet ones. BOQ takes
quantities off a CAD drawing. Both stop before money moves.

Everything below is the same shape: **a business document arrives by email, a
person reads it by hand, and the reading is the bottleneck.** Prism already
owns the inbox. The only thing that changes per industry is the reader.

---

## 1. PCB fabricators

**First customer:** Fine Circuits and Components Pvt Ltd, trading as **Fineline
Circuit Company** — Plot E-8, Savli GIDC, Manjusar, Vadodara 391775.
`fccindia.com`. ~150 people, 60,000 sq ft, 5,000 m²/month, 100% Export
Oriented Unit, UL + TÜV Rheinland certified, US office in Elk Grove Village
Illinois. Single/double/multilayer to 8, aluminium metal-clad, Teflon/PTFE for
RF and microwave. Customers in power, medical, consumer, musical instruments,
aerospace.

*(Not to be confused with **Fine-Line Circuits Limited**, Mumbai, listed, since
1990. Different company entirely.)*

**The job.** A customer emails a Gerber folder — one file per layer plus drill
files. Someone opens it in a viewer and reads off the board size, layer count,
hole count and sizes, and the finest track. That reading is what Prism removes.

**Proven, on their real 4-layer file:**

```
li-ion_charger rev 04
Board size       125.93 x 76.40 mm  (96.2 cm2)
Copper layers    4
Thickness        1.6002 mm     Material  FR4
Copper weight    0.035 mm (~1 oz)
Drilling         238 holes — 167 vias, 71 component
                 7 distinct sizes, smallest 0.305 mm
Tracks           narrowest 0.152 mm (6.0 mil)
Design rules     min track 0.1524, track-to-track 0.1524 mm
```

Verified independently (`grep -c 'D03\*$'` → 238). Under a second, offline.

**Two things learned that change the design:**

- **The `.gbrjob` file carries the stackup** — thickness, material, copper
  weight, finish, design rules. An earlier note in this project said those
  were not in the Gerber; that was wrong for modern exports. Older exports
  have no `.gbrjob`, so the reader still needs a fallback.
- **Layer names cannot be trusted.** That board's copper layers are called
  `Composant` and `Cuivre` — French. `gerbonara` returned *copper layers: 0*.
  But every file declares `%TF.FileFunction,Copper,L1,Top` in its own header.
  **Read the header, not the filename.** Order of trust: file header → `.gbrjob`
  → filename guess.

---

## 2. EMS and assembly houses — the bigger prize

**Why they matter more than fabricators.** There are far more of them, their
inquiry volume is higher, and their quoting pain is worse — because they
receive *three* file types where a fabricator receives one:

| File | What it is |
|---|---|
| Gerber folder | the bare board |
| **BOM** | every component, quantity, manufacturer part number |
| **Pick-and-place** | where each part sits, and at what rotation |

The test board already had `pnp_top.gbr` and `pnp_bottom.gbr` sitting in it.
The pick-and-place data is *right there* and nobody reads it automatically.

**What Prism could tell them without a person opening anything:**

- board size, layers, holes — as above
- **component count, top and bottom** — from the pick-and-place
- **how many unique part numbers** — from the BOM
- **which side needs which process** — SMT one side or both, any through-hole
- **placements per board** — the number their machine time is priced on

**How close we already are.** Everything needed is in the same folder Prism
already files against the inquiry. The Gerber reader handles the board; the
BOM is a CSV, which `quoting.load_rates()` machinery already understands; the
pick-and-place is a CSV too. **This is the same reader with two more parsers,
not a new product.**

**Where they are.** Bangalore is the largest cluster, then Pune (automotive),
Hyderabad (defence and telecom), Delhi NCR. Gujarat and Karnataka are the
fastest-growing states, but Gujarat is not the biggest — so unlike springs and
plastics, **this cannot be sold by driving around GIDC.** Budget for travel or
for selling remotely.

**Honest sizing.** IPCA has 300+ members, but that includes material and
equipment suppliers. Real fabricators of a size that would pay: perhaps
80–150 nationally. EMS is larger but harder to count. At ₹8,000–20,000/month
this is a ₹1.5–2.5 crore/year market at its absolute best, and much less in
the first years. Not nothing — but worth weighing against going deeper where
we can drive to the customer.

---

## 3. What the PCB add-on has to look like

**A separate add-on. NOT inside Inquiry Automation.** It sits on the sidebar
shelf beside BOQ, and reuses BOQ's window shape so there is one way to give
Prism a file rather than two.

### The window

Modelled on the BOQ dialog, because a customer who has used one add-on should
recognise the next:

- **Drop a Gerber zip or folder** → the measurements appear, as above
- **Optionally attach more files** — this is the part that matters:
  - their **company details** (letterhead, address, GST, standard terms)
  - a **sample or template** of the document they want out

### The rule that must not be broken

> **The Gerber files never leave the machine. Not ever.**

Prism reads the board locally, in Python, and produces the measurements.
**Only the measurements, the customer's template, and their company details go
to the AI tools** — which then format a proper document in whatever shape the
template asks for.

```
   Gerber zip ──► Prism (Python, local, exact)
                       │
                       ▼
                  measurements ─┐
   company details ─────────────┼──► AI tools (browser) ──► formal document
   template/sample ─────────────┘
        ▲
        └── the Gerber itself NEVER goes here
```

Three reasons, and the third is why it is a hard rule rather than a
preference:

1. **It is exact, not a judgement.** 238 holes is 238 holes. An AI adds
   nothing to a count and can only get it wrong.
2. **Speed.** Under a second offline, against a minute per browser round trip.
3. **Their customers forbid it.** FCC exports to aerospace and medical clients
   in the USA. Board geometry arrives under NDA and in some cases under export
   control. Uploading a customer's board to a web AI to count holes would
   breach those contracts — and it would throw away the strongest thing we
   have to sell them.

The same division as everywhere else in Prism: **the browser tools write
prose; Python does the measuring and owns the file.**

### Still to prove

The reader has been tested on **one** board — a KiCad export, X2/X3 attributes
present. Before building properly, get two or three real customer zips from
FCC, ideally from Altium and Eagle, and ideally one older one with no
`.gbrjob`. That is where the fallback path gets exercised, and where this
breaks if it is going to.

---

## 4. What to charge

Benchmarks: Indian SMB B2B SaaS runs ₹999–4,999/month; manufacturing ERP for
SMEs ₹3,000–25,000/month; Indian buyers expect 20–30% off list whatever is
published.

| Customer | Monthly |
|---|---|
| FCC / Fineline — 150 people, UL+TÜV, exporter | **₹15,000–20,000** |
| Mid PCB shop, 30–60 people | ₹8,000–12,000 |
| Small shop, under 20 | ₹5,000 floor |

**Publish ₹20,000 and settle at ₹15,000.** Publishing ₹15,000 ends at ₹10,000,
because they will ask regardless.

**Price it as an add-on, never standalone.** The moment it is a standalone
Gerber tool it gets compared to JLCPCB's free viewer — and NextPCB gives away
50+ DFM checks with no login, because the tool is marketing for their fab. We
cannot win that fight and should not enter it. Sold as *"it reads the board
out of the email and files it before anyone opens CAM"*, there is nothing to
compare it to.

---

## 5. The question worth answering before any of this

Three verticals are now in play — springs, plastics, PCB — and each needs its
own reader, its own vocabulary, its own demo.

**Has any of them said they would pay, or are they being helpful?** Those feel
identical in a meeting and they are completely different businesses. That
answer should decide the order of this list, not the technical interest of the
file format.
