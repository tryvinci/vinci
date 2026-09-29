# Vinci

**Vinci** is the MIT-licensed open-source generative media runtime. Bring your own API keys, use any supported model/provider, and run portable generation/editing/clipping workflows with transparent cost and routing.

The proprietary hosted product is **Vinci Platform**. It is a separate codebase and will consume versioned packages from this repo.

> Cost honesty: Magnific sometimes undercuts direct API prices. Vinci markets **transparency, choice, and a $0 monthly floor**, never "always cheaper."

## Status

Phases 0–3 are in this tree: protocol v0, local CAS+SQLite, daemon `:4310`, cost engine, Wavespeed/Google/fal/ElevenLabs/Cloudflare/Higgsfield/Magnific HTTP plugins from public API docs (live HTTP off unless `VINCI_ALLOW_LIVE_SPEND=1`; MCP is a *custom* provider type, not the only one), first-party skills including image/video generate, still-to-4K, cinema-still canvas graphs, clips DAG, `vinci find`, Studio with Explore/templates/canvas, Higgsfield-style model cards, and BYOK key paste, Mac and Android WebView shells, skill registry, timeline, and authored `vinci.*` MCP.

This repository is **private** until a human opens it. Do not publish to npm or PyPI yet. npm `vinci` and PyPI `vinci` are taken — packages use `@tryvinci/*` and `vinci-core` / `vinci-runtime` / `vinci-media` / `vinci-harness` / `vinci-provider-*`. See `NAMESPACE.md`.

Until `tryvinci/vinci` exists, this tree ships at `apps/vinci-oss/` in `tryvinci/vinci-monorepo` (not turbo/npm workspaces). Clone the monorepo, `cd apps/vinci-oss`, then the same gates. Extract later without changing the architecture. Monorepo link plan: `docs/VINCI_OSS_PUBLIC_LINK.md` at repo root.

## Quick start (demo, no provider spend)

`@tryvinci/cli` is unpublished. From a clone, use the repo wrapper (it builds the CLI on first use and prefers `.venv` so the daemon spawn works). Needs Python 3.12+, Node 20+, and `ffmpeg`/`ffprobe` on PATH (`make test` runs media fixtures):

```bash
sudo apt-get install -y ffmpeg   # or brew install ffmpeg
python3 -m venv .venv && source .venv/bin/activate
make install
make test && make conformance && make lint
./scripts/vinci init --demo
./scripts/vinci studio
```

Studio opens at `http://127.0.0.1:4310/studio`. Paste any supported provider key under **Keys**, or stay on mock at $0. Live HTTP stays off until `VINCI_ALLOW_LIVE_SPEND=1`.

`make demo` runs `python -m vinci_harness demo` (in-process skill + $0 receipt) then `./scripts/vinci init --demo` and `./scripts/vinci run @tryvinci/image-generate`. The CLI starts `vinci-daemon` on `:4310` if it is not already up.

Mac / Android: `apps/mac` and `apps/android` wrap the same `/studio` page. For a phone on the LAN: `./scripts/vinci studio --lan`.

`make clone-smoke` git-archives this subtree (`HEAD:apps/vinci-oss/` in the monorepo) into a temp dir and proves the stranger path at `$0`: harness demo, `vinci init --demo`, CLI image+video (64×64 PNG + playable MP4), receipt fetch, `POST /runs`, MCP `vinci.image_generate` + `vinci.video_generate`, fixture `podcast-to-shorts` (5 jobs), two `vinci skills add` installs, HTML Studio `/studio`, `vinci find pricing`, and loopback `vinci providers add mcp` → `mcp:png:v1` + `mcp:mp4:v1`. Monorepo CI is `.github/workflows/vinci-oss.yml`. Do not set `VINCI_ALLOW_LIVE_SPEND`.

`make github` creates or pushes the private `tryvinci/vinci` repo (`scripts/create-github-repo.sh`, refuses `--public`). Org create is a human gate if this token 403s.

Equivalent by hand:

```bash
python3 -m vinci_daemon --host 127.0.0.1 --port 4310
./scripts/vinci init --demo
./scripts/vinci run @tryvinci/image-generate --input '{"prompt":"a red cube"}'
```

Do not `npx @tryvinci/cli` from the npm registry until a human publishes.

## Layout

See `docs/VINCI_OSS_RUNTIME.md`. Python owns protocol/core/runtime/providers/media/index/MCP. TypeScript owns CLI and Studio talking to the daemon over HTTP.

Config lives in `~/.vinci/` (config.toml, `keys/` at mode 0600, sqlite, cas/). Asset URIs: `vinci://assets/{id}`, `vinci://jobs/{id}`, `vinci://receipts/{id}`.

## License

MIT. `vinci-clips` is AGPL and **must not** enter this tree. See `legal/AGPL_CLEAN_ROOM.md`.
