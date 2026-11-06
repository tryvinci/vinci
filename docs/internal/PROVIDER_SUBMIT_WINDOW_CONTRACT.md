# Provider submit-window test contract (free gate)

**Scope:** Local loopback fake providers only (`VINCI_TEST_LOOPBACK_I2I_URL`). This document describes **test guarantees**, not production exactly-once across regions or vendors.

## What we prove

| Guarantee | Mechanism |
|-----------|-----------|
| No duplicate **external submit** after ref is persisted (same `VINCI_HOME` or ledger child) | Durable **prepare** on `{parent}:provider_inflight:{node}` before `provider.submit` (workflow `generate` nodes and **adapt** `ai_extend` targets use `adapt:{index}`); committed row includes `provider_job_ref` before poll; resume uses `submit_resume` / `submit_resume_ledger` |
| No double submit across accept→ledger gap | Pending `provider_inflight` without `provider_job_ref` after provider accept → **fail closed** unless same-home SQLite still holds the ref (then ledger commit completes and resume polls) |
| Loopback **request counts** | `LoopbackI2IHandler` global `submit_count` + optional `VINCI_TEST_LOOPBACK_SUBMIT_COUNTER_PATH` |
| Role-scoped effects | `effects.jsonl` phases: `submit`, `submit_accepted`, `submit_resume`, `completion`, `ledger_commit` |
| Zero stale compute after lease takeover | `stale` role forbidden phases in `test_midcompute_takeover.py` |
| Acknowledged journal data survives home wipe | Parent op + receipts remain in ledger; **provider ref** is also on committed `{parent}:provider_inflight:{node}` when journaling is enabled |

## What we do **not** claim

- **Cross-home-wipe without ledger ref:** Non-journaled runs may resubmit once (honest `submit_count==2` in legacy test). **With journal:** `:provider_inflight` child + loopback reconciliation → **one** external submit (`submit_count==1`).
- **Fail closed:** Ledger ref + vendor without `durable_job_reconciliation` (e.g. OpenAI sync image) → error, no blind resubmit.
- **Dedup without terminal receipt:** Idempotent HTTP replay returns the same **acknowledged** operation response; it does **not** prove prior compute finished. Terminal work is evidenced by committed `:output` / `:batch_bundle` rows, not digest alone.
- **Ledger commit digest upgrade:** Local SQLite and Cloudflare DO `/commit` allow a **single** payload digest change only for a **pending** `submit_intent` row upgrading empty `provider_job_ref` → committed ref, with **unchanged** `kind`, `path`, and payload identity fields (`run_id`, `node_id`, `job_id`, `model_id`, `provider`, `idempotency_key`). Any other pending digest mismatch or mutated identity field is `payload_conflict` (no blanket bypass).
- **Cancellation mid-poll:** See `DURABLE_CONTROL_PLANE.md` uncancelable in-flight limits.

## Barriers (deterministic)

- `VINCI_TEST_SLEEP_AFTER_SUBMIT_MS` — after `provider_job_ref` is persisted, before status polling (barrier for takeover)
- `VINCI_TEST_SLEEP_DURING_EXECUTE_MS` — before execute entry (not after submit)
- `VINCI_TEST_EXIT_AFTER_SUBMIT` — crash after persisting `provider_job_ref` and committing ledger inflight (same-home resume test)
- `VINCI_TEST_EXIT_AFTER_SUBMIT_ACCEPTED` — crash after provider accept + SQLite ref but **before** ledger inflight commit (home-wipe fail closed; same-home ledger completion)
