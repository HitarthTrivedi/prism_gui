# Prism cinematic benchmark roadmap

This document records what has been implemented for the `inspo.mp4` direction,
what is still missing, and the gates required before calling Prism's output
production-quality. It is intentionally a roadmap, not a claim that the
current AI-generated reels already match the reference.

## Benchmark target

The supplied reference is a vertical 60 FPS film (`384×848`, approximately
29.2 seconds). Its important qualities are visual and editorial rather than
just technical:

- one visual idea survives from beginning to end;
- glass surfaces have controlled transparency, edge highlights, depth and
  readable contrast;
- scenes transform into one another instead of behaving like independent
  slides;
- camera movement, subject movement and transitions share one rhythm;
- typography is deliberately placed, legible and subordinate to the idea;
- effects are restrained and purposeful; there is no decorative AI clutter;
- the ending resolves the same visual subject into a clear answer or CTA.

The target is therefore **motion continuity + art direction + rendering
reliability**, not simply “more shapes” or “more animation.”

## What is now implemented

### Existing Studio/reel recovery and rendering work

- Fragile DOM child-index editing was replaced with persistent element IDs and
  duplicate-ID disambiguation.
- Studio follow-ups can recover a saved project even when the first MP4 failed,
  provided its design conversation matches.
- Scene roots remain correctly positioned for vertical multi-scene capture.
- Preview/inspection now uses saved edits and timing.
- Asset manifests distinguish usable artwork from contact sheets/reference-only
  images; production no longer guesses crops from a board.
- Missing assets, invalid durations, animation fill modes and layout faults are
  reported before export.
- Attached Motion images are inlined as portable `data:` URIs and the Motion
  safety switch is enabled.

### Cinematic lab reference

`prism_terminal/core/cinematic/` contains an isolated, authored reference film.
It demonstrates the intended visual grammar without changing normal GUI
generation. Its V3 continuity spine is:

```text
scattered sources → band → core → graph → light field → answer → memory → orb
```

The lab supports settled-frame previews and 17% / 50% / 83% handoff previews
for every transition. It is a reference and promotion gate, not a hard-coded
template for every user request.

### Production Motion continuity slice

The real Motion path now supports the `cinematic_glass` profile:

```text
user prompt
  → Motion storyboard profile
  → scene-at-a-time node generation
  → schema validation
  → continuity manifest
  → existing Motion resolver/runtime/FFmpeg export
```

The profile is wired into terminal `/motion`, the Motion add-on dialog and
routed local Motion planning. Its prompts require:

- one persistent visual spine;
- a stable `continuity_key` on returning hero subjects;
- outgoing and incoming pose agreement;
- a continuous camera track;
- restrained glass layering and negative space;
- an ending that resolves the carried subject.

`continuity_key` is normalized by schema validation while node `id` remains
unique for editing. The resolver adds `_continuity`, grouped by key, so Studio
and follow-up tooling can select a complete visual thread.

### Continuity compiler (Phase 1 — done, 10 Sep 2026)

`prism_terminal/core/motion/continuity.py` turns the contract into rendered
motion instead of trusting the model to obey it:

- `report(spec)` reads every subject's settled pose on both sides of each cut
  it crosses and plans a bridge: position, scale and rotation deltas over the
  same window the resolver gives the two scenes' visibility overlap.
- `compile(spec)` (called once by the resolver, before transitions are
  stamped) writes that bridge onto both instances as a matched exit/enter pair
  with one easing, so at every frame the two instances share one pose. The
  cut becomes the new `morph` transition (runtime/transitions.js): a linear
  container crossfade, so only the subject moves and everything else
  dissolves. Opacity is never bridged on the node; the crossfade owns it.
- What cannot be bridged is a specific error: a hard cut between keyed scenes
  (cold reset), a subject that vanishes for a scene and returns (missing
  subject), one key on two nodes in a scene, a jump too fast for the window,
  a scale change beyond 6x, or an instance that settles invisible. Under the
  cinematic profile, a scene with no keyed node and an opening subject that
  the final scene does not resolve are warnings.
- `render()` refuses a spec whose errors remain, before FFmpeg is located,
  with the scene, subject and fix in the message. The caller keeps the
  editable JSON.
- `build_spec()` runs one whole-piece repair pass for the cinematic profile:
  each offending scene is sent back with the exact faults and the neighbouring
  keyed poses it must meet, and the correction is kept only if the piece has
  fewer issues afterwards. Every scene prompt also states the outgoing
  subject's settled position and scale.

Verified with a real Playwright render of a keyed two-scene spec: the subject
travels, scales and rotates across the cut as one object while the text
crossfades.

