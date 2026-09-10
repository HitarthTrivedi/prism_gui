# Studio render recovery and quality pass

Local, uncommitted work. No commit, push, licensed-server change, or live
ChatGPT message was made in this pass. The active engine is the nested
`prism_gui/prism_terminal`; the sibling reported as `ignored` is not loaded.

## The follow-up failure

The reported run captured a design/storyboard reply but never entered the
Studio renderer. The GUI located a saved Studio project only through a media
link ending in `.mp4`. A failed initial export had saved its JSON but had no
media link, so follow-up routing fell back to ordinary chat.

`MainWindow._studio_reel_in` now also recovers the newest valid saved project
whose `_studio.design_url` matches the current design conversation exactly
(allowing trailing slash/whitespace differences). It never picks the newest
unrelated project. Regression tests cover absent MP4s, corrupt records and
unrelated projects. A storyboard plus shared CSS is no longer accepted as an
executable follow-up; the engine requests complete scene HTML/CSS once more.

Restart Prism to load the changed Python modules, then reopen the failed run
from History and submit the render/fix follow-up. The live external ChatGPT
turn has not been replayed here; routing and reply handling were tested with
controlled responses, and the renderer was tested separately in Chromium.

## Rendering and asset fixes

- Scene roots remain absolute film layers even when generated `.scene` CSS
  requests `position:relative`. That override previously stacked later scenes
  below the 1920-pixel canvas. The original failed Consiz project now returns
  an empty fault list in browser preflight.
- New element IDs reserve existing identities before allocation, including
  IDs later in the document. Duplicate IDs from single-scene generation are
  disambiguated without changing an existing unique target.
- Stills and inspection apply saved Studio edits and timing, like export.
- Multiple correctly filled CSS animations no longer trigger a false
  `fill-mode: both` error. Invalid non-finite durations are rejected.
- Layout logging distinguishes passed checks, unresolved problems and an
  unavailable checker. A failed check cannot make a proposed correction
  look better than the original.
- Production no longer guesses seven crops from a contact sheet or selects
  a tile using the scene number. Boards remain reference-only; deliberate
  single-image crops must be supplied as separate assets. Legacy `panels`
  metadata does not bypass this restriction. Existing files are not deleted.
- Missing asset paths and unusable/reference-only visual-review flags are
  honored in preflight and rendering. `limited` assets remain usable.

Contact-sheet detection is still heuristic. It is not semantic image review,
and false positives remain possible. A future review UI should expose the
classification and deliberate crop/approval choices.

## Art direction

The audit-first refinement keeps Prism's existing HTML/CSS renderer. Scene
prompts no longer demand 12–30 elements, several easing curves, continuous
motion, a geometric hero or three decorative depths in every shot. They ask
for meaningful source material, a coherent visual idea, deliberate spacing,
early readable entrances and complete-message holds. Saved art direction is
included in follow-ups. Rejected assets are excluded from placement quotas.

The reference-first and snapshot/validation workflow is informed by
[HyperFrames' production pipeline](https://hyperframes.heygen.com/guides/pipeline)
and [prompting guide](https://hyperframes.heygen.com/guides/prompting).
[Higgsfield Vibe Motion](https://higgsfield.ai/vibe-motion) is a product
reference, not an integrated rendering dependency or a guarantee of parity.

## Concrete reference output

`examples/consiz_refined.py` is an authored, reproducible reference using the
existing main Consiz copy. It embeds the repository's Barlow fonts and uses
one visual idea: interference resolving to a signal, focus and invitation.
It is deliberately not a template imposed on every future brand.

Output in the parent workspace:

- `consiz-refined-v2/consiz-refined.mp4`: H.264, 1080×1920, 30 fps, 627 frames,
  20.9 seconds. Silent; no music or voiceover was added.
- `consiz-refined-v2/consiz-refined.json`: editable, self-contained reference.
- `consiz-refined-v2/scene-1.png` through `scene-6.png`: settled previews.

Reproduce from `prism_gui`, using a new output directory:

```bash
python examples/consiz_refined.py --out ../consiz-review-next --render
```

This demonstrates an authored direction, not proof that every fresh model
generation now reaches that quality. Automated geometry checks do not judge
storytelling, brand fit, musical pacing or taste. The reference project does
not carry a live design conversation URL.

## Production Motion continuity slice

The local Motion pipeline now accepts the `cinematic_glass` profile. `/motion`,
the Motion add-on dialog, and routed local Motion planning all use it by
default. Its storyboard and scene prompts require one persistent visual spine,
matched outgoing/incoming poses, a continuous camera move, restrained glass
layers, and a resolved final destination. Hero nodes can carry a stable
`continuity_key` (their editor `id` remains unique); schema validation
normalizes the key and the resolver emits a `_continuity` manifest for Studio
selection and future follow-up patches. The metadata does not alter the
existing renderer's timing or asset resolution, so legacy specs remain safe.

Focused continuity, asset, scene, follow-up and engine-boundary tests pass.
The full suite includes long browser lanes and was not allowed to run
indefinitely in this handoff.

## Verification

Linux verification used local Chromium and FFmpeg; browser runs needed to
run outside the filesystem/network sandbox. No user browser session was used.

- 142 targeted tests passed (4 browser-dependent tests deselected in that run).
- Broader Studio suite: 124 passed, 1 skipped.
- Browser/editor/export suite: 21 passed. Includes multi-scene positioning,
  saved edits, multiple animations and preview/export comparisons before,
  during and after a cut. Suites overlap; these are not unique-test totals.
- `ffprobe` verified the reference MP4's dimensions, duration and frame count.
- Both worktrees pass `git diff --check`.

Representative commands from `prism_gui`:

```bash
QT_QPA_PLATFORM=offscreen pytest -q -o addopts='' tests/test_asset_quality.py tests/test_asset_cutout.py tests/test_router_json.py tests/test_studio_followup.py tests/test_followup_session.py tests/test_scene_by_scene.py tests/test_studio_v2.py -k 'not endpoint and not Browser and not Golden'
QT_QPA_PLATFORM=offscreen pytest -q -o addopts='' tests/test_reel_edit.py tests/test_reel_editor_tools.py tests/test_reel_capture.py tests/test_asset_plan.py tests/test_motion_assets.py tests/test_followup_plan.py tests/test_reel_dialog.py
QT_QPA_PLATFORM=offscreen PRISM_RUN_RENDER_TESTS=1 pytest -q -o addopts='' tests/test_layout_overlap.py tests/test_studio_v2.py
```

Windows/macOS builds, installer packaging, external-provider round trips,
music/audio synchronisation and an exhaustive all-frame visual audit were not
performed. The existing preflight samples settled frames and cannot establish
that every animated frame is readable. Next quality work should make shot
references and approval explicit, then add multi-time visual review and
beat-aware audio rather than more decorative prompt constraints.
