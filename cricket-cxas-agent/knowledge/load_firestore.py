"""Load the tutorial catalog into Firestore.

    python -m knowledge.load_firestore            # upsert changed tutorials, delete removed ones
    python -m knowledge.load_firestore --dry-run  # print what would change

Collections: devices/{device} {device, os, label}; tutorials/{device}__{tutorial_id} = the catalog
record plus content_hash and updated_at; meta/content {version, updated_at}. The server reloads when
meta/content.version changes, so this command is how new content goes live.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from knowledge.catalog import read_catalog_dir

CATALOG = Path(__file__).parent / "catalog"
BOOKKEEPING = ("content_hash", "updated_at")


def doc_id(device: str, tutorial_id: str) -> str:
    return f"{device}__{tutorial_id}"


def content_hash(rec: dict) -> str:
    body = {k: v for k, v in rec.items() if k not in BOOKKEEPING}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def content_version(hashes) -> str:
    return hashlib.sha256("".join(sorted(hashes)).encode()).hexdigest()[:16]


def plan_upserts(tutorials: list[dict], existing: dict[str, str]):
    want = {doc_id(r["device"], r["id"]): {**r, "content_hash": content_hash(r)} for r in tutorials}
    writes = [(i, d) for i, d in want.items() if existing.get(i) != d["content_hash"]]
    deletes = sorted(set(existing) - set(want))
    return writes, deletes


def write(db, devices: list[dict], tutorials: list[dict]) -> tuple[int, int]:
    existing = {s.id: (s.to_dict() or {}).get("content_hash", "") for s in db.collection("tutorials").stream()}
    writes, deletes = plan_upserts(tutorials, existing)
    now = dt.datetime.now(dt.timezone.utc)
    for d in devices:
        db.collection("devices").document(d["device"]).set(d)
    for i, doc in writes:
        db.collection("tutorials").document(i).set({**doc, "updated_at": now})
    for i in deletes:
        db.collection("tutorials").document(i).delete()
    if writes or deletes or not db.collection("meta").document("content").get().exists:
        hashes = [content_hash(r) for r in tutorials]
        db.collection("meta").document("content").set({"version": content_version(hashes), "updated_at": now})
    return len(writes), len(deletes)


def main():
    load_dotenv(Path(__file__).parent.parent / ".env")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    devices, tutorials = read_catalog_dir(CATALOG)
    from google.cloud import firestore
    db = firestore.Client(project=os.environ["GOOGLE_CLOUD_PROJECT"],
                          database=os.environ.get("FIRESTORE_DATABASE", "(default)"))
    if a.dry_run:
        existing = {s.id: (s.to_dict() or {}).get("content_hash", "")
                    for s in db.collection("tutorials").select(["content_hash"]).stream()}
        writes, deletes = plan_upserts(tutorials, existing)
        print(f"would write {len(writes)}, delete {len(deletes)} of {len(tutorials)} tutorials")
        return
    w, d = write(db, devices, tutorials)
    print(f"wrote {w}, deleted {d}, {len(tutorials)} tutorials across {len(devices)} devices")


if __name__ == "__main__":
    main()
