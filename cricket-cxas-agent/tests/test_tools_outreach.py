import pytest

from support_mcp import account_store
from support_mcp.tools_outreach import open_ticket, send_guide_link

URL = "https://www.cricketwireless.com/support/device-tutorials#/tutorial/iphone-13/27.0.0/wifi"

@pytest.fixture(autouse=True)
def seed(monkeypatch):
    for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM"):
        monkeypatch.delenv(k, raising=False)
    account_store.reset_profile("cust_2001", "P3")


def test_unconfigured_sms_is_honest_not_fatal():
    r = send_guide_link("cust_2001", "L1", "Wi-Fi slow", URL)
    assert r["sent"] is False and r["url"] == URL
    assert "not configured" in r["message"]


def test_a_link_that_is_not_a_cricket_guide_is_refused():
    r = send_guide_link("cust_2001", "L1", "Wi-Fi slow", "https://example.com/x")
    assert r["sent"] is False and "url" in r["message"]


def test_unknown_line_is_an_error_not_an_exception():
    r = send_guide_link("cust_2001", "L9", "Wi-Fi slow", URL)
    assert r["sent"] is False and "line" in r["message"].lower()


def test_ticket_has_id_and_summary():
    r = open_ticket("cust_2001", "L2", "Galaxy A15 will not power on after force restart")
    assert r["ticket_id"].startswith("T-") and "power" in r["summary"]
