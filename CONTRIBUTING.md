# Contributing to Vinci

Vinci is the MIT-licensed open-source generative media runtime.

## DCO

Every commit must be signed off (`git commit -s`) certifying the Developer Certificate of Origin in `DCO`.

## Ground rules

- Smallest correct change. No proprietary Vinci Platform code (Clerk, Dodo, credits, Mongo tenancy, hosted vault, marketing).
- Do not copy `vinci_ai_service.py` or any AGPL `vinci-clips` source. See `legal/AGPL_CLEAN_ROOM.md`.
- Secrets: names only in git. Resolvers read OS keychain → `$VINCI_HOME/keys/` → env → `~/.vinci/config.toml` refs. Conformance must prove keys never hit logs, jobs, receipts, or MCP payloads.
- Do not add Sora to the default catalog (API sunsets 2026-09-24).
- Market transparency, choice, and a $0 monthly floor. Never claim Vinci is always cheaper than Magnific.
- Provider plugins land only after the conformance suite passes.

## Dev

```bash
python3 -m venv .venv && source .venv/bin/activate
make install
make test && make conformance && make lint
```

Demo mode (no provider spend): `make demo` or `./scripts/vinci init --demo` then `./scripts/vinci run @tryvinci/image-generate --input '{"prompt":"a red cube"}'`. Do not `npx @tryvinci/cli` from the registry until a human publishes.

Do not publish `@tryvinci/*` to npm or `vinci-*` to PyPI until a human explicitly asks. Keep `tryvinci/vinci` **private** until a human opens it. `scripts/create-github-repo.sh` creates the repo `--private` and refuses `--public`. Cursor GitHub App tokens cannot create org repos; use an org-admin `gh` session or `TRYVINCI_GITHUB_TOKEN`.

## Protocol

`vinci-protocol` is semver'd independently. Changing a schema requires a compatibility note. Daemon/CLI negotiate `protocol_version`.

## Catalog

Curated JSON allowlists. `vinci catalog refresh` produces a reviewable diff, never a silent live mutation.

## License

MIT. Plugin authors are unencumbered. Vinci Platform may consume versioned packages.
