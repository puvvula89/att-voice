# AudioCodes Steering Relay — Phase 1

## What Phase 1 Proves

A single inbound voice session can be steered across multiple AI back-ends — ADK agents running on Agent Engine and a CES billing agent on a separate platform — with no audible re-greeting at each handoff. The caller hears one continuous conversation; the routing decision is invisible. Phase 1 uses a browser mic harness in place of an AudioCodes Media Gateway, so the full relay + steering stack can be verified without telephony infrastructure.

## Architecture

```
Browser (harness/client.html)
        │ WebSocket /ws  16 kHz PCM16 up · 24 kHz PCM16 down
        ▼
relay/server.py  (uvicorn, :8080)
  ├── MediaGateway port  — receives caller audio, sends agent audio back
  └── AgentSession port  — owns one session lifetime
        │
        ▼
Steering loop  (relay/steering.py)
  ├── Turn 1: Greeter agent classifies intent
  │     → "internet" → internet_specialist (ADK / Agent Engine)
  │     → "phone_upgrade" → phone_upgrade_specialist (ADK / Agent Engine)
  │     → "billing" → billing_specialist (CES)
  └── Each specialist receives a (handoff) nudge carrying the caller's
      opening utterance so it continues — never re-greets.

Session-of-record: shared InMemorySessionService (in-process ADK) or
AeAdkSession adapter (Agent Engine bidi stream).  CES receives the
greeter turn as historicalContexts on open.
```

**Ports**

| Component | Default |
|-----------|---------|
| Relay WebSocket | `:8080` |
| Harness static server | `:8000` |

## How to Run

### Prerequisites

1. **Python 3.12** virtual environment inside `audiocodes-to-adk-agent/`:
   ```bash
   python3.12 -m venv .venv && . .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Application Default Credentials** for Vertex AI:
   ```bash
   gcloud auth application-default login
   ```

3. Copy `.env.example` to `.env` and fill in:
   ```
   GOOGLE_CLOUD_PROJECT=your-project-id
   GOOGLE_CLOUD_LOCATION=us-central1
   AE_ENGINE_ID=projects/.../reasoningEngines/...   # from deploy step
   CES_APP=projects/.../apps/...                    # CES billing app resource
   ```
   Omit `AE_ENGINE_ID` to run ADK agents in-process (no Agent Engine needed).

4. **Deploy ADK agents to Agent Engine** (one-time, idempotent):
   ```bash
   python deploy/deploy_agent_engine.py
   ```
   Copy the printed engine ID into `.env` as `AE_ENGINE_ID`.

5. **CES billing app** — provision a CES app with the billing agent and set `CES_APP`.

### Running

Terminal A — relay:
```bash
cd audiocodes-to-adk-agent
. .venv/bin/activate
uvicorn relay.server:app --port 8080
```

Terminal B — harness static server:
```bash
cd audiocodes-to-adk-agent/harness
python serve.py
```

Browser — open `http://localhost:8000/client.html`, click **Start call**, speak.

## Demo Routes

| Caller says | Routes to | Expected |
|-------------|-----------|----------|
| (opening — any) | Greeter | "Thanks for calling AT&T. How can I help you today?" |
| "my internet is down" | Internet specialist (ADK / AE) | Continues without re-greeting |
| "I want to upgrade my phone" | Phone-upgrade specialist (ADK / AE) | Continues without re-greeting |
| "I have a question about my bill" | Billing specialist (CES) | Continues without re-greeting; different back-end platform |

In every case the conversation sounds like a single continuous voice. No "hello / welcome" at handoff.

## Phase 2 — Next Steps

Phase 2 replaces the browser harness with a real AudioCodes `MediaGateway` connection, enabling PSTN calls through the same relay with no changes to the steering loop or agent back-ends.
