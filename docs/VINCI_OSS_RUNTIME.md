# Vinci OSS Runtime

> **Vinci** — the open-source generative media runtime. Bring your own API keys, use any supported model/provider, and run portable generation/editing/clipping workflows with transparent cost and routing.

This file is the architecture contract. Do not invent a second architecture.
Executable gates live in `VINCI_OSS_E2E_ACHIEVEMENT.md`.

**Meeting anchor:** Aug 26 L'Oreal/Shiva sync — Engram/Vinci as open-source workflow layer; users bring Google/etc. API keys; Magnific/Higgsfield compete on workflow, not unique models. Cost transparency is the wedge.

## 1. Brand & naming

| Thing | Name |
| --- | --- |
| OSS runtime | **Vinci** |
| Proprietary hosted product | **Vinci Platform** (never "Vinci Cloud") |
| GitHub | `tryvinci/vinci` (until that repo exists: `apps/vinci-oss/` in `tryvinci/vinci-monorepo`) |
| CLI binary | `vinci` |
| JS/TS | `@tryvinci/*` |
| Python | `vinci-core`, `vinci-runtime`, `vinci-media`, `vinci-harness`, `vinci-provider-*` |
| MCP | `vinci` (tools `vinci.*`) |
| Asset URI | `vinci://assets/{id}`, `vinci://jobs/{id}`, `vinci://receipts/{id}` |
| Config | `~/.vinci/` |

License: **MIT**. `vinci-clips` is AGPL-3.0 — capabilities are clean-room reimplemented as MIT skills. No AGPL code enters this repo. See `NAMESPACE.md` and `legal/AGPL_CLEAN_ROOM.md`.

## 2. System shape

CLI + Studio → Daemon (HTTP + worker + MCP) → Runtime → Plugins + Cost engine + Media + local CAS/SQLite.

Language split: Python for protocol/core/runtime/providers/media/index/MCP; TypeScript for CLI + Studio.

Local-first defaults: SQLite + CAS under `~/.vinci/cas/`. No Mongo/Redis/Docker/account for the default path.

Proprietary never lands here: Clerk, Dodo/credits, Mongo user ledgers, hosted vault, marketing pages, enterprise moderation ops.

## 3. Protocol

`vinci-protocol` ships JSON Schemas + Pydantic/TypeScript types: Asset, ModelSpec, Job, WorkflowSpec, Receipt, Event, Timeline (Phase 3), error taxonomy (`auth`, `quota`, `rate_limit`, `invalid_input`, `content_policy`, `provider_down`, `timeout`, `cancelled`, `unknown`).

Job states: `created → awaiting_approval → queued → running → completed | failed | cancelled`.

`protocol_version` handshake. Current: `0.1.0`.

## 4. Provider plugin SDK

`Provider` ABC: `catalog`, `capabilities`, `estimate`, `submit`, `status`, `cancel`, `normalize_error`.

Conformance: schema round-trips, estimate-before-submit, error normalization, idempotent status polling, secret-free logging. A plugin is not listed until it passes.

Credential resolution: providers declare secret **names**; `vinci-core` resolves keychain → `$VINCI_HOME/keys/` (mode 0600) → env → config refs. Studio can paste a key; the raw value never lands in git, jobs, receipts, or logs.

MVP providers: Wavespeed, Google, fal, ElevenLabs, Cloudflare, **Higgsfield**, **Magnific / Freepik**. Mock ships in the SDK. Higgsfield auth is key **and** secret (`Authorization: Key id:secret`). Magnific auth is `x-magnific-api-key`. Catalogs are curated allowlists from public API docs (Higgsfield OpenAPI, Magnific `llms.txt` / changelog, fal app IDs) — not the full vendor gallery, and **not MCP-only**. **MCP is a custom provider type**, not the only extension — paste a URL when you want an external MCP backend (including a vendor MCP such as Magnific MCP).

Catalog: curated versioned allowlist JSON; `vinci catalog refresh` produces a reviewable diff, never a silent live mutation. **Sora is excluded** from the default catalog (API sunsets 2026-09-24).

## 5. Cost engine

Pre-run estimate, budgets/approvals, immutable receipts, cheapest-compatible routing, pricing snapshots, CAS/idempotency replay at $0, skill cost metadata.

Honesty: Magnific sometimes undercuts direct API. Market transparency, choice, $0 monthly floor — never "always cheaper."

## 6. Skills

Each skill: `SKILL.md` + `vinci.yaml` + `workflow.yaml`. First-party launch set is listed in the original contract (image-generate, video-generate, product-reveal-5s in Phase 1; remaining in Phase 2).

