# Phone Upgrade Assistant — OpenAPI-Adapter Variant

A self-contained voice-and-chat assistant that steers a contact-center caller into a
specialist agent for a phone-upgrade flow. The steering app (CX Agent Studio) reaches
the ADK chat agent through a private Cloud Run **adapter** exposed as an OpenAPI tool.

Everything in this folder deploys as one stack. You edit a single `.env` file and run
one command. No project, engine, or app identifiers are hardcoded in the source.

> Native-A2A variant (CES calls the chat engine directly, no adapter): see
> `../cxas-to-adk-a2a/`.

---

## Architecture

Three channels, one shared brain. Browser **voice** and browser **chat** connect to the
relay; the **IVR/telephony** caller is anchored on CX Agent Studio (CXAS), which reaches
the same ADK agent through a private Cloud Run adapter. Every channel passes the same
`customer_id`, so all three land in the **same session**.

```
  CHANNEL 1  ·  BROWSER VOICE            CHANNEL 2  ·  BROWSER CHAT             CHANNEL 3  ·  IVR / TELEPHONY
  ═══════════════════════════            ══════════════════════════             ════════════════════════════

  ┌────────────────────────────────┐     ┌────────────────────────────────┐     ┌────────────────────────────────┐
  │  Web UI                        │     │  Web UI                        │     │  AudioCodes                    │
  │  mic · audio                   │     │  text box                      │     │  SBC · ASR · TTS               │
  └────────────────────────────────┘     └────────────────────────────────┘     └────────────────────────────────┘
                   │                                      │                                      │
                   │ WebSocket audio  /ws                 │ WebSocket text  /chat                │ Bidi SAC (audio)
                   ▼                                      ▼                                      ▼ voice reaches CXAS
  ┌───────────────────────────────────────────────────────────────────────┐     ┌────────────────────────────────┐
  │  RELAY   ·   Cloud Run: att-phone-upgrade-relay                       │     │ CX AGENT STUDIO (CXAS)         │
  │  /ws    →  run_live             (bidi audio)                          │     │ steering app                   │
  │  /chat  →  async_stream_query   (text)                                │     │                                │
  │  resolve_session(user_id = customer_id, session_id?)                  │     │ voice STOPS here — only        │
  │                                                                       │     │ text + metadata cross          │
  └───────────────────────────────────────────────────────────────────────┘     └────────────────────────────────┘
                   │                                      │                                      │
                   │ run_live                             │ async (text)                         │ OpenAPI tool call
                   ▼                                      ▼                                      ▼
  ┌────────────────────────────────┐     ┌────────────────────────────────┐     ┌────────────────────────────────┐
  │  VOICE Agent Engine            │     │  CHAT Agent Engine             │     │ CXAS ADAPTER                   │
  │  native-audio Live             │     │  text model                    │     │ Cloud Run · private            │
  │  upgrade_agent                 │     │  upgrade_agent                 │     │ OIDC-gated                     │
  │                                │     │                                │     │ resolve_session →              │
  │                                │     │                                │     │ chat engine, then flatten      │
  └────────────────────────────────┘     └────────────────────────────────┘     └────────────────────────────────┘
                   │                                      │                                      │
                   │                                      │                                      │
                   ▼                                      ▼                                      ▼
  ╔══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╗
  ║   SHARED SESSION STORE      VertexAiSessionService · on the VOICE Agent Engine                                               ║
  ║                                                                                                                              ║
  ║   key   =   app_name   +   user_id ( = customer_id )   +   session_id                                                        ║
  ║   get-or-create   ·   resume within 10-min TTL   ·   else a fresh session                                                    ║
  ║                                                                                                                              ║
  ║   ⇒   any channel with the SAME customer_id continues the SAME conversation                                                  ║
  ╚══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╝
```

### Detailed CXAS → Cloud Run → ADK path (Channel 3)

Voice stays inside CXAS; only **text + metadata** cross to the ADK plane. The steering
tree does coarse routing, the Sales Master fires one OpenAPI tool call per turn, and the
adapter is the single place that resolves the session and flattens the ADK event stream
to one speakable line.

