# CXAS Voice + Chat (two apps over A2A)

Two separate CX Agent Studio apps that share a single customer entry point:

- **cxas-voice-and-chat** — the voice app (live model). A root steering agent
  routes each caller by intent to an in-app **Internet** or **Billing**
  specialist, or hands **troubleshooting** to a thin `a2a-to-cxas-chat`
  sub-agent that forwards over A2A to the chat app.
- **cxas-chat** — the chat app (flash model). A root routes to a
  **Troubleshooting** specialist with basic device software-update steps. This
  is the app the voice side reaches over A2A.

```
cxas-voice-and-chat  (live: gemini-3.1-flash-live)
  Voice Concierge (root)
    ├─ Internet Support
    ├─ Billing Support
    └─ Troubleshooting Specialist ──chat_adapter A2A──▶ cxas-chat
                                                          │
cxas-chat  (flash: gemini-3.5-flash)                      ▼
  Chat Concierge (root)
    └─ Troubleshooting
```

Routing is instruction-driven: each parent lists its children via `child_agents`
and transfers by `{@AGENT: Display Name}` in its instruction. The A2A hop is a
`RemoteAgentTool` (`chat_adapter`) whose card points at the deployed cxas-chat
app's native A2A endpoint.

---

## Architecture

Two entry points reach the **same** CXAS voice app: a browser client (talk **or**
type on one session) and the CXAS Simulator. A returning customer is recognised
before the agent speaks, through a private hydration service that reads their
previous conversation.

```
  CHANNEL 1  ·  BROWSER  (voice + chat, one session)        CHANNEL 2  ·  CXAS SIMULATOR      CHANNEL 3  ·  IVR / GTP
  ══════════════════════════════════════════════            ═══════════════════════════       ═══════════════════════

  ┌────────────────────────────────────────────┐            ┌─────────────────────────┐       ┌─────────────────────────┐
  │  Web UI   ·  Cloud Run: cxas-web-ui        │            │  Console Simulator      │       │  Telephony  (NOT set up)│
  │  mic  ·  text box  ·  one transcript       │            │  mic / text             │       │  version-pinned channel │
  └────────────────────────────────────────────┘            └─────────────────────────┘       └─────────────────────────┘
                        │                                                │                                 │
                        │ WebSocket  /session/{uuid}                     │ direct                          │ direct
                        ▼                                                │                                 │
  ┌────────────────────────────────────────────┐                         │                                 │
  │  RELAY   ·  Cloud Run: cxas-web-relay      │                         │                                 │
  │  browser frames  ⇄  CXAS bidi session      │                         │                                 │
  │  text + audio on ONE session (per-turn     │                         │                                 │
  │  modality); ADC token per connection       │                         │                                 │
  └────────────────────────────────────────────┘                         │                                 │
                        │                                                │                                 │
                        └────────────────────────┬───────────────────────┴─────────────────────────────────┘
                                                 ▼
  ╔══════════════════════════════════════════════════════════════════════════════════════════════════════════════════╗
  ║  CX AGENT STUDIO  ·  cxas-voice-and-chat        (live: gemini-3.1-flash-live)                                    ║
  ║                                                                                                                  ║
  ║   before_model_callback  ──  fires hydration ONCE, on the first model step, only if customer_id is set           ║
  ║                                                                                                                  ║
  ║   Voice Concierge (root)                                                                                         ║
  ║     ├─ Internet Support                                                                                          ║
  ║     ├─ Billing Support                                                                                           ║
  ║     └─ Troubleshooting Specialist  ──chat_adapter A2A──▶  cxas-chat  (flash: gemini-3.5-flash)                    ║
  ╚══════════════════════════════════════════════════════════════════════════════════════════════════════════════════╝
                                                 │
                                                 │  OpenAPI tool call · HTTPS + OIDC
                                                 │  (token minted by the CES service agent)
                                                 │  payload: { customer_id, conversation_id }
                                                 ▼
  ┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │  HYDRATION SERVICE   ·  Cloud Run: cxas-hydration  ·  PRIVATE · OIDC-gated · min-instances=1                      │
  │                                                                                                                  │
  │   1.  get_conversation(prior UUID)            ← conversation id == session id                                    │
  │   2.  extract text from every chunk           ← `transcript` (spoken) AND `text` (typed)                          │
  │   3.  digest → { found, topic, summary, turn_count }                                                             │
  └──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
                                                 │
                                                 ▼
  ┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │  CES ConversationHistory        every session is readable afterwards as {app}/conversations/{uuid}                │
  └──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### First turn: how hydration fires (and can only fire once)

The model never decides to call the tool — a callback injects the call, then
removes the tool from the schema. Everything below is deterministic Python in the
CES sandbox: no model hop, no egress, no added latency.

```
  session starts
        │
        ▼
  ┌───────────────────────────────────────────────────────────────────────────────────────┐
  │  MODEL STEP 1   ·   before_model_callback                                             │
  │                                                                                       │
  │     hydrated latch set?  ──yes──▶  hide_tool()  ·  return None      (later turns)     │
  │     customer_id empty?   ──yes──▶  latch "skipped"  ·  hide_tool()  (never hydrate)   │
  │     tool already in this invocation?  ──yes──▶  latch "done"  ·  return None          │
  │                                                                                       │
  │     otherwise:  latch "done"  BEFORE firing, then return an LlmResponse whose only    │
  │                 part is  FunctionCall(hydration_load_prior_conversation)              │
  │                 ⇒ the response REPLACES this model step — the model never ran         │
  └───────────────────────────────────────────────────────────────────────────────────────┘
        │
        ▼   platform executes the injected call
  ┌───────────────────────────────────────────────────────────────────────────────────────┐
  │  cxas-hydration  /hydrate   →   { found: true, topic: "…", summary: "…" }              │
  └───────────────────────────────────────────────────────────────────────────────────────┘
        │
        ▼   result returns to the session
  ┌───────────────────────────────────────────────────────────────────────────────────────┐
  │  MODEL STEP 2   ·   before_model_callback  →  latch is "done"  →  hide_tool()          │
  │                     the model now runs FOR REAL, with the digest in context            │
  │                     and the tool absent from its schema                                │
  └───────────────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
   found=true  ─▶  "Welcome back! Are you calling about your internet issue from earlier?"
   found=false ─▶  "Thanks for calling! How can I help you today?"   (history never mentioned)
