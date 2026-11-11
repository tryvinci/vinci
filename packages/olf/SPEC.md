# Open Lore Format (OLF) v0.1 (Draft)

Nov 8, 2026 · @Team Vinci

This file is the canonical copy of the spec. It lives next to the reference engine (`vinci_olf`). Spec text: CC-BY-4.0. Code and schema in this package: Apache-2.0.

## Overview

The Open Lore Format (OLF) is an open, model-agnostic schema for AI-generated episodic video. It is not a new file format: OLF files are plain YAML, JSON and images. One project holds a show bible and its episodes, which seasons MAY group. Any conforming engine can read, validate and render it.

**In scope for v0.1**

- Show bible: style, characters, locations, props, voices, camerawork.
- Structure: episode, scene, shot, and the episode's cut list.
- Keyframe, video and audio takes, with approval status and provenance.
- Asset references, content hashes and licenses.
- Backend-specific extensions.

**Not in scope for v0.1**

- How a model renders. The spec describes what to make, not how.
- Editing beyond order, trims, cuts and fades. Export to OpenTimelineIO for that.
- Audio mixing beyond start times, volume and ducking. Export stems to an editor for that.
- Real-time collaboration and permissions.

**Existing formats OLF reuses**

| Need | Format |
| --- | --- |
| Scripts | Fountain |
| Edits beyond the OLF cut list | OpenTimelineIO |
| Previs | Storyboard images and OLF camera moves (glTF or USD later, optional) |
| Provenance in exported files | C2PA |
| Images, audio, video | Standard files (PNG, WAV, MP4) |

**Status:** draft. Field names and structure can change until v1.0. The words MUST, SHOULD and MAY follow RFC 2119.

## Design principles

Seven rules decide every field in this spec. A new field that breaks one of them needs an RFC.

1. **Model-agnostic core.** Core fields describe intent (framing, lens, action). They never hold a model parameter. Model settings go in `extensions`.
2. **Layered overrides.** Each level inherits from the level above. A file states only what changes.
3. **Assets by reference.** Each bible entry is a folder: a short YAML file plus its images. The YAML refers to them by relative path, and the lock file records each file's hash.
4. **Provenance on every take.** Each render records provider, model, version, seed, inputs and prompt.
5. **License on every asset.** Each asset states its owner and how others can reuse it.
6. **Human- and LLM-writable.** YAML, readable field names and a published JSON Schema. An LLM given the schema can write a valid episode.
7. **Diff-friendly.** One object per file where practical, and no generated noise in source files.

## Project layout

A project is one folder: a manifest, a bible, episodes, machine-written takes and an asset lock file. Files are YAML 1.2 in UTF-8. The same structure in JSON is also valid.

```text
my-show/
  project.yaml              # manifest: spec version, show id, defaults
  bible/
    show.yaml               # logline, format, tone
    style.yaml              # global look
    characters/
      mira/
        mira.yaml           # short: name, voice, forms, credits
        sheet.png           # the full character sheet
        forms/
          winter/           # front.png, back.png
          ember/            # front.png, back.png
        details/            # eyes.png, hair.png, tail.png
        accessories/        # bell.png, ribbon.png, boots.png
        textures/           # snowflake.png, peony.png
    locations/
      lighthouse/
        lighthouse.yaml
        establishing.png
        north.png
        south.png
    props/brass-key/
      brass-key.yaml
      ref.png
    voices/mira/
      mira.yaml
      sample.wav
    camerawork/tu-to-eyes/
      tu-to-eyes.yaml       # a camera template that shots name
  seasons/
    01.yaml                 # optional: a season's episodes and season-wide overrides
  episodes/
    e02/
      episode.yaml
      scenes/s03.yaml       # a scene and its shots
  takes/                    # machine-written
    e02/s03/sh014/v2.yaml
  assets/
    lock.yaml               # asset ID -> URI, hash, license
  exports/                  # machine-written, derived: not in the lock file
    e02/e02-16x9.mp4        # e02-9x16.mp4, e02.srt
  previs/                   # machine-written, derived: not in the lock file
    e02/e02-sheet.pdf       # e02-sheet-01.png, e02-animatic.mp4
```

**Manifest**

