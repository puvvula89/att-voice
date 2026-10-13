import pytest

from support_mcp import account_store
from support_mcp.tools_outreach import open_ticket, send_guide_link

RESET = "feature_network_reset-resetting-your-iphone-s-settings-and-network-settings"


@pytest.fixture(autouse=True)
def seed(monkeypatch):
    for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM"):
        monkeypatch.delenv(k, raising=False)
    account_store.reset_profile("cust_2001", "P3")


def test_unconfigured_sms_is_honest_not_fatal():
    r = send_guide_link("cust_2001", "L1", "iphone-13", RESET)
    assert r["sent"] is False
    assert r["url"].startswith("https://www.cricketwireless.com")
    assert "not configured" in r["message"]


def test_url_is_the_exact_device_tutorial():
    r = send_guide_link("cust_2001", "L2", "galaxy-a15-5g", "155859-can-t-make-or-receive-calls")
    assert "galaxy-a15-5g" in r["url"]


def test_unknown_tutorial_is_an_error_not_an_exception():
    r = send_guide_link("cust_2001", "L1", "iphone-13", "nope")
    assert r["sent"] is False and "tutorial" in r["message"].lower()


def test_ticket_has_id_and_summary():
    r = open_ticket("cust_2001", "L2", "Galaxy A15 will not power on after force restart")
    assert r["ticket_id"].startswith("T-") and "power" in r["summary"]