```

### Components

| Component | Runs on | Role |
|---|---|---|
| cxas-voice-and-chat | CX Agent Studio | Voice app (live model); root steering + specialists |
| cxas-chat | CX Agent Studio | Chat app (flash model); A2A target for troubleshooting |
| Hydration service | Cloud Run (private, OIDC) | Reads the prior conversation, returns a digest |
| Hydration toolset | CX Agent Studio | OpenAPI tool → the private service |
| `before_model` callback | CES sandbox | Fires the tool once per conversation, gated on `customer_id` |
| Relay | Cloud Run (public) | Bridges the browser to the CXAS bidi session |
| UI | Cloud Run (public) | Unified talk-or-type client |

> The relay and UI are **public** so a browser can open a WebSocket to them (a
> browser cannot attach an OIDC token to the handshake). The hydration service is
> **private** — only the CES service agent can invoke it.

---

## Prerequisites

- **`gcloud` CLI**, authenticated twice — user credentials for the `gcloud`
  calls, and ADC for the Python SDKs and the relay:

  ```bash
  gcloud auth login
  gcloud auth application-default login
  gcloud config set project YOUR_PROJECT_ID
  ```

- **Python 3.10+**. Nothing else needs installing by hand: `deploy_all.sh`
  creates `.venv` and installs `requirements.txt` on first run.

- **APIs enabled** in the project:

  ```bash
  gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
    ces.googleapis.com --project YOUR_PROJECT_ID
  ```

- **CX Agent Studio opened once in the console** for the project. That is what
  provisions the CES service agent
  (`service-<PROJECT_NUMBER>@gcp-sa-ces.iam.gserviceaccount.com`), which the
  hydration service's IAM binding targets. Skip it and the deploy fails at that
  binding.

- **`.env`** — copy the template and fill in the project and models:

  ```bash
  cd cxas-to-cxas-a2a       # all commands in this README run from here
  cp .env.example .env
  ```

  `GOOGLE_CLOUD_LOCATION` is the **Cloud Run region** (e.g. `us-central1`) and is
  not the same as `CXAS_LOCATION` (e.g. `us`).

### Installing the dependencies by hand

Only needed to run the `bootstrap/` scripts or the `cxas` CLI without going
through `deploy_all.sh`:

```bash
cd cxas-to-cxas-a2a
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt      # cxas-scrapi, google-cloud-ces, python-dotenv
```

`cxas-scrapi` is on public PyPI — no private index or extra credentials — so
`pip install cxas-scrapi` works standalone if you only want the SDK. Installing it
also puts a `cxas` CLI on the venv's `bin/`. Built against **1.7.0**.

Use the venv's interpreter explicitly (`.venv/bin/python …`) rather than
activating, so the scripts never pick up a different Python.

---

## Deploy everything (one command)

```bash
cd cxas-to-cxas-a2a
bash deploy_all.sh
```

Expect **~10–15 minutes**, nearly all of it Cloud Build compiling the three
container images.

| Step | Action |
|---|---|
| 1 | Chat app → CX Agent Studio (skipped if it exists) |
| 2 | Voice app → CX Agent Studio (skipped if it exists) |
| 3 | Hydration service → Cloud Run (private) + `run.invoker` + OpenAPI toolset |
| 4 | Attach the toolset and the firing callback to the root agent |
| 5 | Relay + UI → Cloud Run (public) |
| 6 | Print URLs and the arm-a-test command |

> **Run it yourself, interactively.** Step 3 binds an IAM policy (`run.invoker`
> for the CES service agent). An unattended shell may be refused the binding.

It is safe to re-run. Cloud Run deploys create a new revision in place and URLs
stay stable; the toolset, callback, and instruction are rewritten each time. The
two CX Agent Studio apps are the exception — creating an app registers its agents
and assigns their IDs, so re-creating one would overwrite agents you may have
edited since. The script skips an app that already exists.

---

## Destroy everything (one command)

```bash
cd cxas-to-cxas-a2a
bash destroy_all.sh              # the three Cloud Run services
bash destroy_all.sh --all        # also both CX Agent Studio apps
bash destroy_all.sh --all --yes  # no confirmation prompt
```

| | Removed |
|---|---|
| default | `cxas-web-ui`, `cxas-web-relay`, `cxas-hydration` |
| `--all` | the above, plus the hydration toolset and session variables, plus the `cxas-voice-and-chat` and `cxas-chat` apps |

**The default deliberately keeps the CXAS apps.** Deleting an app destroys its
agents, its toolsets, and its **conversation history** — the history hydration
reads. That is rarely what you want between test runs, so it takes an explicit
`--all`. It prompts before deleting either way, and is safe to re-run: anything
already gone is skipped.

---

## Deploy one component at a time

`deploy_all.sh` runs exactly these, in this order. Use them individually to
re-deploy a single piece. Run every command from this folder, after:

```bash
cd cxas-to-cxas-a2a
set -a; source .env; set +a
PROJECT="${CXAS_PROJECT:-$GOOGLE_CLOUD_PROJECT}"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
PY=.venv/bin/python          # deploy_all.sh creates this venv on first run
```

**1 · CXAS chat app** — create once; the voice app's A2A tool targets it.

```bash
$PY bootstrap/create_chat_app.py
```

**2 · CXAS voice app** — create once. Pass the chat app's A2A endpoint to enable
the troubleshooting hop, or omit it (the wrapper then carries only `end_session`).

```bash
$PY bootstrap/create_voice_app.py "${CHAT_A2A_URL:-}"
```

**3 · Hydration service** → Cloud Run, private, plus the IAM binding and the
OpenAPI toolset. The wrapper script does all three:

```bash
bash hydration/deploy_hydration.sh
```

Or the container alone, when only `hydration/server.py` changed:

```bash
gcloud run deploy "${HYDRATION_SERVICE:-cxas-hydration}" --source hydration \
  --region "$REGION" --project "$PROJECT" --port 8080 --timeout 60 \
  --min-instances 1 --max-instances 3 --cpu 2 --memory 1Gi \
  --cpu-boost --no-cpu-throttling --no-allow-unauthenticated --quiet \
  --set-env-vars "^@^CXAS_PROJECT=${PROJECT}@CXAS_LOCATION=${CXAS_LOCATION:-us}@VOICE_APP_ID=${VOICE_APP_ID:-cxas-voice-and-chat}"
