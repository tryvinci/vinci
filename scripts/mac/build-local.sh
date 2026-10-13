#!/usr/bin/env bash
# One-command local Mac build + review runbook (macOS arm64, Ventura+). No brew/sudo/secrets.
set -euo pipefail

STAGE="init"
fail() {
  local ec="${1:-1}"
  echo "build-local.sh: failed at stage: ${STAGE} (exit ${ec})" >&2
  exit "${ec}"
}
on_err() {
  fail "$?"
}
trap on_err ERR

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)
cd "${ROOT}"

VENV="${ROOT}/.venv"
APP="${ROOT}/dist/Vinci Studio.app"
ZIP="${ROOT}/dist/Vinci-Studio-0.1.0-alpha-arm64.zip"
DMG="${ROOT}/dist/Vinci-Studio-0.1.0-alpha-arm64.dmg"

require_cmd() {
  local name="$1"
  local hint="${2:-}"
  if ! command -v "${name}" >/dev/null 2>&1; then
    echo "build-local.sh: missing required command: ${name}" >&2
    if [ -n "${hint}" ]; then
      echo "  hint: ${hint}" >&2
    fi
    fail 1
  fi
}

verify_sha256sums_file() {
  local sums="${1}"
  if [ ! -f "${sums}" ]; then
    echo "build-local.sh: missing checksum file: ${sums}" >&2
    fail 1
  fi
  require_cmd shasum "Xcode CLT (shasum)"
  local line hash file actual
  while IFS= read -r line || [ -n "${line}" ]; do
    line=$(echo "${line}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    if [ -z "${line}" ]; then
      continue
    fi
    hash=$(echo "${line}" | awk '{print $1}')
    file=$(echo "${line}" | awk '{print $NF}')
    if [ -z "${hash}" ] || [ -z "${file}" ]; then
      echo "build-local.sh: invalid SHA256SUMS line: ${line}" >&2
      fail 1
    fi
    if [ ! -f "${file}" ]; then
      echo "build-local.sh: SHA256SUMS missing artifact: ${file}" >&2
      fail 1
    fi
    actual=$(shasum -a 256 "${file}" | awk '{print $1}')
    if [ "${actual}" != "${hash}" ]; then
      echo "build-local.sh: SHA256 mismatch for ${file}" >&2
      fail 1
    fi
  done < "${sums}"
}

STAGE="host_platform"
sys=$(uname -s 2>/dev/null || echo unknown)
arch=$(uname -m 2>/dev/null || echo unknown)
if [ "${sys}" != "Darwin" ] || [ "${arch}" != "arm64" ]; then
  echo "build-local.sh: requires macOS arm64 (host: ${sys}/${arch})" >&2
  fail 2
fi

STAGE="macos_version"
if ! command -v sw_vers >/dev/null 2>&1; then
  echo "build-local.sh: sw_vers not found" >&2
  fail 1
fi
prod_ver=$(sw_vers -productVersion)
major=$(echo "${prod_ver}" | cut -d. -f1)
if [ "${major}" -lt 13 ] 2>/dev/null; then
  echo "build-local.sh: requires macOS 13.0 or newer (sw_vers ${prod_ver})" >&2
  fail 1
fi

STAGE="gui_session"
if [ "$(id -u)" -eq 0 ]; then
  echo "build-local.sh: do not run as root; use a logged-in macOS GUI session." >&2
  fail 1
fi
session_user=$(id -un 2>/dev/null || echo "")
console_user=$(stat -f%Su /dev/console 2>/dev/null || echo "")
if [ -z "${console_user}" ] || [ "${console_user}" = "loginwindow" ]; then
  echo "build-local.sh: no active console GUI user (stat /dev/console)." >&2
  echo "  hint: log in at the Mac display or use a session with a logged-in user." >&2
  fail 1
fi
case "${console_user}" in
  SetupUser|_mbsetupuser|"Setup User")
    echo "build-local.sh: console user ${console_user} is not an interactive GUI session." >&2
    fail 1
    ;;
esac
if [ -z "${session_user}" ] || [ "${session_user}" != "${console_user}" ]; then
  echo "build-local.sh: id -un (${session_user}) must match console user (${console_user})." >&2
  fail 1
fi

STAGE="xcode_clt"
if ! xcode-select -p >/dev/null 2>&1; then
  echo "build-local.sh: Xcode Command Line Tools not selected." >&2
  echo "  hint: run xcode-select --install and accept the license." >&2
  fail 1
fi
require_cmd swiftc "install Xcode Command Line Tools (swiftc)"

STAGE="toolchain"
require_cmd git "install Xcode CLT or git"
require_cmd make "install Xcode CLT (make)"
require_cmd curl "install Xcode CLT (curl)"
require_cmd tar "install Xcode CLT (tar)"
require_cmd codesign "install Xcode CLT (codesign)"
require_cmd open "macOS open(1) required to reveal dist/"
if command -v cc >/dev/null 2>&1; then
  :
elif command -v xcrun >/dev/null 2>&1 && xcrun --find clang >/dev/null 2>&1; then
  :
else
  echo "build-local.sh: no C compiler (cc/clang via Xcode CLT)." >&2
  fail 1
