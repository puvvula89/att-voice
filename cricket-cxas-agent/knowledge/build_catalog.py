"""Build knowledge/catalog/<device>.json from knowledge/raw/<device>.json.

Raw records are what the extractor saw. Catalog records are what the tools serve:
steps normalized with safety flags, procedures given a single path, landing pages
dropped. Run after any re-extraction. Output is committed so the server needs no
browser.
"""
import json
from pathlib import Path

from knowledge import enrich
from knowledge.steps import normalize_step

RAW = Path(__file__).parent / "raw"
OUT = Path(__file__).parent / "catalog"
REVIEW = Path(__file__).parent / "step_review.json"
RISKS = {"drops": (True, False), "may_drop": (False, True), "safe": (False, False)}
LABELS = {
    "iphone-13": "iPhone 13",
    "moto-g-2025": "Moto G 2025",
    "moto-g-stylus-5g-2024": "Moto G Stylus 5G 2024",
    "galaxy-a15-5g": "Galaxy A15 5G",
}


def build_unlabelled(device: str) -> dict:
    raw = json.loads((RAW / f"{device}.json").read_text())
    tutorials, os_version = [], None
    for rec in raw.values():
        os_version = rec["os"]
        if not rec["steps"]:
            continue  # landing pages such as "Getting to know your device"
        paths = rec.get("paths") or [{"choices": [], "steps": rec["steps"]}]
        # Vendor intros repeat the device label and the title as leading lines.
        label = LABELS.get(device, device)
        lines = [l.strip() for l in rec["intro"].strip().split("\n")]
        while lines and lines[0] in ("", rec["title"], label):
            lines.pop(0)
        intro = "\n".join(lines).strip()
        tutorials.append({
            "id": rec["id"], "kind": rec["kind"], "title": rec["title"], "intro": intro,
            "url": rec["url"], "category": rec.get("category", ""),
            "paths": [
                {"choices": p["choices"],
                 "steps": [normalize_step(s, rec["title"]) for s in p["steps"] if s["n"] is not None]}
                for p in paths
            ],
        })
    tutorials.sort(key=lambda t: (t["kind"] != "article", t["title"]))
    return {"device": device, "os": os_version, "label": LABELS.get(device, device), "tutorials": tutorials}


def apply_review(rec: dict, entries: list[dict]) -> tuple[dict, list[dict]]:
    """Hand-reviewed risk wins over the labels: drops warns first, may_drop checkpoints silently.

    Entries match a step by number and text (a guide can repeat a tap such as "Tap Delete eSIM again.");
    returns the entries that no longer match.
    """
    by_key = {(e["n"], e["text"]): e for e in entries}
    hit, paths = set(), []
    for p in rec["paths"]:
        steps = []
        for s in p["steps"]:
            e = by_key.get((s["n"], s["text"]))
            if e:
                hit.add((e["n"], e["text"]))
                s = {**s, "call_ending": RISKS[e["risk"]][0], "may_drop": RISKS[e["risk"]][1]}
            steps.append(s)
        paths.append({**p, "steps": steps})
    return {**rec, "paths": paths}, [e for e in entries if (e["n"], e["text"]) not in hit]


def build(device: str) -> dict:
    """The unlabelled catalog with cached Gemini labels, then the hand review, applied."""
    doc = build_unlabelled(device)
    review = json.loads(REVIEW.read_text()).get(device, {}) if REVIEW.exists() else {}
    cache_path = enrich.OUT / f"{device}.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    out, diffs = [], []
    for rec in doc["tutorials"]:
        hit = cache.get(rec["id"])
        if hit and hit["hash"] == enrich.content_hash(rec):
            rec, d = enrich.apply(rec, hit["result"])
            diffs += [{**x, "device": device} for x in d]
        # may_drop is set here, not in normalize_step, so it never changes the hash the label cache keys on
        rec = {**rec, "paths": [{**p, "steps": [{**s, "may_drop": False} for s in p["steps"]]} for p in rec["paths"]]}
        if rec["id"] in review:
            rec, stale = apply_review(rec, review[rec["id"]])
            for e in stale:
                print(f"{device}/{rec['id']} step {e['n']}: review entry no longer matches the step text")
        out.append(rec)
    return {**doc, "tutorials": out, "_review": diffs}


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    review = []
    for f in sorted(RAW.glob("*.json")):
        doc = build(f.stem)
        review += doc.pop("_review")
        (OUT / f.name).write_text(json.dumps(doc, indent=1, ensure_ascii=False))
        print(f.stem, len(doc["tutorials"]), "tutorials")
    enrich.OUT.mkdir(exist_ok=True)
    (enrich.OUT / "review.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in review))
    print(len(review), "flag disagreements written to", enrich.OUT / "review.jsonl")
