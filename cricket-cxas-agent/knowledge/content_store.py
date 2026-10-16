"""Where tutorial content comes from at runtime, and when to reload it.

CONTENT_BACKEND=local reads knowledge/catalog/*.json (tests and local runs); =firestore reads the
`devices` and `tutorials` collections written by knowledge/load_firestore.py. Either way the server
holds one Catalog in memory and reloads it only when the source's version changes, checked at most
every CONTENT_CHECK_SECONDS. A content update therefore never needs a redeploy.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from knowledge.catalog import Catalog

log = logging.getLogger(__name__)
DEFAULT_DIR = Path(__file__).parent / "catalog"


class LocalSource:
    def __init__(self, directory: Path | str | None = None):
        self.dir = Path(directory or os.environ.get("CATALOG_DIR", DEFAULT_DIR))

    def version(self) -> str:
        return str(max((f.stat().st_mtime_ns for f in self.dir.glob("*.json")), default=0))

    def load(self) -> Catalog:
        return Catalog.load(self.dir)


class FirestoreSource:
    def __init__(self, client=None):
        if client is None:
            from google.cloud import firestore
            client = firestore.Client(project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
                                      database=os.environ.get("FIRESTORE_DATABASE", "(default)"))
        self.db = client

    def version(self) -> str:
        snap = self.db.collection("meta").document("content").get()
        return (snap.to_dict() or {}).get("version", "") if snap.exists else ""

    def load(self) -> Catalog:
        devices = [s.to_dict() for s in self.db.collection("devices").stream()]
        if not devices:
            raise RuntimeError("No tutorial content in Firestore; run python -m knowledge.load_firestore")
        tutorials = [s.to_dict() for s in self.db.collection("tutorials").stream()]
        return Catalog.from_records(devices, tutorials)


def make_source():
    backend = os.environ.get("CONTENT_BACKEND", "local")
    if backend == "local":
        return LocalSource()
    if backend == "firestore":
        return FirestoreSource()
    raise ValueError(f"CONTENT_BACKEND must be 'local' or 'firestore', not {backend!r}")


class CatalogCache:
    """Serve one Catalog; reload when the source version changes, checked at most every check_every s."""

    def __init__(self, source, check_every: float = 60.0, clock=time.monotonic):
        self.source, self.check_every, self.clock = source, check_every, clock
        self._cat: Catalog | None = None
        self._version: str | None = None
        self._checked = float("-inf")

    def get(self) -> Catalog:
        now = self.clock()
        if self._cat is not None and now - self._checked < self.check_every:
            return self._cat
        self._checked = now
        try:
            v = self.source.version()
        except Exception:  # noqa: BLE001 - any store failure: keep serving what is loaded, logged
            if self._cat is None:
                raise
            log.exception("content version check failed; serving the loaded catalog")
            return self._cat
        if self._cat is None or v != self._version:
            self._cat, self._version = self.source.load(), v
        return self._cat