### Material and camera primitives (Phase 2 — done, 10 Sep 2026)

Three runtime primitives (`runtime/primitives.js`), validated first with the
authored fixture in `core/motion/fixtures.py` and only then added to the
model catalogue:

- `glass_panel` — backdrop blur + saturation, transmission (how much of the
  scene shows through the tint), border light (edge + top inset highlight),
  inner shadow, a diagonal specular, and a `contrast_guard` scrim ("dark" or
  "light") so copy on the panel keeps contrast over a bright light as well as
  a dark wash. Children mount above the surface.
- `light_field` — two screen-blended radial lobes, blurred, each drifting on
  its own seeded phase; the background layer in place of a flat wash.
- `depth_layer` — a group with a `depth`; the runtime refreshes its parallax
  transform on every seek so far layers drift and zoom less than the camera
  and near layers more. Depth from hierarchy, not repeated cards.

Camera grammar (`core/motion/camera.py`): a scene names a `shot`
(`hold`, `reveal`, `push`, `pull`, `orbit`, `parallax`, `macro`, `resolve`,
with an optional node or point target and zoom). The resolver compiles all
shots into one continuous `camera.tracks` list — an opening set at t=0 and
one destination per scene, non-overlapping, so the runtime's walk never
resets. An authored camera is kept when no scene names a shot and seeds
the opening state when one does. `safe_area()` reserves the 9:16 platform
bands and `inspect()` flags text or images that sit under them.

`examples/motion_materials.py` renders the fixture and writes start, mid,
settled and exit frames per scene for review. Verified with a real
Playwright render: the panel reads as a lit surface, the light lifts the
frame, and the headline keeps contrast.

### Studio editing surface (Phase 3 — done, 10 Sep 2026)

`prism_terminal/core/motion/studio.py` is the Motion counterpart of
`reel_edit.py`, served by `runtime/studio.js` + `studio.css` over the same
runtime page the renderer films. The Motion dialog's **Edit in Studio**
button opens it in the browser; the newest saved motion graphic is restored
onto the bench when the dialog opens.

- **One rule:** an edit is a small record applied to the scene-local spec
  before validation (`apply_edits`), and both the editor's `/preview` and
  `render()` go through that same function, so preview and export cannot
  differ. Records are sanitised (`clean_edits`); junk and no-ops are dropped.
- **Left rail:** scenes (length, shot, cut), continuity threads from the
  compiled manifest (click to select the thread's node in the current scene
  and outline every instance), and the layer tree with keyed nodes marked.
- **Inspector:** pose (move, scale, rotate, opacity, hide), glass material
  (blur, transmission, edge light, inner shadow, specular), text; per scene:
  length, camera shot (intent, target, zoom), and the handoff easing of the
  cut into the scene, which the continuity compiler now honours on both
  sides of the bridge. A continuity check panel shows the compiler's errors
  and warnings after every preview.
- **Timeline:** scene blocks carry the compiled camera shot and the threads
  they carry; a handoff handle sits on every cut and turns red while the
  continuity check fails. Start / Midpoint / Settled / Exit review buttons
  seek each shot's four review points. A safe-area overlay draws the 9:16
  platform bands and the title/action zones.
- **Follow-up:** the prompt row posts the change with the selected scene,
  node and continuity key. `followup_prompt()` sends only that scene's JSON
  and the thread's poses elsewhere; `apply_followup()` folds the one-scene
  reply back, keeps timing, drops hand edits on the rewritten scene, and
  names layout and continuity problems in its note. The dialog runs it as a
  one-stage automation turn and re-renders.

Verified in headless Chromium: the workspace mounts, threads are listed,
review points seek, a layer selects, and a nudge round-trips through
`/preview` and autosave with no page error.

### Visual review, beats and the export gate (Phase 4 — done, 10 Sep 2026)

- **Review sheet** (`core/motion/review.py`): renders or takes the MP4,
  pulls the start / midpoint / settled / exit frame of every scene and the
  17 / 50 / 83 % frame of every continuity handoff onto one labelled
  `review_sheet.png`, and writes `review.json` with every fault. Seeks snap
  to frames so the last frame of a low-rate render is reviewable.
- **Checks at playback, not only at rest:** text hold time against word
  count; cold cuts under the cinematic profile; text contrast measured on
  the rendered settled frame (ink 95th percentile against ground 5th, floor
  3:1); a one-frame pop at any cut (a frame-to-frame jump far above the
  motion around it); FFmpeg's own probe of the file for size, frame rate,
  duration and codec (`export_gate`); and `preview_matches_export`, which
  seeks the Studio's runtime page to the review times and compares its
  screenshot with the exported frame within a pixel tolerance.
