# AudioCodes → Multi-Agent Voice Steering — Design Spec

Date: 2026-06-21
Status: Draft — pending review

## 1. Objective

Prototype an inbound-voice system for a single 1-800 number that, on each call,
(1) detects the caller's intent from their first utterance and (2) steers the
live audio to the right specialist agent — **without** dropping the call, losing
context, or re-greeting the caller. The conversation is **one linear flow** from
the caller's perspective.

Two things this prototype must prove:

1. **AudioCodes works with WebSockets** as the media path for our agents, using a
   pattern AudioCodes natively supports (so it inherits AudioCodes' proven scale
   rather than becoming a custom bottleneck).
2. **The relay can establish a voice channel to a specialist agent on _any_ GCP
   platform, seamlessly** — proven by routing to agents hosted two different ways
   (ADK + Gemini Live, and CX Agent Studio) behind one identical relay.

## 2. Scope

In scope:

- One AudioCodes VoiceAI Connect (VAIC) bot endpoint, WebSocket (Bot API) mode.
- A **steering relay** that owns the AudioCodes WebSocket and bridges audio to a
  selected backend agent, swapping the agent in-process on intent.
- A **greeter/router** agent that greets and classifies intent on the first turn.
- **Three specialist agents**, deliberately minimal (they only need to prove
  connectivity, not full troubleshooting depth):
  - **Internet** — ADK agent on Agent Engine, Gemini Live API.
  - **Phone-upgrade** — ADK agent on Agent Engine, Gemini Live API.
  - **Billing** — CX Agent Studio (CES) agent via `BidiRunSession`.
- Seamless, **linear** handoff: the specialist continues the conversation with no
  "welcome back" and no re-greeting.
- Native AudioCodes `transfer` reserved for human escalation (documented; a real
  human queue is optional for the first cut).

Non-goals (explicitly out):

- **No load/throughput benchmark.** We prove scale *by design* (native pattern,
  stateless relay), not with a stress test.
- **No chat channel and no chat/voice duplex complexity.** Channel is always IVR
  voice. The agents do not need the half-duplex / shared chat-voice handling from
  the `shared-session-voice-and-chat` module.
- **No callback continuity / return-call greeting.** No 45-minute "welcome back"
  behavior. One call = one linear conversation.
- **No deep specialist business logic.** Specialists just answer enough to show
  the channel is live and context arrived.

## 3. Validated platform facts

All confirmed against current official docs (2026-06-21):

