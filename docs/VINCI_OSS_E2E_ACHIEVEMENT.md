# Vinci OSS — end-to-end achievement playbook

Contract companion to `VINCI_OSS_RUNTIME.md`. Execute **one phase at a time**. Do not start Phase N+1 until Phase N's exit gate is green. If blocked, stop and report. Do not weaken gates.

North star: a stranger can clone this tree, run `vinci init --demo` or plug a Wavespeed/Google key, execute a portable skill, and get a generated asset plus an immutable cost receipt — no Clerk, no credits, no Mongo. Vinci Platform later consumes the same versioned OSS packages.

Until `tryvinci/vinci` exists, the tree lives at `apps/vinci-oss/` in `tryvinci/vinci-monorepo`. Clone the monorepo, `cd apps/vinci-oss`, then the same gates. Extract later without changing this architecture.

## Hard constraints

1. Do not copy Clerk, Dodo, credits, Mongo tenancy, hosted vault, or marketing into `tryvinci/vinci`.
2. Do not copy `vinci_ai_service.py` or any AGPL `vinci-clips` source. Reimplement from semantics. Do not open `tryvinci/vinci-clips`.
3. Do not publish to npm/PyPI or announce publicly. npm `vinci` and PyPI `vinci` are taken — use scoped/suffixed names only (`NAMESPACE.md`).
4. Do not merge or push Vinci Platform `main`. Default integration branch is `dev`.
5. Do not spend real provider money in CI. Mock + fixtures only.
6. Never claim Vinci is always cheaper than Magnific. Market transparency, choice, $0 monthly floor.
7. Secrets: names only in git; keychain / `$VINCI_HOME/keys/` / env / config refs; conformance must prove keys never hit logs, jobs, receipts, or MCP payloads.
8. Exclude Sora from the default catalog (API sunsets 2026-09-24).
9. Keep the repo private until a human opens it.

## Phase 0 — Bootstrap

Create `tryvinci/vinci` (private MIT), protocol v0, local CAS + SQLite, provider-sdk + mock + conformance CI, AGPL clean-room memo, `NAMESPACE.md`.

**Exit:** `make test && make conformance && make lint`.

Human gates that do not block this exit: USPTO/EUIPO clearance; public repo; npm/PyPI publish.

## Phase 1 — MVP

Daemon `:4310`, cost engine (estimate → approval → receipt, CAS replay $0), Wavespeed + Google + fal plugins, catalog snapshots, skills `image-generate` / `video-generate` / `product-reveal-5s`, CLI commands from the runtime doc, authored MCP tools (`vinci.*`).

**Exit:** demo runs via CLI, `POST /runs`, and MCP. Same skill, mock provider, cost receipt. Live USD spend = $0.

## Phase 2 — Parity + clips + index

Remaining first-party skills, clean-room clips DAG (do not open or copy vinci-clips), `vinci-index` + `vinci find`, thin Studio.

**Exit:** fixture `podcast-to-shorts` + Studio smoke. AGPL memo is a gate.

## Phase 3 — Ecosystem + Platform spike

Skills add/registry, external MCP providers, minimal timeline, one Platform consumption spike (OSS protocol types or `vinci-core` router + `CreditsBudgetAdapter`).

**Exit:** second skill installs; Platform video tests still pass.

## Parallel Platform work (this is the sibling monorepo)

`credential_resolver` seam, intentional `vinci.*` MCP tool list, later `VinciAiService` split. Separate PRs off `dev`. No dump of app trees into OSS.

## Report template (end of each phase and end of run)

- Gate status
- Repo/PR URLs
- Exit-gate transcripts
- Remaining human gates
- Any live USD spend
- `rg` proof that Clerk/Dodo/Mongo/AGPL are absent from the OSS tree (except exclusion notes in docs/legal)
