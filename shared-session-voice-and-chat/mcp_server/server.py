"""MCP server exposing the phone-upgrade *data* tools over streamable-HTTP.

Runs as a standalone process (locally on :9000, on Cloud Run via $PORT). The
ADK agent consumes it through ``McpToolset`` (see ``backend/agent.py``).

Only the data tools live here. ``render_component`` and ``end_call`` stay
agent-local because they are UI / session-control side-effects that depend on
ADK ``tool_context.state`` — which a remote MCP process cannot reach.

Tools are stateless: the agent passes the relevant ids on every call. The
agent-side ``after_tool_callback`` stages each response into session state for
the formatter.

Run locally:  python -m mcp_server.server
"""
import os

from mcp.server.fastmcp import FastMCP

from mcp_server import catalog

# Cloud Run injects $PORT (usually 8080); default to 9000 for local dev so it
# does not collide with the relay on :8000. host 0.0.0.0 so the container is
# reachable.
PORT = int(os.environ.get("PORT", "9000"))
HOST = os.environ.get("HOST", "0.0.0.0")

# stateless_http: every call is independent (our tools hold no per-session
# state), which is what lets Cloud Run scale instances freely.
mcp = FastMCP("att-phone-upgrade", host=HOST, port=PORT, stateless_http=True)


@mcp.tool()
def get_lines() -> dict:
    """List the account's lines available for upgrade. Use the returned
    line_id values when calling select_line / get_eligible_phones."""
    return catalog.list_lines()


@mcp.tool()
def get_eligible_phones(line_id: str) -> dict:
    """List the phones the given line is eligible for. Use the returned
    phone_id values when calling select_phone."""
    return catalog.eligible_phones(line_id)


@mcp.tool()
def select_line(line_id: str) -> dict:
    """Record the line the customer chose to upgrade."""
    return catalog.select_line(line_id)


@mcp.tool()
def select_phone(line_id: str, phone_id: str) -> dict:
    """Record the phone the customer chose for the given line and prepare the
    confirmation summary. Pass the line_id being upgraded and the chosen
    phone_id."""
    return catalog.select_phone(line_id, phone_id)


@mcp.tool()
def confirm_upgrade(line_id: str, phone_id: str) -> dict:
    """Finalize the upgrade for the given line + phone and return the order
    receipt. Pass the same line_id and phone_id used for select_phone."""
    return catalog.confirm_upgrade(line_id, phone_id)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
