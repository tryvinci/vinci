#!/usr/bin/env bash
# Ensure Mac alpha work only touches apps/vinci-oss (monorepo path).
set -euo pipefail
BASE_SHA="${1:-origin/dev}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"
CHANGED=()
while IFS= read -r line; do
  CHANGED+=("$line")
done < <(git diff --name-only "${BASE_SHA}...HEAD" 2>/dev/null || git diff --name-only "${BASE_SHA}" HEAD)
if [[ ${#CHANGED[@]} -eq 0 ]]; then
  echo "No changes vs ${BASE_SHA}"
  exit 0
fi
BAD=0
for f in "${CHANGED[@]}"; do
  if [[ "$f" != apps/vinci-oss/* ]]; then
    echo "out-of-scope: $f"
    BAD=1
  fi
done
if [[ "$BAD" -ne 0 ]]; then
  exit 1
fi
echo "scope ok (${#CHANGED[@]} files under apps/vinci-oss/)"