**AudioCodes VAIC — Bot API WebSocket mode** ([docs](https://techdocs.audiocodes.com/voice-ai-connect/Content/Bot-API/ac-bot-api-mode-websocket.htm)):

- One WebSocket per call, opened by VAIC, alive for the whole call.
- Handshake: VAIC sends `session.initiate` (`conversationId`, `botName`,
  `caller`, `expectAudioMessages`, `supportedMediaFormats`); bot replies
  `session.accepted` with a chosen `mediaFormat`. On reconnect VAIC sends
  `session.resume`.
- Inbound caller audio: `userStream.start` / `userStream.chunk` (base64) /
  `userStream.stop`. Optional `userStream.speech.hypothesis` /
  `.recognition` for barge-in.
- Outbound agent audio: `playStream.start` / `playStream.chunk` (base64) /
  `playStream.stop`. One play stream active at a time.
- Media formats: `raw/mulaw` & `raw/lpcm16` (8 kHz telephony), plus
  `raw/lpcm16_24` (24 kHz) on VAIC-E ≥ 3.24.1.
- Disconnect: bot sends a `hangup` activity; VAIC then sends `session.end`.

**AudioCodes transfer** ([docs](https://techdocs.audiocodes.com/voice-ai-connect/Content/VAIG_Combined/call-transfer.htm)):

- Bot sends an `activities` message with a `transfer` (a.k.a. `handover`) event;
  `transferTarget` is a **SIP or tel URI**. It is a telephony re-route (SBC issues
  SIP REFER/INVITE), not a WebSocket swap. By default VAIC disconnects the bot on
  transfer; `transferNotifications: true` lets the bot survive a *failed* transfer.
- Used here only for human escalation, not for AI-to-AI steering.

**CX Agent Studio (CES) — `BidiRunSession`** ([API access](https://docs.cloud.google.com/customer-engagement-ai/conversational-agents/ps/deploy/api-access), [RPC ref](https://docs.cloud.google.com/customer-engagement-ai/conversational-agents/ps/reference/rpc/google.cloud.ces.v1)):

- Native bidirectional streaming voice, exposed as a WebSocket:
  `wss://ces.googleapis.com/ws/google.cloud.ces.v1.SessionService/BidiRunSession/locations/{loc}`.
- Auth: ADC bearer token, `cloud-platform` scope (same ADC the relay uses for Vertex).
- First client message = `SessionConfig` (`session` resource name,
  `input_audio_config`, `output_audio_config`, optional `historical_contexts[]`,
  optional `entry_agent`), then stream audio frames.
- Server stream: `recognition_result` (user transcript), `session_output` (agent
  reply text/audio, `turn_completed`), `interruption_signal`, `end_session`.
- **CES owns its session server-side.** Context is seeded via `historical_contexts[]`;
  there is no client read/write state dict mid-stream.

## 4. Architecture (Option B: in-process steering)

```
                AudioCodes Bot API (WS #1)              backend voice channel (#2)
  PSTN            VAIC / SBC                                 (run_live OR BidiRunSession)
 caller ──SIP──►  ═══════════════════════►  STEERING RELAY  ═══════════════════════► [ Agent ]
                  session.initiate/accepted   (owns WS #1,      ┌───────────────────────────┐
                  userStream  (caller PCM)     bridges audio,    │ Greeter/Router  (ADK/Live)│
                  playStream  (agent  PCM)     steers, is the    │ Internet        (ADK/Live)│
                  transfer    (human only)     session-of-record)│ Phone-upgrade   (ADK/Live)│
                                                                 │ Billing         (CES bidi)│
                                                                 └───────────────────────────┘
```

Two independent connections; the relay owns both. The relay core is written
against **two ports** so each side is a drop-in:

- **Caller side — `MediaGateway` port (WS #1).** End state: AudioCodes VAIC Bot API
  protocol. The relay core never assumes AudioCodes — it talks to a `MediaGateway`
  interface (`recv` caller PCM, `send` agent PCM, `transfer`, `end`). Phase 1 uses
  a `HarnessGateway`; Phase 2 adds an `AudioCodesGateway`.
- **Agent side — `AgentSession` port (channel #2).** Opened *by the relay*. For ADK
  agents this is `runner.run_live()` (which establishes the Gemini Live connection
  internally); for the billing agent it is a `BidiRunSession` WebSocket to CES.

The caller never talks to an agent directly — the relay pumps PCM across the seam.
Both ends being swappable behind ports is the whole point: it makes the AudioCodes
work (Phase 2) and the cross-platform agents (Phase 1) each a drop-in.

### Components and boundaries

| Unit | Responsibility | Interface | Depends on |
|---|---|---|---|
| `relay` | Run the call lifecycle, steer, keep the session-of-record, resample — port-agnostic on both sides | `MediaGateway` in/out; `AgentSession` out | port impls, session store |
| `MediaGateway` (interface) | Caller-side media channel | `recv()` → caller PCM/events, `send_pcm(bytes)`, `transfer(uri)`, `end()` | — |
| `HarnessGateway` | `MediaGateway` for local dev (Phase 1) | implements `MediaGateway` | WAV replay / mic test client |
| `AudioCodesGateway` | `MediaGateway` over VAIC Bot API WS (Phase 2) | implements `MediaGateway` | VAIC tenant |
| `AgentSession` (interface) | One backend voice channel | `open(ctx)`, `send_pcm(bytes)`, `recv()` → audio/transcript/intent events, `close()` | — |
| `AdkLiveSession` | `AgentSession` over ADK `run_live` | implements `AgentSession` | ADK Runner, Agent Engine, `VertexAiSessionService` |
| `CesBidiSession` | `AgentSession` over CES `BidiRunSession` | implements `AgentSession` | CES app, ADC token |
| Greeter/Router agent | Greet + emit `{intent}` | ADK agent (tool/structured output) | Gemini Live |
| Internet / Phone-upgrade agents | Minimal specialist replies | ADK agents | Gemini Live |
| Billing agent | Minimal specialist replies | CES app/playbook | CES |
| session store | Shared ADK sessions + relay record | `VertexAiSessionService` (`SESSION_ENGINE_ID`) | Agent Engine |

The relay's AudioCodes side, steering logic, and bookkeeping are **identical
regardless of backend** — only the `AgentSession` implementation differs. That
sameness *is* the cross-platform proof (goal 2).

## 4a. Build order (milestones)

Prove the novel part first; add telephony onboarding last.

- **Phase 1 — Relay ↔ agents, seamless (no AudioCodes yet).**
  - Relay core + `MediaGateway`/`AgentSession` ports.
  - `HarnessGateway`: a local test client (mic web client or WAV replay) that feeds
    caller audio in and plays agent audio out.
  - `AdkLiveSession` (Internet, Phone-upgrade) and `CesBidiSession` (Billing).
  - Greeter/router + steering + session-of-record + context passing.
  - **Done when:** speaking an intent routes to the right agent across *both*
    platforms, the conversation is one seamless linear flow (no re-greet), and
    context carries. This proves goal 2 (relay → any GCP platform, seamlessly).
- **Phase 2 — AudioCodes drop-in.**
  - `AudioCodesGateway` implementing the VAIC Bot API WS contract
    (`session.initiate`/`accepted`, `userStream`/`playStream`, `transfer`, `resume`).
  - Onboard a VAIC self-service tenant + US test DID; point its bot at the relay.
  - **Done when:** a real PSTN call to the test number runs the same Phase-1 flow
    end-to-end. This proves goal 1 (AudioCodes + WebSockets, native pattern).

Phase 2 changes *only* the `MediaGateway` impl — relay core, steering, agents, and
session model from Phase 1 are untouched.

**Deployment & call duration (decided):** relay runs on **Cloud Run** with a
**15-minute request timeout** for the demo (`wss://` works natively on Cloud Run;
no separate endpoint). Cloud Run's request timeout caps a single call at 60 min
max; 15 min is sufficient for the demo. Production note: calls beyond ~60 min need
the relay on **GKE/GCE** (no request-duration cap) *and* model-session-resume
handling (Gemini Live / CES sessions are themselves time-bounded). Because the
relay is stateless behind the `MediaGateway` port and is the session-of-record,
that move is a deployment change, not a code change. (See §11.)

## 5. Steering flow (one linear conversation)

```
CALLER          VAIC                 RELAY                         AGENTS
  │ dials ─────►│                      │
  │             │ session.initiate ───►│  create session_id X
  │             │◄─── session.accepted │  (X derived from conversationId)
  │             │                      │── open ──► Greeter (ADK run_live)
  │             │◄─ playStream ────────│◄ "Thanks for calling, how can I help?"
  │ "internet   │                      │
  │  is down" ─►│─ userStream ────────►│── PCM ──► Greeter (classifying)
  │             │                      │◄ intent = "internet"
  │             │           ┌──────────┴───────────────┐
  │             │           │ STEER:                    │
  │             │           │  • close Greeter channel  │  ← greeter goes silent
  │             │           │  • open Internet channel  │
  │             │           │    (same session_id X)    │
  │             │           └──────────┬───────────────┘
  │             │◄─ playStream ────────│◄ "...let's take a look"  ← continues, NO re-greet
  │ ⇄ ========== relay pumps PCM both ways for the rest of the call ========== │
  │             │  (caller frustrated → relay sends native VAIC transfer → human SIP queue)
```

- **No re-greeting / no "welcome back."** The specialist's opening line continues
  the existing conversation; it must not restart or re-introduce. WS #1 to
  AudioCodes never drops — only channel #2 is re-pointed — so the caller hears one
  continuous conversation.
- **Where intent detection runs:** a one-shot greeter turn, not a hot inline LLM.
  After the swap the relay is a cheap audio pump; the specialist does the work.

## 6. Session & context model

The relay is the **session-of-record**, keyed by `session_id X` (derived from the
AudioCodes `conversationId`). Continuity is delivered differently per boundary —
this is a deliberate, validated distinction:

| Boundary | Shared store? | Context mechanism |
|---|---|---|
| Greeter → ADK specialist (Internet, Phone-upgrade) | **Yes** | All ADK agents use one `VertexAiSessionService(agent_engine_id=SESSION_ENGINE_ID)` and the **same `session_id X`**; the specialist reads prior turns and appends to the same session — even across separate Agent Engine deployments. |
| Greeter → CES specialist (Billing) | **No shared store** | CES owns its session server-side. Relay **seeds** the greeter transcript/intent via `historical_contexts[]` at connect and **captures** CES turns from `recognition_result` / `session_output`. The same `X` is reused as the CES session id **for correlation only**. |

- **ADK shared session** is the proven pattern from `shared-session-voice-and-chat`
  (`agent_app.py`, `session_resolve.py`): explicit `agent_engine_id` decouples the
  session store from compute, so any number of ADK agents share one continuous session.
- **Same id string across platforms** is a *correlation key*, not a data bridge.
  It buys end-to-end tracing (one id across AudioCodes / ADK / CES logs, traces,
  CDRs), relay reconciliation (`X → {ADK session X, CES session X}`), and audit
  reconciliation. The actual content transfer to CES is `historical_contexts[]`.
- Transcription must be enabled on the ADK Live config so the greeter's audio
  turns land in the session as text for the specialist to inherit.

## 7. Audio format / resample seam

- AudioCodes telephony: 8 kHz (`raw/mulaw` or `raw/lpcm16`); 24 kHz `lpcm16_24`
  available on VAIC-E ≥ 3.24.1.
- Gemini Live: 16 kHz in, 24 kHz out.
- CES: `input_audio_config` / `output_audio_config` take explicit
  `audio_encoding` + `sample_rate_hertz`.
- Relay normalizes to PCM16 internally and resamples per backend:
  - Inbound: 8 kHz → 16 kHz for Gemini; for CES set the input config to match.
  - Outbound: 24 kHz → 8 kHz to AudioCodes (or pass 24 kHz if `lpcm16_24`); CES
    output configured to 8 kHz LINEAR16.
- Reuse the resample/`Blob` plumbing already proven in the existing module
  (`send_realtime(types.Blob(data=pcm, mime_type="audio/pcm;rate=16000"))`).

## 8. Error handling & lifecycle

- **`session.resume`:** relay re-accepts and rebinds the in-progress backend
  channel to the same `session_id X` (ADK store survives; CES re-seeded if needed).
- **Backend channel failure:** relay keeps WS #1 alive, plays a short hold/retry
  line, and re-opens the channel — the caller is not dropped.
- **Transfer (human escalation):** relay sends the native VAIC `transfer` with
  `transferNotifications: true` so a failed transfer returns control to the bot.
- **Hangup / end:** relay tears down channel #2, sends `hangup`, closes on
  `session.end`. Mic/socket lifecycle hygiene from the existing module applies.

## 9. AudioCodes onboarding path

VAIC has a **self-service edition (Live Hub)** with wizard onboarding, pay-as-you-go,
and US numbers (BYOC or purchased) — a real test DID + Bot API without enterprise
sales. AT&T's existing AudioCodes relationship is a faster alternative for a lab
tenant. We build against the documented Bot API contract immediately and point a
real tenant at the relay when provisioned — this is the real integration, not a
simulation.

## 10. Reuse from `shared-session-voice-and-chat`

- Relay audio-bridge pattern (browser WS → AudioCodes WS is the only swap).
- ADK `run_live` driver, `LiveRequestQueue` / `Blob` usage, transcription handling.
- `VertexAiSessionService` + `SESSION_ENGINE_ID` shared-session wiring.
- Idempotent Agent Engine deploy scripts (update-in-place, stable ids).
- Dropped: chat channel, chat/voice duplex handling, return-call greeting.

## 11. Risks & open questions

- **CES media encodings:** confirm CES `AudioEncoding` supports the chosen
  telephony rate/encoding (LINEAR16 8 kHz at minimum) during the first spike.
- **Greeter→specialist seam latency:** measure the gap when closing the greeter
  channel and opening the specialist; if audible, have the greeter speak a short
  bridging clause as the swap fires.
- **CES `historical_contexts[]` fidelity:** verify the billing agent actually
  honors injected context (opens mid-conversation, no re-greet).
- **VAIC version:** confirm the tenant's VAIC-E version for `lpcm16_24` support;
  otherwise standardize on 8 kHz end-to-end.
- **Long calls:** Cloud Run caps a call at 60 min (demo uses 15 min). Calls beyond
  that need the relay on GKE/GCE plus model-session-resume (Gemini Live / CES are
  time-bounded). Out of scope for the demo; flagged for production.

## 12. Sources

- AudioCodes VAIC WebSocket Bot API — https://techdocs.audiocodes.com/voice-ai-connect/Content/Bot-API/ac-bot-api-mode-websocket.htm
- AudioCodes call transfer — https://techdocs.audiocodes.com/voice-ai-connect/Content/VAIG_Combined/call-transfer.htm
- AudioCodes VAIC self-service edition — https://voiceaiconnect.audiocodes.com/self-service-edition
- CES `BidiRunSession` API access — https://docs.cloud.google.com/customer-engagement-ai/conversational-agents/ps/deploy/api-access
- CES v1 RPC reference — https://docs.cloud.google.com/customer-engagement-ai/conversational-agents/ps/reference/rpc/google.cloud.ces.v1
