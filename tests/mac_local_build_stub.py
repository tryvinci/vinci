"""Temp PATH stubs for build-local.sh subprocess tests (test-only fake toolchain)."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import textwrap
from pathlib import Path

REAL_BASH = "/bin/bash"
# Stubs must use REAL_BASH in shebangs — `#!/usr/bin/env bash` would resolve stub/bash and recurse.


def _shebang(body: str) -> str:
    if body.startswith("#!"):
        return body
    return f"#!{REAL_BASH}\n{body}"


def _write_exe(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_shebang(body), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def install_mac_stubs(stub_bin: Path, oss_root: Path) -> None:
    stub_bin.mkdir(parents=True, exist_ok=True)
    root = str(oss_root)
    sbin = str(stub_bin)

    _write_exe(
        stub_bin / "uname",
        textwrap.dedent(
            """
if [ "$1" = "-s" ]; then echo "${MAC_STUB_UNAME_S:-Darwin}"; exit 0; fi
if [ "$1" = "-m" ]; then echo "${MAC_STUB_UNAME_M:-arm64}"; exit 0; fi
echo Darwin
"""
        ),
    )
    _write_exe(
        stub_bin / "sw_vers",
        '[ "$1" = "-productVersion" ] && echo "${MAC_STUB_SW_VER:-14.0}" && exit 0\necho 14.0\n',
    )
    _write_exe(
        stub_bin / "id",
        textwrap.dedent(
            """
[ "$1" = "-u" ] && echo 501 && exit 0
[ "$1" = "-un" ] && echo "${MAC_STUB_ID_USER:-testuser}" && exit 0
echo 501
"""
        ),
    )
    _write_exe(
        stub_bin / "stat",
        textwrap.dedent(
            """
[ "$1" = "-f%Su" ] && echo "${MAC_STUB_CONSOLE_USER:-testuser}" && exit 0
echo testuser
"""
        ),
    )
    _write_exe(
        stub_bin / "xcode-select",
        textwrap.dedent(
            """
[ "$1" = "-p" ] && echo /Library/Developer/CommandLineTools && exit 0
exit 0
"""
        ),
    )
    _write_exe(stub_bin / "swiftc", "exit 0\n")
    _write_exe(
        stub_bin / "git",
        textwrap.dedent(
            """
[ "$1" = "-C" ] && [ "$3" = "rev-parse" ] && echo deadbeefcafe && exit 0
exit 0
"""
        ),
    )
    _write_exe(stub_bin / "curl", "exit 0\n")
    _write_exe(stub_bin / "tar", "exit 0\n")
    _write_exe(stub_bin / "codesign", "exit 0\n")
    _write_exe(stub_bin / "cc", "exit 0\n")
    _write_exe(stub_bin / "xcrun", '[ "$1" = "--find" ] && echo /usr/bin/clang && exit 0\nexit 1\n')
    _write_exe(
        stub_bin / "node",
        '[ "$1" = "-p" ] && echo 22 && exit 0\n[ "$1" = "-v" ] && echo v22.0.0 && exit 0\nexit 0\n',
    )
    _write_exe(stub_bin / "npm", "exit 0\n")
    _write_exe(
        stub_bin / "make",
        textwrap.dedent(
            """
if [ "$1" = "test" ] && [ "${MAC_STUB_FAIL_TEST:-0}" = "1" ]; then
  echo "stub make test fail" >&2
  exit 1
fi
exit 0
"""
        ),
    )
    _write_exe(
        stub_bin / "open",
        textwrap.dedent(
            """
: >> "${MAC_STUB_OPEN_LOG:?MAC_STUB_OPEN_LOG unset}"
echo "open $*" >> "${MAC_STUB_OPEN_LOG}"
exit 0
"""
        ),
    )
    _write_exe(
        stub_bin / "shasum",
        textwrap.dedent(
            """
if [ "$1" = "-a" ] && [ "$2" = "256" ]; then
  f="$3"
  if [ "${MAC_STUB_BAD_SHA:-0}" = "1" ]; then
    echo "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef  $f"
    exit 0
  fi
  if command -v sha256sum >/dev/null 2>&1; then
    h=$(sha256sum "$f" | awk '{print $1}')
  elif [ -x /usr/bin/shasum ]; then
    h=$(/usr/bin/shasum -a 256 "$f" | awk '{print $1}')
  else
    echo "stub shasum: no system hasher" >&2
    exit 1
  fi
  echo "$h  $f"
  exit 0
fi
exit 1
"""
        ),
    )

    inner_py = textwrap.dedent(
        """
