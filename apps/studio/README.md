# @tryvinci/studio

TypeScript Studio for the local Vinci daemon. Canvas, templates, cinema stack, Keys (BYOK), and timeline live here. The daemon HTML at `/studio` is the Mac/Android WebView shell.

- Next.js app: `npm run dev --workspace @tryvinci/studio` on port `4311`
- API proxy: `/vinci-api/:path*` → daemon (runtime route handler; set `VINCI_DAEMON_URL` + `VINCI_BRIDGE_TOKEN` for Mac bundle). Dev may set `VINCI_STUDIO_USE_REWRITE=1` to use Next rewrites instead.
- Daemon page: `http://127.0.0.1:4310/studio`
- `./scripts/vinci studio` starts the daemon and opens `/studio`
- Local models run without a pasted key. Live HTTP needs a provider key **and** `VINCI_ALLOW_LIVE_SPEND=1`.
