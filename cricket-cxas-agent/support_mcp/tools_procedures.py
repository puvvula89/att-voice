"""Procedure tools: pick a tutorial once, then page through it step by step.

get_step is the only thing the agent calls during a walk-through. It returns one
step, its warning, its image, and whether it ends the call, so the agent never
has to hold the whole tutorial in context and can never invent a step.
"""
import logging
import os
import re

from google.api_core.exceptions import GoogleAPIError

from knowledge.catalog import Catalog
from knowledge.content_store import CatalogCache, make_source

log = logging.getLogger(__name__)
CONTENT_ERROR = {"error": "Tutorial content is unavailable right now. Offer to text the guide link or open a ticket."}
_cache: CatalogCache | None = None


def catalog() -> Catalog:
    global _cache
    if _cache is None:
        _cache = CatalogCache(make_source(), float(os.environ.get("CONTENT_CHECK_SECONDS", "60")))
    return _cache.get()


def _catalog_or_none() -> Catalog | None:
    try:
        return catalog()
    except (RuntimeError, GoogleAPIError):
        log.exception("tutorial content unavailable")
        return None


def _summary(t) -> str:
    sents = re.split(r"(?<=[.!?])\s+", t.intro.strip())
    k = t.step_count
    return (" ".join(sents[:2]).strip() + f" {k} steps, about {k // 2 + 1} minutes.").strip()


def _branch_choices(t) -> list[str]:
    """Choices that actually fork the tutorial: those not shared by every path."""
    if len(t.paths) < 2:
        return []
    common = set.intersection(*(set(p.choices) for p in t.paths))
    return sorted({c for p in t.paths for c in p.choices} - common)


def _branch_question(t) -> str | None:
    """The last line of the step just before the paths diverge."""
    if len(t.paths) < 2:
        return None
    a, b = t.paths[0].steps, t.paths[1].steps
    for i, (x, y) in enumerate(zip(a, b)):
        if x["text"] != y["text"]:
            prev = a[i - 1] if i else x
            return prev["text"].split("\n")[-1]
    return None


def _path(t, choice: str):
    if len(t.paths) == 1:
        return t.paths[0], None
    forks = _branch_choices(t)
    for p in t.paths:
        if choice and choice in p.choices and choice in forks:
            return p, None
    return None, {
        "error": "This tutorial branches; pass one of valid_choices as `choice`.",
        "valid_choices": forks,
    }


def _title_index(cat: Catalog, device: str) -> dict[str, str]:
    return {t.title: t.id for t in cat._d[device].values()}


def find_tutorials(device: str, symptom: str) -> dict:
    cat = _catalog_or_none()
    if cat is None:
        return CONTENT_ERROR
    try:
        results = cat.search(device, symptom)
    except KeyError:
        known = [d["device"] for d in cat.devices()]
        return {"device": device, "results": [], "note": f"Unknown device '{device}'. Known devices: {known}"}
    return {"device": device, "results": results}


def get_tutorial(device: str, tutorial_id: str) -> dict:
    cat = _catalog_or_none()
    if cat is None:
        return CONTENT_ERROR
    try:
        t = cat.get(device, tutorial_id)
    except KeyError:
        return {"error": f"No tutorial '{tutorial_id}' for device '{device}'."}
    steps0 = t.paths[0].steps
    return {
        "id": t.id, "kind": t.kind, "title": t.title, "summary": _summary(t),
        "step_count": t.step_count, "url": t.url, "branch_question": _branch_question(t),
        "choices": _branch_choices(t),
        "call_ending_steps": [s["n"] for s in steps0 if s["call_ending"]],
        "destructive_steps": [s["n"] for s in steps0 if s["destructive"]],
    }


def get_step(device: str, tutorial_id: str, n: int, choice: str = "") -> dict:
    cat = _catalog_or_none()
    if cat is None:
        return CONTENT_ERROR
    try:
        t = cat.get(device, tutorial_id)
    except KeyError:
        return {"error": f"No tutorial '{tutorial_id}' for device '{device}'."}
    p, err = _path(t, choice)
    if err:
        return err
    steps = p.steps
    idx = next((i for i, s in enumerate(steps) if s["n"] == n), None)
    if idx is None:
        return {"error": f"Step {n} does not exist; this tutorial has {len(steps)} steps."}
    s = steps[idx]
    titles = _title_index(cat, device)
    return {
        "n": s["n"], "of": len(steps), "heading": s["heading"], "text": s["text"], "notes": s["notes"],
        "warning": s["warning"], "image_url": s["image_url"], "call_ending": s["call_ending"],
        "destructive": s["destructive"],
        "linked_procedures": [{"id": titles[l], "title": l} for l in s["links"] if l in titles],
        "is_last": idx == len(steps) - 1,
        "next_options": [o for o in s["options"] if not o.startswith("Next")],
    }
