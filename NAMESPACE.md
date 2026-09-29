# Namespace notes

Verified 2026-08-27. **Do not publish to npm or PyPI until a human says so.**
**Do not announce publicly.** This repository stays private until a human opens it.

## npm

| Name | Status | Vinci use |
| --- | --- | --- |
| `vinci` | Taken (dormant canvas library, last publish 2022) | Do not publish this name. |
| `@tryvinci` scope | Free (no packages published as of check) | All JS/TS packages: `@tryvinci/cli`, `@tryvinci/protocol`, `@tryvinci/studio`. |
| CLI bin `vinci` | Set by `@tryvinci/cli` `bin` field | Bin names do not collide on npm unless a user also globally installs the old `vinci` package. Acceptable. |

Claiming `@tryvinci` by publishing a placeholder is deferred until a human authorizes publish.

## PyPI

| Name | Status | Vinci use |
| --- | --- | --- |
| `vinci` | Taken (abandoned 2015-era package) | Do not publish this name. |
| `vinci-core` | Free | Core config, credentials, catalog, cost engine |
| `vinci-runtime` | Free | Scheduler / agent loop |
| `vinci-media` | Free | FFmpeg ops |
| `vinci-harness` | Free | Meta-install (core+runtime+providers+MCP). Unpublished; `packages/harness`. |
| `vinci-protocol` | Use this suffix | JSON schemas + Pydantic types |
| `vinci-storage` | Use this suffix | Local CAS + adapters |
| `vinci-provider-sdk` | Use this suffix | Plugin ABC + conformance |
| `vinci-provider-*` | Suffix pattern | google, wavespeed, fal, elevenlabs, cloudflare, higgsfield, magnific, mock |

The pip meta-install will be `pip install vinci-harness` when a human publishes. Until then docs lead with `./scripts/vinci` and `python -m vinci_harness demo`, not the unpublished npm registry package.

## GitHub

| Name | Status |
| --- | --- |
| `tryvinci` org | Ours |
| `tryvinci/vinci` | Target. **Not created yet** — org repo create 403s for Cursor App / PAT. Local `main` is ready to `git push` once a human creates the empty private repo. Keep **private** until a human opens it. |

## Trademark

"Vinci" is a crowded mark (Vinci SA construction, DaVinci Resolve adjacency). We already trade as Vinci, so risk posture is unchanged, but a formal USPTO/EUIPO clearance pass for the "generative media software" class is required **before** any public launch announcement. Flag, do not block engineering.

Worst case: org/repo stay; marketing wording adjusts.

## Docs language

| Thing | Name |
| --- | --- |
| OSS runtime | **Vinci** |
| Proprietary hosted product | **Vinci Platform** (never "Vinci Cloud") |
| This repo's sibling proprietary monorepo | Vinci Platform monorepo (internal) |
