"""Support MCP server: tutorial procedures plus the mock account/network store.

Stateless streamable HTTP so Cloud Run may route each request anywhere. The
account store is per-process; with min-instances=1 and max-instances=1 that is
one consistent demo state, which is all a POC needs.
"""
import os

from mcp.server.mcpserver import MCPServer

from support_mcp import tools_account as A
from support_mcp import tools_outreach as O
from support_mcp import tools_procedures as P

mcp = MCPServer("cricket-support")


@mcp.tool()
def find_tutorials(device: str, symptom: str) -> dict:
    """Find the troubleshooting article or procedure for a symptom on ONE device.
    Call this once, after you know the device, with the caller's words as the symptom.
    Prefer an 'article' result when the caller describes a problem; a 'procedure' when
    they ask how to do a specific thing. Never call it again mid walk-through."""
    return P.find_tutorials(device, symptom)


@mcp.tool()
def get_tutorial(device: str, tutorial_id: str) -> dict:
    """Get the summary, step count, branch question and safety flags for a tutorial.
    Call this right after find_tutorials, before offering the caller the summary."""
    return P.get_tutorial(device, tutorial_id)


@mcp.tool()
def get_step(device: str, tutorial_id: str, n: int, choice: str = "") -> dict:
    """Get ONE step of a tutorial. Call this for each step as the caller confirms the
    previous one; never ask for more than one step ahead. Pass `choice` with the
    caller's answer when the tutorial has a branch question."""
    return P.get_step(device, tutorial_id, n, choice)


@mcp.tool()
def get_lines(customer_id: str) -> dict:
    """List the lines and devices on the account, marking the calling line.
    Call this first on every troubleshooting call, before asking about the device."""
    return A.get_lines(customer_id)


@mcp.tool()
def get_line_status(customer_id: str, line_id: str) -> dict:
    """Whether a line is active or suspended and why. Call this before any device
    step when calls, texts or data are failing."""
    return A.get_line_status(customer_id, line_id)


@mcp.tool()
def check_outage(zip_code: str) -> dict:
    """Whether there is a network outage at a ZIP code. Call this before any device
    step when the symptom is connectivity."""
    return A.check_outage(zip_code)


@mcp.tool()
def get_data_usage(customer_id: str, line_id: str) -> dict:
    """Data used versus allowance and whether the line is throttled. Call this when
    the symptom is slow or missing data."""
    return A.get_data_usage(customer_id, line_id)


@mcp.tool()
def get_sim_status(customer_id: str, line_id: str) -> dict:
    """SIM type, activation and provisioning state. Call this when calls or texts fail
    on a line whose SIM changed recently."""
    return A.get_sim_status(customer_id, line_id)


@mcp.tool()
def refresh_network(customer_id: str, line_id: str) -> dict:
    """Send a network refresh to the line. Use this only after account checks are
    clean and before device steps, and tell the caller the phone may drop signal."""
    return A.refresh_network(customer_id, line_id)


@mcp.tool()
def send_guide_link(customer_id: str, line_id: str, device: str, tutorial_id: str) -> dict:
    """Text the caller the link to this exact tutorial. Call this when the caller asks
    for the guide, or chooses 'text me' when offered. Say honestly if it did not send."""
    return O.send_guide_link(customer_id, line_id, device, tutorial_id)


@mcp.tool()
def open_ticket(customer_id: str, line_id: str, summary: str) -> dict:
    """Open a support ticket with a one-line summary of what was tried. Call this when
    the tutorial is exhausted and the problem remains."""
    return O.open_ticket(customer_id, line_id, summary)


# json_response: the platform's tool discovery reads plain JSON replies. With SSE
# replies tools/list returned 200 but no tools were declared to the agent.
app = mcp.streamable_http_app(stateless_http=True, json_response=True, host="0.0.0.0")

from starlette.requests import Request  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402

from support_mcp import account_store  # noqa: E402
from support_mcp.wire_log import install as _install_wire_log  # noqa: E402


async def admin_reset(request: Request) -> JSONResponse:
    """Developer control, never exposed to the agent: reseed the demo account.

    POST /admin/reset?profile=P1 — behind Cloud Run IAM like everything else.
    """
    profile = request.query_params.get("profile", "")
    if profile not in account_store.profiles():
        return JSONResponse({"error": f"unknown profile '{profile}'", "profiles": account_store.profiles()}, 400)
    acct = account_store.reset_profile(os.environ.get("DEMO_CUSTOMER_ID", "cust_2001"), profile)
    return JSONResponse({"profile": profile, "customer_id": acct["customer_id"],
                         "lines": {k: v["status"] for k, v in acct["lines"].items()},
                         "outage": bool(acct.get("outage"))})


app.routes.append(Route("/admin/reset", admin_reset, methods=["POST"]))
app = _install_wire_log(app)
