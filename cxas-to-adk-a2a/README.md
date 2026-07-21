# Phone Upgrade Assistant — Native-A2A Variant

A self-contained voice-and-chat assistant that steers a contact-center caller into a
specialist agent for a phone-upgrade flow. The steering app (CX Agent Studio) reaches
the ADK chat agent **directly over the Agent Engine's native A2A endpoint** — no adapter.

Everything in this folder deploys as one stack. You edit a single `.env` file and run
one command. No project, engine, or app identifiers are hardcoded in the source. Every
deployed resource carries an `-a2a` suffix, so this stack runs side by side with the
OpenAPI-adapter variant in `../cxas-to-adk/`.

---

## Architecture

Three channels, one shared brain. Browser **voice** and browser **chat** connect to the
relay; the **IVR/telephony** caller is anchored on CX Agent Studio (CXAS), which reaches
the same ADK agent **directly over the chat engine's native A2A endpoint — no adapter**.
Every channel passes the same `customer_id`, so all three land in the **same session**.

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
  │  RELAY   ·   Cloud Run: att-phone-upgrade-relay-a2a                   │     │ CX AGENT STUDIO (CXAS)         │
  │  /ws    →  run_live             (bidi audio)                          │     │ steering app                   │
  │  /chat  →  async_stream_query   (text)                                │     │                                │
  │  resolve_session(user_id = customer_id, session_id?)                  │     │ voice STOPS here — only        │
  │                                                                       │     │ text + metadata cross          │
  └───────────────────────────────────────────────────────────────────────┘     └────────────────────────────────┘
                   │                                      │                                      │
                   │ run_live                             │ async (text)                         │ A2A call · P4SA
                   ▼                                      ▼                                      ▼
  ┌────────────────────────────────┐     ┌────────────────────────────────┐     ┌────────────────────────────────┐
  │  VOICE Agent Engine            │     │  CHAT Agent Engine             │     │ A2A tool → CHAT engine         │
  │  native-audio Live             │     │  text model                    │     │ native /a2a endpoint           │
  │  upgrade_agent                 │     │  upgrade_agent  + /a2a         │     │ P4SA auth                      │
  │                                │     │                                │     │ no adapter, no OIDC            │
  │                                │     │                                │     │ resolve_session on engine      │
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

### Detailed CXAS → ADK path (Channel 3, native A2A)

Voice stays inside CXAS; only **text + metadata** cross to the ADK plane. The steering
tree does coarse routing; the Sales Master delegates through a **RemoteAgentTool** that
speaks A2A straight to the chat engine — the adapter and OIDC hop of the OpenAPI variant
are gone, replaced by CES's per-project service agent (**P4SA**) auth.

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
                                                          │      delegates via the A2A RemoteAgentTool                           │
                                                          │      (only when SALES_TOOL_ENABLED = true)                           │
                                                          │ Care Agents  (stub)                                                  │
                                                          │                                                                      │
                                                          └──────────────────────────────────────────────────────────────────────┘
                                                                                              │
      voice STOPS at the CXAS boundary — only text + metadata cross to the ADK plane          │
                                                                                              │
      A2A protocol call · HTTPS → chat engine /a2a · auth CES P4SA (no adapter, no OIDC)      │
      payload: { customer_id, utterance, sentiment, ... }                                     │
                                                                                              │
                                        ┌──────────────────────────────────────────────────────────────────────────────────────────┐
                                        │  CHAT Agent Engine       ·       native /a2a endpoint                                    │
                                        │                                                                                          │
                                        │  1.  resolve_session(user_id = customer_id, id?)         ← single session authority      │
                                        │         · turn 1  →  get-or-create, returns session_id                                   │
                                        │         · turn N  →  validate id, else re-resolve                                        │
                                        │  2.  upgrade_agent runs over the persistent session                                      │
                                        │         · fine-routes, sub-agent stickiness preserved across turns                       │
                                        │  3.  returns the agent's text response over A2A                                          │
                                        └──────────────────────────────────────────────────────────────────────────────────────────┘
                                                                                      │
                                                                                      │  returns  response text
                                                                                      ▼
      ┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
      │  CXAS speaks the response text back to the caller via TTS                                                            │
      └──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

> **Allowlist note.** The RemoteAgentTool is allowlist-gated on CXAS. Until it exists,
> deploy with `SALES_TOOL_ENABLED=false` — the Sales Master runs without the A2A
> delegation leg. See **The A2A tool** below.

### Components

| Component | Runs on | Role |
|---|---|---|
| MCP server | Cloud Run | Tools/data the agents call |
| Voice Agent Engine | Vertex AI Agent Engine | Live audio agent; also the shared session store |
| Chat Agent Engine | Vertex AI Agent Engine | Text agent, exposes the native **A2A** endpoint |
| Relay | Cloud Run | Proxies browser voice (`/ws`) and chat (`/chat`) |
| UI | Cloud Run | Demo web front end |
| Steering app | CX Agent Studio | Concierge → Sales Master routing tree |

