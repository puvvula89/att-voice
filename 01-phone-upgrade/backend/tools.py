from backend import mock_data, stage_intents as si

def get_lines(tool_context) -> dict:
    """List the account's lines available for upgrade. Returns a count; UI data is in state."""
    lines = mock_data.get_account_lines()
    tool_context.state[si.data_key(si.LINE_SELECTOR)] = {"lines": lines}
    return {"count": len(lines)}

def get_eligible_phones(line_id: str, tool_context) -> dict:
    """List phones the given line is eligible for. Returns a count; UI data is in state."""
    phones = mock_data.get_phones_for_line(line_id)
    tool_context.state[si.data_key(si.PHONE_OPTIONS)] = {"phones": phones}
    return {"count": len(phones)}

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
    tool_context.state[si.data_key(si.CONFIRMATION)] = {
        "line": line_id, "phone": phone.get("name", phone_id),
        "monthly_price": phone.get("monthly_price"), "terms": "24-month installment",
    }
    return {"selected_phone": phone_id}

def confirm_upgrade(tool_context) -> dict:
    """Finalize the upgrade and stage the receipt data."""
    tool_context.state[si.data_key(si.RECEIPT)] = {
        "order_id": "UPG-100423",
        "line": tool_context.state.get("selected_line"),
        "phone": tool_context.state.get("selected_phone"),
        "ship_estimate": "3-5 business days",
    }
    return {"order_id": "UPG-100423"}

def render_component(stage_intent: str, tool_context) -> dict:
    """Render the named UI component. Choose stage_intent based on the user's request.
    Valid values: line_selector, phone_options, confirmation, receipt."""
    return {"status": "requested", "stage_intent": stage_intent}
