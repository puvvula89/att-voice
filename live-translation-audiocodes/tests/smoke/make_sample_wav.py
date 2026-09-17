"""Regenerate tests/smoke/sample_16k.wav (16kHz mono LINEAR16) via Cloud TTS + ADC.

Fixture generator for the CES bidi smoke test — it needs genuine speech because
CES only transcribes real speech (not tones/silence). Requires texttospeech.googleapis.com.
Run with .env loaded:  python tests/smoke/make_sample_wav.py
"""
import base64
import json
import os
import urllib.request

import google.auth
import google.auth.transport.requests

TEXT = "Hi, can you explain the late fee that showed up on my bill this month?"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_16k.wav")

creds, _ = google.auth.default(
    scopes=["https://www.googleapis.com/auth/cloud-platform"]
)
creds.refresh(google.auth.transport.requests.Request())

body = {
    "input": {"text": TEXT},
    "voice": {"languageCode": "en-US", "name": "en-US-Chirp3-HD-Charon"},
    "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": 16000},
}
req = urllib.request.Request(
    "https://texttospeech.googleapis.com/v1/text:synthesize",
    data=json.dumps(body).encode(),
    headers={
        "Authorization": f"Bearer {creds.token}",
        "Content-Type": "application/json",
        "x-goog-user-project": os.environ.get("GOOGLE_CLOUD_PROJECT", ""),
    },
)
with urllib.request.urlopen(req) as r:
    resp = json.load(r)
with open(OUT, "wb") as f:
    f.write(base64.b64decode(resp["audioContent"]))
print("wrote", OUT)
