"""backend.mcp

Model Context Protocol (MCP) tool integration and client scaffolding for LoanProcessAI.
"""

from .mcp_client import get_mcp_client, MCPClient

__all__ = ["get_mcp_client", "MCPClient"]
