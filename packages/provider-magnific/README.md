# vinci-provider-magnific

First-class Magnific / Freepik HTTP plugin. Auth is the `x-magnific-api-key`
header (`MAGNIFIC_API_KEY`). This is not an MCP wrapper. Magnific also ships an
OAuth MCP server; Vinci treats that as a *custom MCP* provider if you point
`mcp.url` at it. Docs: https://docs.magnific.com/introduction
