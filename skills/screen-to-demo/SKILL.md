# Screen to demo

Clean-room demo DAG: transcribe a rough screen recording, polish the script
(deterministic filler pass), plan zooms/spotlights/callouts, render the
effects, synthesize narration, mux it under the video, burn captions.

## Cost

$0 by construction in every configuration: no API keys, no provider calls.
FFmpeg is the only required tool.

## Speech engines: mock by default, real when local tools are configured

- **Transcription** (`transcribe` op): falls back to a deterministic mock
  transcript. For real local STT, install whisper.cpp
  ([ggml-org/whisper.cpp](https://github.com/ggml-org/whisper.cpp), MIT) and
  point `VINCI_WHISPER` at the `whisper-cli` binary and
  `VINCI_WHISPER_MODEL` at a ggml model file (e.g. `ggml-tiny.bin`, free
  download). The transcript JSON carries an `engine` field: `whisper.cpp`
  or `mock`.
- **Narration** (`synth_voiceover` op): falls back to a deterministic tone
  track. For real local TTS, install piper from
  [rhasspy/piper](https://github.com/rhasspy/piper) (MIT; archived at
  v1.2.0, prebuilt binaries on its releases page) and point `VINCI_PIPER`
  at the piper binary and `VINCI_PIPER_MODEL` at a voice `.onnx` file from
  [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices).
  Each script line is synthesized and placed at its timed offset. Do not
  substitute the actively maintained continuation
  [OHF-Voice/piper1-gpl](https://github.com/OHF-Voice/piper1-gpl): it is
  GPL-3.0, which carries different redistribution obligations than MIT and
  would need legal review before use, so it is excluded from this skill's
  scope.

The pinned tools above are MIT-licensed, run fully offline after the
one-time model download, and never send media anywhere. Voice models are
licensed per voice, not per repo: the piper-voices dataset card's MIT tag
does not cover individual voices, and each voice's `MODEL_CARD` names its
own training-data provenance and license (observed range: research-only
agreements, CC BY-NC-SA, CC BY). Local testing with any voice is fine, but
recommending a default voice or bundling one with Vinci artifacts requires
checking that voice's model card first. A hosted voice (e.g. ElevenLabs,
already a provider package) only enters when a key is set, deliberately
outside this DAG.
