"""Where a caller's place in a tutorial is kept between calls.

Written before a step that can drop the call, read when the caller calls back.
PROGRESS_BACKEND=firestore keeps it in progress/{customer_id}; otherwise in process memory.
"""
import os

_mem: dict[str, dict] = {}
_db = None


def _firestore():
    global _db
    if _db is None:
        from google.cloud import firestore
        _db = firestore.Client(project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
                               database=os.environ.get("FIRESTORE_DATABASE", "(default)"))
    return _db


def _remote() -> bool:
    return os.environ.get("PROGRESS_BACKEND", "local") == "firestore"


def save(customer_id: str, record: dict) -> None:
    if _remote():
        _firestore().collection("progress").document(customer_id).set(record)
    else:
        _mem[customer_id] = dict(record)


def load(customer_id: str) -> dict | None:
    if _remote():
        snap = _firestore().collection("progress").document(customer_id).get()
        return snap.to_dict() if snap.exists else None
    rec = _mem.get(customer_id)
    return dict(rec) if rec else None


def forget(customer_id: str) -> None:
    if _remote():
        _firestore().collection("progress").document(customer_id).delete()
    else:
        _mem.pop(customer_id, None)


def reset() -> None:
    _mem.clear()
