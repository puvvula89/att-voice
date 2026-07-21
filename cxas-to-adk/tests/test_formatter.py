import pytest
from backend import formatter, stage_intents as si

def test_line_selector_expands_options():
    state = {si.data_key(si.LINE_SELECTOR): {"lines": [
        {"line_id": "line_1243", "last4": "1243", "device": "iPhone 12"}]}}
    p = formatter.build_payload(si.LINE_SELECTOR, state)
    assert p["stage_intent"] == "line_selector"
    opt = p["options"][0]
    assert opt["header"] == "Line ending 1243"
    assert "iPhone 12" in opt["eyebrow"]
    assert opt["submitValue"] == "line_1243"

def test_phone_options_fills_price_and_image():
    state = {si.data_key(si.PHONE_OPTIONS): {"line_last4": "1243", "phones": [
        {"phone_id": "iphone_17", "name": "iPhone 17",
         "image": "data:image/png;base64,AAA", "monthly_price": 32.99}]}}
    p = formatter.build_payload(si.PHONE_OPTIONS, state)
    assert "1243" in p["message"]              # message token filled
    opt = p["options"][0]
    assert opt["header"] == "iPhone 17"
    assert opt["image"] == "data:image/png;base64,AAA"
    assert opt["price"]["amount"] == "32.99"   # numeric token -> string
    assert opt["submitValue"] == "iphone_17"

def test_confirmation_summary_and_primary():
    state = {si.data_key(si.CONFIRMATION): {
        "line_last4": "1243", "phone": "iPhone 17",
        "monthly_price": 32.99, "terms": "24-month installment"}}
    p = formatter.build_payload(si.CONFIRMATION, state)
    vals = {r["label"]: r["value"] for r in p["summary"]}
    assert "1243" in vals["Line"]
    assert vals["New phone"] == "iPhone 17"
    assert "32.99" in vals["Monthly"]
    assert p["primary"]["submitValue"] == "yes, confirm"
    assert p["primary"]["label"] == "Place the order"

def test_receipt_summary():
    state = {si.data_key(si.RECEIPT): {
        "order_id": "UPG-100423", "phone": "iPhone 17", "ship_estimate": "3-5 business days"}}
    p = formatter.build_payload(si.RECEIPT, state)
    vals = {r["label"]: r["value"] for r in p["summary"]}
    assert vals["Order number"] == "UPG-100423"
    assert vals["Ships in"] == "3-5 business days"

def test_missing_state_raises():
    with pytest.raises(KeyError):
        formatter.build_payload(si.PHONE_OPTIONS, {})

def test_unknown_intent_raises():
    with pytest.raises(ValueError):
        formatter.build_payload("bogus", {})


# --- resume_pending_ui: cross-channel screen reconstruction -----------------

def test_resume_prefers_stored_pending_ui():
    # A web-origin session already rendered a screen — return it untouched.
    stored = {"stage_intent": "phone_options", "options": []}
    state = {"pending_ui": stored, si.data_key(si.LINE_SELECTOR): {"lines": []}}
    assert formatter.resume_pending_ui(state) is stored


def test_resume_reconstructs_furthest_stage_when_no_pending_ui():
    # IVR-origin session: data staged by the tools, but pending_ui never written.
    # Rebuild the furthest-progressed screen (phone_options here, not line_selector).
    state = {
        si.data_key(si.LINE_SELECTOR): {"lines": [
            {"line_id": "line_1243", "last4": "1243", "device": "iPhone 12"}]},
        si.data_key(si.PHONE_OPTIONS): {"line_last4": "1243", "phones": [
            {"phone_id": "iphone_17", "name": "iPhone 17",
             "image": "data:image/png;base64,AAA", "monthly_price": 32.99}]},
    }
    p = formatter.resume_pending_ui(state)
    assert p["stage_intent"] == "phone_options"
    assert p["options"][0]["submitValue"] == "iphone_17"


def test_resume_none_when_nothing_staged():
    assert formatter.resume_pending_ui({}) is None
    assert formatter.resume_pending_ui(None) is None
