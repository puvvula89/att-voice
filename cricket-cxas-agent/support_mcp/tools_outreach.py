"""Things the agent sends out of the call: a guide link by SMS, a ticket.

The SMS provider is optional. When it is not configured the tool says so in a
result the agent can speak honestly; it never raises.
"""
import base64
import itertools
import json
import os
import urllib.parse
import urllib.request

from support_mcp import account_store as store
from support_mcp.tools_procedures import _catalog_or_none

_tickets = itertools.count(1001)
_TWILIO_KEYS = ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM")


def _twilio_send(to: str, body: str) -> None:
    sid, tok, frm = (os.environ[k] for k in _TWILIO_KEYS)
    data = urllib.parse.urlencode({"To": to, "From": frm, "Body": body}).encode()
    req = urllib.request.Request(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json", data=data)
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{sid}:{tok}".encode()).decode())
    with urllib.request.urlopen(req, timeout=10) as r:
        json.load(r)


def send_guide_link(customer_id: str, line_id: str, device: str, tutorial_id: str) -> dict:
    a = store.get(customer_id)
    line = (a or {}).get("lines", {}).get(line_id)
    if not line:
        return {"sent": False, "message": f"No line '{line_id}' on this account."}
    cat = _catalog_or_none()
    if cat is None:
        return {"sent": False, "message": "The guide is unavailable right now; offer to open a ticket."}
    try:
        t = cat.get(device, tutorial_id)
    except KeyError:
        return {"sent": False, "message": f"No tutorial '{tutorial_id}' for '{device}'."}
    url, last4 = t.url, line["phone_last4"]
    to = line.get("sms_number") or os.environ.get("DEMO_SMS_NUMBER", "")
    configured = all(os.environ.get(k) for k in _TWILIO_KEYS) and to
    if not configured:
        return {"sent": False, "to_last4": last4, "url": url,
                "message": "Messaging is not configured; read the link aloud or show it on screen."}
    try:
        _twilio_send(to, f"Cricket support guide for your {line['device_label']}: {t.title}\n{url}")
        return {"sent": True, "to_last4": last4, "url": url, "message": f"Sent to the number ending {last4}."}
    except Exception as e:  # the agent must be able to say it did not go through
        return {"sent": False, "to_last4": last4, "url": url,
                "message": f"The text did not go through ({type(e).__name__})."}


def open_ticket(customer_id: str, line_id: str, summary: str) -> dict:
    return {"ticket_id": f"T-{next(_tickets)}", "summary": summary,
            "next_step": "A support specialist will call back within one business day; "
                         "a store visit is available sooner."}
