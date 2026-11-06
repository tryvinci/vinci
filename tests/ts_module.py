"""Run assertions against a self-contained Studio TS module from pytest."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_ts(module: str, names: list[str], body: str) -> subprocess.CompletedProcess[str]:
    """Transpile `module` and run `body` with `names` in scope.

    Node 20 is the OSS CI runtime and cannot import .ts via --experimental-strip-types,
    so this uses the repo TypeScript compiler and a data: URL import. Relative imports
    are inlined first (one module) so Studio libs can share `modelsFor`.

    Args:
        module: Repo-relative path to a TS file.
        names: Exports to destructure into scope for `body`.
        body: JS statements; throw to fail.

    Returns:
        The finished node process; returncode 0 means every assertion held.
    """
    script = f"""
import ts from "typescript";
import {{ readFileSync }} from "node:fs";
import {{ dirname, resolve }} from "node:path";
const entry = resolve(process.cwd(), {module!r});
const __vinciBundleSeen = new Set();
const __vinciParts = [];
function __vinciAbsorb(file) {{
  if (__vinciBundleSeen.has(file)) return;
  __vinciBundleSeen.add(file);
  let src = readFileSync(file, "utf8");
  const dir = dirname(file);
  const deps = [];
  src = src.replace(/import\\s+(?:type\\s+)?\\{{[^}}]*\\}}\\s+from\\s+"(\\.[^"]+)"\\s*;?/g, (_m, spec) => {{
    const dep = resolve(dir, spec.endsWith(".ts") ? spec : spec + ".ts");
    deps.push(dep);
    return "";
  }});
  for (const dep of deps) __vinciAbsorb(dep);
  __vinciParts.push(src);
}}
__vinciAbsorb(entry);
const js = ts.transpileModule(__vinciParts.join("\\n"), {{
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
