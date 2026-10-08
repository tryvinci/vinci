# Free acceptance gate artifacts

CI and local runs write raw logs and exit codes under `ci-artifacts/free-gate/<git-head>/`:

- `HEAD.txt` — exact commit SHA
- `summary.txt` — per-gate exit codes
- `*.log` — full stdout/stderr per gate
- `*.exit` — numeric exit code per gate

Run locally from `apps/vinci-oss`:

```bash
make free-gate
```

Ruff baseline at this gate: **0 errors** (previously ~21 E501/I001 before line-wrap fixes).
