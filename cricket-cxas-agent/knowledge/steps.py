"""Per-step normalization and the two safety flags the agent relies on.

The flags are heuristics over the step's own instruction text, never its notes:
a note that says "do not choose Erase" must not make the step destructive.
"""
import re

CALL_ENDING = re.compile(
    r"\b(restart|reboot|power (your|the|it) (phone|iphone|device) off|power off|"
    r"turn (your|the|it) (phone|iphone|device) off|turn off (your|the) (phone|iphone|device)|"
    r"airplane mode|remove (the|your) sim|reset network settings|force[- ]restart|"
    r"hold (the )?(side|power) button)\b",
    re.I,
)
DESTRUCTIVE = re.compile(
    r"\b(erase all content|factory (data )?reset|reset all settings|delete all esims?|"
    r"erase (your|the|this) (phone|iphone|device)|wipe)\b",
    re.I,
)
OVERVIEW = re.compile(r"within this guide|you'll learn how to|in this guide", re.I)
DESTRUCTIVE_MENTION = re.compile(
    r"(erase all content|factory (data )?reset|reset all settings|delete all esims?|wipe)", re.I
)


def _split_heading(text: str) -> tuple[str, str]:
    lines = [l for l in text.split("\n") if l.strip()]
    if len(lines) >= 2 and len(lines[0]) <= 70 and not lines[0].endswith((".", ":")):
        return lines[0].strip(), "\n".join(lines[1:]).strip()
    return "", text.strip()


def normalize_step(raw: dict, tutorial_title: str) -> dict:
    heading, body = _split_heading(raw["text"])
    instr = body if heading else raw["text"]
    notes = raw.get("notes", [])
    warning = next((n for n in notes if DESTRUCTIVE_MENTION.search(n)), None)
    # A menu prompt ("From this screen, you can…:") lists its options as notes; the
    # action the caller takes is in those notes, so they count toward the flags.
    if instr.rstrip().endswith(":"):
        instr = instr + "\n" + "\n".join(notes)
    # An article's overview step lists what the guide covers; it instructs nothing.
    if OVERVIEW.search(instr):
        instr = ""
    return {
        "n": raw["n"],
        "heading": heading,
        "text": body,
        "notes": list(raw.get("notes", [])),
        "links": list(raw.get("links", [])),
        "options": list(raw.get("options", [])),
        "substeps": list(raw.get("substeps", [])),
        "image_url": raw.get("image_url", ""),
        "call_ending": bool(CALL_ENDING.search(instr)),
        "destructive": bool(DESTRUCTIVE.search(instr)),
        "warning": warning,
    }