- **Beat markers** (`core/motion/beats.py`): a tempo the cuts already land
  on (or the production track's own), the beat and bar times across the
  timeline, and a marker for every cut, bridge, camera move and text
  entrance with its drift from the nearest beat. `snap_scene_lengths()` is
  an opt-in editing aid. The Studio timeline draws the ticks and flags
  off-beat cuts.
- **Production audio without a baked score:** `spec["audio"]` names a
  music and/or voiceover file, tempo, offset and music volume. The schema
  normalises it, `render()` refuses a missing file before any frame is
  spent, and muxes the tracks onto the finished film through the existing
  audio subsystem. No temporary score enters the design contract.
- `examples/motion_review.py` runs the whole review on the fixture or a
  saved motion JSON and prints the beat grid.

Verified in the render lane: the fixture's sheet has 18 frames and no
faults, the export gate passes, and preview matches export at every
settled and midpoint-handoff frame; a deliberately muddy headline is
caught on the rendered frame.

Relevant implementation:

- [Continuity compiler](../prism_terminal/core/motion/continuity.py)
- [Camera grammar and safe areas](../prism_terminal/core/motion/camera.py)
- [Motion Studio](../prism_terminal/core/motion/studio.py)
- [Visual review and export gate](../prism_terminal/core/motion/review.py)
- [Beat grid](../prism_terminal/core/motion/beats.py)
- [Studio tests](../tests/test_motion_studio.py)
- [Authored fixture](../prism_terminal/core/motion/fixtures.py)
- [Material tests](../tests/test_motion_materials.py)
- [Motion generation profile](../prism_terminal/core/motion/generate.py)
- [Continuity resolver manifest](../prism_terminal/core/motion/resolver.py)
- [Schema normalization](../prism_terminal/core/motion/schema.py)
- [Pipeline wiring](../prism_terminal/core/automation.py)
- [Motion dialog wiring](../addons/motion/dialog.py)
- [Continuity tests](../tests/test_motion_continuity.py)

## What is still missing

Phases 1 to 4 closed the compiler, material, camera, Studio and review gaps
listed below; each entry now records what is done and what is still open.
The one untouched area is asset intelligence (item 6).

1. **Continuity compiler** — done (see above). Still open inside it: blur
   and colour are not bridged (position, scale and rotation are), and a
   subject nested under a parent that itself moves is bridged in its own
   local space only.

2. **Glass material system** — done (see above). Still open: the
   "one panel per shot" rule is doctrine in the prompt, not yet an
   `inspect()` fault; contrast is guarded by a scrim, not measured.

3. **Camera and shot grammar** — done (see above). Still open: the camera
   curve is compiled from scene shots only; a camera authored per scene by
   hand is not merged, it is replaced (kept on `_authored_tracks`).

4. **Temporal and audio direction** — done (see above). Still open:
   sound-effect cue points are not yet a spec concept (only music, voice
   and tempo), and readability is checked through hold time and settled
   contrast, not by reading every animated frame.

5. **Studio editing surface** — done (see above). Still open: handoff
   handles scrub the cut but do not drag the overlap length; nodes cannot
   yet be added from the Studio (only edited, hidden or reset); the
   History/Artifacts screens do not offer the Motion editor.

6. **Asset intelligence**
   - Show supplied images to the design agent with explicit roles and flags.
   - Mark contact sheets, low-resolution images, logos and “do not use” assets.
   - Require approval before a reference image becomes a production layer.

7. **Quality gates** — largely done (see Phase 4): scene-boundary and
   handoff frames, preview/export consistency, off-frame, overlap, safe
   area, contrast, hold time, cold cuts, missing threads and one-frame
   pops. Still open: clipping inside a panel is not measured, and the
   golden frames are compared against the live preview, not against
   stored reference images.

## Recommended implementation order

### Phase 1 — compiler safety (done)

Continuity-track synthesis lives in `core/motion/continuity.py`, the
resolver compiles it, `render()` raises “continuity broken” with a specific
message, and `build_spec()` sends the offending scene back with a repair
prompt. The runtime API is unchanged; unkeyed specs render exactly as before.

### Phase 2 — material and camera primitives (done)

`glass_panel`, `light_field`, `depth_layer` and the shot/camera-curve
compiler are in the runtime, validated by the authored fixture and its
render-lane test, and exposed in the catalogue and the cinematic doctrine.

### Phase 3 — Studio controls (done)

The continuity manifest is a selectable thread rail; the timeline carries
scene blocks, camera shots and handoff handles; the safe-area overlay and
the inspector controls are in; follow-up prompting sends only the selected
scene/thread context plus the requested change.

### Phase 4 — visual review and audio (done)

The review sheet, the beat grid, production-audio muxing and the export
gate are in `core/motion/review.py` and `core/motion/beats.py`.

### Phase 5 — promotion (gate built; Linux run passes, Windows and macOS not yet run)

`core/motion/promotion.py` runs the acceptance list below as code against
one spec on one machine and writes `promotion.json` / `promotion.md`: every
criterion with pass, fail or *manual* and its evidence, stamped with the
platform. Two criteria no program can judge (effects support hierarchy;
the four review states pass visual review) are reported as manual with the
review sheet as evidence, never silently passed. `same_prompt_everywhere()`
sends one brand and tagline through the authored lab (settled and handoff
previews), the Motion runtime (the materials fixture at 1080x1920, 60 fps,
rendered and gated) and the Studio page. `examples/motion_promote.py` runs
it; `tests/test_motion_promotion.py` pins the checklist to this document's
wording and, under the render lane, promotes the fixture on the machine
that runs the tests.

Status on 10 Sep 2026: every automated criterion passes on Linux (this
machine). Windows and macOS have not been run here. The CI test matrix
already covers all three platforms; setting `PRISM_RUN_RENDER_TESTS=1` on
those runners (they install Playwright's Chromium for the build job) runs
the promotion test there. Promotion of the direction is the owner's call
once those two reports read PASS and a reviewer has signed the two manual
criteria off against the review sheet.

## Closing the gap to inspo.mp4

Started 10 Sep 2026, after Phase 5. The reference is a phone screen
recording of a story ad: a 9:16 film letterboxed in a 384×848 frame with
the platform's chrome over it. `core/motion/benchmark.py` finds the ad,
keeps to the band the chrome leaves clear, and scores a Prism render
against it every half second (luminance, colour, edge structure, busyness,
and whether motion happens together); `examples/inspo_compare.py` renders
the recreation and draws the reference row over the Prism row.

The recreation is `core/motion/fixtures.py::inspo_fixture()` — the ad's
ten beats through the real pipeline (spec → resolver → runtime → FFmpeg),
editable in Motion Studio. Building it exposed and fixed one defect in the
runtime: text reveals, arrow draw-ons and field phases were registered at
global time, so every scene after the first showed its text already
revealed and its lines already drawn. The resolver now shifts them per
scene like enter/exit. Four primitives were added for the reference's
grammar: `particle_field` (tiles that hold a layout and travel to the next:
scatter, band, column, ring, points, hidden), `icon` (chat, phone, mail,
whatsapp, book, dial, spark, check on an optional glass tile), `orb` (lit
sphere with rim, specular, glow and a great ring) and `spline_tree` (thin
curved lines drawn on from a hub to leaves). All four are in the catalogue.

| render | score | motion corr | note |
|---|---|---|---|
| materials fixture (Phase 2, 7.5 s) | 57.3 | 0.26 | baseline, different film |
| inspo-01 (first recreation, 30 fps) | 64.3 | 0.52 | field too sparse and dim; light scenes dark at the corners; orbit tilt persisted; bokeh too soft |
| inspo-02 (720×1280, 30 fps) | 68.8 | 0.65 | denser field, full-frame gradient skies, no orbit tilt, split logo; light sweep still ~0.5 s late, card scene ran into the reference's dark Knowledge Base beat |
| inspo-03 (720×1280, 30 fps) | 70.4 | 0.71 | unsigned field random, exits no longer render early, sweep as a great circle, retimed beats; opening field invisible (hidden-start alpha bug), black too blue, sweep too white, Knowledge Base beat too dark |
| inspo-04 (720×1280, 30 fps) | 65.0 | 0.47 | opening field now visible, neutral black, brighter bokeh; the keyed blue bubble was bridged in half a second before the cut, splitting the reference's single sweep spike, and the sweep landed early |
| inspo-05 (720×1280, 30 fps) | 72.1 | 0.75 | light scene unkeyed with an explicit morph so the sweep spike lands at 12.5 s; band bursts upward before streaming; Knowledge Base later; still: conversation beat under-detailed and late, hub too still, ending moves after the reference settles |
| inspo-06 (720×1280, 30 fps) | 73.2 | 0.79 | bubbles arrive together with smaller copy, hub livelier, ending settled by 28 s; still: conversation layout differs per pixel, the Knowledge Base cut is harsher than the reference's fade, the burst is weaker |
| inspo-07 (720×1280, 30 fps) | 77.0 | 0.90 | shots gained an optional `duration`, so the conversation settles the camera in 0.45 s instead of drifting from the hub for the whole scene (bubbles had sat 400 px low); light circle leaves the top-left dark; still: the card scene stays bright into the Knowledge Base beat, bubbles leave late |
| inspo-08 (720×1280, 30 fps) | 76.1 | 0.85 | larger bubbles that leave earlier, darker card scene; its early fade moved motion to 19.0 s where the reference changes at 19.5–20.0 s, so the fade goes back to the cut |
| inspo-09 (720×1280, 30 fps) | 77.5 | 0.91 | card-scene fade back at the cut; best so far |

Re-baselined 10 Sep 2026 (evening), after the owner set the target at 85 in
every sector. Two corrections to the table above. First, the on-disk
recreation re-rendered at 720×1280 scored 64.8, not 77.5, so the numbers
before this line are not comparable with those after it. Second, the
structure sector could never reach 0.85 as defined: the reference against
itself shifted four pixels scored 0.64 on raw edge correlation and only 0.33
against itself half a second later. `structure` is now the correlation of
coarse edge-density maps (a 12×21 grid of the band; a shifted copy scores
0.90, an unrelated render ~0.25) and the raw value is kept as
`structure_raw`. Luminance, colour and busyness were checked the same way
and are reachable (the shifted copy scores 0.94, 1.00 and 0.98).

Sectors are the score's own terms, each 0-1: lum, col, struct, busy from the
frame metrics, move from the motion correlation.

| render | score | lum | col | struct | busy | move | note |
|---|---|---|---|---|---|---|---|
| inspo-10 (baseline, rescored) | 66.3 | .77 | .86 | .39 | .90 | .52 | the sweep half a second late; the burst weak and early; the hub gather a second early |
| inspo-11 | 76.1 | .78 | .88 | .38 | .90 | .84 | retimed beats; motion correlation 0.79 |
| inspo-12 | 77.7 | .78 | .90 | .33 | .91 | .91 | positions from side-by-side crops: band, icons, bubbles, cards; the first sky no longer leaks through the crossfade |
| inspo-13 | 81.3 | .81 | .91 | .41 | .92 | .94 | the band forms low and rises like the reference; the sphere scene 250 px lower; bokeh inside the band; KB card and orb where the reference has them |
| inspo-14 | 79.3 | .81 | .91 | .35 | .91 | .92 | REGRESSION: frame-point targets were written in 1080 space and the iteration renders at 720, so every targeted shot aimed right and down; the second sky faded too far |
| inspo-15 | 81.5 | .82 | .92 | .46 | .90 | .92 | targets scaled with the fixture; shots gained `delay` so scene 3 holds on the icons then pans down to the hub sphere; scene 4 authored under that camera; a keyed particle_field hands off from its last layout's centre, not the corner |
| inspo-16 | 83.3 | .82 | .92 | .49 | .92 | .95 | the band rises later with its cards; the column gone by 6 s; the KB card slides in at a cut 0.2 s earlier; the ring at the lower right with 24/7 inside it; a per-cell luminance grid then showed the reference's sky is lit from the TOP, not the lower right |
| inspo-17 | 81.7 | .78 | .87 | .50 | .92 | .95 | REGRESSION: skies lit from the top overshot to luma ~200 against the reference's ~150; the burst glow too strong. Structure still rose (logo at 10.3 s, hang-line glow, the larger arc) |
| inspo-18 | 84.2 | .83 | .94 | .50 | .92 | .96 | both skies at the reference's level (a near-uniform mid-blue, luma ~150); best so far — colour, busyness and motion all past 0.85 |
| inspo-19 | 83.7 | .83 | .95 | .48 | .92 | .95 | the second sky as the reference's diagonal band (kept); smaller bubbles and a relocated Knowledge Base card cost structure (reverted in 20) |
| inspo-20 | 84.4 | .83 | .95 | .50 | .92 | .96 | the two reverts; the icon glow peaks at 8 s; best so far |
| inspo-21 | 83.8 | .83 | .94 | .48 | .91 | .95 | edge overlays placed the sphere, violet node, inbound card, icons and ring exactly (structure up at 6.5 and 10.5 s); a re-read of the bubble grid was wrong and cost the conversation beat (reverted in 22) |
| inspo-22 | 84.4 | .83 | .95 | .51 | .91 | .96 | iteration 20's conversation beat restored over 21's dark-scene gains; best structure so far |

What the difference maps showed at inspo-13: a shot that targets a NODE puts
that node at the frame's centre, so the sphere, phone and cards landed where
the camera put them, not where the reference has them. From inspo-14 the
recreation targets frame points and authors positions to land under the
zoom; the Knowledge Base scene gained the reference's upward drift (a
parallax shot with a duration).

Where this leaves the recreation against the acceptance list: the film
keeps one continuity thread across every cut but the light sweep (which
is the subject there), the camera curve is continuous, every handoff is a
compiled morph, the review checks pass, and the motion profile now
correlates with the reference at 0.9. The per-frame metrics have
plateaued at the point where what remains is the reference's own copy,
exact pixel placement and its production typography (Inter is fetched at
render time and falls back to Noto Sans offline; bundling a face is the
owner's packaging call). The final 1080×1920, 60 fps render, its
benchmark sheet, review sheet and promotion report are the deliverable
of this pass.

What this did to the pipeline, beyond the fixture: content-animation
times are scene-local; the field's random is unsigned; exits never render
early; shots can name a duration; the continuity gate degrades instead
of refusing a production render; scene prompts after the first are short
and the repair pass is bounded; four primitives and the reference grammar
are in the catalogue. A model-written plan still tends to build from
plain rectangles (the Alphakore run did), so the next prompt work is
making the catalogue's material primitives the writer's default, not the
authored fixture's.

Materials as the writer's default (10 Sep 2026, after inspo-09): the
catalogue now says what a `shape_rect` is for (hairlines, pills, badges,
bubbles) and that a flat rectangle wider and taller than half the frame is
the wrong primitive for a background or a card; the cinematic scene rules
carry the same as rule 12; the storyboard turn asks each row's `look` to
name the material primitives that carry the scene; and `inspect()` sends a
flat, non-gradient, non-glass `shape_rect` covering half the frame both
ways back under the layer doctrine, naming `light_field` or `glass_panel`.
Gradient skies, glass rects, chat bubbles and undoctrined scenes are left
alone, and the authored recreation trips nothing. Pinned by
`tests/test_motion_materials.py::MaterialsAreTheWritersDefault`. Still to
do on this pass: the final 1080×1920, 60 fps deliverable render with its
benchmark, review and promotion sheets — deferred while Prism's own Chrome
holds the machine's memory.

The motion profile (frame-to-frame change every half second, reference
against render) is now the first thing read each iteration: it showed the
sweep spike at 12.5 s, the band burst at 5.0–6.0 s and the Knowledge Base
arrival at 19.8 s more plainly than any frame did.

Probing the runtime page directly for inspo-02 found two defects that no
settled-frame check had caught, both fixed and pinned by
`tests/test_motion_inspo.py`:

- the particle field's seeded random went negative after its XOR steps
  (JavaScript XOR yields a signed 32-bit int), so half the tiles landed
  off the top-left of the frame — the "sparse field" was mostly off-screen;
- an exit tween rendered its from-value at creation, overwriting the hidden
  state the enter had set, so any node with a delayed entrance showed at
  full opacity from the scene's first frame until its entrance began.
  Exits no longer render early (`immediateRender` follows the block).

The first real production run through this gate (10 Sep 2026, a routed
Alphakore reel: seven scenes, twenty minutes of ChatGPT turns) was refused
at render because the writer keyed `alphakore_mark` in scenes 2 and 5 but
not 3 and 4. That is the wrong trade for a finished plan, so the gate now
degrades instead of refusing: a thread gap is a warning, an unbridgeable
cut keeps its ordinary transition, and `render()` refuses only when the
spec carries `_strict_continuity` (the promotion gate and its tests). The
reel then rendered and passed the export gate. Its frames also show the
next prompt problem: the writer built the piece from full-frame `shape_rect`
backgrounds and arrows rather than the material primitives, so it reads as
flat blocks, not the reference's glass and light.

Also from this pass: the `_repair_continuity` turn is capped to real
errors and three scenes, and scene prompts after the first name the
catalogue instead of repeating it — a routed Motion run on this 7.6 GB
machine lost its ChatGPT tab to the kernel's out-of-memory killer at the
seventh long turn while the full test suite and a 1080×1920 render ran
alongside it. Iterations here now render at 720×1280 and never while
Prism's own Chrome is active.

## The story contract, and the first generated reel through it

The 20:25 Alphakore run (motion_1789052157) had seven scenes and no story:
the copy stage's script never reached the motion writer, turn one answered
whole scenes instead of a storyboard, every scene prompt said "carry the
argument forward" with no argument, the writer drifted to x/y, text, source
and top-level enter/exit after scene 4 (the tolerant schema dropped them and
the last three scenes rendered blank), and a shot targeting an arrow parked
the camera in the top-left corner for eleven seconds. Benchmark: 33.

What changed, all in the engine and all pinned by tests:

- the copy stage's script is threaded into the motion writer's first turn
  (`automation.motion_turn_one`), each storyboard row carries the beat's
  `caption` and `subject`, a whole-spec answer to turn one is asked again for
  the storyboard, every scene is checked against its caption
  (`generate.caption_faults`) and must name a shot (`shot_faults`);
- the schema maps the writer's near-misses to the keys the runtime reads
  (`schema.normalize_aliases`: x/y, text, source, stroke, glow/ring, top-level
  animation blocks, from/to tweens, shape_group parts, string particle-field
  phases, `project.palette.x` colour references);
- camera targets resolve to a node's visual centre and never to a placeless
  node; a scene without a shot settles back to the centre; text the settled
  camera would clip is a continuity error (`continuity._camera_clip_faults`);
- the inspector refuses empty text, sourceless images, placeless nodes, flat
  full-frame rectangles and empty glass panels; the per-scene repair runs two
  rounds, the second naming the change each fault needs (`generate.repair_prompt`);
- a carried subject that sits at the same pose for three scenes is a warning.

The first generated reel through all of that (run_1789060262, 20 minutes of
ChatGPT turns, `inspo-final/alphakore-story-contract-720.mp4`): a real
seven-row storyboard, every scene carrying the script's exact line in order,
no continuity errors, the logo opening and closing the piece, rendered after
one runtime fix. Benchmark 46 (lum .60, col .64, struct .22, busy .74, move
.27): a story now, but nearly static — the writer's heroes enter and sit, its
placeholder "screenshot" frames are empty glass, and the camera parked
off-centre because scenes 3-7 named no shot. The settle rule, the shot
fault, the empty-panel fault and the guided second repair round exist
because of that run and are what the next run is measured on.

Run 2 through the same contract plus the settle rule, the shot check, the
empty-panel fault and the two-round guided repair (run_1789063743, 54
minutes — 26 of them automation cycling the empty brains stage through
Perplexity and Claude after the plan was already done, a failover that
nothing downstream needed): a cleaner plan (every caption in order, no
per-scene faults left, the writer's own continuous camera), benchmark 45.5,
motion correlation 0.004. Its frames exposed one runtime defect and two
writer habits: the `split_slide` text mode emptied its line and drew two
absolutely positioned halves, so the text box was 0×0 and its clipping hid
every split_slide caption (fixed with an in-flow invisible copy; pinned in
the render lane); the writer's particle fields were 2 px dust and its light
fields the background colour (both are now inspect faults). A missing shot is
no longer a fault when the storyboard authored `camera.tracks` — that check
cost two wasted repair rounds a scene. Still open: the writer builds no
transformation beats, so the next lever is an authored spine of beats with
required primitives and phases that the storyboard maps the script onto.

Run 3 with the authored spine (`core/motion/spine.py`: ten beats — gather,
channel, converge, hub, sweep, cards, knowledge, arc, orb, resolve — each with
the primitives, phases, counts and sizes the recreation uses; the storyboard
turn maps the script's lines onto them; every scene prompt carries its beat's
recipe; a scene missing its beat's transformation is sent back with it;
run_1789068261, 39 minutes with failover off): the writer built eight scenes,
the repair rounds fixed 5→3→2 faults on one scene and "no better" on five, the
continuity pass sent 18 problems back. Benchmark 44.4 (lum .58, col .58,
struct .33, busy .74, move .20). The candidate's mean colour sat at (28,37,56)
for the reference's whole bright-sky passage (12.5-19.5 s, ~(125,160,190)) and
its frame-to-frame busyness never left 0.05: asked for a sky sweeping in at
0.42 s the writer draws a dim rectangle, asked for 100 tiles travelling into a
band it draws 40 that sit. Three runs, three ways of asking, one result.

## The composer: structure in code, words from the model

The lesson of runs 1-3 is that the transformation cannot be asked for; it has
to be given. `core/motion/compose.py` builds the reference's grammar in code —
the same nodes, phases, sizes and timings as the hand-authored recreation
(`inspo_fixture` is now `compose(REFERENCE_COPY)`, byte for byte) — and leaves
the model the COPY: brand, tagline, call to action, three channel labels, the
hub card, the three-bubble exchange, two labelled cards, the knowledge card
and its labels, the fact in the ring, and optional one-line captions for the
beats without words. Every slot has a character width and a line budget
measured off the reference's boxes (`compose.SLOTS`); `fit()` wraps and trims,
`normalise_copy()` fills a missing slot with the reference's words so the film
never has a hole. The client's own mark (the asset table's "logo") takes the
resolve beat: a wide wordmark where the reference's name stands, a compact
symbol above the name set in type.

In the pipeline this is the `spine` motion skeleton: `storyboard_instructions`
becomes `copy_instructions` (one turn, the slots and their widths, the script
threaded in), `build_spec` becomes `build_composed` (parse the copy, ask once
more if none came, compose, run the inspector for the log) and never asks for
a scene — so the motion stage is one ChatGPT turn instead of ten to thirty.
Pinned by `tests/test_motion_compose.py`.

Run 4 through the pipeline on the composed path (run_1789109658, 17
minutes end to end instead of 39-54; ChatGPT's one turn wrote the copy —
"Technology with purpose.", "Visit our site", a three-line exchange — and the
engine composed and rendered the film at 1080x1920): benchmark 83.4 (lum .82,
col .94, struct .47, busy .91, move .96), against 44-46 for the three
writer-built runs. `inspo-final/alphakore-run4-1080.mp4`.

The structure sector is now the whole gap. It is a 12x21 edge-density
correlation over the top 54 % of the frame, and in the dark passages the
reference has three or four bright cells per frame, so the composition has
to put the same few features in the same cells. The loop for that is a
stills benchmark (screenshots at the sample times straight from the runtime,
33 s a pass) plus a per-frame listing of the strongest edge cells in ad
coordinates for the reference and the candidate. First passes: the opening
scatter uses the reference's own tile positions (`compose.REFERENCE_SCATTER`,
structure at 0.5 s from .07 to .83), the converge icons and the hub camera
pan take the reference's screen positions (the phone at the band's 0.7, an
1100 px pan in a second, a sphere 450 px below the tree's hub, cards rising
past it at 350 px/s), the knowledge card sits a row lower under a faint tree,
and the great ring settles from twice its size at (500, 800). Stills: 85.5
(lum .83, col .95, struct .56, busy .92, move .96).

