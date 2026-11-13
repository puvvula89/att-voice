"""after_model_callback for Tech Support, chat only: under the reply that gives a step, attach the
step's picture (a signed link from `image_links`) and quick replies, as a rich content payload the
web chat renders. The model only writes the text. On voice nothing is attached.
A step reply is headed "Step 3 of 13".
A guide link the customer asked for (`show_link`) is attached the same way, as a card that opens it.

The model sometimes writes the previous step again after next_step has moved on. When the reply fits
the previous step's words better than the new step's, the new step's own text is sent instead.

On both channels, a turn that has just fetched a step cannot end the session: an end_session call in
that turn is dropped, because the model sometimes takes the caller's "done" as goodbye. In chat an
end_session call is always dropped and the goodbye kept, so the customer can go on typing. On voice,
when the model ends the call without saying anything, a short goodbye is added."""
import json
import re
from typing import Optional

CHIPS = ["Done", "Say it again", "I'm stuck"]


def _fit(reply: str, step_text: str) -> float:
    """Share of the step's longer words that the reply uses."""
    words = {w for w in re.findall(r"[a-z]{4,}", step_text.lower())}
    return sum(w in reply.lower() for w in words) / len(words) if words else 1.0


def after_model_callback(callback_context: CallbackContext, llm_response: LlmResponse) -> Optional[LlmResponse]:
    v = callback_context.variables
    shown = v.get("show_image") or ""
    parts = llm_response.content.parts if llm_response.content else []
    said = json.loads(v.get("step_said") or "{}")
    ending = [p for p in parts if getattr(getattr(p, "function_call", None), "name", "") == "end_session"]
    chat = v.get("channel") == "chat"
    # "done" in a walk means the step is finished, not the conversation. And a chat is never ended from
    # here: ending it locks the customer's message box, so the goodbye is said and the chat stays open.
    dropped = bool(ending and (v.get("step_given") or chat))
    if dropped:
        parts = [p for p in parts if p not in ending]
        if not any((getattr(p, "text", None) or "").strip() for p in parts):
            last = said.get("of") and said.get("n") == said.get("of")   # the guide's closing step
            parts = [Part(text=(said.get("cur", "").strip() + " Did that do the trick?") if last else
                           ("Next: " + said.get("cur", "").strip() + " Tell me when that's done."))] if v.get("step_given") \
                else [Part(text="You're all set. Thanks for chatting with Cricket Wireless. "
                                "If anything else comes up, just type it here.")]
    elif ending and not any((getattr(p, "text", None) or "").strip() for p in parts):
        return LlmResponse(content=Content(parts=[Part(text="Thanks for calling Cricket Wireless. Take care.")] + parts))
    kept = LlmResponse(content=Content(parts=parts)) if dropped else None
    link = json.loads(v.get("show_link") or "{}")
    if v.get("channel") != "chat" or not (shown or link):
        return kept
    if not parts or any(getattr(p, "function_call", None) for p in parts):
        return kept
    text = "".join(p.text or "" for p in parts)
    if not text.strip():
        return kept
    v["show_image"] = v["show_link"] = ""
    cur, prev = said.get("cur", ""), said.get("prev", "")
    if shown and cur and prev and _fit(text, cur) < 0.5 and _fit(text, prev) > _fit(text, cur):
        text = "Next: " + cur.strip() + (" See the picture below." if shown != "-" else "") + " Tell me when that's done."
    if shown and said.get("of"):   # a step reply: head it with where the customer is in the guide
        text = "**Step %d of %d**\n\n" % (said["n"], said["of"]) + text.strip()
    cards = []
    if link:
        cards.append([{"type": "info", "title": link.get("title", "Guide"), "subtitle": "Open the full guide",
                       "actionLink": link.get("url", "")}])
    pic = json.loads(v.get("image_links") or "{}").get(shown, "")
    if pic:
        cards.append([{"type": "image", "rawUrl": pic, "accessibilityText": "Screen for this step"}])
    if shown:
        cards.append([{"type": "chips", "options": [{"text": c} for c in CHIPS]}])
    return LlmResponse(content=Content(parts=[Part(text=text),
                                              Part.from_json(data=json.dumps({"richContent": cards}))]))