```

**4 · Attach hydration to the root agent** — toolset + the firing callback +
greeting instruction. Re-run after any change to the callback or instruction:

```bash
$PY bootstrap/attach_hydration.py
```

**5 · Relay and UI** → Cloud Run, public. The wrapper deploys the relay, points
the UI at it, deploys the UI, then restores `config.js` for local use:

```bash
bash deploy_web.sh
```

Or each on its own:

```bash
# relay (root Dockerfile; needs backend/ + relay-requirements.txt)
gcloud run deploy "${RELAY_SERVICE:-cxas-web-relay}" --source . \
  --region "$REGION" --project "$PROJECT" --port 8080 --timeout 3600 \
  --min-instances 1 --max-instances 5 --cpu 2 --memory 1Gi \
  --cpu-boost --no-cpu-throttling --allow-unauthenticated --quiet \
  --set-env-vars "^@^CXAS_PROJECT=${PROJECT}@CXAS_LOCATION=${CXAS_LOCATION:-us}@VOICE_APP_ID=${VOICE_APP_ID:-cxas-voice-and-chat}"

# UI (inject the live relay URL, deploy, restore the file for local runs)
RELAY_BASE="$(gcloud run services describe "${RELAY_SERVICE:-cxas-web-relay}" \
  --region "$REGION" --project "$PROJECT" --format='value(status.url)')"
