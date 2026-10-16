"""Normalized tutorial catalog: one JSON per device, loaded read-only.

Search is lexical on purpose. The agent's job is to turn a caller's words into a
query; this ranks titles, intros and step headings for the caller's device only,
so an iPhone caller can never be handed an Android article.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

# Caller words -> catalog words. Applied to the query only, so platform wording
# ("messages" on iOS, "texts" on Android) resolves inside the caller's own device.
SYNONYMS = {
    "texts": "messages texts sms",
    "text": "messages texts sms",
    "sms": "messages texts",
    "messages": "messages texts",
    "imessage": "messages",
    "internet": "wi-fi internet data",
    "wifi": "wi-fi",
    "data": "data internet mobile",
    "dead": "power on off turn",
    "won't turn on": "power on",
    "wont turn on": "power on",
    "calls": "calls call",
    "hotspot": "hotspot tethering",
    "slow": "slow slowdowns",
    "battery": "battery draining",
    "bluetooth": "bluetooth pair",
    "email": "email mail",
}
STOP = {"my", "the", "a", "is", "it", "i", "can't", "cant", "won't", "wont", "not", "to", "on", "phone"}
_tok = re.compile(r"[a-z0-9']+")


def tokens(s: str) -> list[str]:
    return _tok.findall(s.lower())


def read_catalog_dir(directory: Path | str) -> tuple[list[dict], list[dict]]:
    devices, tutorials = [], []
    for f in sorted(Path(directory).glob("*.json")):
        doc = json.loads(f.read_text())
        devices.append({"device": doc["device"], "os": doc["os"], "label": doc["label"]})
        tutorials += [{**rec, "device": doc["device"]} for rec in doc["tutorials"]]
    return devices, tutorials


@dataclass
class Path_:
    choices: list[str]
    steps: list[dict]


@dataclass
class Tutorial:
    id: str
    kind: str
    device: str
    os: str
    title: str
    intro: str
    url: str
    category: str
    paths: list[Path_] = field(default_factory=list)
    summary: str = ""
    symptoms: list[str] = field(default_factory=list)

    @property
    def step_count(self) -> int:
        return len(self.paths[0].steps) if self.paths else 0


class Catalog:
    def __init__(self, data: dict[str, dict[str, Tutorial]], meta: dict[str, dict]):
        self._d, self._meta = data, meta
        self._idx: dict[str, dict[str, dict[str, int]]] = {
            dev: {t.id: self._bag(t) for t in tuts.values()} for dev, tuts in data.items()
        }

    @staticmethod
    def _bag(t: Tutorial) -> dict[str, int]:
        words = tokens(t.title) * 3 + tokens(t.intro)
        for p in t.paths:
            for s in p.steps:
                words += tokens(s["text"].split("\n")[0])
        bag: dict[str, int] = {}
        for w in words:
            bag[w] = bag.get(w, 0) + 1
        return bag

    @classmethod
    def from_records(cls, devices: list[dict], tutorials: list[dict]) -> "Catalog":
        """devices: [{device, os, label}]; tutorials: catalog records, each carrying its `device`."""
        meta = {d["device"]: {"device": d["device"], "os": d["os"], "label": d["label"]} for d in devices}
        data: dict[str, dict[str, Tutorial]] = {d: {} for d in meta}
        for rec in tutorials:
            dev = rec["device"]
            data[dev][rec["id"]] = Tutorial(
                id=rec["id"], kind=rec["kind"], device=dev, os=meta[dev]["os"], title=rec["title"],
                intro=rec["intro"], url=rec["url"], category=rec.get("category", ""),
                paths=[Path_(choices=p["choices"], steps=p["steps"]) for p in rec["paths"]],
                summary=rec.get("summary", ""), symptoms=list(rec.get("symptoms", [])),
            )
        return cls(data, meta)

    @classmethod
    def load(cls, directory: Path | str) -> "Catalog":
        return cls.from_records(*read_catalog_dir(directory))

    def devices(self) -> list[dict]:
        return [self._meta[d] for d in sorted(self._meta)]

    def get(self, device: str, tutorial_id: str) -> Tutorial:
        return self._d[device][tutorial_id]  # KeyError on unknown device or id is the contract

    def search(self, device: str, query: str, limit: int = 5) -> list[dict]:
        q = query.lower()
        for k, v in SYNONYMS.items():
            if k in q:
                q += " " + v
        qt = set(tokens(q)) - STOP
        tuts, idx = self._d[device], self._idx[device]
        n = len(tuts)
        df = {w: sum(1 for b in idx.values() if w in b) for w in qt}
        out = []
        for tid, bag in idx.items():
            score = sum(bag[w] * math.log((n + 1) / (df[w] + 1)) for w in qt if w in bag)
            if score <= 0:
                continue
            t = tuts[tid]
            if t.kind == "article":
                score *= 1.5
            out.append({
                "id": t.id, "kind": t.kind, "title": t.title, "intro": t.intro[:240],
                "step_count": t.step_count, "branches": len(t.paths), "score": round(score, 3),
            })
        out.sort(key=lambda r: (-r["score"], r["kind"] != "article", r["title"]))
        return out[:limit]
