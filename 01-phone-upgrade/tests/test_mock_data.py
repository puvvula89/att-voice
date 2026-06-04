from backend import mock_data

def test_lines_have_required_fields():
    lines = mock_data.get_account_lines()
    assert len(lines) == 3
    for line in lines:
        assert set(line) >= {"line_id", "last4", "device", "eligible"}

def test_eligible_phones_for_known_line():
    phones = mock_data.get_phones_for_line("line_1243")
    assert len(phones) >= 1
    for p in phones:
        assert set(p) >= {"phone_id", "name", "image", "monthly_price", "trade_in"}

def test_phones_for_unknown_line_is_empty():
    assert mock_data.get_phones_for_line("nope") == []
