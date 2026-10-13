from starlette.testclient import TestClient

from support_mcp import account_store
from support_mcp.server import app


def test_admin_reset_switches_profile_and_rejects_unknown():
    # One client: the MCP session manager allows a single lifespan per app instance.
    with TestClient(app) as c:
        r = c.post("/admin/reset", params={"profile": "P1"})
        assert r.status_code == 200 and r.json()["profile"] == "P1"
        assert account_store.get("cust_2001")["lines"]["L1"]["status"] == "SUSPENDED_NONPAY"
        c.post("/admin/reset", params={"profile": "P3"})
        assert account_store.get("cust_2001")["lines"]["L1"]["status"] == "ACTIVE"
        assert c.post("/admin/reset", params={"profile": "P99"}).status_code == 400
