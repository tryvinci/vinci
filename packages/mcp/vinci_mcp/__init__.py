from typing import Any

from vinci_mcp.adapter import HttpMcpTransport, McpProvider

__all__ = [
    "HttpMcpTransport",
    "McpProvider",
    "TOOL_NAMES",
    "call_tool",
    "handle_rpc",
    "tool_schemas",
]


def __getattr__(name: str) -> Any:
    """The authored MCP server loads on first use: it needs vinci-runtime, and a host that only
    runs the connectors (the hosted Studio, COREPRODUC-614) does not install it."""
    if name in {"TOOL_NAMES", "call_tool", "handle_rpc", "tool_schemas"}:
        from vinci_mcp import server

        return getattr(server, name)
    raise AttributeError(name)
