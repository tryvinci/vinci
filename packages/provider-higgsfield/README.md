# vinci-provider-higgsfield

First-class Higgsfield HTTP plugin. Auth is `Authorization: Key KEY_ID:KEY_SECRET`
(`HIGGSFIELD_API_KEY` + `HIGGSFIELD_API_SECRET`). This is not an MCP wrapper.

Subscription credits use a separate connector, `mcp_higgsfield`, which signs in
to `https://mcp.higgsfield.ai/mcp` with OAuth. No API key. Its tool mapping was
captured from a live, signed-in `tools/list` on 2026-11-12 (see the `vinci-mcp` README).
Docs: https://docs.higgsfield.ai
