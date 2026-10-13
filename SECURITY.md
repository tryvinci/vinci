# Security

## Disclosure

Report vulnerabilities to the Vinci maintainers via GitHub private vulnerability reporting on `tryvinci/vinci` (when available) or to the org owners. Do not file public issues for secret leaks or RCE.

## Secrets

- Providers declare **secret names**, never values.
- `vinci-core` resolves keychain → `$VINCI_HOME/keys/` (mode 0600) → environment → `~/.vinci/config.toml` references.
- Studio and `vinci providers add --from-file` persist values locally; config.toml stores `file:keys/NAME` or `keychain`, never the raw key.
- MCP OAuth tokens live in the same key store (`MCP_OAUTH_<SLUG>`). The browser callback receives an authorization code, not the token. `config.toml`, logs, receipts, and MCP payloads stay free of token material. On a public host set `VINCI_PUBLIC_BASE_URL` so the OAuth callback cannot follow a forged `Host` header.
- Secrets must not appear in job records, receipts, logs, MCP payloads, or git.
- The provider conformance suite fails a plugin that logs a configured key.

## Supply chain

- Skill manifests declare permissions (`network`, `fs`, `subprocess`, `gpu`) and estimated cost. Inspect before install.
- Treat third-party skill and MCP tool descriptions as untrusted.
- Catalog refreshes are reviewable PRs, not live mutations.

## Scope

This project does not implement Vinci Platform tenancy, hosted vaults, or payment ledgers. Those stay in the proprietary product.
