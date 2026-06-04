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

## 2. FastAPI relay → Cloud Run  ⏳ pending

`backend/server.py`. Needs `MCP_SERVER_URL` (above) + Vertex/ADC env. WebSocket
support (Cloud Run supports WS; set a long request timeout). Frontend points at
the relay's `wss://…/ws/…`.

## 3. Agent → Vertex AI Agent Engine  ⏳ pending

Package `upgrade_agent` with `MCP_SERVER_URL` set to the deployed MCP URL.
