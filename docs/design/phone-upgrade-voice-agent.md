# Voice Phone-Upgrade Agent — Architecture

**Date:** 2026-06-03 · **Status:** Approved design · **Module:** `01-phone-upgrade`

A voice agent for a phone-upgrade flow, built on Google ADK and the Gemini Live API. It speaks naturally to the user while pushing custom JSON UI components to the frontend on the same stream, driven by a single streaming agent — no second LLM, no orchestration hop.

---

## Goals

| # | Goal |
|---|------|
| 1 | Deliver custom JSON UI payloads on the **same stream** as the voice response. |
| 2 | Use **one** streaming agent + a **deterministic** formatter — no second LLM, no orchestration hop. |
| 3 | Support **dual input**: voice *or* click advances the same session state. |
| 4 | Preserve the `stage_intent` / template model so it maps onto the planned formatter-as-a-tool evolution. |

---

## Architecture: chat (current) → voice (this design)

**Current chat flow** — two LLMs orchestrated across hops:

```
Frontend → Orchestrator
            ├─► Sales Master (LLM)  → writes tool data to state by `stageintent`, returns text + intent id
            └─► Formatter   (LLM)  → reads state by intent, fills template → { text, ui[] }
          ↓ Frontend renders text + UI
```

**Voice flow** — one LLM, one stream:

```
Browser ⇄ WS Relay ⇄ Upgrade Agent (Live)
   • data tool        → writes result to state["data:<intent>"]
   • render_component(intent)  → after_tool_callback runs deterministic formatter
        → state["pending_ui"]  → relay emits ui_event to browser
   • native audio     → streams to browser in parallel
```

**Concept parity** — same mental model, second LLM and hop removed:

| Chat (current) | Voice (this design) |
|---|---|
| Sales Master writes tool data to state by `stageintent` | Data tool writes `state["data:<intent>"]` |
| Sales Master returns text + `stageintent` id | Agent speaks audio + calls `render_component(intent)` |
| Orchestrator hops to Formatter **LLM** | No hop — same process |
| Formatter LLM reads state, fills template | **Deterministic** formatter (pure function) fills template |
| Pushes `{ text, ui }` | `ui_event` JSON + native audio |

---

## Components

| Component | Responsibility |
|---|---|
| **Web client** | Mic capture → PCM; audio playback; render `ui_event` components; emit `user_action` on click. No business logic. |
| **WS relay** (`server.py`) | One WebSocket/session. Upstream: audio → `send_realtime`, clicks → `send_content`. Downstream: forward audio/transcript, emit `ui_event` from `state_delta`. No LLM, no logic. |
| **Upgrade Agent** (`agent.py`) | Single `LlmAgent` on `run_live` (BIDI). Instructions decide *when/which* `stage_intent` to render. |
| **Tools** (`tools.py`) | Data tools (mock) write to state; `render_component(stage_intent)` signals the chosen component. |
| **Formatter** (`formatter.py` + `templates/`) | Pure function `build_payload(intent, state) → ui_json`. Deterministic, unit-testable. |

**Formatter wiring** (`after_tool_callback` on `render_component`):

```python
def on_render(tool, args, tool_context, tool_response):
    if tool.name == "render_component":
        payload = build_payload(args["stage_intent"], tool_context.state)  # deterministic
        tool_context.state["pending_ui"] = payload     # relay reads this from state_delta
        return {"status": "shown"}                     # model sees an ack, never narrates JSON
    return None
```

> The callback returns a short ack to the model and stashes the full payload in `state`. The relay reads the rich payload from `state_delta`, not from the function response — keeping spoken text and UI cleanly separate.

---

## Flow & stage intents

```
"upgrade my phone"  → get_lines()        → render_component("line_selector")   🔊 "Which line?"
select line (🎤/🖱)  → get_eligible_phones → render_component("phone_options")   🔊 "Here are 3 phones…"
select phone (🎤/🖱) → select_phone()      → render_component("confirmation")    🔊 "Confirm the upgrade?"
"yes"               → confirm_upgrade()   → render_component("receipt")         🔊 "Done."
```

| Stage intent | Payload (shape) |
|---|---|
| `line_selector` | `{ lines: [{ last4, device, eligible }] }` |
| `phone_options` | `{ phones: [{ id, name, image, monthly_price, trade_in }] }` |
| `confirmation` | `{ line, phone, monthly_price, terms }` |
| `receipt` | `{ order_id, line, phone, ship_estimate }` |

Either path advances the same state: a click is injected as a user turn via `send_content`, identical to the spoken equivalent.

---

## Wire protocol (one WebSocket)

| Direction | Message | Maps to |
|---|---|---|
| Browser → server | `audio` (PCM frame) | `send_realtime(blob)` |
| Browser → server | `user_action` `{ stage_intent, selection }` | `send_content(text)` → user turn |
| Server → browser | audio / transcript / `turn_complete` | `event.model_dump_json()` |
| Server → browser | `ui_event` `{ stage_intent, payload }` | from `state_delta["pending_ui"]` |

---

## ADK: provided vs. application code

| Provided by ADK + Live API | Application code |
|---|---|
| Native-audio bidi voice (`run_live`, `BIDI`), barge-in | WS relay (ADK `bidi-demo` sample as base) |
| Tools, automatic execution, tool-call/response events | Deterministic formatter + JSON templates |
| LLM choosing `stage_intent` as a tool argument | `ui_event` envelope |
| `after_tool_callback`, session state + `state_delta` | Web client (ADK reference JS client as base) |
| Click injection via `send_content`, transcripts, resumption | Mock data fixtures |

Every agent-side capability is native; application code covers only transport, formatting, and frontend.

---

## Risks

| Risk | Mitigation |
|---|---|
| LLM calling `render_component` with the right intent at the right time (a reliability knob, not a capability gap) | Explicit agent instructions, clear tool/intent descriptions, iterate on transcripts |
| Audio format match (browser ↔ relay ↔ Live API) | Reuse ADK reference client audio settings |
| Cloud Run deploy (later): WS request timeout (max 60 min) | High timeout, `min-instances ≥ 1`, client reconnect |

---

## Repository layout

```
att-voice/
├── docs/design/phone-upgrade-voice-agent.md   ← this doc
├── shared/                # ws_server + web_client primitives (grows only when a 2nd module needs it)
└── 01-phone-upgrade/
    ├── backend/  agent.py · tools.py · formatter.py · templates/ · server.py · mock_data.py
    └── frontend/          # lightweight web client
```

Each module under a numbered folder is independently runnable.

---

## Scope & stack

**In:** the four-step upgrade flow, voice + click, mock data.
**Out:** real integrations, real auth (mock authorized user), production scaling/observability, cascade STT→TTS variant.

**Stack:** Python + ADK + Gemini Live + FastAPI (relay); lightweight TS web client (Web Audio API); in-code mock fixtures.

---

## References

- ADK — event handling (`run_live`): https://google.github.io/adk-docs/streaming/dev-guide/part3/
- ADK — RunConfig / `LiveRequestQueue` / resumption: https://google.github.io/adk-docs/streaming/dev-guide/part4/
- ADK — callback types: https://google.github.io/adk-docs/callbacks/types-of-callbacks/
- ADK — bidi WebSocket sample: https://github.com/google/adk-samples/tree/main/python/agents/bidi-demo
- Cloud Run — WebSockets: https://docs.cloud.google.com/run/docs/triggering/websockets
