# 01 — Phone Upgrade (voice)

Voice phone-upgrade agent on Google ADK + Gemini Live.

## Setup (ADC / Vertex AI)
1. `python -m venv .venv && source .venv/bin/activate`
2. `pip install -r requirements.txt`
3. `gcloud auth application-default login`
4. `cp .env.example .env` and set `GOOGLE_CLOUD_PROJECT` (and region if not us-central1).

## Run — option A: adk web (quick agent/voice test, generic dev UI)
Shows ADK's built-in dev UI (voice + tool-call trace). Does NOT render the custom phone-upgrade cards.
```
export SSL_CERT_FILE=$(python -m certifi)   # required for voice
adk web --port 8001
```
Open the printed URL, select the `phone_upgrade` agent, click the mic.

## Run — option B: FastAPI relay + custom UI (the full demo)
```
uvicorn backend.server:app --reload        # :8000  (run from 01-phone-upgrade/)
```
In another terminal: `cd frontend && python -m http.server 5500`, open http://localhost:5500, grant mic.

> Run adk web and the relay on different ports (adk web on 8001, relay on 8000) — the frontend expects the relay on :8000.

## Test
`pytest tests/ -v` (from `01-phone-upgrade/`)