```yaml
spec: olf/0.1
show: tidewatch
title: Tidewatch
defaults:
  aspect: "16:9"
  fps: 24
  resolution: 1920x1080
exports: ["16:9", "9:16"]
license:                      # default license for assets the engine adds
  owner: "@creator"
  terms: all-rights-reserved
```

**IDs**

| Kind | Format | Example |
| --- | --- | --- |
| Character | `char/<slug>` | `char/mira` |
| Location | `loc/<slug>` | `loc/lighthouse` |
| Prop | `prop/<slug>` | `prop/brass-key` |
| Voice | `voice/<slug>` | `voice/mira` |
| Camerawork | `cam/<slug>` | `cam/tu-to-eyes` |
| Season | `season/<NN>` | `season/01` |
| Episode | `e<NN>` | `e02` |
| Scene | `e<NN>/s<NN>` | `e02/s03` |
| Shot | `e<NN>/s<NN>/sh<NNN>` | `e02/s03/sh014` |
| Keyframe take | `<shot>/kf<N>` | `e02/s03/sh014/kf3` |
| Video take | `<shot>/v<N>` | `e02/s03/sh014/v2` |
| Audio cue | `e<NN>/cue/<slug>` | `e02/cue/theme` |
| Audio take | `<shot or cue>/a<N>` | `e02/cue/theme/a1` |
| Asset | `asset/<full SHA-256 hash>` | `asset/2c1d9f` |

- Slugs use lowercase letters, digits and hyphens.
- IDs MUST be unique in a project. They MUST NOT change after the first render. Examples in this spec shorten asset hashes to 6 characters for space. Real asset IDs MUST use the full hash; tools MAY show a short form.
- Number new shots in steps of 10 (`sh010`, `sh020`). An insert then takes `sh015` and nothing is renumbered.
- An ID from another project carries its show ID as a prefix: `tidewatch:char/mira`. Forked bibles use this.

## Show bible

The bible holds everything that must stay the same across episodes. Shots refer to bible entries by ID and MUST NOT redefine them. A look that changes on purpose (a form, an outfit, a time of day) is a named variant in the bible.

**Style** (`bible/style.yaml`)

```yaml
id: style/main
look:
  medium: 2D anime          # live-action, 3D, stop-motion, ...
  palette: ["#1b2a3a", "#e8c07d", "#c44b3a"]
  grade: teal shadows, warm highlights, low contrast
  grain: light
lenses: [24mm, 35mm, 50mm, 85mm]
references: [asset/7f3a21, asset/91bc04]
negative: [text, watermark, extra limbs]
```

**Character** (`bible/characters/mira/mira.yaml`)

```yaml
id: char/mira
name: Mira Sol
description: Lighthouse keeper and fox spirit. Fox ears, long hair, large tail.
voice: voice/mira
sheet: sheet.png              # the whole sheet is the character reference
sheets: [sheet-ember.png]     # more whole sheets, for example one per form
forms:                        # whole-body looks of one character
  winter:
    description: White hair fading to ice blue, snowflake motifs.
    palette: ["#eef6fb", "#7cc7e8", "#1f3a6b"]
  ember:
    description: Orange-red hair, maple-leaf motifs, flame-tipped tail.
    palette: ["#ff7a1a", "#c4161c", "#3a0d0d"]
    views: { front: forms/ember/front.png, back: forms/ember/back.png }
outfits:                      # clothing, worn in any form
  default: { description: "Off-shoulder kimono dress, wide sleeves, boots." }
  night: { description: "Wool sweater, no ribbons." }
details: { eyes: details/eyes.png, hair: details/hair.png, tail: details/tail.png }
accessories: [prop/bell, prop/fox-mask, prop/ribbon]
textures: [textures/snowflake.png, textures/peony.png]
credits: { design: "@artist", owner: "@creator" }
likeness: { real_person: false }
```

- **The sheet comes first.** The whole character sheet image is the character reference. A character MAY list more whole sheets in `sheets` (for example one per form, or an expression sheet). Form `views` and `details` are optional, and each is a separate image file. A reference always names a whole file: OLF has no crops, so `sheet.png#eyes` is an error.
- **Which images a render sends.** For each character: the chosen form's `views.front` when it has one, else every sheet, else its first other reference.
- **Forms vs outfits.** A form changes the whole body (hair, palette, tail). An outfit changes only clothing. Scenes and shots select a form the same way as an outfit: `forms: { char/mira: ember }`.
- **Accessories are props.** Each one has its own `prop/` entry, so it stays consistent when it appears without the character.
- **Credits feed the license.** `credits.design` becomes the attribution when someone forks the bible.

