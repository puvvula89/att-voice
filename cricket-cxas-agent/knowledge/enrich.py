"""Ask Gemini to label each tutorial: a per-step call-ending flag, symptom phrases, a one-line summary.

    python -m knowledge.enrich                      # all devices, cached results reused
    python -m knowledge.enrich iphone-13 --workers 8

Gemini only labels; it never rewrites step text. Results are cached per tutorial by the hash of the
unlabelled record in knowledge/enrichment/<device>.json, so only new or changed tutorials are sent.
build_catalog applies the cache and writes every step where Gemini and the keyword rules disagree to
knowledge/enrichment/review.jsonl.
"""
import argparse
import hashlib
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

log = logging.getLogger(__name__)
OUT = Path(__file__).parent / "enrichment"
FLAGS = ("call_ending",)
RETRIES = 6   # rate-limited (429) calls back off 5, 10, 20, 40, 60 s
TIMEOUT_MS = 120_000   # a call with no timeout once hung a whole run

PROMPT = """You label phone troubleshooting steps for a voice agent that guides a caller ON THE PHONE BEING FIXED.
For each numbered step decide:
- call_ending: doing this step drops or interrupts a phone call on this device: it restarts the phone,
  powers it off or cuts its cellular service (restart, force restart, power off, airplane mode, reset
  network settings, reset all settings, erase all content, factory reset, removing the SIM, deleting an eSIM).
Judge only the action the step tells the user to do. A note saying NOT to do something does not count.
A step that shows a screen of options for the caller to pick from is call_ending if any listed option is.
A step that only describes what the guide covers, or turns the phone ON, is neither.
Also give a one-sentence summary of what the tutorial fixes and 3-8 short phrases a caller might say.

Device: {device}
Title: {title}
Steps:
{steps}"""

SCHEMA = {"type": "OBJECT", "properties": {
    "summary": {"type": "STRING"},
    "symptoms": {"type": "ARRAY", "items": {"type": "STRING"}},
    "steps": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "n": {"type": "INTEGER"}, "call_ending": {"type": "BOOLEAN"},
        "reason": {"type": "STRING"}},
        "required": ["n", "call_ending"]}}},
    "required": ["summary", "symptoms", "steps"]}


def content_hash(rec: dict) -> str:
    """Cache key: an unlabelled record's exact content, so only new or changed tutorials go to Gemini."""
    return hashlib.sha256(json.dumps(rec, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def unique_steps(rec: dict) -> list[dict]:
    seen, out = set(), []
    for p in rec["paths"]:
        for s in p["steps"]:
            if s["text"] not in seen:
                seen.add(s["text"])
                out.append(s)
    return out


def is_menu_prompt(s: dict) -> bool:
    return s["text"].rstrip().endswith(":") and bool(s.get("notes"))


def step_text(s: dict) -> str:
    """A menu prompt ("From this screen, you can…:") lists the caller's options as notes; send them too."""
    if is_menu_prompt(s):
        return s["text"] + " " + " | ".join(s["notes"])
    return s["text"]


def apply(rec: dict, result: dict) -> tuple[dict, list[dict]]:
    u = unique_steps(rec)
    labels: dict[str, dict] = {}
    for r in result.get("steps", []):
        if 1 <= r["n"] <= len(u):
            labels[u[r["n"] - 1]["text"]] = r
    diffs, seen, paths = [], set(), []
    for p in rec["paths"]:
        steps = []
        for s in p["steps"]:
            new, r = dict(s), labels.get(s["text"])
            if r:
                for f in FLAGS:
                    if bool(r[f]) != bool(s[f]) and (s["text"], f) not in seen:
                        seen.add((s["text"], f))
                        diffs.append({"tutorial_id": rec["id"], "n": s["n"], "flag": f, "rule": bool(s[f]),
                                      "gemini": bool(r[f]), "reason": r.get("reason", ""), "text": s["text"][:200]})
                    new[f] = bool(r[f])
            steps.append(new)
        paths.append({**p, "steps": steps})
    return {**rec, "paths": paths, "summary": result.get("summary", ""),
            "symptoms": list(result.get("symptoms", []))}, diffs


class Enricher:
    def __init__(self, generate):
        self.generate = generate

    def label(self, device: str, rec: dict) -> dict:
        body = "\n".join(f"{i + 1}. {step_text(s)[:800]}" for i, s in enumerate(unique_steps(rec)))
        return self.generate(PROMPT.format(device=device, title=rec["title"], steps=body))


def gemini_generate(model: str):
    from google import genai
    from google.genai import types
    client = genai.Client(vertexai=True, project=os.environ["GOOGLE_CLOUD_PROJECT"],
                          location=os.environ.get("GEMINI_LOCATION", "us-central1"),
                          http_options=types.HttpOptions(timeout=TIMEOUT_MS))
    cfg = types.GenerateContentConfig(response_mime_type="application/json", response_schema=SCHEMA, temperature=0)

    def generate(prompt: str) -> dict:
        return json.loads(client.models.generate_content(model=model, contents=prompt, config=cfg).text)
    return generate


def enrich_device(device: str, records: list[dict], enricher: Enricher, workers: int) -> dict:
    import httpx
    from google.genai import errors
    path = OUT / f"{device}.json"
    cache = json.loads(path.read_text()) if path.exists() else {}
    todo = [r for r in records if cache.get(r["id"], {}).get("hash") != content_hash(r)]

    def one(rec):
        for attempt in range(RETRIES):
            try:
                return rec, enricher.label(device, rec)
            except errors.APIError as e:
                if e.code != 429 or attempt == RETRIES - 1:
                    log.warning("enrich failed for %s/%s: %s", device, rec["id"], e)
                    return rec, None
                time.sleep(min(60, 5 * 2 ** attempt))
            except httpx.TimeoutException:
                log.warning("enrich timed out for %s/%s", device, rec["id"])
                return rec, None
            except json.JSONDecodeError as e:
                log.warning("enrich returned bad JSON for %s/%s: %s", device, rec["id"], e)
                return rec, None
        return rec, None

    failed = 0
    with ThreadPoolExecutor(workers) as pool:
        for rec, result in pool.map(one, todo):
            if result is None:
                failed += 1
            else:
                cache[rec["id"]] = {"hash": content_hash(rec), "result": result}
    OUT.mkdir(exist_ok=True)
    path.write_text(json.dumps(cache, indent=1, ensure_ascii=False))
    print(f"{device}: {len(todo)} sent, {failed} failed, {len(records) - len(todo)} cached, {len(cache)} total")
    return cache


def main():
    from knowledge.build_catalog import RAW, build_unlabelled
    load_dotenv(Path(__file__).parent.parent / ".env")
    ap = argparse.ArgumentParser()
    ap.add_argument("devices", nargs="*")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--model", default=os.environ.get("EXTRACT_MODEL", "gemini-2.5-flash"))
    a = ap.parse_args()
    enricher = Enricher(gemini_generate(a.model))
    for device in a.devices or sorted(f.stem for f in RAW.glob("*.json")):
        enrich_device(device, build_unlabelled(device)["tutorials"], enricher, a.workers)


if __name__ == "__main__":
    main()
