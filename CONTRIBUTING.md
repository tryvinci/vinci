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

Do not publish `@tryvinci/*` to npm or `vinci-*` to PyPI until a maintainer explicitly asks.

## Where to start

- Browse issues labelled [`good first issue`](https://github.com/tryvinci/vinci/labels/good%20first%20issue). Each one names the files to touch and how to test.
- **Add a skill.** A skill is a folder under `skills/` with `vinci.yaml` (inputs, outputs, cost range), `workflow.yaml` (a small node graph) and `SKILL.md`. Copy `skills/tts/` to start. `make skills-validate` checks it.
- **Add a model to a provider.** Catalogs live in `packages/core/vinci_core/catalogs/<provider>.json`. Add the entry with its price and capabilities, then run `make conformance`.
- **Add a provider.** Start from `packages/provider-sdk` and an existing plugin such as `packages/provider-fal`. It lands after the conformance suite passes.
- Questions and ideas go in [Discussions](https://github.com/tryvinci/vinci/discussions).

## Protocol

`vinci-protocol` is semver'd independently. Changing a schema requires a compatibility note. Daemon/CLI negotiate `protocol_version`.

## Catalog

Curated JSON allowlists. `vinci catalog refresh` produces a reviewable diff, never a silent live mutation.

## License

MIT. Plugin authors are unencumbered. Vinci Platform may consume versioned packages.
