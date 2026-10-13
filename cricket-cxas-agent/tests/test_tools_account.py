import pytest

from support_mcp import account_store
from support_mcp.tools_account import (check_outage, get_data_usage, get_line_status, get_lines,
                                       refresh_network)


@pytest.fixture(autouse=True)
def seed():
    account_store.reset_profile("cust_2001", "P3")


def test_two_lines_with_calling_line_marked():
    r = get_lines("cust_2001")
    assert len(r["lines"]) == 2 and sum(l["is_calling_line"] for l in r["lines"]) == 1


def test_lines_are_returned_both_never_first_only():
    assert {l["device"] for l in get_lines("cust_2001")["lines"]} == {"iphone-13", "galaxy-a15-5g"}


def test_p1_is_suspended():
    account_store.reset_profile("cust_2001", "P1")
    assert get_line_status("cust_2001", "L1")["status"] == "SUSPENDED_NONPAY"


def test_p2_has_outage():
    account_store.reset_profile("cust_2001", "P2")
    zip_code = get_lines("cust_2001")["zip_code"]
    assert check_outage(zip_code)["outage"] is True


def test_p3_is_clean():
    assert get_line_status("cust_2001", "L1")["status"] == "ACTIVE"
    assert check_outage(get_lines("cust_2001")["zip_code"])["outage"] is False
    assert get_data_usage("cust_2001", "L1")["throttled"] is False


def test_refresh_is_recorded():
    r = refresh_network("cust_2001", "L1")
    assert r["ok"] and account_store.get("cust_2001")["lines"]["L1"]["last_refresh"]


def test_unknown_customer():
    assert "error" in get_lines("cust_9999")