printf 'window.RELAY_URL = "wss://%s";\n' "${RELAY_BASE#https://}" > frontend/config.js
gcloud run deploy "${UI_SERVICE:-cxas-web-ui}" --source frontend \
  --region "$REGION" --project "$PROJECT" --port 8080 \
  --allow-unauthenticated --quiet
printf 'window.RELAY_URL = "ws://localhost:8000";\n' > frontend/config.js
```

A Cloud Run redeploy creates a new revision in place — no teardown, and the
service URL is unchanged.

> **The two CXAS apps are create-once.** Steps 1 and 2 register agents on the
> platform and assign their IDs; re-running them on a live app overwrites agents
> you may have edited since. `deploy_all.sh` therefore skips an app that already
> exists. To change an existing app, edit it in the console — or, for the
> hydration wiring specifically, re-run step 4, which is written to be re-runnable.

## Unified voice + chat client

A single page where the user can **tap the mic and talk, or type — in one
conversation**. This is the customer-facing use case: one entry point, either
modality, no channel switch.

```
browser (chat.html)  ──WS──►  relay (backend/relay.py)  ──wss──►  cxas-voice-and-chat
   mic  ─┐                      one CXAS bidi session              (live model)
   text ─┘  one socket          session id never changes
```

Why a relay is required: the browser cannot reach CXAS directly. The text path is
unary gRPC (browsers can't speak it) and the audio path needs a Google OAuth
bearer token, which must never ship to a page.

How one session serves both: CXAS's bidirectional protocol carries text *and*
audio on the same socket — `SessionInput.text` for a typed turn,
`SessionInput.audio` for mic frames — against one `session` that never changes.

```bash
cd cxas-to-cxas-a2a
gcloud auth application-default login   # once — the relay uses ADC
.venv/bin/pip install -r relay-requirements.txt
bash run_local.sh                       # relay :8000 + UI :8080
# open http://localhost:8080/chat.html
```

Requires the app to be on a **live** model (live models accept both audio and
text; a text-only model cannot do audio). `cxas-voice-and-chat` already is.

Behaviour notes, all observed against the live app:

- The agent's reply **streams as text fragments**, so the client accumulates a
  turn into one bubble and closes it on `turn_complete`.
- CXAS **synthesizes audio even for typed turns**. Playback is governed by a
  latched `voiceMode`: a conversation starts silent (text in, text out), and the
  first time the user turns the mic on it becomes a spoken conversation — every
  reply from then on is played, including replies to turns they type. Turning the
  mic back off does not silence it; only a new session resets to text-only.
- CXAS **does not greet on connect**; the relay sends a benign opener
  (`GREETING_KICK`, default `hello`) to trigger it. The browser never echoes it.
- The mic must keep streaming while a turn is in flight — the endpointer needs a
  continuous stream to detect end-of-speech. Frames are gated only while the
  agent is speaking (half-duplex), so the model never hears itself.

## Cross-channel hydration (continue a prior conversation)

A returning customer is greeted with what they were last working on, instead of a
cold "how can I help you". It works on any channel — web, simulator, telephony —
because the trigger is an identity check, not a channel check.

```
new session ─► before_model_callback ─► customer_id set?
                                          │ no  ─► normal greeting, tool never fires
                                          │ yes ─► inject tool call
                                                    │
                                        Cloud Run /hydrate ─► get_conversation
                                                    │
                                        {found, topic, summary}
                                                    │
                                          "Welcome back! Are you calling
                                           about your internet issue?"
