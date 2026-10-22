# Vinci

**The open-source generative media runtime.** Bring your own keys, pick any provider, and run real image, video, upscale, and clipping workflows - with a receipt for every dollar.

![Vinci Studio tour](docs/assets/studio-tour.gif)

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](docs/quickstart.md)
[![Self-host on Cloudflare](https://img.shields.io/badge/self--host-Cloudflare-orange.svg)](docs/SELF_HOST_CLOUDFLARE.md)

Runs at **$0** in mock mode. Live spend stays off until you set `VINCI_ALLOW_LIVE_SPEND=1`.

## Why Vinci

- **Any provider, one runtime.** Wavespeed, Google, fal, ElevenLabs, Cloudflare, Higgsfield, Magnific - swap models without rewriting your workflow. MCP is one provider type, not the only one.
- **Cost transparency.** Every run writes a receipt (`vinci://receipts/{id}`) and the daemon prices a job before you fire it. No black-box billing.
- **Workflows, not demos.** Canvas shot graphs with camera/lens/look controls, clips DAG, batch generation from a Google Sheet, installable skills, `vinci find` across your assets.
- **$0 monthly floor.** The full Studio UI, mock providers, and the demo path run with no keys and no spend. Pay only when you point it at a live model.

> Cost honesty: some providers (e.g. Magnific) sometimes undercut direct API prices. Vinci promises transparency, choice, and a $0 floor - not "always cheapest."

## Quickstart (5 minutes, $0)

Needs Python 3.12+, Node 20+, and `ffmpeg`/`ffprobe` on PATH.

```bash
python3 -m venv .venv && source .venv/bin/activate
make install
./scripts/vinci init --demo
./scripts/vinci studio
```

Studio opens at `http://127.0.0.1:4310/studio`. Stay on mock providers at $0, or paste a provider key under **Connect**. Higgsfield and Magnific also work over OAuth - no API key needed.

`make demo` runs an end-to-end image + video generation at $0 and prints the receipts.

**Self-host on your own Cloudflare account:** see [`docs/SELF_HOST_CLOUDFLARE.md`](docs/SELF_HOST_CLOUDFLARE.md).

## What you get

- **Studio** - web UI (also wrapped by Mac and Android shells): Explore templates, Cinema Stack canvas, timeline, library, cost report.
- **CLI + daemon** - `./scripts/vinci run @tryvinci/image-generate`, `POST /runs`, [`vinci sheets sync`](docs/google-sheets.md) for batch work.
- **MCP** - authored `vinci.*` tools (`vinci.image_generate`, `vinci.video_generate`, ...) for agent clients.
- **Providers** - HTTP plugins built from public API docs; add your own over MCP.
- **Skills** - portable, installable workflow graphs (`vinci skills add`).

Architecture: Python owns protocol/core/runtime/providers/media/MCP; TypeScript owns the CLI and Studio. Details in [`docs/VINCI_OSS_RUNTIME.md`](docs/VINCI_OSS_RUNTIME.md) and [`docs/quickstart.md`](docs/quickstart.md).

## Package names

npm `vinci` and PyPI `vinci` are taken, so packages publish as `@tryvinci/*` and `vinci-core` / `vinci-runtime` / `vinci-media` / `vinci-harness` / `vinci-provider-*`. Nothing is published to npm or PyPI yet - run from a clone. See `NAMESPACE.md`.

The proprietary hosted product, **Vinci Platform**, is a separate codebase and consumes versioned packages from this repo. Canonical source tree: `apps/vinci-oss/` in `tryvinci/vinci-monorepo`, split-synced here.

## Contributing

MIT-licensed, contributions welcome. See `CONTRIBUTING.md`. `vinci-clips` is AGPL and **must not** enter this tree - see `legal/AGPL_CLEAN_ROOM.md`.

## License

MIT
