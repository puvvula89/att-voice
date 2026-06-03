import pytest
from backend import formatter, stage_intents as si

def test_line_selector_payload():
    state = {si.data_key(si.LINE_SELECTOR): {"lines": [{"last4": "1243"}]}}
    payload = formatter.build_payload(si.LINE_SELECTOR, state)
    assert payload["component"] == "line_selector"
    assert payload["data"]["lines"] == [{"last4": "1243"}]
    assert payload["selectable"] is True

def test_phone_options_payload():
    state = {si.data_key(si.PHONE_OPTIONS): {"phones": [{"phone_id": "iphone_17"}]}}
    payload = formatter.build_payload(si.PHONE_OPTIONS, state)
    assert payload["component"] == "phone_options"
    assert payload["data"]["phones"][0]["phone_id"] == "iphone_17"

def test_missing_state_raises():
    with pytest.raises(KeyError):
        formatter.build_payload(si.PHONE_OPTIONS, {})

def test_unknown_intent_raises():
    with pytest.raises(ValueError):
        formatter.build_payload("bogus", {})
