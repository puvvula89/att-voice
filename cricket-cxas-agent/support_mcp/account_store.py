"""Seeded, in-memory account state. One process, one dict; good enough for a demo.

Profiles P1..P7 (PRD §7) are patches over one two-line base account. DEMO_PROFILE
selects which patch seeds the demo customer the first time it is read.
"""
import copy
import json
import os
from pathlib import Path

_PROFILES = json.loads((Path(__file__).parent / "profiles.json").read_text())
_state: dict[str, dict] = {}


def _merge(base: dict, patch: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def profiles() -> list[str]:
    return [k for k in _PROFILES if not k.startswith("_")]


def reset_profile(customer_id: str, profile: str) -> dict:
    acct = _merge(_PROFILES["_base"], _PROFILES[profile])
    acct["customer_id"] = customer_id
    acct["profile"] = profile
    _state[customer_id] = acct
    return acct


def get(customer_id: str) -> dict | None:
    if customer_id not in _state and customer_id == _PROFILES["_base"]["customer_id"]:
        reset_profile(customer_id, os.environ.get("DEMO_PROFILE", "P3"))
    return _state.get(customer_id)
