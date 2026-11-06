# Voice model license evidence (screen-to-demo local TTS)

Preserved 2026-10-26 before any future bundling decision. These are
verbatim upstream statements with source URLs, not legal conclusions.
A dataset-level license tag (including the piper-voices repo's MIT card)
does not establish the license of any individual trained voice model;
each voice carries its own MODEL_CARD with training-data provenance, and
a dataset's license statement alone is not a trained-weights license.
Recheck at the source before bundling or recommending any voice.

## en_US-ljspeech-medium (currently used for local verification)

MODEL_CARD, verbatim
(https://huggingface.co/rhasspy/piper-voices/raw/main/en/en_US/ljspeech/medium/MODEL_CARD):

    # Model card for ljspeech (medium)

    * Language: en_US (English, United States)
    * Speakers: 1
    * Quality: medium
    * Samplerate: 22,050Hz

    ## Dataset

    * URL: https://keithito.com/LJ-Speech-Dataset/
    * License: public domain

    ## Training

    See: https://brycebeattie.com/files/tts/

Dataset page (https://keithito.com/LJ-Speech-Dataset/) states verbatim:
"License  Public Domain" (page section "Latest Version 1.1").
Attribution required by the stated license: none.

## Voices checked and NOT cleared for bundling

- en_US-lessac-medium: MODEL_CARD names the Blizzard 2013 dataset,
  whose license page (cstr.ed.ac.uk/projects/blizzard/2013/lessac_blizzard2013/license.html)
  is a per-named-organization, manually verified research license
  agreement. Not used further; earlier local test outputs with this
  voice must not be redistributed.
- en_US-hfc_female-medium: MODEL_CARD names CC BY-NC-SA 4.0
  (non-commercial).
- en_US-amy-medium: MODEL_CARD says "License: See URL" (unresolved).
- en_GB-alba-medium and en_GB-vctk-medium: MODEL_CARD names CC BY 4.0
  (attribution required if ever used for artifacts).
