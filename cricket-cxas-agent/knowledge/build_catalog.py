"""Build knowledge/catalog/<device>.json from knowledge/raw/<device>.json.

Raw records are what the extractor saw. Catalog records are what the tools serve:
steps normalized with safety flags, procedures given a single path, landing pages
dropped. Run after any re-extraction. Output is committed so the server needs no
browser.
"""
import json
from pathlib import Path

from knowledge.steps import normalize_step

RAW = Path(__file__).parent / "raw"
OUT = Path(__file__).parent / "catalog"
LABELS = {
    "iphone-13": "iPhone 13",
    "moto-g-2025": "Moto G 2025",
    "moto-g-stylus-5g-2024": "Moto G Stylus 5G 2024",
    "galaxy-a15-5g": "Galaxy A15 5G",
}


def build(device: str) -> dict:
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


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for f in sorted(RAW.glob("*.json")):
        doc = build(f.stem)
        (OUT / f.name).write_text(json.dumps(doc, indent=1, ensure_ascii=False))
        print(f.stem, len(doc["tutorials"]), "tutorials")
