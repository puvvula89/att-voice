from backend import mock_data, stage_intents as si

def _last4(line_id: str) -> str:
    line = next((l for l in mock_data.get_account_lines() if l["line_id"] == line_id), {})
    return line.get("last4", line_id)

def get_lines(tool_context) -> dict:
    """List the account's lines available for upgrade. Use the returned line_id values when calling select_line."""
    lines = mock_data.get_account_lines()
    tool_context.state[si.data_key(si.LINE_SELECTOR)] = {"lines": lines}
    return {"lines": [{"line_id": l["line_id"], "last4": l["last4"], "device": l["device"]} for l in lines]}

def get_eligible_phones(line_id: str, tool_context) -> dict:
    """List phones the given line is eligible for. Use the returned phone_id values when calling select_phone."""
    phones = mock_data.get_phones_for_line(line_id)
    tool_context.state[si.data_key(si.PHONE_OPTIONS)] = {
        "line_last4": _last4(line_id), "phones": phones,
    }
    return {"phones": [{"phone_id": p["phone_id"], "name": p["name"], "monthly_price": p["monthly_price"]} for p in phones]}

def select_line(line_id: str, tool_context) -> dict:
    """Record the line the user chose."""
    tool_context.state["selected_line"] = line_id
    return {"selected_line": line_id}

def select_phone(phone_id: str, tool_context) -> dict:
    """Record the phone the user chose and stage the confirmation data."""
    tool_context.state["selected_phone"] = phone_id
    line_id = tool_context.state.get("selected_line")
    phones = mock_data.get_phones_for_line(line_id)
    phone = next((p for p in phones if p["phone_id"] == phone_id), {"phone_id": phone_id})
    tool_context.state["selected_phone_name"] = phone.get("name", phone_id)
    tool_context.state[si.data_key(si.CONFIRMATION)] = {
        "line_last4": _last4(line_id), "phone": phone.get("name", phone_id),
        "monthly_price": phone.get("monthly_price"), "terms": "24-month installment",
    }
    return {"selected_phone": phone_id}

def confirm_upgrade(tool_context) -> dict:
    """Finalize the upgrade and stage the receipt data."""
    tool_context.state[si.data_key(si.RECEIPT)] = {
        "order_id": "UPG-100423",
        "phone": tool_context.state.get("selected_phone_name",
                                        tool_context.state.get("selected_phone")),
        "ship_estimate": "3-5 business days",
    }
    return {"order_id": "UPG-100423"}

def render_component(stage_intent: str, tool_context) -> dict:
    """Render the named UI component. Choose stage_intent based on the user's request.
    Valid values: line_selector, phone_options, confirmation, receipt."""
    return {"status": "requested", "stage_intent": stage_intent}

def end_call(tool_context) -> dict:
    """End the session after the customer confirms they need nothing else. Call this
    only after saying the closing line aloud."""
    return {"status": "ending"}