```

| Piece | What it does |
|---|---|
| `hydration/server.py` | Private Cloud Run service. Reads the prior conversation and returns a digest. |
| `bootstrap/create_hydration_tool.py` | Session variables + the OpenAPI toolset (OIDC via the CES service agent). |
| `steering/hydration_callback.py` | The `before_model` callback that fires the tool. |
| `bootstrap/attach_hydration.py` | Attaches toolset + callback and sets the greeting instruction. |
| `bootstrap/set_hydration_vars.py` | Arms/disarms a test. |

**Two variables, two different jobs.** `customer_id` decides *whether* to hydrate;
`resume_conversation_id` decides *what* to load. An empty `customer_id` means the
callback returns immediately and the model never sees the tool.

Arm a test (both variables; `deploy_all.sh` has already deployed and attached it):

```bash
.venv/bin/python bootstrap/set_hydration_vars.py \
    --customer-id cust-test --conversation-id <PRIOR_SESSION_UUID>
```

The UUID is the session id from an earlier conversation — conversation id and
session id are the same value. Then start a **new** session: these are app-level
variable defaults, so they seed new sessions only. Disarm with `--clear`.

### Why a callback and not an instruction

Asking the model to "call this tool once, before greeting" fails in both
directions — it can skip the call on turn 1 and re-call it on turn 5. The callback
removes the decision from the model. Three locks make a second call impossible:
the `hydrated` session variable (across turns), a scan of the current invocation's
parts (within a turn), and `hide_tool()`, which strips the tool from the schema
once hydration is settled.

Returning an `LlmResponse` from a `before_model` callback *replaces* that model
step, and a `FunctionCall` in it is executed like any model-emitted call — so the
tool runs, the result returns, and the model then greets with it in context.

### Digest and callback gotchas

- **`_text_of` must read `transcript`, not just `text`.** Spoken turns — caller ASR
  and agent TTS alike — arrive as `chunk["transcript"]`; only typed turns use
  `text`. Reading `text` alone silently reduces a full conversation to whatever
  was typed, which looks like "no history" rather than a bug.
- **`summary` is a verbatim tail, not a paraphrase.** Last `HYDRATION_RECENT_TURNS`
  messages (default 6, counted per message, not per exchange), capped at
  `HYDRATION_MAX_CHARS`. No model in the path, so no added latency.
- **`topic` is the first *substantive* customer utterance.** Greetings and
  one-or-two-word turns are filtered out, so a thin prior conversation yields an
  empty topic and a plain welcome-back rather than "your previous hello".
- Callback contract: fully-typed snake_case signature, and `Optional` must be
  imported. An unannotated signature is silently ignored.

## Telephony (IVR / GTP)

Not configured by `deploy_all.sh`, and not wired in this bundle. A phone channel
needs, in the Conversational Agents console: a published **version** of the voice
app, a Google Telephony Platform channel pinned to that version, a phone number,
and a mapping from the caller's identity into the `customer_id` session variable
(that last part is what makes hydration fire on a call).

> **Channels are version-pinned.** Once a channel exists, editing the draft — including
> changing `customer_id` or `resume_conversation_id` — has **no effect on live
> calls**. Every change needs a new version and the channel repointed at it.
> Skipping this makes tests look broken for entirely the wrong reason.

The hydration callback itself needs nothing telephony-specific: it gates on
`customer_id`, not on the channel.

## Notes

- **A2A plumbing is stubbed.** The `chat_adapter` tool and its card are created
  when `CHAT_TOOL_ENABLED=true`, but wiring the deployed cxas-chat A2A endpoint,
  its executor, and P4SA/IAM auth is left to you.
- **Live modality.** The live model is set per-agent (`VOICE_LIVE_MODEL`). If the
  platform needs an app-level streaming/modality flag for live audio, set it in
  the console.
- Config is read from `.env`; nothing is hardcoded. `CXAS_PROJECT` overrides
  `GOOGLE_CLOUD_PROJECT` if CXAS lives in a different project.

## Tests

```bash
cd cxas-to-cxas-a2a
.venv/bin/python -m pytest tests/
```