if [ "$1" = "-c" ]; then exit 0; fi
if [ -n "${1:-}" ] && echo "$1" | grep -q verify-packaging-paths; then exit 0; fi
exit 0
"""
    )
    _write_exe(stub_bin / "_venv_python.sh", inner_py)

    _write_exe(
        stub_bin / "python3.12",
        textwrap.dedent(
            f"""
if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
  dest="$3"
  mkdir -p "$dest/bin"
  cp "{sbin}/_venv_python.sh" "$dest/bin/python3"
  chmod +x "$dest/bin/python3"
  cp "$dest/bin/python3" "$dest/bin/python"
  chmod +x "$dest/bin/python"
  printf '%s\\n' '#!{REAL_BASH}' \\
    'export VIRTUAL_ENV="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/.." && pwd)"' \\
    'export PATH="$VIRTUAL_ENV/bin:$PATH"' > "$dest/bin/activate"
  chmod +x "$dest/bin/activate"
  exit 0
fi
if [ "$1" = "-c" ]; then exit 0; fi
if [ -n "${{1:-}}" ] && echo "$1" | grep -q verify-packaging-paths; then exit 0; fi
exit 0
"""
        ),
    )
    _write_exe(stub_bin / "python3", f'exec "{sbin}/python3.12" "$@"\n')
    _write_exe(stub_bin / "python", f'exec "{sbin}/python3.12" "$@"\n')

    _write_exe(
        stub_bin / "bash",
        textwrap.dedent(
            f"""
MAC_STUB_ROOT="{root}"
case "$*" in
  *fetch-deps.sh*|*build-ffmpeg.sh*|*prepare-studio-bundle.sh*|*smoke-app.sh*|*scan-bundle.sh*)
    exit 0 ;;
  *build-app.sh*)
    if [ "${{MAC_STUB_SKIP_ARTIFACTS:-0}}" = "1" ]; then exit 0; fi
    mkdir -p "$MAC_STUB_ROOT/dist/Vinci Studio.app"
    touch "$MAC_STUB_ROOT/dist/Vinci-Studio-0.1.0-alpha-arm64.zip"
    exit 0 ;;
  *build-dmg.sh*)
    if [ "${{MAC_STUB_SKIP_ARTIFACTS:-0}}" = "1" ]; then exit 0; fi
    touch "$MAC_STUB_ROOT/dist/Vinci-Studio-0.1.0-alpha-arm64.dmg"
    zip="$MAC_STUB_ROOT/dist/Vinci-Studio-0.1.0-alpha-arm64.zip"
    dmg="$MAC_STUB_ROOT/dist/Vinci-Studio-0.1.0-alpha-arm64.dmg"
    zh=$(/usr/bin/shasum -a 256 "$zip" 2>/dev/null | awk '{{print $1}}')
    echo "$zh  $(basename "$zip")" > "$MAC_STUB_ROOT/dist/SHA256SUMS"
    dh=$(/usr/bin/shasum -a 256 "$dmg" 2>/dev/null | awk '{{print $1}}')
    echo "$dh  $(basename "$dmg")" >> "$MAC_STUB_ROOT/dist/SHA256SUMS"
    exit 0 ;;
  *)
    echo "stub bash: unexpected invocation: $*" >&2
    exit 1
    ;;
esac
"""
        ),
    )


def layout_oss_tree(base: Path, build_local_src: Path) -> Path:
    oss = base / "vinci-oss"
    mac = oss / "scripts" / "mac"
    mac.mkdir(parents=True)
    shutil.copy2(build_local_src, mac / "build-local.sh")
    (mac / "build-local.sh").chmod(0o755)
    verify = build_local_src.parent / "verify-packaging-paths.py"
    if verify.is_file():
        shutil.copy2(verify, mac / "verify-packaging-paths.py")
    return oss


def run_build_local(
    oss_root: Path,
    stub_bin: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PATH"] = f"{stub_bin}:{env.get('PATH', '')}"
    env["MAC_STUB_ROOT"] = str(oss_root)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [REAL_BASH, str(oss_root / "scripts" / "mac" / "build-local.sh")],
        cwd=oss_root,
        capture_output=True,
        text=True,
        env=env,
    )


def write_conflicting_venv(oss_root: Path) -> None:
    venv = oss_root / ".venv" / "bin"
    venv.mkdir(parents=True)
    bad = textwrap.dedent(
        """
if [ "$1" = "-c" ]; then
  if echo "$2" | grep -q 'version_info\\[:2\\]==(3, 12)'; then exit 1; fi
  if echo "$2" | grep -q 'version_info\\[:2\\]==(3,12)'; then exit 1; fi
  if echo "$2" | grep -q 'print'; then echo "3.11"; exit 0; fi
fi
exit 0
"""
    )
    _write_exe(venv / "python3", bad)
