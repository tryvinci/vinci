# Self-host Vinci OSS on Cloudflare

Run the **current** Vinci OSS daemon (Python FastAPI + HTML Studio) on **your** Cloudflare account as a **single-tenant** instance. This is deployment packaging, not Vinci Platform SaaS.

## What runs where

| Surface | Role |
|--------|------|
| **Worker** (`deploy/cloudflare`) | Owner auth (`/_auth/login`), cheap `/healthz` (no container), `/readyz` (auth + container) |
| **Container** | `vinci-selfhost` — full OSS runtime, R2 CAS + fenced home snapshots |
| **Studio** | HTML `/studio` (daemon). Next `:4311` is optional for **local** dev only |

Local `~/.vinci` / `./scripts/vinci` unchanged when self-host env vars are unset.

## Prerequisites

- [Workers Paid](https://developers.cloudflare.com/workers/platform/pricing/) (Containers billed separately: [Containers pricing](https://developers.cloudflare.com/containers/platform/pricing/))
- [R2](https://developers.cloudflare.com/r2/pricing/) bucket + API token scoped to that bucket
- Docker (image build), Node 20+, Python 3.12+ for local validation
- `wrangler login` on the deploy machine

## Deploy (your account)

The script bootstraps **pinned** `npm ci` under `deploy/cloudflare`, ensures the R2 bucket exists, then runs an R2 read/write probe (create-only on a fresh bucket), and reuses `deploy/cloudflare/.deploy-state.json` for stable worker/bucket names across retries.

```bash
cd deploy/cloudflare
export VINCI_INSTANCE_SECRET="$(openssl rand -hex 24)"   # store safely
export CLOUDFLARE_ACCOUNT_ID="..."
export VINCI_R2_ACCESS_KEY_ID="..."
export VINCI_R2_SECRET_ACCESS_KEY="..."
# optional overrides (defaults saved in .deploy-state.json):
# export VINCI_CF_WORKER_NAME=vinci-oss-selfhost
# export VINCI_R2_BUCKET_NAME=vinci-oss-data-<account-prefix>
./scripts/deploy.sh
```

Validation only (no remote mutation):

```bash
DRY_RUN=1 FIXTURE_MODE=1 ./scripts/deploy.sh
```

The script prints the **observed** `*.workers.dev` URL parsed from `wrangler deploy` output.

## Persistence contract (durable-before-ack)

- **Canonical cloud authority:** `VinciHost` Durable Object SQLite (`/__vinci/journal/*`) holds the operation ledger, writer lease, outbox, and completion receipts. R2 holds immutable CAS blobs only. Container RAM + local SQLite are reconstructable compute caches.
- **Ack ordering:** for journaled mutations, immutable blob write must succeed first, then DO journal commit, then HTTP response. Orphan blobs without DO references are acceptable; DO references without blobs are not.
- **Env:** `VINCI_DURABLE_JOURNAL=do` with `VINCI_DO_JOURNAL_BASE` (worker public origin **or** full `…/__vinci/journal` prefix; deploy script sets the latter after `wrangler deploy`); `local` for loopback journal file tests; `off` preserves legacy loopback-only behavior.
- **Timer snapshots:** `VINCI_HOME_SNAPSHOT_ROLE=compact` (default in container) runs optional R2 home tarball compaction only — **not** an acknowledgement durability boundary. Do not rely on shutdown/final snapshots for zero-loss acks.
- **Coverage:** see `docs/MUTATION_INVENTORY.md`. All inventoried mutation paths are wired for durable-before-ack when journaling is enabled (`local` / `do`); loopback default keeps `VINCI_DURABLE_JOURNAL=off`.
- **Interrupted work:** when `VINCI_DURABLE_JOURNAL` is `do` or `local`, startup calls `reconcile_pending_outbox` (replay committed ops, resume runs, terminal `:output` receipts). `recover_interrupted_jobs` runs only for **non-journaled** R2 home snapshots (`journal` off) and marks local in-flight rows failed.
- **Provider refs:** committed ledger child `{op_id}:provider_inflight:{node_id}` survives fresh `VINCI_HOME`; resume polls vendor status when `durable_job_reconciliation` is true. Vendors without reconciliation (e.g. synchronous OpenAI image submit) **fail closed** if a ledger ref exists after home loss — no blind resubmit.

## Provider spend and auth

**Go-live provider set (initial):** enable only what you need in Studio — **OpenAI** (`OPENAI_API_KEY`), **Google Gemini** (`GEMINI_API_KEY`), **Higgsfield** (API key + secret or OAuth/MCP config), **Magnific** (`MAGNIFIC_API_KEY` or OAuth/MCP). Other bundled providers stay off until configured. Async vendors (Higgsfield, Magnific, Gemini Veo LRO) support ledger ref recovery; synchronous one-shot submits do not.

- `VINCI_ALLOW_LIVE_SPEND` worker secret defaults to `0`.
- Internet exposure: instance secret + expiring session cookie (or Bearer). Same-origin checks on state-changing requests. No wildcard CORS in self-host mode.
- `/healthz` does **not** start the container; `/readyz` requires auth.

## Upgrade / rollback / reset

| Action | Command |
|--------|---------|
| Upgrade | Pull OSS tag, `cd deploy/cloudflare && ./scripts/deploy.sh` (same state file) |
| Rollback | Deploy previous git SHA with same bucket/state file |
| Backup | Copy R2 bucket off-account |
| Reset | Delete bucket objects (or bucket) + remove `.deploy-state.json`, redeploy |
| Delete worker | `npx wrangler delete --name <worker>` (from `deploy/cloudflare` after `npm ci`) |

## Local vs Cloudflare

| | Local | Self-host |
|---|--------|-----------|
| Studio | HTML `:4310` or Next `:4311` | HTML `/studio` via Worker |
| Storage | `~/.vinci` | R2 CAS + snapshots |
| Auth | None on loopback | Instance secret |

## Limits (this repo)

- Real R2 SigV4 against Cloudflare is **not** exercised in CI (mock dir only).
- Container image build is defined in `deploy/cloudflare/container/Dockerfile`; run `docker build -f deploy/cloudflare/container/Dockerfile .` from repo root to verify locally.

Canonical tree: [`tryvinci/vinci`](https://github.com/tryvinci/vinci) (`apps/vinci-oss/` in the monorepo).