## 7. Daemon / CLI / Studio / MCP

Daemon FastAPI: `/runs`, `/jobs`, `/events`, `/assets`, `/models`, `/skills`, `/templates`, `/cost/report`, `/providers`, `POST /providers/{name}/oauth`, `GET /providers/oauth/callback`, `/agent/plan`, `/collab/sessions`, `/settings`, `/healthz`, Studio at `/studio`, MCP at `/mcp`. MCP servers that publish OAuth discovery and a registration endpoint sign in with PKCE; Higgsfield and Magnific are presets. Credit-priced models stay out of cheapest USD routing unless a run pins them. Named MCP ids are `mcp_<slug>` beside Custom MCP. Studio compose chips pass `aspect_ratio`, `duration`, `resolution`, first/last frames, cinema optical (`camera`, `lens`, `look`, `lighting`, `palette`, `motion`), and local Elements stills as `image_urls` into `/runs` inputs. Mock honors aspect (default 16:9 960×540) and clip duration. `@tryvinci/studio` (Next, `:4311`) is the TypeScript Studio (Mac/Android/CLI default); `/studio` remains the HTML fallback. Supercomputer plans a brief onto templates; 3D orbits the last still; Collab snapshots graph/cast JSON under `$VINCI_HOME/collab`.

CLI: `init`, `doctor`, `providers`, `models`, `run`, `jobs`, `skills`, `cost`, `catalog refresh`, `find` (Phase 2), `studio` (Phase 2; `--lan` for phone/Mac shells), `mcp print-config`.

Authored MCP tools: `vinci.models_list`, `vinci.skills_search`, `vinci.image_generate`, `vinci.video_generate`, `vinci.media_inspect`, `vinci.workflow_run`, `vinci.jobs_get`, `vinci.jobs_cancel`, `vinci.cost_estimate`.

## 8. Phased delivery

Phase 0–3 as in `VINCI_OSS_E2E_ACHIEVEMENT.md`. Extraction seams from Vinci Platform are **semantics, not file dumps**: capability router, image plugins, storage adapters, catalog decisions. `vinci_ai_service` is split, not ported.

## 9. Quality

CI: ruff+mypy / tsc; protocol schema round-trips; provider conformance against fixtures (no live keys); skill validation; secret-scan; proprietary/AGPL scan; mock provider for offline tests.

## 10. Visual language

Studio matches **tryvinci.com** (apps/vinci-landing editorial cream), not a zinc IDE:

- Cream page `hsl(43, 28%, 97%)`, ink `hsl(200, 14%, 22%)`, teal `hsl(177, 59%, 50%)` as accent only
- UI: Inter Tight. Instrument Serif italic only on emphasis words, not every title
- Product chrome: top bar, icon rail, content, inspector — same hierarchy as the hosted frontend
- Compose tools (Image, Video, Upscale, Speak): one job per screen. Empty state is a centered offer (eyebrow, title, one-line, dark-ink CTA). Results fill the stage. Model cards stay behind “Choose a model”.
- Primary actions: dark ink pills, white text. Teal is logo, rail-on, eyebrows, status
- Eyebrows: uppercase, `letter-spacing: 0.15em`

Canonical CSS: `apps/studio/app/globals.css`. HTML `/studio` keeps the same tokens.

## 11. Onboarding

First-run overlay (`vinci-onboard-v1` in localStorage): Welcome → Start generating or Connect → Make a still. Skip for now dismisses. Hosted Studio uses `vinci-hosted-onboard-v1` and points at credits / Image Studio instead of BYOK.

## 12. Hosted Platform = this Studio + managed backend

| | OSS | Vinci Platform (`/studio`) |
| --- | --- | --- |
| UI | TypeScript Studio (`:4311`) + HTML `/studio` | **Same Studio chrome** (`apps/vinci-frontend/app/studio`) |
| Auth | None | Clerk |
| Spend | BYOK, local receipts | Dodo subscription + credit ledger |
| Models | Whatever the user connects (Wavespeed, Higgsfield, Magnific, mock, MCP) | **Defined Wavespeed models** via `vinci-backend` (platform key, allowlist) |

Do not copy Clerk, Dodo, or Mongo into this tree. Hosted does not paste keys. Hosted swaps the API base; it does not fork a second design system. Remaining work: speak the daemon `/runs` contract from vinci-backend so compose runs that Wavespeed allowlist instead of routing out to Image Studio / Video Gen.
