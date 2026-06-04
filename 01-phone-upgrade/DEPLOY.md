# Cloud deployment

Topology target: browser → FastAPI relay (Cloud Run) → agent (Vertex Agent
Engine) → MCP data-tool server (Cloud Run) → back.

Project `REDACTED_PROJECT`, region `us-central1`.

## 1. MCP data-tool server → Cloud Run  ✅ deployed

Self-contained (`mcp_server/`, only the `mcp` SDK). Stateless streamable-HTTP,
binds `$PORT`.

```bash
gcloud run deploy att-mcp-phone-upgrade \
  --source mcp_server \
  --region us-central1 \
  --project REDACTED_PROJECT \
  --allow-unauthenticated \
  --port 8080
```

- **Service URL:** https://att-mcp-phone-upgrade-REDACTED_PROJECT_NUMBER.us-central1.run.app
- **MCP endpoint (set as `MCP_SERVER_URL`):** `…/mcp`
- **Auth:** public (`--allow-unauthenticated`) — mock data only. To harden:
  redeploy `--no-allow-unauthenticated`, grant the caller (Agent Engine SA)
  `roles/run.invoker`, and pass an identity token via `McpToolset` headers.

Verify the cloud hop from a local agent:
```bash
export MCP_SERVER_URL="https://att-mcp-phone-upgrade-REDACTED_PROJECT_NUMBER.us-central1.run.app/mcp"
export SSL_CERT_FILE=$(python -m certifi)
python scripts/smoke_mcp.py        # expect RESULT: PASS
```

## 2. Agent → Vertex AI Agent Engine  ✅ deployed (Topology B)

The Live agent runs on Agent Engine via a hand-rolled bidi op (stock `AdkApp`
has none). `backend/agent_app.py` (`live_agent`) wraps `run_live` and yields
events; `deploy/deploy_agent_engine.py` packages `backend/` as source and wires
`MCP_SERVER_URL` to the Cloud Run MCP.

```bash
python deploy/deploy_agent_engine.py
```

- **Resource:** `projects/REDACTED_PROJECT_NUMBER/locations/us-central1/reasoningEngines/REDACTED_ENGINE_ID`
- **Config:** EXPERIMENTAL server mode (required for bidi), `python_version=3.12`
  (no py3.14 base image), env `MCP_SERVER_URL` + `LIVE_MODEL`/`LIVE_VOICE` +
  `GOOGLE_GENAI_USE_VERTEXAI=TRUE` (do NOT set reserved `GOOGLE_CLOUD_PROJECT`).
- **Verify:** `python deploy/probe_agent_engine.py` → all four screens + audio.
- **Limits:** Preview; 10-min max per bidi stream.

## 3. Relay (`backend/server.py`) — dual topology

The relay serves either topology by env toggle:
- **`AGENT_ENGINE_NAME` set** → proxies browser WS ⇄ Agent Engine bidi (Topology B).
  Verified end-to-end: browser → relay → Agent Engine → Cloud Run MCP → back.
- **unset** → runs the agent in-process via `run_live` (Topology A).

```bash
export AGENT_ENGINE_NAME="projects/REDACTED_PROJECT_NUMBER/locations/us-central1/reasoningEngines/REDACTED_ENGINE_ID"
uvicorn backend.server:app --port 8000
```

### Relay → Cloud Run  ✅ deployed (fully-hosted)

`Dockerfile` + `relay-requirements.txt` build the proxy-mode relay; deployed
public with the AE toggle + Vertex env.

```bash
gcloud run deploy att-phone-upgrade-relay --source . --region us-central1 \
  --port 8080 --timeout 3600 --min-instances 1 --allow-unauthenticated \
  --set-env-vars "^@^AGENT_ENGINE_NAME=<engine>@GOOGLE_CLOUD_PROJECT=REDACTED_PROJECT@GOOGLE_CLOUD_LOCATION=us-central1@GOOGLE_GENAI_USE_VERTEXAI=TRUE"
```

- **Service URL:** https://att-phone-upgrade-relay-REDACTED_PROJECT_NUMBER.us-central1.run.app
- **WebSocket:** `wss://…/ws/<user_id>` (the frontend's `RELAY_URL` default).
- `--min-instances 1` keeps one instance warm (avoids cold-start 503 on first
  connect); `server.py` also pre-imports `vertexai` at startup. Drop to
  `--min-instances 0` to save cost when not demoing.
- The Cloud Run compute SA reaches Agent Engine via its existing `roles/editor`.

## Fully-hosted round-trip ✅ verified

```
Browser ⇄ Relay (Cloud Run) ⇄ Agent Engine ⇄ MCP server (Cloud Run)
```

Every hop runs in the cloud. `frontend/` is static and points at the relay via
`RELAY_URL` (set `window.RELAY_URL = "ws://localhost:8000"` for local dev).
