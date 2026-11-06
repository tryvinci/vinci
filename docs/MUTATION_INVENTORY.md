# Acknowledged mutation inventory (Vinci OSS daemon)

Paths that change durable application state or accept work that must survive abrupt container kill when `VINCI_DURABLE_JOURNAL` is enabled. Read-only and streaming endpoints are excluded.

| Path | Method | Durable intent | Blob-before-DO | Notes |
|------|--------|----------------|----------------|-------|
| `/init` | POST | home bootstrap | optional | demo seed |
| `/settings` | PATCH | settings record | no | preference, caps, gsheet refs |
| `/runs` | POST | run acceptance | outputs later | job intent + operation id |
| `/runs/{id}/approve` | POST | run state | no | spend gate |
| `/runs/{id}/cancel` | POST | run state | no | |
| `/assets` | POST | asset metadata | **yes** (CAS/R2) | upload |
| `/skills/install` | POST | skill install | optional | filesystem |
| `/workflows/import/comfy` | POST | workflow + optional run | optional | |
| `/adapt/estimate` | POST | estimate only | no | read-mostly |
| `/adapt/run` | POST | adapt job | outputs | provider spend gated |
| `/presets` | POST | preset config | no | |
| `/presets/{id}` | DELETE | preset config | no | |
| `/adapts/batch` | POST | batch job | outputs | |
| `/integrations/gsheet/sync` | POST | sheet sync rows | optional | external API |
| `/providers` | POST | provider secret config | no | secrets at rest in home |
| `/providers/{name}` | DELETE | provider config | no | |
| `/providers/{name}/oauth` | POST | oauth state | no | |
| `/providers/{name}/disconnect` | POST | drop oauth tokens | no | provider URL stays |
| `/providers/oauth/callback` | GET | oauth tokens at rest | no | code is not stored in the journal payload |
| `/agent/plan` | POST | plan artifact | no | ephemeral unless persisted |
| `/collab/sessions` | POST | collab session | no | |
| `/collab/sessions/{sid}` | PUT | canvas snapshot | optional | |
| `/catalog/refresh` | POST | catalog cache | no | |
| `/mcp` | POST | tool side effects | per tool | not fully journaled in v1 |

**Coverage in this branch:** all rows above except `/adapt/estimate` and `/agent/plan` (non-durable / read-mostly) are wired through `with_journal_ack` when `VINCI_DURABLE_JOURNAL` is `local` or `do`. `/mcp` is journaled at the HTTP boundary only; per-tool side effects are not individually ledgered in v1.

**Authority:** Cloudflare DO SQLite (`VinciHost`) when `VINCI_DURABLE_JOURNAL=do`. Local SQLite journal file when `local` (default for loopback). R2 remains immutable blob CAS only. Timer home snapshots are compaction backup only, not an ack durability boundary.
