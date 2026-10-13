# Quickstart

Needs Python 3.12+, Node 20+, and `ffmpeg`/`ffprobe` (`sudo apt-get install -y ffmpeg` or `brew install ffmpeg`).

```bash
python3 -m venv .venv && source .venv/bin/activate
make install
make test && make conformance && make lint
```

## Studio (frontend)

`@tryvinci/cli` is unpublished — use the repo wrapper, not the npm registry:

```bash
./scripts/vinci init --demo
./scripts/vinci studio
```

That starts `vinci-daemon` on `:4310` and TypeScript Studio on `:4311` (HTML `/studio` is the fallback). No account. Mock generations stay $0. Pass `--html` to skip Next.

Bring your own key: in Studio, **Connect**, paste a Wavespeed / Google / fal / ElevenLabs / Cloudflare / MCP secret (or an env var name). Named MCP (`mcp_<slug>`) takes a URL plus an optional bearer. Higgsfield and Magnific also offer **Sign in**, which runs OAuth against their MCP servers and stores tokens under `~/.vinci/keys` (mode 0600) or the OS keychain. Live HTTP stays off until `VINCI_ALLOW_LIVE_SPEND=1`. Supercomputer, 3D, and Collab are first-party Studio pages on the same daemon.

Phone or another Mac: `./scripts/vinci studio --lan` then load the printed LAN TypeScript URL (`:4311`) in `apps/android` or `apps/mac`. HTML `/studio` is the fallback.

Or `make demo` / `python3 -m vinci_harness demo`. `make clone-smoke` is the archived-tree proof (CLI + `POST /runs` + MCP image/video + `podcast-to-shorts` + skill installs + Studio + `find` + loopback MCP provider `mcp:png:v1`/`mcp:mp4:v1` at `$0`).

Same skill via HTTP and MCP:

```bash
curl -sS -X POST http://127.0.0.1:4310/runs \
  -H 'content-type: application/json' \
  -d '{"skill":"@tryvinci/image-generate","inputs":{"prompt":"a red cube"}}'

curl -sS -X POST http://127.0.0.1:4310/mcp \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"vinci.image_generate","arguments":{"prompt":"a red cube","max_cost":1}}}'
```

No hosted tenancy, no credits ledger. Live provider HTTP stays off unless `VINCI_ALLOW_LIVE_SPEND=1`.

CLI equivalent: `vinci providers add wavespeed --from-file /path/to/key` or `--from-env WAVESPEED_API_KEY` stores a ref, never a raw key in git. Magnific sometimes undercuts direct API prices — Vinci markets transparency, choice, and a $0 monthly floor, never "always cheaper."
