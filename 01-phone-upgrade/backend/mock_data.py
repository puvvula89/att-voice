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

def get_account_lines():
    return [dict(line) for line in _LINES]

def get_phones_for_line(line_id):
    phones = []
    for pid in _LINE_OPTIONS.get(line_id, []):
        spec = _CATALOG[pid]
        phones.append({"phone_id": pid, "image": f"/img/{pid}.png", **spec})
    return phones
