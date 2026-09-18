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

# Every language Live Translate supports, from the model's own documentation.
# Ordered by code so typing "hi" in the picker lands on Hindi.
LANGUAGES = [
    {"code": "af", "name": "Afrikaans"},
    {"code": "ak", "name": "Akan"},
    {"code": "am", "name": "Amharic"},
    {"code": "ar", "name": "Arabic"},
    {"code": "az", "name": "Azerbaijani"},
    {"code": "be", "name": "Belarusian"},
    {"code": "bg", "name": "Bulgarian"},
    {"code": "bn", "name": "Bengali"},
    {"code": "ca", "name": "Catalan"},
    {"code": "cs", "name": "Czech"},
    {"code": "da", "name": "Danish"},
    {"code": "de", "name": "German"},
    {"code": "el", "name": "Greek"},
    {"code": "en", "name": "English"},
    {"code": "es", "name": "Spanish"},
    {"code": "et", "name": "Estonian"},
    {"code": "eu", "name": "Basque"},
    {"code": "fa", "name": "Persian"},
    {"code": "fi", "name": "Finnish"},
    {"code": "fil", "name": "Filipino"},
    {"code": "fr", "name": "French"},
    {"code": "gl", "name": "Galician"},
    {"code": "gu", "name": "Gujarati"},
    {"code": "ha", "name": "Hausa"},
    {"code": "he", "name": "Hebrew"},
    {"code": "hi", "name": "Hindi"},
    {"code": "hr", "name": "Croatian"},
    {"code": "hu", "name": "Hungarian"},
    {"code": "hy", "name": "Armenian"},
    {"code": "id", "name": "Indonesian"},
    {"code": "is", "name": "Icelandic"},
    {"code": "it", "name": "Italian"},
    {"code": "ja", "name": "Japanese"},
    {"code": "jv", "name": "Javanese"},
    {"code": "ka", "name": "Georgian"},
    {"code": "kk", "name": "Kazakh"},
    {"code": "km", "name": "Khmer"},
    {"code": "kn", "name": "Kannada"},
    {"code": "ko", "name": "Korean"},
    {"code": "lo", "name": "Lao"},
    {"code": "lt", "name": "Lithuanian"},
    {"code": "lv", "name": "Latvian"},
    {"code": "mk", "name": "Macedonian"},
    {"code": "ml", "name": "Malayalam"},
    {"code": "mn", "name": "Mongolian"},
    {"code": "mr", "name": "Marathi"},
    {"code": "ms", "name": "Malay"},
    {"code": "my", "name": "Burmese (Myanmar)"},
    {"code": "ne", "name": "Nepali"},
    {"code": "nl", "name": "Dutch"},
    {"code": "pa", "name": "Punjabi"},
    {"code": "pl", "name": "Polish"},
    {"code": "pt-BR", "name": "Portuguese (Brazil)"},
    {"code": "pt-PT", "name": "Portuguese (Portugal)"},
    {"code": "ro", "name": "Romanian"},
    {"code": "ru", "name": "Russian"},
    {"code": "rw", "name": "Kinyarwanda"},
    {"code": "sd", "name": "Sindhi"},
    {"code": "si", "name": "Sinhala"},
    {"code": "sk", "name": "Slovak"},
    {"code": "sl", "name": "Slovenian"},
    {"code": "sq", "name": "Albanian"},
    {"code": "sr", "name": "Serbian"},
    {"code": "su", "name": "Sundanese"},
    {"code": "sv", "name": "Swedish"},
    {"code": "sw", "name": "Swahili"},
    {"code": "ta", "name": "Tamil"},
    {"code": "te", "name": "Telugu"},
    {"code": "th", "name": "Thai"},
    {"code": "tr", "name": "Turkish"},
    {"code": "uk", "name": "Ukrainian"},
    {"code": "ur", "name": "Urdu"},
    {"code": "uz", "name": "Uzbek"},
    {"code": "vi", "name": "Vietnamese"},
    {"code": "zh-Hans", "name": "Chinese (Simplified)"},
    {"code": "zh-Hant", "name": "Chinese (Traditional)"},
    {"code": "zu", "name": "Zulu"},
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