**Location** (`bible/locations/lighthouse/lighthouse.yaml`)

```yaml
id: loc/lighthouse
name: Lamp room
description: Round glass room, brass lamp at the centre, sea on all sides.
variants: [day, dusk, night, storm]
references:
  establishing: establishing.png
  angles: { north: north.png, south: south.png }
```

**Prop and voice**

```yaml
id: prop/brass-key
description: Old brass key, long shank, ring bow, wrapped in cloth.
references: [ref.png]
---
id: voice/mira
description: Low, calm, slight rasp.
sample: sample.wav          # reference audio
extensions:
  elevenlabs: { voice_id: "..." }
```

**Camerawork** (`bible/camerawork/tu-to-eyes/tu-to-eyes.yaml`)

A camerawork template is a named recipe for the camera and staging of one shot: a house style for a move, as an outfit is a house style for clothing. A shot names it in `camera.template`.

```yaml
id: cam/tu-to-eyes
source: anime/tu-to-eyes@1    # optional: the library template and version it was copied from
family: push                  # hold, push, pan, follow, dialogue, action, mood
name: Track up to the eyes
notation: T.U.                # the production term for the move
intent: Push from a close-up to the eyes for a realization or a decision.
camera: { move: push_in, amount: 0.35, ease: in_out, hold_start: 0+12, hold_end: 0+12, center: [0.5, 0.42], render: engine }
framing: [close_up, medium_close]
timing: { default: 3+00, min: 2+00, max: 5+00 }
slots: [a]
rules: { not_twice_in_a_row: true }
keyframe: The eyes of {a} catch the light.
prompt: A slow, steady push toward {a}'s eyes. Only the eyes move.
avoid: [camera drift]
```

