#!/usr/bin/env bash
# Bounded free acceptance gate for vinci-oss (logs under ci-artifacts/free-gate/<git-head>/).
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

HEAD="$(git rev-parse HEAD)"
OUT="$ROOT/ci-artifacts/free-gate/$HEAD"
mkdir -p "$OUT"

echo "$HEAD" > "$OUT/HEAD.txt"
date -u +"%Y-%m-%dT%H:%M:%SZ" > "$OUT/timestamp.txt"

FAIL=0
SUMMARY="$OUT/summary.txt"
: > "$SUMMARY"

run_gate() {
  local name="$1"
  shift
  local log="$OUT/${name}.log"
  local ecfile="$OUT/${name}.exit"
  set +e
  "$@" >"$log" 2>&1
  local ec=$?
  set -e
  echo "$ec" >"$ecfile"
  echo "${name} exit=${ec}" | tee -a "$SUMMARY"
  if [[ "$ec" -ne 0 ]]; then
    FAIL=1
  fi
  return 0
}

run_gate ruff-baseline ruff check packages tests apps/daemon
run_gate pytest-gates python3 -m pytest -q \
  tests/test_durable_transaction_lease.py \
  tests/test_midcompute_takeover.py \
  tests/test_provider_submit_window_gate.py \
  tests/test_provider_reconciliation.py \
  tests/test_batch_idempotency.py \
  tests/test_batch_crash_recovery.py \
  tests/test_do_journal_committed_cursor_protocol.py
run_gate make-test make test
run_gate make-conformance make conformance
run_gate make-lint make lint
run_gate proprietary-scan make proprietary-scan
run_gate secret-scan make secret-scan
run_gate skills-validate make skills-validate
run_gate clone-smoke make clone-smoke
run_gate selfhost-dry-run make selfhost-dry-run

if [[ -f "$OUT/pytest-gates.log" ]]; then
  tail -n 3 "$OUT/pytest-gates.log" >>"$SUMMARY"
fi
if [[ -f "$OUT/make-test.log" ]]; then
  tail -n 3 "$OUT/make-test.log" >>"$SUMMARY"
fi

echo "overall_fail=$FAIL" | tee -a "$SUMMARY"
exit "$FAIL"
