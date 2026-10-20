"""Save a caller's place before a step that can drop the call, and hand it back when they call back.

The agent's step tool keeps the place in session variables; the agent's callback copies them into
save_progress, so the model never handles them. A saved place is used once, within the resume window.
"""
import datetime as dt
import json
import os

from support_mcp import progress_store


def save_progress(customer_id: str, walk: str, steps_by_id: str) -> dict:
    resume = json.loads(walk or "{}").get("resume")
    if not resume:
        return {"saved": False, "message": "Nothing to save yet; carry on with the step."}
    progress_store.save(customer_id, {"walk": walk, "steps_by_id": steps_by_id,
                                      "saved_at": dt.datetime.now(dt.timezone.utc)})
    return {"saved": True, "step": resume["step"]}


def get_progress(customer_id: str) -> dict:
    rec = progress_store.load(customer_id)
    if not rec:
        return {"progress": None}
    progress_store.forget(customer_id)  # resume once; the walk saves again at its next risky step
    age = dt.datetime.now(dt.timezone.utc) - rec["saved_at"]
    if age > dt.timedelta(minutes=float(os.environ.get("RESUME_WINDOW_MINUTES", "30"))):
        return {"progress": None}
    resume = json.loads(rec["walk"])["resume"]
    title = json.loads(rec["steps_by_id"] or "{}").get(resume["tutorial_id"], {}).get("title", "")
    return {"progress": {**resume, "title": title, "minutes_ago": int(age.total_seconds() // 60)},
            "walk": rec["walk"], "steps_by_id": rec["steps_by_id"]}
