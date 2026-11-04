# Vinci

A free, open-source AI video studio that runs on your machine. Generate images, video, voice, and lipsync with models from many providers in one app. You bring your own API keys, see the price before every job, and get a receipt after.

<!-- DEMO GIF: the repo already has docs/assets/studio-tour.gif. If re-recording, show in about 25 seconds: `./scripts/vinci studio` in a terminal, the studio opening at 127.0.0.1:4310, picking the product-reveal-5s template, dropping in a product photo, the cost preview before running, the finished clip, then the receipt in the cost report. Record in demo mode so it costs $0. -->
![Vinci Studio tour](docs/assets/studio-tour.gif)

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](docs/quickstart.md)

If you want one tool instead of five AI subscriptions, please [star the repo](https://github.com/tryvinci/vinci). It helps other people find it.

## Quick start

Needs Python 3.12+, Node 20+, and ffmpeg.

```bash
git clone https://github.com/tryvinci/vinci && cd vinci && python3 -m venv .venv && . .venv/bin/activate && make install && ./scripts/vinci init --demo && ./scripts/vinci studio
```

Open http://127.0.0.1:4310/studio. Demo mode uses practice providers, so it costs nothing and needs no key. Outputs in demo mode are marked as mock. Add real provider keys in **Connect** when you are ready.

## What you can make

- Product photo to a 5-second reveal clip (`product-reveal-5s`)
- Podcast or stream to vertical shorts with captions (`podcast-to-shorts`, `clip-select`, `reframe-9x16`, `captions-burn`, `streamer-split`)
- Connected shot sequences with the same character (`cinema-still`, `cinema-sequence`, `soul-character`, `first-last-frame`)
- Talking photos and lipsync (`still-to-talk`, `talking-photo`, `lipsync`, `emote-animate`)
- Speech and voice cloning (`tts`, `voice-clone`)
- Upscaling stills and clips (`image-upscale`, `still-to-upscale`, `video-upscale`)
- Plain generation (`image-generate`, `video-generate`)

Each one is a skill in `skills/`. A skill is a small workflow graph, so adding your own does not need a plugin SDK.

## Providers

Provider packages in `packages/`: Cloudflare, ElevenLabs, fal, Google, Higgsfield, Magnific, OpenAI, Wavespeed. Keys stay on your machine (`~/.vinci/keys` or the OS keychain). There is no Vinci account in between.

## Cost controls

- Live spend is off until you turn it on with `VINCI_ALLOW_LIVE_SPEND=1`.
- Each live job shows its price before it runs.
- Every generation writes a receipt. The cost report sums them per project.

## Ways to use it

- **Studio**: visual app with templates, shot canvas, timeline, asset library, cost report (`apps/studio`, plus `apps/mac` and `apps/android`).
- **CLI**: `./scripts/vinci run @tryvinci/image-generate` (`apps/cli`).
- **MCP server**: let an AI assistant drive the studio (`packages/mcp`).

Docs: [quickstart](docs/quickstart.md), [first scene](docs/first-film.md), [self-host on Cloudflare](docs/SELF_HOST_CLOUDFLARE.md), [Google Sheets batch](docs/google-sheets.md), [runtime internals](docs/VINCI_OSS_RUNTIME.md).

## Related: Vinci Clips

Only need to cut long videos into shorts? [Vinci Clips](https://github.com/tryvinci/vinci-clips) is a smaller, self-hosted Node app that does just that: transcribe, pick clips, reframe to 9:16, burn captions. It is a separate AGPL codebase and shares no code with this repo.

## Contributing

MIT, contributions welcome. See [CONTRIBUTING.md](CONTRIBUTING.md). Contributions need a DCO sign-off (see `DCO`). Do not copy code from vinci-clips into this repo, see `legal/AGPL_CLEAN_ROOM.md`.

## License

MIT. Generated output is covered by the terms of the provider whose model made it.

---

Useful? A [star](https://github.com/tryvinci/vinci) is the easiest way to help.
