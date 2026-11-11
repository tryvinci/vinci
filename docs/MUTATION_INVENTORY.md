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
| `/olf/sample` | POST | none (copies a show into `$VINCI_HOME/shows`) | no | project files, not journaled |
| `/olf/render` | POST | runtime run + project files | outputs | **409 while the journal is on** (not journaled yet, COREPRODUC-545) |
| `/olf/batch` | POST | runtime runs + project files (one render per job) | outputs | **409 while the journal is on** (not journaled yet, COREPRODUC-545) |
| `/olf/take` | PATCH | project file (take status, notes) | no | user's folder, not journaled |
| `/olf/shot` | PATCH, POST | project file (shot fields; a new inline shot) | no | user's folder, not journaled |
| `/olf/scene`, `/olf/episode` | POST | new scene or episode files, plus the list that names them | no | user's folder, not journaled |
| `/olf/new` | POST | a new show folder in `$VINCI_HOME/shows` (project, bible, character, episode 1) | no | user's folder, not journaled |
| `/olf/script` | POST | new scene files, new location and character files, and `episode.yaml`; in a 2D anime show also the `kuchipaku-hold` template file in the bible | no | user's folder, not journaled |
| `/olf/script/model`, `/olf/draft` | POST | a runtime run (one text-model step) | outputs | **409 while the journal is on** (not journaled yet, COREPRODUC-545) |
| `/olf/cue` | POST | a runtime run (one music or SFX cue), the cue take, `episode.yaml` (`cues`, `audio`) | outputs | **409 while the journal is on** (not journaled yet, COREPRODUC-545) |
| `/olf/sheet`, `/olf/form` | POST | bible image files and the character file | no | user's folder, not journaled |
| `/olf/camerawork` | POST | a camerawork template file in the bible (a copy of a library template) and the shot's `camera`, `duration` and `characters` lines | no | user's folder, not journaled |
| `/olf/previs` | POST | `previs/<episode>/` (the e-conte sheet as PDF and PNG pages, the animatic MP4, and with `mock` the mock render MP4): derived files, not in the lock file | no | user's folder, not journaled |
| `/olf/voice` | POST | the voice entry (`bible/voices/<slug>/<slug>.yaml`) and the character's `voice` | no | user's folder, not journaled |
| `/olf/voice/clone` | POST | an ElevenLabs voice (one voice slot), then the voice entry, its new `sample` file and lock entry, and the character's `voice`; then it removes the replaced sample file and its lock entry | no | user's folder and the ElevenLabs account, not journaled |
| `/olf/keep` | POST | a take file (`inputs_hash`, `kept_from`) and its `.inputs.json` | no | user's folder, not journaled |
| `/olf/select` | PATCH | project file (shot `select`) | no | user's folder, not journaled |
| `/olf/cut` | PATCH | project file (episode `cut` list) | no | user's folder, not journaled |
| `/olf/export` | POST | files in `exports/<episode>/` (MP4s, `.srt`, `.otio`, stems); the first C2PA export makes the local signer in `$VINCI_HOME/c2pa/` | no | derived files in the user's folder, not journaled |

**Coverage in this branch:** all rows above except `/adapt/estimate` and `/agent/plan` (non-durable / read-mostly) and the `/olf/*` rows are wired through `with_journal_ack` when `VINCI_DURABLE_JOURNAL` is `local` or `do`. The `/olf/*` routes write files in the user's show folder, not daemon state; `/olf/render` and `/olf/batch` return 409 while the journal is on (COREPRODUC-545). `/mcp` is journaled at the HTTP boundary only; per-tool side effects are not individually ledgered in v1. The OLF tools (`vinci.olf_*`) write the user's show folder, not daemon state, so they are not in `MUTATING_TOOLS`; `vinci.olf_render` refuses to spend while the journal is on (COREPRODUC-545).

**Authority:** Cloudflare DO SQLite (`VinciHost`) when `VINCI_DURABLE_JOURNAL=do`. Local SQLite journal file when `local` (default for loopback). R2 remains immutable blob CAS only. Timer home snapshots are compaction backup only, not an ack durability boundary.
