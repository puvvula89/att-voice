"""Pure phone-upgrade catalog logic.

No ADK, no ``tool_context`` — safe to import in the standalone MCP server
process *and* in unit tests. The MCP tools (``mcp_server/server.py``) and the
agent-side ``after_tool_callback`` (``backend/callbacks.py``) both build on the
return shapes defined here:

- ``list_lines``        -> ``{"lines": [...]}``
- ``eligible_phones``   -> ``{"line_last4": str, "phones": [...]}``
- ``select_line``       -> ``{"selected_line": str, "line_last4": str}``
- ``select_phone``      -> ``{"selected_phone": str, "selected_phone_name": str,
                              "confirmation": {...}}``
- ``confirm_upgrade``   -> ``{"order_id": str, "receipt": {...}}``

These payloads carry everything the formatter needs; the callback stages them
into session state under the ``data:<stage_intent>`` keys.
"""

_LINES = [
    {"line_id": "line_1243", "last4": "1243", "device": "iPhone 12", "eligible": True},
    {"line_id": "line_5588", "last4": "5588", "device": "Pixel 6", "eligible": True},
    {"line_id": "line_9001", "last4": "9001", "device": "iPhone 11", "eligible": True},
]

# Device catalogue. image paths are placeholders (the UI renders an emoji until
# real assets exist) — kept so the schema has an `image` field to fill.
_CATALOG = {
    "iphone_17":       {"name": "iPhone 17",        "monthly_price": 32.99, "trade_in": 400},
    "iphone_17_pro":   {"name": "iPhone 17 Pro",    "monthly_price": 41.99, "trade_in": 500},
    "pixel_x":         {"name": "Pixel X",          "monthly_price": 27.99, "trade_in": 300},
    "pixel_x_pro":     {"name": "Pixel X Pro",      "monthly_price": 35.99, "trade_in": 380},
    "galaxy_s9":       {"name": "Galaxy S9",        "monthly_price": 29.99, "trade_in": 350},
    "galaxy_s9_ultra": {"name": "Galaxy S9 Ultra",  "monthly_price": 38.99, "trade_in": 420},
}

# Each line is eligible for several phones.
_LINE_OPTIONS = {
    "line_1243": ["iphone_17", "pixel_x", "galaxy_s9"],
    "line_5588": ["pixel_x", "pixel_x_pro", "iphone_17", "galaxy_s9"],
    "line_9001": ["iphone_17", "iphone_17_pro", "galaxy_s9_ultra", "pixel_x"],
}

_TERMS = "24-month installment"
_ORDER_ID = "UPG-100423"
_SHIP_ESTIMATE = "3-5 business days"


# --- low-level accessors (kept for direct data tests) ------------------------

def get_account_lines():
    return [dict(line) for line in _LINES]


def get_phones_for_line(line_id):
    phones = []
    for pid in _LINE_OPTIONS.get(line_id, []):
        spec = _CATALOG[pid]
        phones.append({"phone_id": pid, "image": f"/img/{pid}.png", **spec})
    return phones


def _last4(line_id):
    line = next((l for l in _LINES if l["line_id"] == line_id), None)
    return line["last4"] if line else line_id


def _phone(line_id, phone_id):
    return next(
        (p for p in get_phones_for_line(line_id) if p["phone_id"] == phone_id),
        {"phone_id": phone_id},
    )


# --- staging-ready tool functions (consumed by MCP server + callback) --------

def list_lines() -> dict:
    """All account lines eligible for an upgrade."""
    return {"lines": get_account_lines()}


def eligible_phones(line_id: str) -> dict:
    """Phones the given line can upgrade to, plus the line's display digits."""
    return {"line_last4": _last4(line_id), "phones": get_phones_for_line(line_id)}


def select_line(line_id: str) -> dict:
    """Record the line the customer chose."""
    return {"selected_line": line_id, "line_last4": _last4(line_id)}


def select_phone(line_id: str, phone_id: str) -> dict:
    """Record the phone choice and build the confirmation summary."""
    phone = _phone(line_id, phone_id)
    name = phone.get("name", phone_id)
    return {
        "selected_phone": phone_id,
        "selected_phone_name": name,
        "confirmation": {
            "line_last4": _last4(line_id),
            "phone": name,
            "monthly_price": phone.get("monthly_price"),
            "terms": _TERMS,
        },
    }


def confirm_upgrade(line_id: str, phone_id: str) -> dict:
    """Finalize the upgrade and build the receipt."""
    name = _phone(line_id, phone_id).get("name", phone_id)
    return {
        "order_id": _ORDER_ID,
        "receipt": {
            "order_id": _ORDER_ID,
            "phone": name,
            "ship_estimate": _SHIP_ESTIMATE,
        },
    }
