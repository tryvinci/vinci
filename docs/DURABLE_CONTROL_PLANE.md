# Durable control plane (Cloudflare self-host)

See `MUTATION_INVENTORY.md` for the full acknowledged-mutation list.

## Layers

| Layer | Role |
|-------|------|
| **DO SQLite (`VinciHost`)** | Writer lease, operation ledger, outbox, receipts — sole cloud metadata authority |
| **R2** | Immutable CAS / snapshot blobs (create-only archives) |
| **Container** | Ephemeral compute + local SQLite cache; replay from DO + R2 on restart |

## Commit order (journaled mutations)

1. Put immutable blob to R2/CAS and await success (when applicable).
2. `prepare_operation` with stable `X-Vinci-Operation-Id` (durable intent before handler side effects).
3. Run handler (no provider/run execution for `run_accept` until post-ack outbox dispatch).
4. Transactionally finalize journal + outbox (`commit_ack`) before HTTP response.
5. Dispatch outbox (runs, approvals, etc.); on completion record `run_output` receipt with output blob keys.

`VINCI_DURABLE_JOURNAL=do` is **fail closed**: missing `VINCI_DO_JOURNAL_BASE` does not fall back to local. Journal HTTP routes require `Authorization: Bearer $VINCI_BRIDGE_TOKEN`.

## Gaps (this branch)

- MCP tool side effects are journaled at HTTP boundary only; per-tool blob/receipt ordering varies.
- Real CF DO output gates + cross-region behavior unverified without disposable account test.
- Docker smoke: manual `workflow_dispatch` only until free Actions allowance verified.

## Uncancelable in-flight work (lease fencing limits)

Once the writer has passed **execute entry** and begun node work, the runtime does **not** cooperatively cancel mid-provider poll or mid-ffmpeg adapt. Fencing stops **new** journal-backed mutations (`renew_writer` failure → `_journal_writer_fenced`):

- No further `cas` / `persist_job` / `run_state_*` / `ledger_commit` / `completion` while fenced.
- Provider `submit` already in flight may still complete externally; the fenced process must not commit outputs (writer check before `submit`, after `_wait_status`, before `_persist_job`, and before durable receipts).
- **FAILED** run state is not written after fence loss (avoids stale terminal rows).
- A new owner acquires the lease and resumes from the ledger/outbox; duplicate node work is detected via operation ids and output receipts, not by killing the old OS process.

Tests use `VINCI_TEST_WRITER_ROLE` + `VINCI_TEST_WRITER_EFFECTS_DIR` (`effects.jsonl`) to assert **zero stale-role compute** after takeover. **Ack replay** (same `X-Vinci-Operation-Id`) preserves the committed HTTP response; it is not evidence that compute finished — only committed `:output` / `:batch_bundle` receipts are. Provider submit-window guarantees are documented in `PROVIDER_SUBMIT_WINDOW_CONTRACT.md` (loopback tests only).
