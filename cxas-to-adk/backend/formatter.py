import json
import re
from pathlib import Path
from backend import stage_intents as si

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_TOKEN = re.compile(r"\{\{(\w+)\}\}")

def _load_template(stage_intent: str) -> dict:
    if stage_intent not in si.ALL:
        raise ValueError(f"Unknown stage_intent: {stage_intent}")
    return json.loads((_TEMPLATE_DIR / f"{stage_intent}.json").read_text())

def _subst(node, ctx: dict):
    """Recursively replace {{token}} occurrences with values from ctx (missing -> '')."""
    if isinstance(node, str):
        return _TOKEN.sub(lambda m: str(ctx.get(m.group(1), "")), node)
    if isinstance(node, list):
        return [_subst(x, ctx) for x in node]
    if isinstance(node, dict):
        return {k: _subst(v, ctx) for k, v in node.items()}
    return node

def build_payload(stage_intent: str, state: dict) -> dict:
    """Pure transform: template + staged tool data -> UI payload. No LLM.

    Templates carry {{tokens}}; this fills them from the data the tools staged
    for this stage_intent. List sections (options_from + option_template) are
    expanded once per item, with each item's fields available as tokens.
    """
    template = _load_template(stage_intent)
    key = si.data_key(stage_intent)
    if key not in state:
        raise KeyError(f"No state data for {stage_intent} (expected '{key}')")
    data = state[key]

    # Top-level context: scalar fields of the staged data (e.g. line_last4, order_id).
    ctx = {k: v for k, v in data.items() if not isinstance(v, list)}

    payload = {"stage_intent": stage_intent, "title": template.get("title", "")}
    if "message" in template:
        payload["message"] = _subst(template["message"], ctx)

    if "options_from" in template:
        items = data.get(template["options_from"], [])
        option_template = template["option_template"]
        payload["options"] = [_subst(option_template, {**ctx, **item}) for item in items]

    if "summary" in template:
        payload["summary"] = _subst(template["summary"], ctx)
    if "primary" in template:
        payload["primary"] = _subst(template["primary"], ctx)

    return payload


def resume_pending_ui(state: dict) -> dict | None:
    """The screen to re-show when a session resumes.

    Prefer the last explicitly rendered screen (``state['pending_ui']``). If none
    was ever set — e.g. the session ran over IVR, where ``render_component`` is
    suppressed so no ``pending_ui`` is written — reconstruct the furthest-progressed
    screen from the data the tools already staged. The data tools (``get_lines`` …
    ``confirm_upgrade``) run on every channel, so ``state['data:<stage>']`` is present
    even for an IVR-origin session; rebuilding from it lands a cross-channel handoff
    (IVR → web, or either → web) on the correct UI. Returns the same payload
    ``render_component`` would have produced, so web-origin sessions are unaffected.
    """
    state = state or {}
    stored = state.get("pending_ui")
    if stored:
        return stored
    for stage in (si.RECEIPT, si.CONFIRMATION, si.PHONE_OPTIONS, si.LINE_SELECTOR):
        if si.data_key(stage) in state:
            try:
                return build_payload(stage, state)
            except (KeyError, ValueError):
                continue
    return None
