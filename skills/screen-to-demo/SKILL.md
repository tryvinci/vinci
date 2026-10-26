# Screen to demo

Clean-room demo DAG: transcribe a rough screen recording, polish the script
(deterministic filler pass), plan zooms/spotlights/callouts, render the
effects, synthesize narration, mux it under the video, burn captions.

## Cost

$0 by construction in every configuration: no API keys, no provider calls.
FFmpeg is the only required tool.

## Speech engines: mock by default, real when local tools are configured

- **Transcription** (`transcribe` op): falls back to a deterministic mock
  transcript. For real local STT, install whisper.cpp and point
  `VINCI_WHISPER` at the `whisper-cli` binary and `VINCI_WHISPER_MODEL` at a
  ggml model file (e.g. `ggml-tiny.bin`, free download). The transcript JSON
  carries an `engine` field: `whisper.cpp` or `mock`.
- **Narration** (`synth_voiceover` op): falls back to a deterministic tone
  track. For real local TTS, install piper and point `VINCI_PIPER` at the
  piper binary and `VINCI_PIPER_MODEL` at a voice `.onnx` file (free
  download). Each script line is synthesized and placed at its timed offset.

Both tools are MIT-licensed, run fully offline after the one-time model
download, and never send media anywhere. A hosted voice (e.g. ElevenLabs,
already a provider package) only enters when a key is set, deliberately
outside this DAG.