- **What changes a render.** `camera` holds the camera fields the template fills (see Layering). `keyframe` is added to the keyframe prompt, `prompt` to the video prompt, and `avoid` to the negative prompt of the video.
- **Slots.** `{a}`, `{b}` and `{c}` in `keyframe` and `prompt` are the shot's `characters`, in order. `slots` lists the ones the template uses. `slots: []` is a BG-only template: its shot has no characters.
- **What a template suits.** `framing`, `timing` (`min`, `max`), `slots` and `rules` say which shots the template suits. `rules` holds `needs_dialogue` (true: the shot has a line; false: it has none), `needs_prop` (the shot names a prop), `not_twice_in_a_row`, `max_per_scene` (the most shots of one scene that use it), `max_amount`, `max_move` (the longest move: the shot's length without its holds) and `sets_axis` (the shot fixes the 180° line of its scene; see Layout). A shot can go against them on purpose, so an engine reports each one as a warning, not an error.
- **`layout`** is the template's pills: where its characters stand (see Layout). A shot's own `layout` wins.
- **`timing.default`** is the length a tool gives the shot when a person applies the template. `dialogue` means the length of the shot's chosen dialogue take. A shot still states its own `duration`.
- **Libraries.** An engine MAY ship a library of templates. A show uses a library template through a copy in its own bible, with `source`, so a project folder holds all that an engine needs to resolve it, and a new library version changes no show until a person takes it.

**Required fields**

| Entry | Required | Notes |
| --- | --- | --- |
| Style | `id`, `look.medium` | One style per show in v0.1 |
| Character | `id`, `name`, `description`, a character sheet or other reference image | A sheet with front and back views is strongly recommended |
| Location | `id`, `name`, `description` | Reference images recommended |
| Prop | `id`, `description` |  |
| Voice | `id`, `description` | `sample` recommended |
| Camerawork | `id`, `family`, `name`, `intent`, `camera`, `timing.default` | `prompt` for a template that a video model renders |

A character based on a real person MUST set `likeness.real_person: true` and SHOULD point `likeness.consent` to a consent record. Identity models such as a LoRA are backend-specific, so they go in `extensions`.

## Seasons, episodes, scenes and shots

A season is an optional, ordered list of episodes. An episode is an ordered list of scenes, and a scene is an ordered list of shots. The shot is the unit that an engine renders. Shots are inline in the scene file by default, because most projects have one author. A scene MAY split into one file per shot (scenes/s03/sh014.yaml) when it grows or a team edits it. Engines MUST read both.

**Season** (`seasons/01.yaml`, optional)

```yaml
id: season/01
title: First Light
synopsis: Mira takes over the lamp and learns what the light keeps away.
episodes: [e01, e02, e03]
forms: { char/mira: winter }   # season-wide default
```

- The season file lists its episodes in order. An episode is in at most one season. An episode in no season has no season level.
- Episode IDs stay unique in the whole show (`e01` to `e36` over three seasons), so a project can add seasons later without renaming episodes or making takes stale.
- **Season overrides.** A season MAY set the same fields as an episode: `defaults`, `forms`, `outfits` and `style` (for example a new palette for season 2). Its `title`, `synopsis` and `episodes` are structure, not overrides.

**Episode** (`episodes/e02/episode.yaml`)

```yaml
id: e02
title: The Second Light
synopsis: Mira finds the key her father hid.
forms: { char/mira: winter }  # episode-wide default
scenes: [e02/s01, e02/s02, e02/s03]
cut:                          # the saved edit, in order
  - { take: e02/s03/sh014/v2, in: 0.2s, out: 3.8s }
  - { take: e02/s03/sh015/v1, in: 0s, out: 2.5s, transition: fade }
cues:                         # music and SFX to render: the cue e02/cue/theme
  theme: { kind: music, description: "Slow piano, distant waves", duration: 20s }
audio:                        # music and SFX over the cut
  - { take: e02/cue/theme/a1, start: 0s, volume: 0.6, duck_under_dialogue: true }
```

The `cut` list is the saved edit: takes in order, each with trim points and an optional `transition` (`cut` by default, or `fade`). A fade overlaps the end of the clip before it. A clip MAY set `audio`: `own` (the default: the take's own sound) or `separate` (the shot's `select.audio` dialogue take). A keyframe take in the cut plays as a still for its shot's duration. A video take plays for its shot's duration too, from `in`, unless the clip sets `out` (a model's shortest clip is often longer than the shot); a take that is shorter than its shot plays whole. Engines use the cut for previews and export. An episode lists its music and SFX cues under `cues`: each cue (`e02/cue/<slug>`) has a `kind` (`music` or `sfx`), a `description` and a `duration`, and a cue take (`e02/cue/theme/a1`) is one render of it. The audio list places music and SFX takes over the cut, with a start time, a volume and optional ducking under dialogue. A scene or shot MAY name its cues in `audio` (`sfx`, `music`); each MUST be a cue of its episode. A more complex edit exports to OpenTimelineIO. The editing UI is out of scope for this spec.

**Subtitles.** An engine that exports subtitles builds them from shot dialogue: each line of a clip gets an equal share of the clip's time, in order. **Exports** go to `exports/<episode>/`. They are derived output, so engines do not add them to the lock file. **Previs** (an e-conte sheet, an animatic) goes to `previs/<episode>/`, also derived output.

**Episode overrides.** An episode MAY set only these fields: `defaults` (aspect, fps, resolution), `forms` and `outfits` (defaults per character for the whole episode), and `style` (changes to the show style, for example a flashback palette). All other fields belong to scenes and shots.

**Scene with one shot** (`episodes/e02/scenes/s03.yaml`)

```yaml
id: e02/s03
heading: INT. LAMP ROOM - NIGHT
location: loc/lighthouse
variant: night
characters: [char/mira]
forms: { char/mira: winter }
outfits: { char/mira: night }
mood: tense, quiet
script: |
  Mira lifts the floorboard. A brass key, wrapped in cloth.
  MIRA: You kept the key?
shots:
  - id: e02/s03/sh014
    duration: 4s
    description: Mira looks up from the key toward the door.
    camera: { framing: close_up, angle: eye_level, lens: 50mm, move: push_in }
    blocking:
      char/mira: kneeling by the open floorboard, key in right hand
    dialogue:
      - { speaker: char/mira, line: "You kept the key?", delivery: whisper }
    props: [prop/brass-key]
    control:
      first_frame: keyframe      # animate from the selected keyframe
    select: { keyframe: kf3, video: v2 }
```

**Shot fields**

| Field | Required | Values and notes |
| --- | --- | --- |
| `id` | Yes | See IDs |
| `duration` | Yes | Seconds (`4s`) or seconds+frames (`3+12`). See Durations |
| `description` | Yes | What happens, in plain words |
| `camera.framing` | Yes | `extreme_wide`, `wide`, `medium`, `medium_close`, `close_up`, `extreme_close_up`, `insert` |
| `camera.angle` | No | `eye_level`, `low`, `high`, `overhead`, `dutch` |
| `camera.lens` | No | MUST be in `style.lenses` |
| `camera.template` | No | A camerawork template of the bible (`cam/<slug>`). It fills the camera fields that no level states |
| `camera.move` | No | `static`, `pan`, `tilt`, `push_in`, `pull_out`, `dolly`, `truck`, `crane`, `orbit`, `handheld`, `shake` |
| `camera.amount` | No | How far the move goes. Push and pull: the part of the frame that the move removes (0.35: the end frame is 65% of the start frame). Pan, tilt and truck: travel in frame widths (frame heights for a tilt). Shake: its size as a part of the frame height |
| `camera.ease` | No | Fairing: `none`, `in`, `out`, `in_out` |
| `camera.hold_start`, `camera.hold_end` | No | Durations with no move at the start and at the end |
| `camera.center` | No | The point a push ends on (or a pull starts from): `[x, y]`, 0 to 1 from the top left of the frame |
| `camera.render` | No | `model` (the default): a video model animates the shot. `engine`: a held drawing, and only the frame moves; an engine makes the video from the chosen keyframe with no video model |
| `camera.canvas` | No | The shape of a drawing larger than the frame (`21:9` for a pan, `9:16` for a tilt). The keyframe is drawn in this shape, and a pan, a tilt or a truck moves the frame across it (with no `amount`, from one edge to the other). With no canvas, a move stays in the centre of its keyframe |
| `layout` | No | Pills: the staging plan of the shot. See Layout |
| `characters` | No | Inherited from the scene when absent |
| `forms`, `outfits` | No | Named looks from the bible, per character. Inherited from the scene when absent |
| `blocking` | No | Position and action per character |
| `dialogue` | No | List of `speaker`, `line`, `delivery` |
| `props` | No | Prop IDs |
| `control` | No | Previs inputs: `first_frame`, `last_frame`, `depth`, `pose`, `storyboard` (asset IDs, relative paths or `keyframe`) |
| `audio` | No | `sfx` and `music` cue references |
| `select` | No | The chosen keyframe, video and dialogue audio take |

Direction words (`pan`, `tilt`, `truck`) take a direction where needed: `{ move: pan, direction: left }`.

**Layout.** A `layout` is the staging plan of a shot as pills: flat stand-ins for its characters. It has a `start` list and an optional `end` list (the places when the shot ends, when they move). Each pill has a `slot` (`a`, `b`, `c`: the shot's first, second, third character), and optional `x` (the centre, 0 at frame left to 1 at frame right), `y` (the eye line, 0 at the frame top), `size` (the head height as a part of the frame height; the body is 7 heads tall), and `facing` (`left`, `right`, `camera`, `away`) or `look_at` (another slot). An engine MAY give a shot with no layout one pill per character. A layout is a plan: no take hashes it, and an engine does not send it to a model. A person can save a pill frame as an image and name it in `control.storyboard`; the file then enters the hash as each asset does.

**The 180° line.** In a scene, a shot whose template has `rules.sets_axis` fixes which side each of its characters is on. A later shot of the scene whose layout puts two of them in the other order, or shows one of them alone looking away from the others, crosses the line, and an engine SHOULD warn ("Crosses the 180° line"). A new `sets_axis` shot sets the line again.

**Durations.** A duration is seconds (`4s`, `2.5s`, or a number) or seconds+frames (`3+12`), the notation of animation storyboards and timesheets: whole seconds, a plus sign, then frames from 0 to 23. A frame is always 1/24 s, also in a project with another `fps`, so one value has one meaning: `3+12` is 3.5 s. Seconds alone cannot state most frame counts (10 frames is 0.41666... s). It applies to each duration: a shot's `duration`, `camera.hold_start` and `camera.hold_end`, a cut row's `in` and `out`, an audio row's `start`, a cue's `duration`, and a template's `timing`.

## Layering and overrides

An engine resolves every shot by merging up to six levels, top to bottom. Each file states only what differs from the level above.

1. **Project defaults** (`project.yaml`): aspect, fps, resolution.
2. **Show bible**: style, characters, locations, props, voices, camerawork.
3. **Season**: season-wide overrides, when a season lists the episode.
4. **Episode**: episode-wide overrides.
5. **Scene**: location, variant, cast, forms, outfits, mood.
6. **Shot**: camera, blocking, dialogue, controls.

Takes are outputs of a resolved shot. They never override anything.

**Merge rules**

1. **Scalars:** the lower level replaces the value.
2. **Maps:** deep merge, key by key.
3. **Lists:** the lower level replaces the list. To add or remove items, use `$append` or `$remove`: `characters: { $append: [char/ren] }`.
4. **Bible entries:** a shot MUST NOT redefine a character, location or prop. It selects a named look instead (`forms`, `outfits`, `variant`).
5. **Camerawork:** after the levels merge, the template that `camera.template` names fills only the camera fields that no level states. A stated value always wins. A template is part of the bible level, not a seventh level.
6. **Resolved view:** every engine MUST be able to output the fully merged shot. Validators and `inputs_hash` use this view.

**Dependency tracking**

An engine SHOULD record which bible entries and assets each take used. When one of them changes, the engine reports those takes as `stale` and offers to re-render only them.

**Resolved shot contents**

- The resolved shot includes every bible entry it uses (style, characters, location, props, voices), merged with only the chosen form, outfit and variant.
- When no level chooses a form or an outfit for a character, the one named `default` applies, if the character has one.
- It leaves out fields that do not change the render: `credits`, `license` and `likeness`. An edit to those fields does not make takes stale.
- `camera.template` becomes the template's `id` and its words for the prompts (`keyframe`, `prompt`, `avoid`). The template's other fields (name, intent, notation, family, framing, timing, slots, rules, source) change no render, so they are left out too.
- Each asset reference is replaced by its full asset ID (`asset/<64 hex>`).

**Hash input**

1. Resolve the shot as above.
2. Remove `select` and `layout`. A choice between takes never makes a take stale, and pills are a plan.
3. Keep only the fields that the take kind uses. Remove a map that becomes empty.
   - Keyframe takes leave out `duration`, `dialogue`, `audio`, `control.first_frame`, `control.last_frame`, and the `voice` of each character. Of the camera they keep `framing`, `angle`, `lens`, `canvas` and the template's `keyframe` words, and leave out the rest: `move`, `direction`, `amount`, `ease`, `hold_start`, `hold_end`, `center`, `render`, and the template's `id`, `prompt` and `avoid`.
   - Video takes replace each `keyframe` value in `control` with the `output` of the keyframe take that they used (`inputs.first_frame` or `inputs.last_frame`). A shot with `camera.render: engine` and no `control.first_frame` hashes as if it stated `first_frame: keyframe`, because an engine move animates the chosen keyframe.
   - Audio takes for dialogue keep only `id`, `dialogue`, and the `id` and `voice` of each character that speaks.
   - Audio takes for a cue hash the cue instead of a shot: its `id`, `kind`, `description` and `duration` (in seconds).
4. Normalize values. Durations become seconds as numbers, so `4s` and `4.0s` both become `4`, and `3+12` and `3.5s` both become `3.5`. Engines MUST NOT add values that no file states.
5. Serialize as JSON with RFC 8785 (JSON Canonicalization Scheme).
6. Hash with SHA-256 and store the result as `inputs_hash: sha256:<64 hex>`.

## Takes and provenance

A take is one render: a keyframe (still) or a video for a shot, or audio for a shot's dialogue or an episode's music and SFX cue. Engines write take files, and people approve them. People SHOULD edit only `status` and `notes` by hand.

**Status values**

| Status | Meaning |
| --- | --- |
| `draft` | Rendered, not reviewed |
| `candidate` | Shortlisted |
| `approved` | Accepted for the cut |
| `rejected` | Not to be used |

Staleness is not a status. A take is stale when the hash of its current resolved inputs differs from its stored `inputs_hash`. Engines calculate this each time they read a project and MUST NOT store it.

**Video take** (`takes/e02/s03/sh014/v2.yaml`)

```yaml
id: e02/s03/sh014/v2
kind: video
status: approved
output: asset/9d0c3e
duration: 4.0s
inputs_hash: sha256:51e2...      # resolved shot + every input asset
inputs:
  first_frame: e02/s03/sh014/kf3
  references: [asset/2c1d9f, asset/b4f0d2]
provenance:
  provider: kling
  model: kling-v2.1-pro
  model_version: "2026-09-12"
  seed: 418223
  prompt: "Close-up, 50mm, slow push in. A woman in a wool sweater..."
  negative_prompt: "text, watermark"
  parameters: { cfg: 0.5 }
  created: 2026-11-08T07:41:00Z
  cost: { amount: 0.42, currency: USD }
qa:
  - { check: character_identity, score: 0.91, pass: true }
notes: Good. Slight flicker at 3.5s.
```

- `provenance.provider`, `model`, `created` and `prompt` (when one was sent) are required. `cost` and `qa` are optional.
- A take that no model made, such as an engine move (`camera.render: engine`), records the engine's own name as `provider` and `model` (the reference engine: `local`, `local:ffmpeg:v1`), has no `prompt`, and SHOULD record the move in `parameters`.
- A person MAY keep a stale take on purpose: the engine sets `inputs_hash` to the current hash and records the replaced hash in `kept_from`. The take is fresh until an input changes again.
- Engines MAY keep each take's hash view next to its take file (`takes/<take>.inputs.json`), so they can say which fields changed when the take becomes stale. Readers skip these files.
- The engine computes `inputs_hash` from the fully resolved shot and the hashes of all input assets. When the current hash differs from the stored one, the take is `stale`.
- The same hash, model version and seed SHOULD give the same output on a deterministic backend. The spec does not promise this.
- Engines SHOULD write provenance into exported files as a C2PA manifest.

A video take with sound records `audio_source`: `model` (generated with the video) or `separate`. The cut list chooses which audio plays: the take's own, or a separate dialogue take.

## Assets and licensing

Every binary file is an asset with an ID, a URI, a content hash and a license. Asset IDs come from the content hash, so a changed file is a new asset. An asset ID is asset/ plus the full 64-character SHA-256 hash. The bible entry then points to the new ID, and dependent takes become `stale`.

**Lock file** (`assets/lock.yaml`)

```yaml
asset/2c1d9f:
  uri: r2://tidewatch/bible/characters/mira/sheet.png
  hash: sha256:2c1d9f...
  type: image/png
  source: uploaded            # generated | uploaded | licensed
  license:
    owner: "@creator"
    terms: CC-BY-4.0          # SPDX ID, all-rights-reserved, or a URL
    attribution: "Tidewatch by @creator"
    ai_training: disallowed   # allowed | disallowed
```

- Valid URI schemes: `https`, relative `file` paths, `r2`, `s3`. Engines MAY support more. A relative `uri` in `lock.yaml` is relative to the project folder. Anywhere else, a relative path is relative to the file that holds it.
- Engines MUST verify the hash when they fetch an asset. A relative path such as sheet.png is valid wherever an asset ID is; the engine adds that file to the lock file.
- Every asset MUST have `license.owner` and `license.terms`. When the engine adds an asset to the lock file (a relative path or a generated take), it copies `license` from `project.yaml`.

**Forking a bible**

A project that builds on another show records it in `project.yaml`:

```yaml
upstream:
  show: tidewatch
  version: 1.2.0
  uri: https://example.com/tidewatch/bible
```

- Imported entries keep their original IDs with the show prefix (`tidewatch:char/mira`) and their original license.
- Engines SHOULD warn before export when a fork breaks the upstream `terms`, for example a no-derivatives license.

## Extensions

Backend-specific settings go under `extensions.<namespace>` on any object. Core fields never depend on them.

```yaml
extensions:
  kling: { mode: pro }
  wan: { lora: asset/77ab10, lora_strength: 0.8 }
  x-router: { max_cost_usd: 0.50, prefer: quality }
```

1. A namespace is a lowercase provider or tool name (`kling`, `veo`, `runway`, `wan`, `elevenlabs`). Private or experimental namespaces start with `x-`.
2. Engines MUST ignore namespaces they do not know. They MUST keep them when they rewrite a file.
3. Extensions follow the same merge rules as core fields.
4. An extension MUST NOT change the meaning of a core field. It can only add detail.
5. A namespace that several engines use can move into the core through an RFC.

## Versioning and conformance

The spec uses semantic versioning. Versions 0.x can break compatibility. From v1.0, only a major version can break it.

- `project.yaml` MUST state the spec version in `spec`.
- Each release publishes a JSON Schema per object, a validator CLI and a conformance suite. The suite holds sample projects with their expected resolved output.

**Conformance levels**

| Level | An engine at this level MUST |
| --- | --- |
| Reader | Parse, validate, resolve overrides and keep unknown extensions |
| Renderer | Do all Reader tasks, render keyframe, video and audio takes, and write provenance |
| Full | Do all Renderer tasks, track stale takes, check licenses, play the cut list, and export 16:9 and 9:16 with subtitles |

**Process and licenses**

- Changes go through public RFCs in the spec repository. The core team is the sole maintainer and decides, before and after v1.0.
- Spec text: CC-BY-4.0. Schema, validator and reference CLI: Apache-2.0.

## Decisions

- [x] What is the spec's name and file extension? Decided: Open Lore Format (OLF), as plain YAML with a spec: olf/0.1 field and no .olf extension.
- [x] Default to shots inline in scene files, or one file per shot? Decided: inline by default, split allowed.
- [x] Previs: which 3D format carries control inputs (USD, glTF, or our own camera-path schema)? Decided for v0.1: 2D first. Previs is storyboard frames, pose sketches and simple camera moves (pan, zoom, push) in YAML. 3D formats come later and stay optional.
- [x] Identity: is there a portable character-identity format beyond reference images? Decided: no. The character sheet and reference images are the identity. Model-specific identity (LoRA, embeddings) stays in extensions.
- [x] Sheet crops: name regions of a sheet and point to them (`sheet.png#eyes`)? Decided (2026-11-09): no. The whole sheet is the reference, a character MAY have several sheets, and form views and details are separate files. No automatic region detection.
- [x] Timeline: a minimal edit list (order, trims, cuts) in the spec, or export only? Decided: a minimal cut list in episode.yaml (order, trims, cut or fade). Anything more exports to OpenTimelineIO.
- [x] Audio: how far into music, SFX and mixing should v0.2 go? Decided: audio takes with provenance, plus start times, volume and ducking in the cut list. Full mixing stays out; export stems instead.
- [x] Localization: dubbed dialogue and subtitles per language. Deferred: not in v0.2; revisit later.
- [x] Governance after v1.0. Decided: the core team stays the sole maintainer, with public RFCs.
- [x] Camera templates: resolve them from a library when a shot is read, copy their fields into each shot, or keep them in the bible? Decided (2026-11-10): a template is a bible entry (`cam/<slug>`) that a shot names. A library template is copied into the show's bible on first use. So a project folder resolves by itself, a show tunes a move in one place, and its shots go stale as they do after an outfit edit.
- [x] Durations in frames? Decided (2026-11-10): a duration can be seconds+frames (`3+12`), with a frame of 1/24 s in each project. Seconds cannot state most frame counts.
- [x] Moves with no video model? Decided (2026-11-10): `camera.render: engine` states the intent (a held drawing, only the frame moves). How an engine makes the video is its own choice.
- [x] Staging plans? Decided (2026-11-10): 2D pills in `layout`, on a shot or a template, in no hash. A pill frame reaches a model only as a file in `control.storyboard`.
- [x] Pans across a larger drawing? Decided (2026-11-10): `camera.canvas` states the shape of the drawing, and keyframe takes hash it: a drawing of another shape is a new drawing. Only a shot with a canvas moves across the extra room (2026-11-11): a keyframe of another shape with no canvas keeps the move it had, so the same take inputs give the same engine video.
