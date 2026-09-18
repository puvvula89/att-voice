"""Call settings the console writes and the bridge reads.

They live in a file next to the recordings rather than in memory: locally the console
runs as its own process, so the two cannot share a variable, and a setting has to
survive either side restarting. Both deployments -- two processes on one laptop, or
one container on Cloud Run -- share that directory.

A translation session is opened when a call starts, so a change here applies to the
next call, never the one in progress.
"""
from __future__ import annotations

import json
import os

DEFAULT_CALLER_LANGUAGE = "hi"

# A working subset of the languages Live Translate accepts, for the picker. The API
# takes any supported BCP-47 code, so `caller_language` is not restricted to these.
LANGUAGES = [
    {"code": "hi", "name": "Hindi"},
    {"code": "es", "name": "Spanish"},
    {"code": "fr", "name": "French"},
    {"code": "de", "name": "German"},
    {"code": "pt", "name": "Portuguese"},
    {"code": "it", "name": "Italian"},
    {"code": "ar", "name": "Arabic"},
    {"code": "zh", "name": "Chinese (Mandarin)"},
    {"code": "ja", "name": "Japanese"},
    {"code": "ko", "name": "Korean"},
    {"code": "ru", "name": "Russian"},
    {"code": "vi", "name": "Vietnamese"},
    {"code": "tl", "name": "Filipino"},
    {"code": "bn", "name": "Bengali"},
    {"code": "ta", "name": "Tamil"},
    {"code": "te", "name": "Telugu"},
    {"code": "mr", "name": "Marathi"},
    {"code": "gu", "name": "Gujarati"},
    {"code": "pa", "name": "Punjabi"},
    {"code": "ur", "name": "Urdu"},
]


def path() -> str:
    return os.environ.get(
        "SETTINGS_PATH",
        os.path.join(os.environ.get("RECORDINGS_DIR", "recordings"), "settings.json"),
    )


def load() -> dict:
    try:
        with open(path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save(values: dict) -> dict:
    current = load()
    current.update(values)
    target = path()
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
    return current


def caller_language() -> str:
    """The saved choice, else CALLER_LANGUAGE from the environment, else Hindi."""
    saved = load().get("caller_language")
    if saved:
        return saved
    return os.environ.get("CALLER_LANGUAGE") or DEFAULT_CALLER_LANGUAGE
