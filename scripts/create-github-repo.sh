#!/usr/bin/env bash
# Create private tryvinci/vinci and push this tree.
# Cursor GitHub App tokens 403 on org repo create. Prefer TRYVINCI_GITHUB_TOKEN
# (org-admin PAT). Keep the repo private until a human opens it. Do not publish npm/PyPI.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ "${1:-}" == "--public" ]]; then
  echo "refusing --public: keep tryvinci/vinci private until a human opens it" >&2
  exit 2
fi

if [[ -n "${TRYVINCI_GITHUB_TOKEN:-}" ]]; then
  export GH_TOKEN="$TRYVINCI_GITHUB_TOKEN"
  export GITHUB_TOKEN="$TRYVINCI_GITHUB_TOKEN"
fi

OWNER="tryvinci"
NAME="vinci"
SLUG="$OWNER/$NAME"

if gh repo view "$SLUG" >/dev/null 2>&1; then
  echo "$SLUG exists; pushing main"
  git push -u origin main
  exit 0
fi

if ! gh repo create "$SLUG" --private --description "Vinci — MIT open-source generative media runtime"; then
  echo "gh cannot create $SLUG with this token (org repo create is 403 for Cursor App tokens)." >&2
  echo "Create an empty private repo in the browser:" >&2
  echo "  https://github.com/organizations/tryvinci/repositories/new" >&2
  echo "Name: vinci" >&2
  echo "Visibility: Private" >&2
  echo "Do not add README, .gitignore, or license." >&2
  echo "Grant the Cursor GitHub App Contents/Issues/PRs/Actions write, then:" >&2
  echo "  git -C \"$ROOT\" push -u origin main" >&2
  echo "Keep it private. Do not npm/PyPI publish." >&2
  exit 1
fi

git push -u origin main
echo "pushed $SLUG (private). Do not npm publish. Do not open until a human says so."
