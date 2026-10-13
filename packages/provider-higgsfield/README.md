# vinci-provider-higgsfield

First-class Higgsfield HTTP plugin. Auth is `Authorization: Key KEY_ID:KEY_SECRET`
(`HIGGSFIELD_API_KEY` + `HIGGSFIELD_API_SECRET`). This is not an MCP wrapper.

Subscription credits use a separate connector, `mcp_higgsfield`, which signs in
to `https://mcp.higgsfield.ai/mcp` with OAuth. No API key. Tool names on that
connector are provisional until a live `tools/list` capture.
Docs: https://docs.higgsfield.ai