## Acceptance criteria for the inspo benchmark

### Visual

- No cold scene reset in the first-to-last continuity thread.
- Every handoff has a visible subject or energy bridge.
- No unintended overlap, clipping, off-frame text or broken image.
- Glass panels preserve edge definition and text contrast at 100% playback.
- Typography remains readable for the intended hold duration.
- Effects support hierarchy; removing any one effect should not collapse the
  composition.

### Motion

- Camera and hero subject have continuous curves across cuts.
- Handoffs are smooth at 60 FPS with no one-frame pop, jump or opacity flash.
- Start, midpoint, settled and exit previews all pass visual review.
- The final scene resolves the same subject introduced in the opening.

### Technical

- Preview and exported MP4 match at golden frames within the configured pixel
  tolerance.
- `ffprobe` confirms requested dimensions, FPS, duration and codec.
- Rendering works with local assets and with no licensed-server dependency.
- A failed render leaves an editable JSON project and actionable diagnostics.
- No automatic git commit or push is part of generation.

## Current verification status

On 10 Sep 2026, on Linux: the full repository suite (`python3 -m pytest`)
passed after each of Phases 1 to 4 (one browser-timeout flake in the Studio
reel inspector during Phase 1 passed alone; one race in a Studio server test
during Phase 4 was fixed by waiting for the callback), the offscreen
`PRISM_SELFTEST` passed after every phase, and the render lanes passed for
`test_motion_assets`, `test_motion_materials`, `test_motion_studio`,
`test_motion_review` and `test_motion_promotion`. The worktree is
intentionally uncommitted; nothing was pulled, merged or pushed.

Useful commands from `prism_gui`:

```bash
pytest -q tests/test_motion_continuity.py tests/test_motion_materials.py \
  tests/test_motion_studio.py tests/test_motion_review.py tests/test_motion_promotion.py
PRISM_RUN_RENDER_TESTS=1 pytest -q tests/test_motion_studio.py tests/test_motion_review.py \
  tests/test_motion_promotion.py
python examples/motion_materials.py --out ../materials-review-01
python examples/motion_review.py --out ../motion-review-01 --preview-check
python examples/motion_promote.py --out ../promotion-linux-01
python examples/cinematic_lab.py --out ../cinematic-review-next \
  --brand Conciz --tagline "Long reads, distilled into decisions."
```

## Bottom line

The direction now has its compiler (continuity bridges and one camera
curve), its materials (glass, light, depth), its editing surface (Motion
Studio with threads, shots, handoffs and review points), its review
(sheet, hold, contrast, pop, beats, export gate, preview-equals-export) and
its promotion gate. What remains is the owner's: run the gate on Windows and
macOS, sign off the two manual criteria on the review sheet, and then decide
whether to promote — and, separately, the asset-intelligence work in item 6,
which no phase of this roadmap covered.
