"""Support MCP server: callback resume plus the mock account/network store.

Tutorials are found and walked inside the agent (data store search and a step tool); this server
only holds what needs the network: account checks, outreach, and the saved place for callbacks.

Stateless streamable HTTP so Cloud Run may route each request anywhere. The
account store is per-process; with min-instances=1 and max-instances=1 that is
one consistent demo state, which is all a POC needs.
"""
import os

from mcp.server.mcpserver import MCPServer

from support_mcp import tools_account as A
from support_mcp import tools_outreach as O
from support_mcp import tools_progress as P

mcp = MCPServer("cricket-support")


@mcp.tool()
def get_progress(customer_id: str) -> dict:
    """Where this caller left off in a tutorial on a recent call that dropped, if anywhere.
    Call this once at the start of every troubleshooting call."""
    return P.get_progress(customer_id)


@mcp.tool()
def save_progress(customer_id: str, walk: str, steps_by_id: str) -> dict:
    """Save the caller's place so a dropped call can resume. Call this when next_step returns
    save_first, before you speak that step. Pass walk and steps_by_id as empty strings; they are
    filled in for you."""
    return P.save_progress(customer_id, walk, steps_by_id)


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
def send_guide_link(customer_id: str, line_id: str, title: str, url: str) -> dict:
    """Text the caller the guide's link, using the title and url from the search result.
    Call this when the caller asks for the guide, or chooses 'text me' when offered.
    Say honestly if it did not send."""
    return O.send_guide_link(customer_id, line_id, title, url)


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

from support_mcp import account_store, progress_store  # noqa: E402
from support_mcp.wire_log import install as _install_wire_log  # noqa: E402


async def admin_reset(request: Request) -> JSONResponse:
    """Developer control, never exposed to the agent: reseed the demo account and forget its last call.

    POST /admin/reset?profile=P1 — behind Cloud Run IAM like everything else.
    """
    profile = request.query_params.get("profile", "")
    if profile not in account_store.profiles():
        return JSONResponse({"error": f"unknown profile '{profile}'", "profiles": account_store.profiles()}, 400)
    customer_id = os.environ.get("DEMO_CUSTOMER_ID", "cust_2001")
    acct = account_store.reset_profile(customer_id, profile)
    progress_store.forget(customer_id)  # a reseeded account starts with no call to resume
    return JSONResponse({"profile": profile, "customer_id": acct["customer_id"],
                         "lines": {k: v["status"] for k, v in acct["lines"].items()},
                         "outage": bool(acct.get("outage"))})


app.routes.append(Route("/admin/reset", admin_reset, methods=["POST"]))
app = _install_wire_log(app)