fi

STAGE="node"
require_cmd node "install Node.js 22.x from nodejs.org or your manager (no auto-brew)"
require_cmd npm "install Node.js 22.x (npm ships with node)"
node_major=$(node -p "process.versions.node.split('.')[0]" 2>/dev/null || echo "0")
if [ "${node_major}" != "22" ]; then
  echo "build-local.sh: Node.js 22.x required (got $(node -v 2>/dev/null || echo unknown))." >&2
  fail 1
fi

STAGE="python_bootstrap"
PY_BOOTSTRAP=""
if command -v python3.12 >/dev/null 2>&1; then
  PY_BOOTSTRAP=python3.12
elif command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; raise SystemExit(0 if sys.version_info[:2]==(3,12) else 1)'; then
  PY_BOOTSTRAP=python3
else
  echo "build-local.sh: install Python 3.12.x (python3.12 or python3 on PATH)." >&2
  fail 1
fi

STAGE="venv"
if [ -n "${VIRTUAL_ENV:-}" ]; then
  case "${VIRTUAL_ENV}" in
    "${VENV}"|"${VENV}/"*) ;;
    *)
      echo "build-local.sh: deactivate foreign virtualenv (VIRTUAL_ENV=${VIRTUAL_ENV})." >&2
      fail 1
      ;;
  esac
fi
if [ -d "${VENV}" ]; then
  if [ ! -x "${VENV}/bin/python3" ]; then
    echo "build-local.sh: ${VENV} exists but bin/python3 is missing or not executable." >&2
    echo "  hint: remove .venv manually if you do not need it." >&2
    fail 1
  fi
  if ! "${VENV}/bin/python3" -c 'import sys; raise SystemExit(0 if sys.version_info[:2]==(3,12) else 1)'; then
    v=$("${VENV}/bin/python3" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "?")
    echo "build-local.sh: conflicting ${VENV} (Python ${v}, need 3.12)." >&2
    echo "  hint: remove .venv manually; this script will not delete it." >&2
    fail 1
  fi
else
  "${PY_BOOTSTRAP}" -m venv "${VENV}"
fi
# shellcheck disable=SC1091
. "${VENV}/bin/activate"
python -c 'import sys; raise SystemExit(0 if sys.version_info[:2]==(3,12) else 1)'

STAGE="make_install"
make install

STAGE="npm_ci"
npm ci

STAGE="fetch_deps"
bash "${ROOT}/scripts/mac/fetch-deps.sh"

STAGE="build_ffmpeg"
bash "${ROOT}/scripts/mac/build-ffmpeg.sh"

STAGE="make_test"
make test

STAGE="make_lint"
make lint

STAGE="prepare_studio_bundle"
export NODE_ENV=production # pragma: allowlist secret
bash "${ROOT}/scripts/mac/prepare-studio-bundle.sh"

STAGE="build_app"
bash "${ROOT}/scripts/mac/build-app.sh"

STAGE="smoke_app"
GIT_SHA=$(git -C "${ROOT}" rev-parse HEAD 2>/dev/null || echo unknown)
export VINCI_GIT_SHA="${GIT_SHA}"
bash "${ROOT}/scripts/mac/smoke-app.sh" "${APP}"

STAGE="build_dmg"
bash "${ROOT}/scripts/mac/build-dmg.sh"

STAGE="verify_outputs"
if [ ! -d "${APP}" ]; then
  echo "build-local.sh: missing app bundle: ${APP}" >&2
  fail 1
fi
if [ ! -f "${ZIP}" ]; then
  echo "build-local.sh: missing zip: ${ZIP}" >&2
  fail 1
fi
if [ ! -f "${DMG}" ]; then
  echo "build-local.sh: missing dmg: ${DMG}" >&2
  fail 1
fi
SUMS="${ROOT}/dist/SHA256SUMS"
if [ ! -f "${SUMS}" ]; then
  echo "build-local.sh: missing dist/SHA256SUMS" >&2
  fail 1
fi
python3 "${ROOT}/scripts/mac/verify-packaging-paths.py" --app "${APP}"
(
  cd "${ROOT}/dist"
  verify_sha256sums_file "SHA256SUMS"
)
bash "${ROOT}/scripts/mac/scan-bundle.sh" "${APP}"
codesign --verify --strict --deep "${APP}"

echo "build-local.sh: outputs verified (ad-hoc codesign, not notarized — Gatekeeper may block; see docs/MAC_ALPHA.md)" >&2
echo "  git HEAD: ${GIT_SHA}" >&2
echo "  app: ${APP}" >&2
echo "  zip: ${ZIP}" >&2
echo "  dmg: ${DMG}" >&2
echo "  SHA256SUMS: ${SUMS}" >&2
while IFS= read -r sumline || [ -n "${sumline}" ]; do
  sumline=$(echo "${sumline}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
  if [ -n "${sumline}" ]; then
    echo "  ${sumline}" >&2
  fi
done < "${SUMS}"

STAGE="open_dist"
open "${ROOT}/dist"

echo "build-local.sh: ok — ${APP} ${ZIP} ${DMG} (smoke sha=${GIT_SHA})"
