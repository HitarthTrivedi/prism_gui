---
format: 1080x1920
duration: 60s
message: "Your last collab's transcript is the brief for your next one — one prompt, one pipeline"
arc: Before → After tease → Bridge (product) → Step 1 attach → Step 2 refract → Step 3 the real plan → Step 4 the chain → Wow (the deliverables) → Trust → Brand outro
audience: YouTubers and creators planning their next collaboration video
mode: autonomous
music: none
---

> **Silent by design.** `music: none` + no `SCRIPT.md` = the canonical fully-silent
> marker. Vertical creator content is watched muted, so every `voiceover` is empty
> and the per-frame `onscreen` key carries the cue rhythm instead — **each `onscreen`
> cue is a spoken cue for pacing purposes.** Reveal each piece when its cue lands;
> never dump the canvas at t=0.

## Video direction

**Palette system** (from `frame.md`, never invented). Ground is `ink-black` on every
frame — one register throughout, no light frames. Text is `cream`; secondary text
`cream-muted`; hairlines and inert chrome `border-dark`. **Teal `fire-orange`
(#4CD9B4) is the lone accent** on every frame that is not showing the refraction.
The `band-*` ramp is the one documented exception (`frame.md` § Brand adaptation):
a band hue may appear **only** when it names a Prism category, only on the
`spectrum-band` / `tool-chip` components, and **never without its stage label** —
colour never carries meaning alone. Frames 2, 4, 6, 7 and 8 are the only frames
that may show more than one hue; frames 1, 3, 5 and 9 are teal-only.

**Type.** Display / statement lines: the `display` → `h2` ramp, lowercase, negative
tracking, per `frame.md`'s fit-to-measure rule. Chrome, stage labels, tool chips,
counts, filenames: the `label` role (IBM Plex Mono, uppercase, 0.14em). Reading
copy: `body` / `lead` (Barlow). Never a raw family or px — roles only.

**Motion grammar + reveal model.** One camera, one feel. Every entrance is a
**long-tail settle — `power3` by default; no `back.out` / `bounce.out` /
`elastic.out` anywhere in this video.** Every frame reveals **sequentially, cued to
its `onscreen` lines**, with reveals spread across the back ~50%; at t=0 a frame
shows only what its first cue says. All entrances are `fromTo` with an explicit
from-state. No CSS `transition` / `@keyframes`, no `repeat` / `yoyo`, no
`Math.random` / `Date.now` — motion is deterministic and driven inside the paused
GSAP timeline. Any variation derives from element index.

**Rhythm / held-frame allocation.** The video alternates dense and still.
**Frame 7 (the deliverables climax) and Frame 9 (the sting) are the allocated held
frames** — content resolves, then reads dead still. Frames 1 and 4 are the two
busiest; Frame 8 is a low-motion breather before the outro. During any hold the
**only** sanctioned aliveness is low-amplitude **subtle jitter** (`sine-wave-loop`,
low register) or a live SVG internal — never a breathing scale loop, never a
back-half pan or push.

**Composition.** 1080×1920. Plan every frame's content into the **top ~83%**; the
bottom ~17% stays clear (caption-band keep-out — held even though this project is
silent, for bottom-edge consistency). Vertical stacking is the house layout: the
refraction runs **top → bottom**, which is why 9:16 suits this idea rather than
fighting it. Primary visual ≥40% of canvas, ≥3 depth layers on every frame.

**Negative list — what never appears.** No rounded corners (0 radius everywhere),
no box-shadow, no gradient ground, no glow that isn't the named `ambient-glow-bloom`
on a hero. No serif. No uppercase display type. No stock-photo texture, no floating
bokeh, no purple-blue "AI" gradient. No third-party **logos** — tool names appear as
mono text only, and only tools Prism actually drives. **No invented UI**: a real
screenshot is cropped, never doctored; when an element must move, it is rebuilt in
the app's own chrome and stays visibly a rebuild. No fabricated figures — the only
counts in this video are 25 tools, 7 categories, and the app's own step counter.
And both motion failure modes are banned outright: **slideshow** (everything dumped
by ~25%, then frozen) and **screensaver** (elements floating independently as a
substitute for motion).

---

## Frame 1 — Six tabs, one context

- scene: Six tab-shaped slabs stack up the vertical frame, each re-typing the same context line, until they crowd the edges
- voiceover: ""
- onscreen: "your next collab video" / "starts with re-explaining" / "everything you already said" / "six times."
- duration: 6s
- transition_in: cut
- status: animated
- src: compositions/frames/01-six-tabs.html
- type: pain_point
- persuasion: Pain validation
- beat: frustration → recognition
- blueprint: overwhelm-surround (Adapt)
- focal: none — typography and rebuilt slabs only
- roles: none
- asset_candidates:

narrativeRole: Opens on the viewer's real friction in their own outcome language — not a feature, not a company description. The pain is repetition, not tooling.
keyMessage: You already said all of this once.

Adapt: keep the accumulate-then-close-in signature (surfaces pile up, then crowd the frame from all sides). **Change:** no avatar morph — a creator promo should not stage a fake face, so the trapped centre is the repeated context line itself. Slabs are rebuilt tab shapes, not screenshots.

Scene 1 (0.0–1.4s): ink ground, empty. One tab-shaped slab — sharp rectangle, `ink-black-alt` fill, 1px `border-dark`, a mono tab label reading `CHATGPT` — settles dead-centre at ~46% of canvas; inside it a `body` line **types on behind a blinking caret** (`discrete-text-sequence`): "so last month I did a collab with @maya, and the video was about…". Cue 1 "your next collab video" enters across the top third as a **per-word staggered reveal** (`dynamic-content-sequencing`), long-tail settle. Centered template, 3 depth layers (ground / slab / type).
Scene 2 (1.4–3.0s): cue 2 "starts with re-explaining" lands beneath cue 1. Two more slabs — `CLAUDE`, `PERPLEXITY` — arrive stacked behind the first on receding z-planes, each already carrying the SAME typed line at reduced opacity; the repetition is the read. Layered-depth, 3 z-planes with static scale/opacity/blur falloff (a fixed depth style, not a move); entrances staggered by index on a long-tail settle.
Scene 3 (3.0–4.6s): cue 3 "everything you already said". Three further slabs — `NOTEBOOKLM`, `MIDJOURNEY`, `CANVA` — drive **inward** from the left, right and bottom edges, closing the gutters until the centre slab is boxed in (`center-outward-expansion` run inward, staggered by index). Density rises hard; the frame goes claustrophobic. Nothing rotates, nothing bounces.
Scene 4 (4.6–6.0s): cue 4 "six times." slams into the one remaining gap in the accent teal (`kinetic-beat-slam`), 3:1 larger than any slab label so it wins the squint test. Everything else holds; **subtle jitter** (`sine-wave-loop`, low amplitude) on the slab crowd keeps it alive. No drift, no push.

## Frame 2 — One prompt. One pipeline.

- scene: A single white prompt line lands mid-frame and refracts downward into four labelled colour bands — the promise, stated as the mechanism
- voiceover: ""
- onscreen: "one prompt." / "one pipeline." / "your last transcript in — your next collab out."
- duration: 6s
- transition_in: zoom-through
- status: animated
- src: compositions/frames/02-promise.html
- type: hook
- persuasion: Negative contrast → future pacing
- beat: relief + curiosity
- blueprint: kinetic-type-beats (Adapt)
- focal: none — typography and the refraction primitive
- roles: none
- asset_candidates:

narrativeRole: The value claim, landing on beat 2 exactly as the spine requires. Everything after this frame is evidence for it. The refraction appears here for the first time so the whole video has one visual thesis.
keyMessage: One prompt becomes the whole pipeline.

Adapt: keep the beat-by-beat statement build. **Change:** the payoff beat is not a word — it is the refraction itself, so the shot's third beat hands the frame to the `spectrum-band` primitive.

Scene 1 (0.0–1.3s): black clears from Frame 1's crowd. A single 2px **white** horizontal line **draws itself** in from the left edge to centre (`svg-path-draw`) at ~38% height — the white light, deliberately the only pure white in the video. Cue 1 "one prompt." slams in above it (`kinetic-beat-slam`), `display` role, lowercase. Centered, high negative space (~55% empty).
Scene 2 (1.3–2.8s): cue 2 "one pipeline." replaces nothing — it lands directly beneath cue 1 on its own beat. The white line reaches an unseen vertex at centre and **refracts**: four `spectrum-band` bars fan downward at increasing angles (`center-outward-expansion`, staggered by index, long-tail settle), each carrying its stage label in `ink-black` mono ON the band — `LOOK THINGS UP` (band-research), `THINK IT THROUGH` (band-reasoning), `WRITE IT UP` (band-writing), `MAKE THE IMAGES` (band-images). Every band is labelled; none reads by hue alone.
Scene 3 (2.8–4.6s): cue 3 "your last transcript in — your next collab out." reveals as a **per-word staggered reveal** (`dynamic-content-sequencing`) in `lead` beneath the fan, its two halves cued either side of the em-dash so the line reads as two beats, not one breath.
Scene 4 (4.6–6.0s): resolved. **Keyword glow** (`asr-keyword-glow`) lands once on "your next collab out" in teal, then the frame holds still — at most subtle jitter on the band fan. No camera move in the back half.

## Frame 3 — Drop the transcript in

- scene: The real task card, cropped tall. A task types itself in; Add file attaches last-collab-transcript.txt; the file card lands in "Files you mentioned"
- voiceover: ""
- onscreen: "add file →" / "last-collab-transcript.txt" / "\"plan my next collab with @maya — research it, script it, make thumbnails\"" / "make a plan"
- duration: 8s
- transition_in: crossfade
- status: animated
- src: compositions/frames/03-attach.html
- type: feature_showcase
- persuasion: Friction reduction
- beat: ease
- blueprint: prompt-type-submit-generate (Adapt)
- focal: assets/app-task-card.png
- roles: app-task-card = cutout (cropped to the task-card region only; lay all type around it, never over it)
- asset_candidates: assets/app-task-card.png — real screenshot of the empty task card with its placeholder line and Speak / Add file / Add folder / Make a plan buttons

narrativeRole: Step 1 of the demo, and the beat the user asked for by name — the old transcript physically entering the pipeline. The ask is typed in plain language; nothing is configured.
keyMessage: The context you already have is the input.

Adapt: keep the type-into-a-real-input → submit signature. **Change:** the input is a real screenshot crop rather than a reconstruction, so the two things that must MOVE — the typed ask and the attached file chip — are rebuilt in the app's own chrome (light `cream` panel, 1px hairline, 0 radius, mono label) and composited onto the crop at measured positions. The screenshot itself is never doctored: its own placeholder text is covered by the rebuilt input, not edited.

Scene 1 (0.0–1.6s): the task-card crop lands as a `ui-inset` panel occupying the middle ~55% of the frame height, 1px `border-dark` frame, no shadow — entering with a restrained scale-up settle from 0.94 (`spring-pop-entrance`, smooth register, no overshoot). A mono kicker `YOUR TASK` sits above it in teal. Ground stays ink; the panel is the only lit surface — 3 depth layers (ground / panel glow-free inset / chrome type).
Scene 2 (1.6–3.4s): cue "add file →" — a teal 2px rule sweeps left-to-right and stops under the crop's real **Add file** button (`svg-path-draw`), then cue "last-collab-transcript.txt" arrives as a **rebuilt file chip** rising from the lower right and docking at the panel's right edge under a mono `ATTACHED` label (long-tail settle). The chip is visibly a rebuild, in the app's own chrome.
Scene 3 (3.4–6.2s): the ask **types on behind a caret** into the panel's input region (`discrete-text-sequence` + `context-sensitive-cursor`), phrase by phrase so the three deliverables land as three separate beats: "plan my next collab with @maya" · "— research it," · "script it," · "make thumbnails". Body role, sentence-cased inside the input. This is the frame's back-half reveal — nothing else moves under it.
Scene 4 (6.2–8.0s): the crop's **Make a plan** button lights teal and takes a tactile press (`press-release-spring`) as cue "make a plan" lands beside it in mono; the frame then holds still.

## Frame 4 — It splits the job for you

- scene: The white prompt line refracts through the prism into seven labelled stage bands; three dim and switch off, four stay lit
- voiceover: ""
- onscreen: "look things up" / "think it through" / "write it up" / "make the images" / "4 steps of 7 — the rest switch off"
- duration: 8s
- transition_in: crossfade
- status: animated
- src: compositions/frames/04-refract.html
- type: product_intro
- persuasion: Show-don't-tell proof
- beat: clarity
- blueprint: grid-card-assemble (Adapt)
- focal: none — the refraction primitive is the hero
- roles: none
- asset_candidates:

narrativeRole: The mechanism beat — the Groq router splitting one task into only the stages this job needs. This is the literal prism, and the only frame where all seven category hues appear at once.
keyMessage: Prism picks the stages; you didn't have to.

Adapt: keep the staggered self-assembling cascade and the "reveal the whole array" payoff. **Change:** the array is not a card grid but the seven-band spectrum, stacked top-to-bottom down the vertical frame — and the payoff is subtractive (three bands switching OFF), which is the actual product behaviour.

Scene 1 (0.0–1.2s): the white prompt line returns at ~22% height with the typed ask from Frame 3 riding it as small mono text, dimmed to `cream-muted` — the frame opens on the input, nothing else. A faceted vertex (flat polygons, the logo's geometry, no gradient) settles beneath it.
Scene 2 (1.2–4.6s): the seven `spectrum-band` bars cascade **outward and downward** from the vertex, one per beat, staggered by index (`center-outward-expansion`, long-tail settle), filling the frame top-to-bottom in plan order: `LOOK THINGS UP` · `THINK IT THROUGH` · `WRITE IT UP` · `MAKE THE IMAGES` · `MAKE THE VIDEO` · `BUILD THE TOOL` · `BUILD THE SLIDES`. Each label is mono `ink-black` ON its band. Full-width strip layout; density peaks here — this is the busiest frame in the video and the only place all seven hues coexist.
Scene 3 (4.6–6.6s): three bands switch off. `MAKE THE VIDEO`, `BUILD THE TOOL` and `BUILD THE SLIDES` desaturate to `cream-hint`, collapse to hairlines, and their square include-markers flip to unchecked (`discrete-text-sequence` for the marker state), receding under `depth-of-field-blur`. The four surviving bands hold position — nothing re-flows, so the eye stays where it was.
Scene 4 (6.6–8.0s): mono line "4 steps of 7 — the rest switch off" lands bottom-left in `cream-muted`; the four lit bands hold with subtle jitter only.

## Frame 5 — And it's real

- scene: The actual app screenshot's plan rows, cropped to a tall column, scrolling one row at a time; each tool chip lights as its row arrives
- voiceover: ""
- onscreen: "look things up — Perplexity" / "think it through — ChatGPT" / "write it up — Claude" / "make the images — ChatGPT" / "don't like a pick? change the chip."
- duration: 7s
- transition_in: crossfade
- status: animated
- src: compositions/frames/05-real-plan.html
- type: feature_showcase
- persuasion: Show-don't-tell proof (real UI, real tool names)
- beat: skepticism → trust
- blueprint: device-surface-showcase (Adapt — cursorless stepwise-flow variant)
- focal: assets/app-plan-rows.png
- roles: app-plan-rows = cutout (crop to the "Your plan" rows column and its tool chips ONLY — exclude the left rail, the right column, the step counter and the Start-the-work button; the read is the rows and their chips, not the window)
- asset_candidates: assets/app-plan-rows.png — real screenshot, cropped to the "Your plan" rows column with its tool chips

narrativeRole: Cashes the abstraction in for the real product. Real screenshot, real tool names, and the fact that every router pick is overridable — the honesty beat the brand demands.
keyMessage: These are real tools, and you can overrule every one of them.

Adapt: keep the held-hero surface stepping through a real flow, cursorless. **Change:** the hero is a cropped real screenshot rather than a device mockup, and the "steps" are the rows taking focus in turn — the surface itself never tilts, rotates or gains a device frame.

Scene 1 (0.0–1.2s): the plan-rows crop lands as a `ui-inset` filling ~68% of the frame height, top-aligned under a mono teal kicker `THE ACTUAL APP` — a restrained scale-up settle from 0.96 (`spring-pop-entrance`, smooth). It is the only lit surface; ink ground, hairline frame, no shadow.
Scene 2 (1.2–2.4s): row 1 takes focus. A teal 2px edge **draws down** the row's left side (`svg-path-draw`) and its chip lights (`asr-keyword-glow`); cue "look things up — Perplexity" lands in mono outside the panel, left. The panel's viewport steps so row 1 sits at the golden upper-third (`viewport-change`).
Scene 3 (2.4–3.6s): the panel steps one row (`viewport-change`, matched direction and speed on both sides of the step — a velocity-matched seam, `cut-catalog.md`); the lit edge hands off to row 2 and cue "think it through — ChatGPT" replaces the previous mono line on a hard cut (`discrete-text-sequence`).
Scene 4 (3.6–4.8s): same step to row 3, cue "write it up — Claude".
Scene 5 (4.8–5.8s): same step to row 4, cue "make the images — ChatGPT" — the images row is the one the thumbnails come from, so the lit edge holds a beat longer here.
Scene 6 (5.8–7.0s): the stepping stops. Cue "don't like a pick? change the chip." lands beneath the panel in `lead`, and one chip takes a single tactile press (`press-release-spring`) to show it is a control, not a label. Then still.

## Frame 6 — Each answer becomes the next question

- scene: Four stage cards stacked down the frame; a lit thread carries each card's output into the next card's input as the chain builds downward
- voiceover: ""
- onscreen: "research →" / "feeds the script →" / "feeds the thumbnails" / "you never paste context twice"
- duration: 7s
- transition_in: crossfade
- status: animated
- src: compositions/frames/06-chain.html
- type: benefit_highlight
- persuasion: Feature-to-benefit translation
- beat: control
- blueprint: camera-journey (Adapt — sub-shape A, action roundtrip)
- focal: none — rebuilt stage cards
- roles: none
- asset_candidates:

narrativeRole: The actual differentiator, and the direct answer to Frame 1's pain — each stage's output is passed forward as context to the next. Delete this frame and the video is just a tool launcher.
keyMessage: The pipeline carries the context so you don't.

Adapt: keep the signature — a beat fires in one region and the camera **travels** to where its consequence renders. **Change:** the journey is a single continuous downward traverse rather than a swoop-and-return, because the pipeline itself runs top-to-bottom; the "click" that fires each leg is a stage completing, not a cursor.

Scene 1 (0.0–1.5s): tight framing on stage card 1, `LOOK THINGS UP`, band-research edge, occupying ~55% of the frame. Its output renders inside it as three short hairline source rows arriving in a **per-word staggered reveal** (`dynamic-content-sequencing`). Nothing else is on screen yet.
Scene 2 (1.5–3.2s): cue "research →". A teal thread **draws** from card 1's bottom edge (`svg-path-draw`) and the camera **travels down** with it (`viewport-change`, one continuous decelerating move) to card 2, `WRITE IT UP`. On arrival the thread deposits the same three source rows into card 2's context slot, dimmed to `cream-hint` — the literal hand-off. Layered-depth: card 1 stays partly in frame above, blurred back.
Scene 3 (3.2–4.9s): cue "feeds the script →". Card 2's own output — three timecoded script rows — writes itself, then the thread continues and the camera travels again to card 3, `MAKE THE IMAGES`, depositing the script's hook line as its context.
Scene 4 (4.9–7.0s): cue "feeds the thumbnails" lands; then the camera makes ONE decelerating pull-back revealing all three cards chained down the frame by the single unbroken thread, and cue "you never paste context twice" resolves in `h2` across the top. Content is resolved — the frame then holds dead still. No further camera move.

## Frame 7 — What you get back

- scene: Three deliverables land in sequence up the frame — a research brief, a scripted outline, then three thumbnail frames snapping into a row
- voiceover: ""
- onscreen: "the research, sourced" / "the script, in your voice" / "three thumbnails to pick from" / "one prompt ago."
- duration: 8s
- transition_in: crossfade
- status: animated
- src: compositions/frames/07-deliverables.html
- type: benefit_highlight
- persuasion: Value stacking → rule of three
- beat: excitement
- blueprint: grid-card-assemble (Reproduce)
- focal: none — rebuilt deliverable cards
- roles: none
- asset_candidates:

narrativeRole: The payoff. Every deliverable the user named — research, script, thumbnails — arriving from the single prompt of Frame 3, closed by the time claim.
keyMessage: One ask, three finished things.

Reproduce: the accumulating staggered cascade, filled with this product's three deliverables. **This is an allocated held frame** — everything resolves by ~6.2s and then reads dead still.

Scene 1 (0.0–1.8s): card 1, `THE RESEARCH, SOURCED`, rises into the lower-middle third on a long-tail settle — a document card, `ink-black-alt` fill, 1px hairline, four hairline text rules and three mono source tags along its foot, band-research edge. Cue 1 lands with it.
Scene 2 (1.8–3.6s): card 1 steps up the frame and card 2, `THE SCRIPT, IN YOUR VOICE`, enters beneath it — timecoded hairline rows, band-writing edge. Both cards co-resident and accumulating; the step is one motion, not a re-layout.
Scene 3 (3.6–6.2s): both cards step up again and **three 16:9 thumbnail frames snap into a row** across the lower third, staggered by index (`spring-pop-entrance`, smooth register). Each thumbnail is a flat band-hued rectangle carrying one bold lowercase condensed word the way a real thumbnail carries type — no photos, no faces, no invented likenesses. Cue "three thumbnails to pick from" lands with the third. Triptych within a full-width strip; density peaks and the squint test resolves on the thumbnail row.
Scene 4 (6.2–8.0s): cue "one prompt ago." lands in teal beneath the row, 3:1 over the card labels. **Everything holds dead still** — the climax reads, with at most subtle jitter on the thumbnail row. No pan, no push, no breathing.

## Frame 8 — In your Chrome, signed in as you

- scene: A browser-frame outline draws itself around a miniature of the running pipeline; the trust claims land one at a time
- voiceover: ""
- onscreen: "it runs in your own Chrome" / "signed in as you" / "no passwords stored" / "it doesn't replace your tools — it drives them"
- duration: 6s
- transition_in: zoom-through
- status: animated
- src: compositions/frames/08-your-chrome.html
- type: social_proof
- persuasion: Risk reversal
- beat: peace of mind
- blueprint: titlecard-reveal (Adapt)
- focal: none — one drawn outline and four type beats
- roles: none
- asset_candidates:

narrativeRole: The trust beat, and the brand's stated honesty — Prism routes to other people's tools and drives the viewer's own browser. This is what separates it from a magic box, so it earns its own frame rather than a footnote.
keyMessage: Your logins, your subscriptions, your browser.

Adapt: keep the ONE restrained move + still hold. **Change:** the single move is the browser outline drawing itself on; the card chain becomes four cued type beats inside and beneath it. **This is the low-motion breather before the outro** — deliberately the quietest frame in the video.

Scene 1 (0.0–1.6s): ink ground. A browser-window outline **draws itself** on (`svg-path-draw`) around the frame's upper-middle — 1px `border-dark`, 0 radius, one hairline top bar, **no traffic lights, no URL text, no scrollbar**: an intentional, minimal UI reconstruction, not fake chrome. A miniature of Frame 4's four lit bands fades up inside it at ~35% scale, labels intact. Cue 1 "it runs in your own Chrome" reveals beneath in `h2`.
Scene 2 (1.6–3.0s): cue 2 "signed in as you" types into the outline's top bar in mono (`discrete-text-sequence` + `context-sensitive-cursor`) — the only motion in this window.
Scene 3 (3.0–4.3s): cue 3 "no passwords stored" lands in teal beneath the outline on a hard cut (`kinetic-beat-slam`, single beat).
Scene 4 (4.3–6.0s): cue 4 "it doesn't replace your tools — it drives them" reveals as a two-part **per-word staggered reveal** split at the em-dash, `h2`, lowercase, with "drives" carrying a single `asr-keyword-glow`. Then still — no jitter here; this frame's stillness is the point.

## Frame 9 — Prism

- scene: The stage clears off all four edges; the prism mark draws itself in and the wordmark completes the lockup
- voiceover: ""
- onscreen: "25 tools. 7 categories." / "one prompt." / "PRISM"
- duration: 5s
- transition_in: crossfade
- status: animated
- src: compositions/frames/09-outro.html
- type: branding
- persuasion: Rule of three
- beat: inevitability
- blueprint: logo-assemble-lockup (Reproduce)
- focal: assets/prism-logo.svg
- roles: prism-logo = cutout (the hero mark; nothing overlaps it)
- asset_candidates: assets/prism-logo.svg — the teal faceted prism mark, vector, transparent

narrativeRole: The sting. Two real counts and the thesis word, then the mark — no invented figures, no CTA the product can't honour.
keyMessage: Prism.

Reproduce: elements clear the stage off all four edges, the mark draws itself on, the wordmark completes the lockup. **The allocated final held frame**, and the only frame in the video with a real exit-class move (the clear-out) — legitimate because it is the last frame.

Scene 1 (0.0–1.2s): Frame 8's outline and type clear off all four edges, staggered by index with each element's direction derived from its own position (deterministic, no randomness), on a long-tail settle. The frame empties to pure ink.
Scene 2 (1.2–2.6s): the prism mark's outline **draws itself on** stroke-by-stroke (`svg-path-draw`), then its five facets fill in staggered along the teal ramp, dead-centre at ~30% of canvas width. `ambient-glow-bloom` blooms once, softly, behind it — the one sanctioned glow in the video.
Scene 3 (2.6–3.8s): the `PRISM` wordmark completes the lockup beneath the mark in condensed display, entering as a **per-word staggered reveal** — here, letter-group by letter-group — on a smooth settle.
Scene 4 (3.8–5.0s): the mono line "25 tools. 7 categories. one prompt." lands beneath the lockup in `cream-muted`, its three clauses cued as three beats. Then the lockup **holds dead still to the final frame** — live SVG internals only if anything at all; no jitter on the mark.
