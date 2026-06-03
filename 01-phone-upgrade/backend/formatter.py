import json
from pathlib import Path
from backend import stage_intents as si

_TEMPLATE_DIR = Path(__file__).parent / "templates"

def _load_template(stage_intent: str) -> dict:
    if stage_intent not in si.ALL:
        raise ValueError(f"Unknown stage_intent: {stage_intent}")
    return json.loads((_TEMPLATE_DIR / f"{stage_intent}.json").read_text())

def build_payload(stage_intent: str, state: dict) -> dict:
    """Pure transform: template + state data -> UI payload. No LLM."""
    template = _load_template(stage_intent)
    key = si.data_key(stage_intent)
    if key not in state:
        raise KeyError(f"No state data for {stage_intent} (expected '{key}')")
    payload = dict(template)
    payload["stage_intent"] = stage_intent
    payload["data"] = state[key]
    return payload
