# Vinci plugin for Claude Code

One install gives Claude Code the Vinci Studio tools and a skill on how to use them well (COREPRODUC-779).

| Part | File | What it does |
| --- | --- | --- |
| MCP server `vinci` | `.mcp.json` | The hosted Studio at `https://app.tryvinci.com/mcp` (HTTP). Sign-in is OAuth on a Vinci sign-in page. There is no API key. |
| Skill `vinci:studio` | `skills/studio/SKILL.md` | Price first, poll runs, chain start images, read refused calls, and write video prompts that move. |
| Icon | `.claude-plugin/icon.png` | The Vinci mark (from `apps/vinci-docs/favicon.svg`), 1024 px square PNG. The plugin directory keeps the first icon it sees, so change it only before the first submission (COREPRODUC-782). |

## Install

In Claude Code:

```text
/plugin marketplace add tryvinci/vinci
/plugin install vinci@tryvinci
```

Then `/mcp` → `vinci` → Authenticate, and sign in to Vinci. Runs use your Vinci credits and show in your Studio.

From a clone, to test a change: `claude --plugin-dir ./plugins/vinci`, or `claude plugin validate ./plugins/vinci`.

## Local daemon (option)

The plugin connects to the hosted Studio. To use the local runtime on your own provider keys instead, start the daemon (`./scripts/vinci studio`) and add its server next to the plugin:

```bash
./scripts/vinci mcp print-config          # {"mcpServers": {"vinci": {"url": "http://127.0.0.1:4310/mcp"}}}
claude mcp add --transport http vinci-local http://127.0.0.1:4310/mcp
```

The tool names are the same (`vinci.*`), so the skill applies to both. The daemon has more tools; see `packages/mcp/README.md`. To turn off the hosted server, disable it in `/mcp`.

## Not the same as `skills/`

`skills/` at the repo root holds Vinci workflow skills (`workflow.yaml`) that the daemon runs. This folder is a Claude Code plugin: it tells an agent how to call the Vinci tools.
