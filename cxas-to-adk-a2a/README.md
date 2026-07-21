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

- **gcloud CLI**, authenticated for both API and application-default credentials:
  ```bash
  gcloud auth login
  gcloud auth application-default login
  ```
- **Vertex AI** enabled on the target project.
- **CX Agent Studio** access in the project (location `us`).
- A **Python virtual environment** for this bundle:
  ```bash
  cd cxas-to-adk-a2a
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

| Set this | What it is |
|---|---|
| `GOOGLE_CLOUD_PROJECT` | Target project ID |
| `GOOGLE_CLOUD_LOCATION` | Region for Cloud Run + Agent Engines (default `us-central1`) |
| `CXAS_PROJECT` / `CXAS_LOCATION` | Steering app project and location (`us`) |
| `CXAS_APP_ID` | Steering app id (default `att-ivr-steering-a2a`) |
| `AE_STAGING_BUCKET` | Staging bucket for Agent Engine builds (leave blank to auto-name) |
| `SALES_TOOL_ENABLED` | See **A2A tool** below — set `false` until the tool exists |

Leave blank for the deploy to fill in: `AGENT_ENGINE_NAME`, `CHAT_AGENT_ENGINE_NAME`,
`SESSION_ENGINE_ID`, `CES_SERVICE_AGENT`. `RELAY_MIN_INSTANCES=1` keeps the first turn warm.

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

## Deploy

```bash
bash deploy/deploy_all.sh
```

Eight steps, in order:

| Step | Action |
|---|---|
| 1 | MCP server → Cloud Run |
| 2 | Voice Agent Engine (also the shared session store) |
| 3 | Chat Agent Engine |
| 4 | Relay → Cloud Run |
| 5 | UI → Cloud Run |
| 6 | Resolve and print the chat engine's A2A endpoint URL |
| 7 | Grant `roles/aiplatform.user` to the CES P4SA |
| 8 | Create the CXAS app + A2A tool (if enabled) + steering tree + callbacks |

> **Run it yourself.** Step 7 binds a project-level IAM policy
> (`gcloud projects add-iam-policy-binding`). Run the script as a human with sufficient
> permissions; an unattended/automated shell may be blocked from the IAM binding.

When it finishes, the script prints the UI URL, the engine/app identifiers, and the A2A
endpoint URL.

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