```
  ┌────────────┐        ┌──────────────────┐              ┌──────────────────────────────────────────────────────────────────────┐
  │  Caller    │ audio  │  AudioCodes      │  Bidi SAC    │ CX AGENT STUDIO  ·  steering                                         │
  │            │──────► │  SBC · ASR · TTS │ ──────────►  │                                                                      │
  └────────────┘        └──────────────────┘              │ Global Concierge Steering  (root)                                    │
                                                          │      greets once, then transfers  ▼                                  │
                                                          │ Consumer Steering                                                    │
                                                          │      picks domain: sales? / care?  ▼                                 │
                                                          │ Telephony Sales Master                                               │
                                                          │      no product knowledge of its own;                                │
                                                          │      holds the "sales-adapter" toolset                               │
                                                          │                                                                      │
                                                          │ Care Agents  (stub)                                                  │
                                                          │                                                                      │
                                                          └──────────────────────────────────────────────────────────────────────┘
                                                                                              │
      voice STOPS at the CXAS boundary — only text + metadata cross to the ADK plane          │
                                                                                              │
      OpenAPI tool call · HTTPS + OIDC (token minted by CES service agent)                    │
      payload: { customer_id, session_id?, utterance, sentiment, correlation_id, channel = ivr }
                                                                                              │
                                        ┌──────────────────────────────────────────────────────────────────────────────────────────┐
                                        │  CXAS ADAPTER     Cloud Run · PRIVATE · OIDC-gated                                       │
                                        │  ( run.invoker granted to the CES service agent )                                        │
                                        │                                                                                          │
                                        │  1.  resolve_session(user_id = customer_id, id?)         ← single session authority      │
                                        │         · turn 1  →  get-or-create, returns session_id                                   │
                                        │         · turn N  →  validate cached id, else re-resolve                                 │
                                        │  2.  chat engine  async_stream_query(utterance + sentiment)                              │
                                        │         · upgrade_agent fine-routes over the persistent session (sub-agent stickiness)   │
                                        │  3.  flatten the ADK event stream → ONE speakable text  (drop pending_ui)                │
                                        │  4.  emit association record  (correlation_id ↔ session_id)                              │
                                        └──────────────────────────────────────────────────────────────────────────────────────────┘
                                                                                      │
                                                                                      │  returns  { response_text, session_id }
                                                                                      ▼
      ┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
      │  CXAS caches session_id on the call (turn 1) and speaks response_text back to the caller via TTS                     │
      └──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Components

| Component | Runs on | Role |
|---|---|---|
| MCP server | Cloud Run | Tools/data the agents call |
| Voice Agent Engine | Vertex AI Agent Engine | Live audio agent; also the shared session store |
| Chat Agent Engine | Vertex AI Agent Engine | Text agent (parity with voice) |
| Relay | Cloud Run | Proxies browser voice (`/ws`) and chat (`/chat`) |
| UI | Cloud Run | Demo web front end |
| CXAS adapter | Cloud Run (private, OIDC) | Bridges the steering app's OpenAPI tool to the chat engine |
| Steering app | CX Agent Studio | Concierge → Sales Master routing tree |

The steering app calls the private adapter over an OpenAPI tool authenticated with an
OIDC token minted by the CES service agent.

---

## Prerequisites

- **gcloud CLI**, authenticated for both API and application-default credentials:
  ```bash
  gcloud auth login
  gcloud auth application-default login
  ```
- **Vertex AI** enabled on the target project.
- **CX Agent Studio** access in the project (location `us`).
- A **Python virtual environment** for this bundle:
  ```bash
  cd cxas-to-adk
  python -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt
  ```

---

## Configure

Copy the template and edit **only** `.env`:

```bash
cp .env.example .env
```

Fill in the values you must set; leave the rest at their defaults.

| Set this | What it is |
|---|---|
| `GOOGLE_CLOUD_PROJECT` | Target project ID |
| `GOOGLE_CLOUD_LOCATION` | Region for Cloud Run + Agent Engines (default `us-central1`) |
| `CXAS_PROJECT` / `CXAS_LOCATION` | Steering app project and location (`us`) |
| `AE_STAGING_BUCKET` | Staging bucket for Agent Engine builds (leave blank to auto-name) |

Leave blank for the deploy to fill in: `AGENT_ENGINE_NAME`, `CHAT_AGENT_ENGINE_NAME`,
`SESSION_ENGINE_ID`, `CES_SERVICE_AGENT`.

Two warm-instance knobs keep the first turn fast:
`RELAY_MIN_INSTANCES=1` and `ADAPTER_MIN_INSTANCES=1` (a cold first CXAS turn ran ~56s,
past the tool-call timeout). Set to `0` to save cost at the risk of a cold-start timeout.

---

## Deploy

```bash
bash deploy/deploy_all.sh
```

Nine steps, in order:

| Step | Action |
|---|---|
| 1 | MCP server → Cloud Run |
| 2 | Voice Agent Engine (also the shared session store) |
| 3 | Chat Agent Engine |
| 4 | Relay → Cloud Run |
| 5 | UI → Cloud Run |
| 6 | CXAS adapter → Cloud Run (private, min-instances warm) |
| 7 | Grant `run.invoker` on the adapter to the CES service agent |
| 8 | Create the CXAS app + sales-adapter toolset |
| 9 | Build the steering tree + Sales Master callbacks |

> **Run it yourself.** Step 7 binds an IAM policy (`run.invoker`). Run the script as a
> human with sufficient permissions; an unattended/automated shell may be blocked from
> the IAM binding.

When it finishes, the script prints the UI URL and the created engine/app identifiers.

---

## Teardown

```bash
bash deploy/destroy_all.sh
```

Deletes the Cloud Run services, both Agent Engines, the CXAS app, and the staging bucket.

---

## Tests

```bash
.venv/bin/python -m pytest
```
