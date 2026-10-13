"""Account and network tools: what the caller cannot see."""
from datetime import datetime, timezone

from support_mcp import account_store as store


def _acct(customer_id: str):
    a = store.get(customer_id)
    return (a, None) if a else (None, {"error": f"No account '{customer_id}'."})


def _line(customer_id: str, line_id: str):
    a, err = _acct(customer_id)
    if err:
        return None, err
    l = a["lines"].get(line_id)
    if not l:
        return None, {"error": f"No line '{line_id}' on this account.", "valid_lines": list(a["lines"])}
    return l, None


def get_lines(customer_id: str) -> dict:
    a, err = _acct(customer_id)
    if err:
        return err
    keys = ("line_id", "phone_last4", "device", "device_label", "os", "is_calling_line")
    return {"customer_id": customer_id, "name": a["name"], "zip_code": a["zip_code"],
            "lines": [{k: l[k] for k in keys} for l in a["lines"].values()]}


def get_line_status(customer_id: str, line_id: str) -> dict:
    l, err = _line(customer_id, line_id)
    return err or {"line_id": line_id, "status": l["status"], "since": l["since"], "reason": l["reason"]}


def check_outage(zip_code: str) -> dict:
    a = store.get("cust_2001")
    o = (a or {}).get("outage")
    if o and o["zip_code"] == zip_code:
        return {"zip_code": zip_code, "outage": True, "started": o["started"], "eta": o["eta"],
                "services": o["services"]}
    return {"zip_code": zip_code, "outage": False}


def get_data_usage(customer_id: str, line_id: str) -> dict:
    l, err = _line(customer_id, line_id)
    return err or {k: l[k] for k in ("used_gb", "allowance_gb", "throttled", "cycle_ends")}


def get_sim_status(customer_id: str, line_id: str) -> dict:
    l, err = _line(customer_id, line_id)
    return err or {k: l[k] for k in ("sim_type", "activated", "changed_days_ago", "provisioned")}


def refresh_network(customer_id: str, line_id: str) -> dict:
    l, err = _line(customer_id, line_id)
    if err:
        return err
    l["last_refresh"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {"ok": True, "line_id": line_id, "wait_seconds": 60,
            "message": "Network refresh sent. The phone may briefly lose signal while it reconnects."}
