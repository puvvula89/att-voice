"""Procedure tools: pick a tutorial once, then page through it step by step.

get_step is the only thing the agent calls during a walk-through. It returns one
step, its warning, its image, and whether it ends the call, so the agent never
has to hold the whole tutorial in context and can never invent a step.
"""
import datetime as dt
import logging
import os
import re

from google.api_core.exceptions import GoogleAPIError

from knowledge.catalog import Catalog
from knowledge.content_store import CatalogCache, make_source
from support_mcp import progress_store

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


WINDOW = 15   # steps returned per get_tutorial call; 13 of 815 paths are longer


def is_gated(s: dict) -> bool:
    return bool(s["call_ending"] or s["destructive"])


def _shared_prefix(t) -> list[dict]:
    """Steps every branch shares, from the start up to the first difference."""
    out = []
    for group in zip(*(p.steps for p in t.paths)):
        if len({s["text"] for s in group}) > 1:
            break
        out.append(group[0])
    return out


def steps_for(t, choice: str):
    """(steps, complete, error). Without a choice a branching tutorial yields only the shared steps."""
    if len(t.paths) > 1 and not choice:
        return _shared_prefix(t), False, None
    p, err = _path(t, choice)
    if err:
        return None, False, err
    return p.steps, True, None


def _public_step(s: dict, titles: dict[str, str]) -> dict:
    if is_gated(s):
        return {"n": s["n"], "gated": True, "call_ending": s["call_ending"], "destructive": s["destructive"]}
    return {"n": s["n"], "gated": False, "heading": s["heading"], "text": s["text"], "notes": s["notes"],
            "warning": s["warning"], "image_url": s["image_url"],
            "linked_procedures": [{"id": titles[l], "title": l} for l in s["links"] if l in titles],
            "next_options": [o for o in s["options"] if not o.startswith("Next")]}


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


def get_tutorial(device: str, tutorial_id: str, choice: str = "", from_step: int = 1) -> dict:
    cat = _catalog_or_none()
    if cat is None:
        return CONTENT_ERROR
    try:
        t = cat.get(device, tutorial_id)
    except KeyError:
        return {"error": f"No tutorial '{tutorial_id}' for device '{device}'."}
    steps, complete, err = steps_for(t, choice)
    if err:
        return err
    window = [s for s in steps if s["n"] >= from_step][:WINDOW]
    more = complete and bool(window) and window[-1]["n"] < steps[-1]["n"]
    titles = _title_index(cat, device)
    return {
        "id": t.id, "kind": t.kind, "title": t.title, "summary": t.summary or _summary(t), "url": t.url,
        "step_count": len(steps) if complete else t.step_count,
        "steps": [_public_step(s, titles) for s in window],
        "path_complete": complete, "choice": choice or None,
        "branch_question": None if complete else _branch_question(t),
        "choices": [] if complete else _branch_choices(t),
        "next_from": window[-1]["n"] + 1 if more else None,
        "last_step": steps[-1]["n"] if complete and steps else None,
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
    if is_gated(s):
        return {"n": s["n"], "gated": True,
                "error": "This step ends the call or erases data; call checkpoint for it instead."}
    titles = _title_index(cat, device)
    return {
        "n": s["n"], "of": len(steps), "heading": s["heading"], "text": s["text"], "notes": s["notes"],
        "warning": s["warning"], "image_url": s["image_url"], "call_ending": s["call_ending"],
        "destructive": s["destructive"],
        "linked_procedures": [{"id": titles[l], "title": l} for l in s["links"] if l in titles],
        "is_last": idx == len(steps) - 1,
        "next_options": [o for o in s["options"] if not o.startswith("Next")],
    }


SAY_CALL_ENDING = ("This next step will disconnect us. When your phone is back, call again and I'll pick up "
                   "right where we left off.")
SAY_DESTRUCTIVE = ("This step will erase data on the phone and it can't be undone. Say exactly what it erases "
                   "and get a clear yes before giving the instruction.")


def checkpoint(customer_id: str, device: str, tutorial_id: str, n: int, choice: str = "") -> dict:
    cat = _catalog_or_none()
    if cat is None:
        return CONTENT_ERROR
    try:
        t = cat.get(device, tutorial_id)
    except KeyError:
        return {"error": f"No tutorial '{tutorial_id}' for device '{device}'."}
    steps, complete, err = steps_for(t, choice)
    if err:
        return err
    s = next((x for x in steps if x["n"] == n), None)
    if s is None:
        return {"error": f"Step {n} is not in the loaded steps; valid steps are {[x['n'] for x in steps]}."}
    if not is_gated(s):
        return {"error": f"Step {n} is not a checkpoint step; speak it from the tutorial you already have."}
    progress_store.save(customer_id, {"device": device, "tutorial_id": tutorial_id, "title": t.title,
                                      "choice": choice or None, "step_n": n,
                                      "updated_at": dt.datetime.now(dt.timezone.utc)})
    say = [m for m, on in ((SAY_DESTRUCTIVE, s["destructive"]), (SAY_CALL_ENDING, s["call_ending"])) if on]
    return {"n": n, "of": len(steps) if complete else None, "heading": s["heading"], "text": s["text"],
            "notes": s["notes"], "warning": s["warning"], "image_url": s["image_url"],
            "call_ending": s["call_ending"], "destructive": s["destructive"], "say_first": " ".join(say)}


def get_progress(customer_id: str) -> dict:
    rec = progress_store.load(customer_id)
    if not rec:
        return {"progress": None}
    window = dt.timedelta(minutes=float(os.environ.get("RESUME_WINDOW_MINUTES", "30")))
    age = dt.datetime.now(dt.timezone.utc) - rec["updated_at"]
    if age > window:
        return {"progress": None}
    return {"progress": {**{k: rec[k] for k in ("device", "tutorial_id", "title", "choice", "step_n")},
                         "resume_at": rec["step_n"] + 1, "minutes_ago": int(age.total_seconds() // 60)}}
