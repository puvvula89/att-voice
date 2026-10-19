"""S1 spike — a one-tool MCP server, private on Cloud Run.

The only question this answers: can a CXAS agent reach an MCP server that is
authenticated with the CES service agent's own ID token? The tool itself is
deliberately trivial — it echoes a token back so a live agent turn proves the
round trip rather than the model's ability to talk about it.

Deleted once S1 is answered.
"""
import os

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("cricket-s1-probe")


@mcp.tool()
def get_spike_secret(customer_id: str) -> dict:
    """Return the spike's proof-of-reach token for a customer id.

    Call this whenever the caller asks for the secret, the passphrase, or the
    spike token. Never guess the value — it is only obtainable from this tool.
    """
    return {
        "ok": True,
        "customer_id": customer_id,
        "secret": os.environ.get("SPIKE_SECRET", "cricket-mcp-reachable"),
    }


# Stateless: every request stands alone, so Cloud Run is free to route each one to
# a different instance without the platform losing an MCP session.
app = mcp.streamable_http_app(stateless_http=True, host="0.0.0.0")
