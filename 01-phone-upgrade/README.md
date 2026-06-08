# 01 — Phone Upgrade (voice + chat)

Phone-upgrade agent on Google ADK + Gemini Live, in **two channels**:

- **Voice** — speak naturally; the agent talks back (Gemini Live native audio).
- **Chat** — type; a text model answers.

Both drive the **same** on-screen UI (line picker → phone options → confirmation → receipt)
and **share one session**, so you can start in one channel and continue in the other from where
you left off. Advance the flow by voice, by typing, or by clicking the cards. A **Mute** button on
the voice UI lets you stop sending mic audio without ending the call.

## How it works — end-to-end flow (voice channel)

This section diagrams the **voice** path; the [chat channel](#the-chat-channel) is a parallel
text path described below. The browser loads the page from the **UI** service, then opens a single
WebSocket to the **relay**, which proxies a bidi stream to the **voice agent** on Agent Engine; the
agent calls the **MCP tools** for data and emits each `render_component` as a `pending_ui` state
delta — the model never hand-writes UI. (Locally the relay runs the agent in-process via `run_live`
instead of proxying — same wire protocol; see the topology toggle below.)

```
        ┌──────────────────────────┐                                   ┌──────────────────────────┐
        │         BROWSER          │      WebSocket  /ws/{user}        │    Relay (Cloud Run)     │
        │  (page from UI service)  │ ───────────────────────────────▶  │        server.py         │
        │  client.js   (WS glue)   │   {type:audio}  16kHz PCM b64     │                          │
        │  audio.js    (mic 16kHz, │   {type:user_action, selection}   │  proxy: browser ⇄ AE     │
        │               play 24kHz)│                                   │  bidi_stream_query       │
        │  components.js (cards)   │ ◀───────────────────────────────  │  --min-instances 1       │
        │  config.js   (RELAY_URL) │   {type:ui_event}   component     │                          │
        │                          │   {type:transcript} you / agent   │                          │
        │                          │   raw event         24kHz audio   │                          │
        │                          │   {type:session_end}              │                          │
        └──────────────────────────┘                                   └────────────┬─────────────┘
                                                                          bidi to AE│  audio in/out
                                                                        (proxy mode)│  + state deltas
                                                                                    ▼
                                                                       ┌──────────────────────────┐
                                                                       │Voice agent (Agent Engine)│
                                                                       │ Gemini Live native audio │
                                                                       │  tools + after_tool_cb   │
                                                                       │  formatter → pending_ui  │
                                                                       └────────────┬─────────────┘
                                                      get_lines / get_phones / order│ MCP tool calls
                                                                                    ▼  streamable-HTTP /mcp
                                                                       ┌──────────────────────────┐
                                                                       │MCP data tools (Cloud Run)│
                                                                       │ FastMCP · lines · phones │
                                                                       │     pricing · order      │
                                                                       └──────────────────────────┘
```

The numbered turn below traces one request — *"I want to upgrade my phone"* — from mic to rendered
screen. The two highlighted callback steps are the heart of the design: tool **data is staged first**
(no UI), and the screen is only **built when the model calls `render_component`** — so the model
chooses *when* and *which* template, and the formatter does the deterministic rendering.

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser · client.js
    participant R as Relay · server.py
    participant A as Agent Engine · agent_app / run_live / on_tool
    participant G as Gemini Live · the model
    participant M as MCP data tools

    Note over B,R: Start clicked → hop-1 WebSocket opens → relay opens bidi_stream_query to AE (hop-2)
    Note over A,G: first frame {user_id} → session + (call_start) nudge → agent greets (audio+transcript flow back to B)

    Note over B,G: ——— one turn: "I want to upgrade my phone" ———
    B->>R: {type:audio} 16kHz PCM frames (you speak)
    R->>A: forward verbatim over hop-2 bidi
    A->>G: send_realtime(Blob) via LiveRequestQueue (hop-3 ws)
    Note over G: VAD detects speech-end → start turn
    G->>A: tool call get_lines
    A->>M: route get_lines over /mcp
    M-->>A: {lines:[…]}
    A->>A: on_tool STAGES state["data:line_selector"] — no UI yet
    G->>A: tool call render_component("line_selector")
    A->>A: on_tool → FORMATTER build_payload → state["pending_ui"]
    G->>A: speak reply → audio + transcription + state_delta(pending_ui)
    A-->>R: yield events ({"bidiStreamOutput": …})
    R-->>B: _emit_event fans 1 event → {type:ui_event} + {type:transcript} + raw audio
    Note over B: handleMessage demuxes → line cards · transcript text · gapless voice

    B->>R: {type:user_action, selection} (pick a line — voice or click)
    R->>A: forward as a text turn (send_content)
    Note over A,G: loop → select_line → get_eligible_phones → render_component("phone_options") → next screen

    Note over B,G: ——— closing ———
    G->>A: end_call (after "anything else?" → "no")
    A->>A: on_tool sets state["call_ended"] = true
    R-->>B: {type:session_end} → WebSocket closes
```

**Wire protocol** (JSON text frames over the WebSocket):

| Direction | Message | Meaning |
|---|---|---|
| browser → relay | `{type:"audio", data}` | mic frame, 16 kHz mono PCM, base64 (gated half-duplex while the agent speaks) |
| browser → relay | `{type:"user_action", selection}` | a card click; injected as an equivalent text turn |
| relay → browser | `{type:"ui_event", stage_intent, payload}` | the component to render (built by the formatter) |
| relay → browser | `{type:"transcript", role, text, final}` | live STT for both sides (deltas, then a cumulative `final`) |
| relay → browser | raw ADK event | carries model audio in `content.parts[].inlineData.data` (24 kHz, **base64url**) |
| relay → browser | `{type:"session_end"}` | agent ended the call; the relay closes the socket |

## The transport model — three hops, not one connection

Voice needs audio flowing **up** (your mic) and **down** (the agent's voice) *at the same time,
continuously*. A normal HTTP request can't do that — it's one question, one answer, then it hangs up.
So every hop in this system is a **persistent, two-way channel**. But they are not all the same kind of
channel, and the connection that actually carries the live voice is one hop deeper than most people expect.

```
   WebSocket                gRPC bidi stream              WebSocket
  (we open this)           (the platform's API)        (ADK opens this)
       │                          │                          │
┌──────────────┐         ┌──────────────┐          ┌──────────────┐         ┌──────────────┐
│   BROWSER    │◀───────▶│    RELAY     │◀────────▶│ AGENT ENGINE │◀───────▶│  GEMINI      │
│  client.js   │  ws://  │  server.py   │   bidi   │  agent_app   │   ws    │  LIVE API    │
│              │         │              │ _stream  │  run_live    │         │ (the model)  │
└──────────────┘         └──────────────┘ _query   └──────────────┘         └──────────────┘
   hop 1                    hop 2                      hop 3
   browser ⇄ relay          relay ⇄ Agent Engine       Agent Engine ⇄ model
                                                        ▲
                              the live voice actually rides on hop 3 —
                              opened by ADK inside the Agent Engine container
```

Each hop uses a different transport for a different reason. Read the official docs for each:

| Hop | Connection | What it is | Official docs |
|---|---|---|---|
| **1 · browser ⇄ relay** | WebSocket (JSON frames) | We open this — `new WebSocket(...)` in `client.js`, accepted by `ws_endpoint` in `backend/server.py`. The only connection the browser has; it never holds cloud credentials. | [MDN — WebSocket API](https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API) · [FastAPI — WebSockets](https://fastapi.tiangolo.com/advanced/websockets/) |
| **2 · relay ⇄ Agent Engine** | gRPC bidirectional stream (*not* a WebSocket) | The platform's API, not our choice. Agent Engine exposes a registered `bidi_stream_query` op; the relay reaches it through the GenAI SDK over gRPC/HTTP/2. | [Agent Engine — Bidirectional streaming](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/bidirectional-streaming) · [gRPC — Bidirectional streaming RPC](https://grpc.io/docs/what-is-grpc/core-concepts/#bidirectional-streaming-rpc) |
| **3 · Agent Engine ⇄ Gemini Live** | WebSocket (**carries the voice**) | Opened by ADK's `run_live` *inside* the Agent Engine container — this is where the PCM audio actually reaches the model. | [ADK — Bidi-streaming dev guide](https://adk.dev/streaming/dev-guide/part1/) · [Gemini Live API overview](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/live-api) |

**Why a relay in the middle at all (hops 1 + 2):** credentials stay server-side; the relay translates the
browser's simple JSON ⇄ the Agent Engine stream format; and flipping one env var (`AGENT_ENGINE_NAME`)
swaps hop 2 for an in-process `run_live`, so the *same* browser connection works in local dev with no
code change.

> Agent Engine docs were reorganized under "Gemini Enterprise Agent Platform" — older
> `cloud.google.com/vertex-ai/...` links now redirect to a generic landing page; use the links above.

## The chat channel

The chat channel mirrors voice with text, reusing the **same** MCP tools, `render_component`
callbacks, and `frontend/components.js` — so it drives the identical four screens. Only the
transport and model differ:

- **Frontend:** `frontend/chat.html` + `chat.js` (a text composer instead of a mic), same `components.js`.
- **Relay path:** the browser opens `wss://<relay>/chat/{user_id}`; the relay proxies **one turn at a
  time** to the chat agent's `async_stream_query` op (not a bidi stream — chat is request/response).
- **Chat agent:** a **separate** Agent Engine running a text model (`CHAT_MODEL`, default
  `gemini-2.5-flash`) — *not* a Live model, so there is no hop-3 voice WebSocket.

**Shared session = cross-channel handoff.** Both agents point `VertexAiSessionService` at the **same**
`SESSION_ENGINE_ID` (one designated Agent Engine id used by *both*, not each engine's own). Resume is
anchored on `user_id`: connect with a `user_id` and the server resumes that user's latest session
(`backend/session_resolve.py`), so a flow started in voice continues in chat — and vice versa — with
both the conversation **and** the picked line/phone carried over.

**Chat wire protocol** adds one browser→relay message; everything relay→browser is shared with voice:

| Direction | Message | Meaning |
|---|---|---|
| browser → relay | `{type:"user_message", text}` | a typed turn |
| browser → relay | `{type:"user_action", selection}` | a card click |
| relay → browser | `{type:"ui_event"}` / `{type:"transcript"}` / `{type:"session_end"}` | same as voice (no audio frames) |

## Running it — three self-contained approaches

Pick one of A, B, or C below. **Each section repeats its full prerequisites**, so you can follow any
one start-to-finish without jumping around. All three (including the **cloud deploy**) need the local
Python tooling in a `.venv` — the deploy scripts run *on your machine* to orchestrate the cloud build,
so the venv is required even when you're only deploying to the cloud. Run everything from `01-phone-upgrade/`.

## Run — option A: adk web (quick agent/voice test, generic dev UI)
Shows ADK's built-in dev UI (voice + tool-call trace). Does NOT render the custom phone-upgrade cards.

```bash
# --- prerequisites (one-time) ---
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
gcloud auth application-default login              # ADC for Vertex
cp .env.example .env                               # then set GOOGLE_CLOUD_PROJECT (+ region if not us-central1)

# --- run ---
export SSL_CERT_FILE=$(python -m certifi)          # required for voice
adk web phone_upgrade --port 8001                  # point at the agent folder
```
Open the printed URL, select `phone_upgrade`, click the mic.

> Pass the agent folder (`phone_upgrade`) explicitly. Plain `adk web` from the module root lists every subdirectory (`backend`, `frontend`, `tests`) as bogus agents; pointing at the single agent folder shows only `phone_upgrade`.

## Run — option B: FastAPI relay + custom UI (the full demo)
Runs the voice agent in-process and renders the real phone-upgrade cards.

```bash
# --- prerequisites (one-time) ---
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
gcloud auth application-default login              # ADC for Vertex
cp .env.example .env                               # then set GOOGLE_CLOUD_PROJECT (+ region if not us-central1)
export SSL_CERT_FILE=$(python -m certifi)          # required for voice
```

The data tools are served by a separate MCP server, so start it first:
```bash
python -m mcp_server.server                 # MCP data tools, streamable-HTTP on :9000
uvicorn backend.server:app --reload         # :8000  (run from 01-phone-upgrade/)
```
In another terminal: `cd frontend && python -m http.server 5500`, open http://localhost:5500, grant mic.

> The agent reaches the MCP server via `MCP_SERVER_URL` (default `http://localhost:9000/mcp`). `render_component`/`end_call` stay agent-local; everything else is an MCP call.

> Run adk web and the relay on different ports (adk web on 8001, relay on 8000) — the frontend expects the relay on :8000.

> **Chat locally:** the voice channel runs in-process, but chat has no in-process mode — `/chat` always
> proxies to a deployed chat engine. To exercise `chat.html` locally, deploy a chat engine and set
> `CHAT_AGENT_ENGINE_NAME` (and `SESSION_ENGINE_ID`) before starting the relay; otherwise use voice locally
> and both channels in the hosted deploy.

## Deploy to Google Cloud (fully hosted)

One command stands the **entire** stack up on Google Cloud — UI, relay, voice agent,
**chat agent**, and MCP tools — from a clean project. All config comes from `.env`; nothing is hardcoded.

> **The deploy runs on your machine.** `deploy_all.sh` → `deploy/*.py` execute locally using the
> Vertex SDK to package the agents and trigger the cloud builds — so you need the local `.venv` with
> `requirements.txt` installed **even though you're deploying to the cloud**. Skipping it fails at
> `import dotenv` / `import vertexai` on the first Python step (the voice agent).

```bash
# --- prerequisites (one-time) ---
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt                    # local deploy tooling (incl. the Vertex SDK)
gcloud auth application-default login               # ADC for the deploy
cp .env.example .env                                # then set GOOGLE_CLOUD_PROJECT (+ region/names if you like)
# enable the APIs the build uses (once per project):
gcloud services enable aiplatform.googleapis.com run.googleapis.com \
  cloudbuild.googleapis.com artifactregistry.googleapis.com storage.googleapis.com

# --- deploy everything (prints the UI URL) ---
deploy/deploy_all.sh
```

`deploy_all.sh` runs the five steps in order and **threads each step's output into the next**
(no hand-wiring): MCP → captures its URL → **voice** agent on Agent Engine (with that URL) → captures
its engine id (the shared session store) → **chat** agent on a separate Agent Engine (pointed at that
same session id) → relay (with both engine names) → UI (with the relay URL injected into `config.js`).
Typical cold build is ~8–10 min. Open the printed **UI URL** (voice) or **`/chat.html`** (chat) and click **Start**.

Tear it **all** back down (stops billing — deletes the 3 Cloud Run services, **both** Agent Engines, and the bucket):

```bash
deploy/destroy_all.sh
```

**Verify the deployment** (optional — what proves a release):

```bash
export SSL_CERT_FILE=$(python -m certifi)
python deploy/probe_agent_engine.py         # voice agent + MCP, direct to Agent Engine → 4 screens + audio
RELAY_WSS=wss://<relay-host> python deploy/probe_relay_ws.py   # browser → relay → AE path → 4 screens + audio
python deploy/probe_resume.py               # resume by user_id across reconnects (no re-greet, no stale screen)
python deploy/probe_handoff.py              # cross-channel: start in voice → resume in chat on the shared session
```

### The five services

`deploy_all.sh` deploys these in order, threading each one's output into the next:

| # | Service | Platform | What it does |
|---|---|---|---|
| 1 | **MCP data tools** (`att-mcp-phone-upgrade`) | Cloud Run · FastMCP | Stateless data API at `/mcp` — looks up account lines, phone catalog, pricing, and places the order. The agents' only data source. |
| 2 | **Voice agent** (`att-phone-upgrade-live`) | Vertex AI Agent Engine | Gemini Live native-audio agent (bidi) that listens, talks, calls the MCP tools, and emits each `render_component` as a `pending_ui` state delta. Custom `bidi_stream_query` server mode. Its engine id is the **shared session store** for both channels. |
| 3 | **Chat agent** (`att-phone-upgrade-chat`) | Vertex AI Agent Engine | Text model (`CHAT_MODEL`) on a **separate** engine, same tools + `render_component` for UI parity. Standard `async_stream_query` op (no EXPERIMENTAL mode). Configured with the voice engine's `SESSION_ENGINE_ID` so sessions are shared. |
| 4 | **Relay** (`att-phone-upgrade-relay`) | Cloud Run | The single endpoint the browser connects to. `/ws/{user}` proxies the voice **bidi** stream; `/chat/{user}` proxies **chat** `async_stream_query`. Translates both into one browser wire protocol. Kept warm (`--min-instances 1`) to avoid cold-start 503s. |
| 5 | **UI** (`att-phone-upgrade-ui`) | Cloud Run | Static frontend — `index.html` (voice, mic + Mute) and `chat.html` (text composer), shared `components.js`. Served over HTTPS so the mic works; served `no-store` (`serve.py`) so a redeploy is never cached; the relay URL is injected into `config.js` at deploy time. |

The **relay topology toggle** lives in `backend/server.py`: with `AGENT_ENGINE_NAME` set the voice path
proxies to Agent Engine (cloud, above); unset, it runs the voice agent in-process via `run_live` (local
dev, option B). The chat path (`/chat`) always proxies to the deployed chat engine (`CHAT_AGENT_ENGINE_NAME`).
Same browser wire protocol either way — see the tables above.

### Prerequisites

- **APIs enabled:** `aiplatform`, `run`, `cloudbuild`, `artifactregistry`, `storage`.
- **IAM:** the Cloud Run runtime service account needs Agent Engine access
  (`roles/aiplatform.user`, or the default compute SA's `roles/editor`) so the relay can reach the agent.
- **`.env` set** (see below) and **ADC** configured (`gcloud auth application-default login`).

### Config (`.env`)

| Var | Purpose |
|---|---|
| `GOOGLE_CLOUD_PROJECT` | **required** — target project |
| `GOOGLE_CLOUD_LOCATION` | region (default `us-central1`) |
| `LIVE_MODEL`, `LIVE_VOICE` | voice Live model id + prebuilt voice |
| `CHAT_MODEL` | chat agent text model (default `gemini-2.5-flash`) |
| `SESSION_ENGINE_ID` | the ONE Agent Engine id both channels use as the shared session store (set automatically by `deploy_all.sh` to the voice engine's id; set it yourself only for partial/manual deploys) |
| `MCP_SERVICE`, `RELAY_SERVICE`, `UI_SERVICE` | Cloud Run service names |
| `AGENT_DISPLAY_NAME`, `CHAT_DISPLAY_NAME` | Agent Engine display names (voice / chat) |
| `AE_STAGING_BUCKET` | staging bucket (default `<project>-agent-engine`) |
| `RELAY_MIN_INSTANCES` | keep a relay warm (default `1`; `0` to save cost) |
| `MCP_SERVER_URL`, `AGENT_ENGINE_NAME`, `CHAT_AGENT_ENGINE_NAME` | produced by the deploy script — don't hand-set |

### What each step runs (for manual/partial deploys)

1. **MCP** — `gcloud run deploy $MCP_SERVICE --source mcp_server …` → captures its URL as `MCP_SERVER_URL`.
2. **Voice agent** — `python deploy/deploy_agent_engine.py` packages `backend/` as source, wires `MCP_SERVER_URL`,
   deploys in EXPERIMENTAL server mode (required for bidi) with `python_version=3.12` (no py3.14 base image).
   Do **not** set the reserved `GOOGLE_CLOUD_PROJECT` env var on the engine. (Preview; ~10-min/stream limit.)
   Its numeric engine id becomes `SESSION_ENGINE_ID` (the shared session store).
3. **Chat agent** — `python deploy/deploy_chat_engine.py` with `SESSION_ENGINE_ID` set (required) → a separate
   engine on `CHAT_MODEL`, standard server mode (no EXPERIMENTAL). → captures `CHAT_AGENT_ENGINE_NAME`.
4. **Relay** — `gcloud run deploy $RELAY_SERVICE --source . …` with `AGENT_ENGINE_NAME` **and** `CHAT_AGENT_ENGINE_NAME` set → proxy mode for both channels.
5. **UI** — `gcloud run deploy $UI_SERVICE --source frontend …` (HTTPS → mic works), relay URL injected into `config.js` first.

## Test
`pytest tests/ -v` (from `01-phone-upgrade/`)