The steering app calls the chat engine's `/a2a` URL directly. Authentication uses the
CES per-project service agent (**P4SA**) — CES presents it by default for internal GCP
auth; the deploy grants it `roles/aiplatform.user`. No adapter, no OIDC token exchange.

---

## Prerequisites

- A **GCP project** with billing enabled, and an account with (at least) these roles on
  it: `roles/run.admin`, `roles/aiplatform.user`, `roles/storage.admin`,
  `roles/iam.serviceAccountUser`, and permission to set **project-level** IAM
  (`roles/resourcemanager.projectIamAdmin`). Owner also works.
- **CX Agent Studio (Conversational Agents)** access in the project.
- Local tools: **`gcloud` CLI** and **Python 3.10+**.

---

## Setup & deploy

Four setup steps, then one deploy command. Run them from this bundle's folder.

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
for the project so its service (the CES P4SA) is provisioned.

### 3. Create a virtual environment and install dependencies

```bash
cd cxas-to-adk-a2a
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. Configure `.env`

Copy the template and edit **only** `.env` (nothing is hardcoded in the source):

```bash
cp .env.example .env
```

| Set this | What it is |
|---|---|
| `GOOGLE_CLOUD_PROJECT` | Target project ID |
| `GOOGLE_CLOUD_LOCATION` | Region for Cloud Run + Agent Engines (default `us-central1`) |
| `CXAS_PROJECT` / `CXAS_LOCATION` | Steering app project and location (`us`) |
| `CXAS_APP_ID` | Steering app id (default `att-ivr-steering-a2a`) |
| `AE_STAGING_BUCKET` | Agent Engine staging bucket (leave blank → `PROJECT-agent-engine`) |
| `SALES_TOOL_ENABLED` | Leave `false` unless the A2A tool is allowlisted — see **The A2A tool** below |

Leave blank for the deploy to fill in: `AGENT_ENGINE_NAME`, `CHAT_AGENT_ENGINE_NAME`,
`SESSION_ENGINE_ID`, `CES_SERVICE_AGENT`. `RELAY_MIN_INSTANCES=1` keeps the first turn warm.

Then read **The A2A tool** section next, then run **Deploy** (step 5) below.

---

## The A2A tool (allowlist-gated)

The steering app delegates to the chat agent through a **RemoteAgentTool**. On CX Agent
Studio this tool type is currently **allowlist-only** — it cannot be created via API or
console until your project is allowlisted. The bundle handles both states with one flag:

- **`SALES_TOOL_ENABLED=false`** — builds the full steering hierarchy **without** the
  tool. The Sales Master runs but has no ADK delegation. Use this to deploy today.
- **`SALES_TOOL_ENABLED=true`** — attaches the A2A tool to the Sales Master. Requires the
  RemoteAgentTool to already exist.

**After your project is allowlisted:**

1. In the CX Agent Studio console, add a tool to the Sales Master: **Add tool → A2A →
   External**, pointing at the chat engine's `/a2a` URL (printed by the deploy, step 6),
   with **P4SA** authentication.
2. Set `SALES_TOOL_ENABLED=true` in `.env`.
3. Re-run the steering builder to attach the tool and restore the delegation macro:
   ```bash
   .venv/bin/python steering/create_steering_tree.py
   ```
4. Test the CES → ADK round trip in the console Simulator.

---

## Deploy (step 5)

```bash
bash deploy/deploy_all.sh
```

One command, eight steps. **Expect ~20–30 minutes** — most of it is Cloud Build compiling
container images and Vertex building the two Agent Engines.

| Step | Action |
|---|---|
| 1 | MCP server → Cloud Run |
| 2 | Voice Agent Engine (also the shared session store) |
| 3 | Chat Agent Engine |
| 4 | Relay → Cloud Run |
| 5 | UI → Cloud Run |
| 6 | Resolve and print the chat engine's A2A endpoint URL |
| 7 | Grant `roles/aiplatform.user` to the CES P4SA (project-level) |
| 8 | Create the CXAS app + A2A tool (if enabled) + steering tree + callbacks |

> **Run it yourself, interactively.** Step 7 binds a **project-level** IAM policy
> (`gcloud projects add-iam-policy-binding`), which needs `projectIamAdmin`/Owner. Run the
> script as a human with the permissions above; an unattended/automated shell may be
> blocked from the IAM binding.

### Use it (step 6)

When it finishes, the script prints the live URLs, identifiers, and the A2A endpoint URL:

- **Voice UI** — `<UI_URL>` · **Chat UI** — `<UI_URL>/chat.html`
- **CXAS path** — open the CXAS app (`att-ivr-steering-a2a`) in the Conversational Agents
  console and test in the **Simulator**. (With `SALES_TOOL_ENABLED=false` the Sales Master
  has no ADK delegation yet — see **The A2A tool** for enabling it once allowlisted.)

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
