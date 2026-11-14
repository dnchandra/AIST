"""mcp_client.py

Standard Model Context Protocol (MCP) client helper for LoanProcessAI.
Enables agents to discover, invoke, and route tool requests through external MCP servers.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("loanprocessai.mcp")


class MCPClient:
    """Manages connections, tool schema catalogs, and RPC execution to MCP servers."""

    def __init__(self, server_url: Optional[str] = None):
        self.server_url = server_url
        self._registered_tools: Dict[str, Dict[str, Any]] = {}
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """Register built-in local MCP lending tools."""
        self._registered_tools["calculate_dscr"] = {
            "name": "calculate_dscr",
            "description": "Calculate Debt Service Coverage Ratio (DSCR) and evaluate credit policy compliance.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "annual_noi": {"type": "number", "description": "Annual Net Operating Income ($)"},
                    "annual_debt_service": {"type": "number", "description": "Annual Total Debt Service ($)"},
                    "minimum_threshold": {"type": "number", "default": 1.20, "description": "Minimum required DSCR"}
                },
                "required": ["annual_noi", "annual_debt_service"]
            }
        }
        self._registered_tools["verify_kyc_completeness"] = {
            "name": "verify_kyc_completeness",
            "description": "Verify applicant ID and proof-of-address documents against FinCEN CIP rules.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "has_government_id": {"type": "boolean"},
                    "utility_bill_age_days": {"type": "integer"},
                    "has_ein_certificate": {"type": "boolean"}
                },
                "required": ["has_government_id", "utility_bill_age_days"]
            }
        }

    async def list_tools(self) -> List[Dict[str, Any]]:
        """Return all available MCP tools."""
        return list(self._registered_tools.values())

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute an MCP tool invocation."""
        if name not in self._registered_tools:
            raise ValueError(f"Unknown MCP tool: '{name}'. Available: {list(self._registered_tools.keys())}")

        logger.info(f"mcp.tool.invoked: name={name} args={arguments}")

        if name == "calculate_dscr":
            noi = float(arguments.get("annual_noi", 0.0))
            debt = float(arguments.get("annual_debt_service", 1.0))
            threshold = float(arguments.get("minimum_threshold", 1.20))
            if debt <= 0:
                dscr = 999.0
            else:
                dscr = round(noi / debt, 2)
            passed = dscr >= threshold
            return {
                "dscr": dscr,
                "minimum_required": threshold,
                "policy_compliant": passed,
                "recommendation": "Passes credit policy guideline" if passed else "Violates minimum 1.20 DSCR requirement"
            }

        elif name == "verify_kyc_completeness":
            has_id = bool(arguments.get("has_government_id"))
            age = int(arguments.get("utility_bill_age_days", 999))
            has_ein = bool(arguments.get("has_ein_certificate", False))
            address_valid = age <= 90
            passed = has_id and address_valid and has_ein
            return {
                "verified": passed,
                "id_status": "valid" if has_id else "missing",
                "address_status": "valid" if address_valid else f"expired ({age} days old)",
                "action_required": "None" if passed else "Request updated utility bill (dated < 90 days)"
            }

        return {"error": "Handler not implemented"}


_default_mcp_client: Optional[MCPClient] = None


def get_mcp_client() -> MCPClient:
    """Return singleton MCP client instance."""
    global _default_mcp_client
    if _default_mcp_client is None:
        _default_mcp_client = MCPClient()
    return _default_mcp_client
