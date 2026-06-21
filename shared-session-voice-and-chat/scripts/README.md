# scripts — live smoke tests & diagnostics

Headless checks that exercise the agent and the FastAPI relay against the live
Gemini Live model. Unlike `pytest` (pure-Python units), these make real Vertex
calls — use them to validate agent/relay changes, which import-only checks miss.

## Prerequisites
- `.env` configured (ADC / Vertex) — see the module README.
- Run from the module root (`shared-session-voice-and-chat/`) with the venv active.
- The **MCP server must be running** — the agent's data tools live there:
  ```
  python -m mcp_server.server        # streamable-HTTP on :9000 (MCP_SERVER_URL)
  ```
- Voice/Live needs the cert bundle:
  ```
  export SSL_CERT_FILE=$(python -m certifi)
  ```
Each script self-bootstraps (adds the module root to `sys.path`, loads `.env`),
so no `PYTHONPATH` is needed.

## Scripts
| Script | What it checks |
|---|---|
| `smoke_greeting.py` | Agent greets on `(call_start)` before any user input (audio + transcript). |
| `smoke_flow.py` | One user turn drives tools → `line_selector` `ui_event` → audio, then the agent **waits** (no auto-advance). |
| `smoke_mcp.py` | Full scripted flow over the MCP topology: all four screens render and the stateless ids (`line_id`+`phone_id`) reach `select_phone`/`confirm_upgrade`. Needs the MCP server running. |
| `smoke_relay.py` | End-to-end through the FastAPI WebSocket relay: `user_action` in → `ui_event` (with options) out. |
| `probe_transcript.py` | Shows Live transcription streaming as deltas then a cumulative `finished=True` chunk. |
| `diag_audio.py` | Tallies audio parts / base64 bytes / MIME types the relay sends (silent-audio debugging). |

```
python scripts/smoke_greeting.py
python scripts/smoke_flow.py
python scripts/smoke_relay.py
```
