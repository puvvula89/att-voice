from mcp_server import catalog


def test_lines_have_required_fields():
    lines = catalog.get_account_lines()
    assert len(lines) == 3
    for line in lines:
        assert set(line) >= {"line_id", "last4", "device", "eligible"}


def test_eligible_phones_for_known_line():
    phones = catalog.get_phones_for_line("line_1243")
    assert len(phones) >= 1
    for p in phones:
        assert set(p) >= {"phone_id", "name", "image", "monthly_price", "trade_in"}


def test_phones_for_unknown_line_is_empty():
    assert catalog.get_phones_for_line("nope") == []


# --- staging-ready tool functions -------------------------------------------

def test_list_lines_shape():
    out = catalog.list_lines()
    assert out["lines"][0]["line_id"] == "line_1243"
    assert len(out["lines"]) == 3


def test_eligible_phones_includes_line_last4():
    out = catalog.eligible_phones("line_1243")
    assert out["line_last4"] == "1243"
    assert out["phones"][0]["phone_id"] == "iphone_17"


def test_select_line_returns_choice_and_digits():
    assert catalog.select_line("line_1243") == {
        "selected_line": "line_1243", "line_last4": "1243"}


def test_select_phone_builds_confirmation():
    out = catalog.select_phone("line_1243", "iphone_17")
    assert out["selected_phone"] == "iphone_17"
    assert out["selected_phone_name"] == "iPhone 17"
    conf = out["confirmation"]
    assert conf["line_last4"] == "1243"
    assert conf["phone"] == "iPhone 17"
    assert conf["monthly_price"] == 32.99
    assert conf["terms"] == "24-month installment"


def test_confirm_upgrade_builds_receipt():
    out = catalog.confirm_upgrade("line_1243", "iphone_17")
    assert out["order_id"] == "UPG-100423"
    receipt = out["receipt"]
    assert receipt["order_id"] == "UPG-100423"
    assert receipt["phone"] == "iPhone 17"
    assert receipt["ship_estimate"] == "3-5 business days"
