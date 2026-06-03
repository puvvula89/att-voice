_LINES = [
    {"line_id": "line_1243", "last4": "1243", "device": "iPhone 12", "eligible": True},
    {"line_id": "line_5588", "last4": "5588", "device": "Pixel 6", "eligible": True},
    {"line_id": "line_9001", "last4": "9001", "device": "iPhone 11", "eligible": False},
]

_PHONES = {
    "line_1243": [
        {"phone_id": "iphone_17", "name": "iPhone 17", "image": "/img/iphone17.png",
         "monthly_price": 32.99, "trade_in": 400},
        {"phone_id": "pixel_x", "name": "Pixel X", "image": "/img/pixelx.png",
         "monthly_price": 27.99, "trade_in": 300},
        {"phone_id": "galaxy_s9", "name": "Galaxy S9", "image": "/img/galaxys9.png",
         "monthly_price": 29.99, "trade_in": 350},
    ],
    "line_5588": [
        {"phone_id": "pixel_x", "name": "Pixel X", "image": "/img/pixelx.png",
         "monthly_price": 27.99, "trade_in": 300},
    ],
}

def get_account_lines():
    return [dict(line) for line in _LINES]

def get_phones_for_line(line_id):
    return [dict(p) for p in _PHONES.get(line_id, [])]
