"""after_model_callback for Tech Support, chat only: under the reply that gives a step, attach the
step's picture (a signed link from `image_links`) and quick replies, as a rich content payload the
web chat renders. The model only writes the text. On voice nothing is attached."""
import json
from typing import Optional

CHIPS = ["Done", "Say it again", "I'm stuck"]


def after_model_callback(callback_context: CallbackContext, llm_response: LlmResponse) -> Optional[LlmResponse]:
    v = callback_context.variables
    shown = v.get("show_image") or ""
    if v.get("channel") != "chat" or not shown:
        return None
    parts = llm_response.content.parts if llm_response.content else []
    if not parts or any(getattr(p, "function_call", None) for p in parts):
        return None
    text = "".join(p.text or "" for p in parts)
    if not text.strip():
        return None
    v["show_image"] = ""
    cards = []
    link = json.loads(v.get("image_links") or "{}").get(shown, "")
    if link:
        cards.append([{"type": "image", "rawUrl": link, "accessibilityText": "Screen for this step"}])
    cards.append([{"type": "chips", "options": [{"text": c} for c in CHIPS]}])
    return LlmResponse(content=Content(parts=[Part(text=text),
                                              Part.from_json(data=json.dumps({"richContent": cards}))]))
