# Deployment

Deploys to **any** GCP project — all config comes from `.env`, nothing is hardcoded.

Target topology (every hop in the cloud):

```
Browser (UI, Cloud Run) ⇄ Relay (Cloud Run) ⇄ Agent (Vertex AI Agent Engine) ⇄ MCP tools (Cloud Run)
```

## One-command deploy

```bash
cp .env.example .env        # set GOOGLE_CLOUD_PROJECT (+ region/names if you like)
gcloud auth application-default login
deploy/deploy_all.sh        # stands the whole stack up, prints the UI URL
```

`deploy_all.sh` deploys in order and threads dynamic outputs between steps
(none are hardcoded): MCP → captures its URL → agent (Agent Engine) with that
URL → captures the engine id → relay with the engine name → UI, injecting the
relay URL into `frontend/config.js`. Open the printed **UI URL**, click Start.

Tear it all down:

```bash
deploy/destroy_all.sh       # deletes the 3 Cloud Run services, the agent, and the bucket
```

## Prerequisites

- APIs enabled: `aiplatform`, `run`, `cloudbuild`, `artifactregistry`, `storage`.
- The Cloud Run runtime service account needs Agent Engine access (`roles/aiplatform.user`,
  or the default compute SA's `roles/editor`) so the relay can reach the agent.
- `.env` set (see `.env.example`). ADC configured (`gcloud auth application-default login`).

## Config (`.env`)

| Var | Purpose |
|---|---|
| `GOOGLE_CLOUD_PROJECT` | **required** — target project |
| `GOOGLE_CLOUD_LOCATION` | region (default `us-central1`) |
| `LIVE_MODEL`, `LIVE_VOICE` | Live model id + prebuilt voice |
| `MCP_SERVICE`, `RELAY_SERVICE`, `UI_SERVICE` | Cloud Run service names |
| `AGENT_DISPLAY_NAME` | Agent Engine display name |
| `AE_STAGING_BUCKET` | staging bucket (default `<project>-agent-engine`) |
| `RELAY_MIN_INSTANCES` | keep a relay warm (default `1`; `0` to save cost) |
| `MCP_SERVER_URL`, `AGENT_ENGINE_NAME` | produced by the deploy script (don't hand-set) |

## What each step does (for reference / manual runs)

1. **MCP server** — `gcloud run deploy $MCP_SERVICE --source mcp_server …` (stateless FastMCP, `/mcp`).
2. **Agent → Agent Engine** — `python deploy/deploy_agent_engine.py` packages `backend/` as source,
   wires `MCP_SERVER_URL`, deploys EXPERIMENTAL server mode (required for bidi), `python_version=3.12`
   (no py3.14 base image). Do **not** set the reserved `GOOGLE_CLOUD_PROJECT` env var on the engine.
   Verify: `python deploy/probe_agent_engine.py` → all four screens + audio. Limits: Preview; 10-min/stream.
3. **Relay** — `gcloud run deploy $RELAY_SERVICE --source . …` with `AGENT_ENGINE_NAME` set → proxy mode.
4. **UI** — `gcloud run deploy $UI_SERVICE --source frontend …` (HTTPS → mic works); the relay URL is
   written into `frontend/config.js` first.

## Relay topology toggle

`backend/server.py` serves either topology:
- `AGENT_ENGINE_NAME` **set** → proxies browser WS ⇄ Agent Engine bidi (Topology B, what deploy_all uses).
- **unset** → runs the agent in-process via `run_live` (Topology A, for local dev).

## Local dev (no cloud)

```bash
python -m mcp_server.server                              # MCP on :9000
uvicorn backend.server:app --port 8000                   # relay, in-process agent
cd frontend && python -m http.server 5500                # UI (config.js defaults to ws://localhost:8000)
```
