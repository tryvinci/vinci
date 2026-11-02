"""Run assertions against a self-contained Studio TS module from pytest."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_ts(module: str, names: list[str], body: str) -> subprocess.CompletedProcess[str]:
    """Transpile `module` (repo-relative, no imports) and run `body` with `names` in scope.

    Node 20 is the OSS CI runtime and cannot import .ts via --experimental-strip-types,
    so this uses the repo TypeScript compiler and a data: URL import.

    Args:
        module: Repo-relative path to a TS file with no imports.
        names: Exports to destructure into scope for `body`.
        body: JS statements; throw to fail.

    Returns:
        The finished node process; returncode 0 means every assertion held.
    """
    script = f"""
import ts from "typescript";
import {{ readFileSync }} from "node:fs";
const src = readFileSync({module!r}, "utf8");
const js = ts.transpileModule(src, {{
  compilerOptions: {{ module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 }},
}}).outputText;
const mod = await import("data:text/javascript," + encodeURIComponent(js));
const {{ {", ".join(names)} }} = mod;
{body}
"""
    return subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
