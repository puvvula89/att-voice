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

- A **GCP project** with billing enabled, and an account with (at least) these roles on
  it: `roles/run.admin`, `roles/aiplatform.user`, `roles/storage.admin`,
  `roles/iam.serviceAccountUser`, and permission to bind IAM on a Cloud Run service
  (`roles/run.admin` covers it). Owner/Editor also works.
- **CX Agent Studio (Conversational Agents)** access in the project.
- Local tools: **`gcloud` CLI** and **Python 3.10+**.

---

## Setup & deploy

Six steps, start to finish. Run them from this bundle's folder.

### 1. Authenticate

```bash
gcloud auth login                       # user credentials (gcloud API calls)
gcloud auth application-default login    # ADC (Vertex AI / Agent Engine SDK)
gcloud config set project YOUR_PROJECT_ID
```

### 2. Enable the required APIs (once per project)

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  aiplatform.googleapis.com \
  storage.googleapis.com \
  --project YOUR_PROJECT_ID
```

CX Agent Studio must also be enabled — open **CX Agent Studio** in the Cloud console once
for the project so its service (the CES service agent) is provisioned.

### 3. Create a virtual environment and install dependencies

```bash
cd cxas-to-adk
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. Configure `.env`

Copy the template and edit **only** `.env` (nothing is hardcoded in the source):

```bash
cp .env.example .env
```

The values you set:

| Set this | What it is |
|---|---|
| `GOOGLE_CLOUD_PROJECT` | Target project ID |
| `GOOGLE_CLOUD_LOCATION` | Region for Cloud Run + Agent Engines (default `us-central1`) |
| `CXAS_PROJECT` / `CXAS_LOCATION` | Steering app project and location (`us`) |
| `CXAS_APP_ID` | Steering app id (default `ivr-steering`) |
| `AE_STAGING_BUCKET` | Agent Engine staging bucket (leave blank → `PROJECT-agent-engine`) |

Leave blank for the deploy to fill in: `AGENT_ENGINE_NAME`, `CHAT_AGENT_ENGINE_NAME`,
`SESSION_ENGINE_ID`, `CES_SERVICE_AGENT`.

Two warm-instance knobs keep the first turn fast: `RELAY_MIN_INSTANCES=1` and
`ADAPTER_MIN_INSTANCES=1` (a cold first CXAS turn ran ~56s, past the tool-call timeout).
Set to `0` to save cost at the risk of a cold-start timeout.

### 5. Deploy

```bash
bash deploy/deploy_all.sh
```

One command, nine steps. **Expect ~20–30 minutes** — most of it is Cloud Build compiling
container images and Vertex building the two Agent Engines.

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

> **Run it yourself, interactively.** Step 7 binds an IAM policy (`run.invoker`). Run the
> script as a human with the permissions above; an unattended/automated shell may be
> blocked from the IAM binding.

### 6. Use it

When it finishes, the script prints the live URLs and identifiers:

- **Voice UI** — `<UI_URL>` · **Chat UI** — `<UI_URL>/chat.html`
- **CXAS path** — open the CXAS app (`ivr-steering`) in the Conversational Agents console
  and test in the **Simulator**.

---

## Teardown

```bash
bash deploy/destroy_all.sh
```

Deletes the Cloud Run services, both Agent Engines, the CXAS app, and the staging bucket.
Safe to re-run — missing resources are skipped.

> **Note on the staging bucket.** Teardown also removes `AE_STAGING_BUCKET`
> (default `PROJECT-agent-engine`). That name is project-generic, so if you share it with
> other Agent Engine work, set `AE_STAGING_BUCKET` to a bundle-specific bucket before
> deploying — or skip the bucket line if you want to keep it.

---

## Tests

```bash
.venv/bin/python -m pytest
```
