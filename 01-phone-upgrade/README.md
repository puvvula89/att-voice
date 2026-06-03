# 01 — Phone Upgrade (voice)

Voice phone-upgrade agent on Google ADK + Gemini Live.

## Run
1. `python -m venv .venv && source .venv/bin/activate`
2. `pip install -r requirements.txt`
3. Set `GOOGLE_API_KEY` (or ADK Vertex env) in the environment.
4. `uvicorn backend.server:app --reload` (from `01-phone-upgrade/`)
5. Open `frontend/index.html` against the local server.

## Test
`pytest tests/ -v` (from `01-phone-upgrade/`)
