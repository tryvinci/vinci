# AGPL clean-room memo — `vinci-clips` boundary

Status: engineering memo (not legal advice). Gate before Phase 2 clips skills.
Date: 2026-08-27
Related: SID-82, `docs/VINCI_OSS_RUNTIME.md` §1 and §15.

## Facts

- `tryvinci/vinci-clips` is licensed **AGPL-3.0**.
- `tryvinci/vinci` (this repository) is licensed **MIT**.
- AGPL copyleft would infect this tree if AGPL source, patches, or derived code land here.
- The product need is behavioral: transcribe → select clips → reframe 9:16 → burn captions → split for streamers. Those behaviors are reimplementable from public product descriptions without reading AGPL source.

## Rule (non-negotiable)

**No AGPL code, comments, assets, tests, or docs from `vinci-clips` enter this repository.**

Contributors and agents:

1. Do **not** clone, open, copy, or vendor `tryvinci/vinci-clips`.
2. Do **not** paste snippets, prompts, or configs from that repo.
3. Implement clips skills from the **behavior list** below, using MIT/BSD libraries (FFmpeg, sqlite, local transcribe adapters).
4. If you have previously read `vinci-clips` source, do not author the MIT reimplementation. A different person (clean-room) writes it from this memo.

## Behavior spec (clean-room inputs)

These are product behaviors, not an API dump:

| Skill id | Observable behavior |
| --- | --- |
| `podcast-to-shorts` | Take a long audio/video file. Produce several short vertical clips with captions. |
| `clip-select` | From a transcript + source media, choose highlight windows (start/end seconds). |
| `reframe-9x16` | Crop/reframe a clip to 9:16 using FFmpeg. |
| `captions-burn` | Burn subtitles onto a clip using FFmpeg (`subtitles`/`drawtext` filter). |
| `streamer-split` | Split a long recording into smaller files on silence or fixed windows. |

Implementation constraints:

- Media ops go through `vinci-media` (FFmpeg). No subprocess flags copied from AGPL code.
- Transcripts come from a provider capability `transcribe` or a local fixture in tests.
- Tests use committed fixtures, never live media from the AGPL repo.

## Review checklist (Phase 2 gate)

- [ ] `rg -i 'agpl|vinci-clips|copyleft' ` on this tree shows only this memo and NAMESPACE/docs references.
- [ ] No files whose origin is `tryvinci/vinci-clips`.
- [ ] Clips skills have original `SKILL.md` / `workflow.yaml` authored here.
- [ ] Human legal review of this memo before public launch (not required to start Phase 0/1).

## Trademark

See `NAMESPACE.md`. Clearance is a public-launch gate, not a Phase 0 engineering gate.
