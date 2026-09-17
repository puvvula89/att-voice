# PRD — Real-Time Voice Translation Layer for Contact Center Calls (POC)

**Status:** Draft for build
**Owner:** [you]
**Target consumer of this doc:** engineering, for planning and implementation

---

## 1. Summary

Build a translation bridge that sits in the media path of a contact center call so a Spanish-speaking customer and an English-speaking human agent can each hear only the language they understand, with translated audio starting as soon as the model emits its first audio chunk.

The bridge is a WebSocket application behind AudioCodes VoiceAI Connect. It holds two independent Gemini Live Translate sessions — one per direction — and crosses the audio streams. Google CCAI Agent Assist continues to operate unchanged.

## 2. Problem

The customer's current flow works like this:

1. Caller reaches a Conversational Agents (CXaaS) voice virtual agent via AudioCodes, over `BiDiStreamingAnalyzeContent` (Bidi-SAC). This handles Spanish natively today.
2. On escalation, the call transfers to a human agent in the contact center.
3. Agent Assist runs against the human-to-human call via a SIPREC fork into Bidi-SAC, returning transcripts and suggestions to the agent's screen.

Step 3 has no translation capability, for three independent reasons:

- **SIPREC is a passive mirror.** It delivers a copy of the audio and has no path back into the live call.
- **Bidi-SAC's audio return (`replyAudio`) only populates for automated agent replies.** In agent-assist mode the responses are suggestions and processed messages, and there is no participant targeting on audio output.
- **Live translation is explicitly excluded** from the Agent Assist feature set Bidi-SAC supports.

A native fix is on the roadmap with Google engineering. This POC proves the capability now and produces the measurements and interface contract that inform the native design.

## 3. Goals

| # | Goal | Measure |
|---|---|---|
| G1 | Prove translation quality on real telephony audio | Bilingual reviewer adequacy + fluency scores on recorded contact center calls |
| G2 | Streaming playback, not utterance-buffered | Translated audio begins playing before the speaker finishes their sentence |
| G3 | Bidirectional on a live two-party call | Each party hears only their own language; no far-end raw audio bleed |
| G4 | Agent Assist unaffected | All currently-enabled Agent Assist features work with no configuration change |
| G5 | Portable to the customer's on-prem VAIC Enterprise | Same wire protocol, config-only differences between Live Hub and VAIC-E |

## 4. Non-goals

- Production hardening, HA, or scale beyond a handful of concurrent calls.
- Translating the virtual agent phase of the call. Conversational Agents already handles Spanish; the bridge engages only at escalation.
- Language detection. The caller's language arrives as a parameter; the bridge never infers it.
- Deep quality validation across all 70+ supported languages. See §7.5 for the tiering approach.
- Transcript continuity or normalization across the VA→agent seam (VA half Spanish, agent half mixed). Explicitly deferred.
- Any change to Bidi-SAC, Agent Assist configuration, or the virtual agent.
- Billing, cost attribution, or capacity modeling.

## 5. Assumptions

- **The agent always speaks English.** The caller may speak any language Live Translate supports. The caller's language is selected upstream and passed to the bridge at call initiation.
- Gemini is accessed via Vertex / Agent Platform (`genai.Client(enterprise=True, project=..., location=...)`), not the AI Studio API-key path, so the POC matches the customer's procurement and data-residency posture.
- Live Hub supports the Bot API WebSocket mode with voice streaming, and supports integration with CXaaS agents. (Confirmed by the customer from prior hands-on use.)
- Development happens on Live Hub; the deliverable must run unmodified against VoiceAI Connect Enterprise apart from configuration.

## 6. Architecture

```
Caller (Spanish)
      │  SIP/RTP
      ▼
AudioCodes (Live Hub / VAIC-E)
      │  Bot API WebSocket, directSTT + directTTS
      ▼
Translation Bridge  ──────►  Gemini session A  (target = en)
      │                       Gemini session B  (target = es)
      │
      ▼  SIP/RTP (English on both legs)
Contact center → Agent (English)
      │
      ▼  SIPREC fork
CXaaS Agent Assist (Bidi-SAC) — sees English on both participants
```

**Insertion point is the escalation transfer, not call start.** The virtual agent phase is untouched. Only escalated calls in a supported language, with the bridge reachable, route through it. Any of those conditions failing routes to the existing agent queue exactly as today. This gate lives in the routing layer, never in the bridge.

**The bridge is stateless with respect to conversation content.** It crosses two audio streams and nothing else. No language detection, no transcript ownership, no CRM integration, no business logic. All of that stays in the virtual agent and routing layer, which makes the bridge removable later by a routing change.

## 7. Components to build

### 7.1 `bridge-server`

WebSocket server implementing the AudioCodes Bot API in streaming mode.

Start from the official reference implementation rather than from scratch:
- `github.com/ac-voice-ai/ac-api-samples` — TypeScript reference servers, including WebSocket Mode with `directSTT` / `directTTS`
- `@audiocodes/ac-bot-api` on npm — official WebSocket client SDK

**Inbound messages to handle:**

| Message | Action |
|---|---|
| `session.initiate` | Respond `session.accepted` with chosen `mediaFormat`. Read `AC-Conversation-Id` and `AC-Caller-Number` from the handshake headers. |
| `session.resume` | Re-attach to existing session state, respond `session.accepted` |
| `userStream.start` | Respond `userStream.started`. In agent-assist mode this carries a `participant` field. |
| `userStream.chunk` | Base64 PCM → forward to the Gemini session for that participant |
| `userStream.stop` | Respond `userStream.stopped` |
| `playStream.mark.reached` | Update playout tracking / buffer depth |
| `session.end` | Tear down both Gemini sessions |

**Outbound messages to emit:**

| Message | When |
|---|---|
| `playStream.start` | On the first translated audio chunk from a Gemini session |
| `playStream.chunk` | Continuously, paced to real-time playback speed |
| `playStream.mark.set` | Periodically, to track playout position |
| `playStream.stop` | When the translation stream for that direction drains |
| `userStream.speech.hypothesis` | Fed from Gemini's `inputTranscription` — VAIC uses this for barge-in |
| `userStream.speech.started` / `stopped` | Fed from Gemini VAD signals |

**Media formats — no resampling required anywhere:**
- Inbound: `raw/lpcm16` (16-bit PCM, 16 kHz) — matches Gemini Live Translate input exactly
- Outbound: `raw/lpcm16_24` (16-bit PCM, 24 kHz) — matches Gemini output exactly. Requires VAIC-E-3.24.1+.

### 7.2 `translation-sessions`

Two independent Gemini Live API sessions per call.

Session A is **fixed** — the agent always speaks English, and Live Translate auto-detects the source, so `target_language_code="en"` regardless of who is calling. Only Session B is parameterized.

```python
model = "gemini-3.5-live-translate-preview"

# Session A: caller (any language) → English for the agent.
# Target is always "en". No configuration varies by caller.
config_a = types.LiveConnectConfig(
    response_modalities=["AUDIO"],
    input_audio_transcription=types.AudioTranscriptionConfig(),
    output_audio_transcription=types.AudioTranscriptionConfig(),
    translation_config=types.TranslationConfig(
        target_language_code="en",
        echo_target_language=True,   # see note below — deliberate
    ),
)

# Session B: agent English → caller's language.
# caller_language is the BCP-47 code passed in at call initiation.
config_b = types.LiveConnectConfig(
    response_modalities=["AUDIO"],
    input_audio_transcription=types.AudioTranscriptionConfig(),
    output_audio_transcription=types.AudioTranscriptionConfig(),
    translation_config=types.TranslationConfig(
        target_language_code=caller_language,
        echo_target_language=False,
    ),
)
```

**On `echo_target_language`, which is asymmetric on purpose:**

`echo_target_language=False` makes a session stay silent when the input is already in the target language. On Session A that produces a bug: cross-participant audio is muted at -32 dB, so any English the caller speaks — numbers, product names, "okay", a code-switched phrase — reaches the agent as *silence*. Callers in every language do this constantly. Set Session A to `True` so English input is echoed through instead of dropped.

The cost is documented: with echo enabled, background noise or music may introduce artifacts in the output when the input is already in the target language. Verify this trade-off on real telephony audio in M4 and record which way it lands.

Session B stays `False`. The agent speaks English and the target is never English, so the echo path is unreachable.

- Send audio with `session.send_realtime_input(audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000"))`
- **Chunk size: 100 ms.** Google specifies this for latency.
- Capture both `input_transcription` and `output_transcription` with language codes; both are needed for the agent screen and for evaluation.
- Live Translate supports translation only — no tools, no system instructions, audio input only. Do not attempt to prompt it.

### 7.3 `player-config` (interactive agent assist)

Configure via a `config` event at session start:

```json
{
  "type": "event",
  "name": "config",
  "sessionParams": {
    "playerSettings": [
      { "player": "ToCustomer", "targets": [{ "participant": "caller", "gainDb": 0, "bargeIn": true }] },
      { "player": "ToAgent",    "targets": [{ "participant": "callee", "gainDb": 0, "bargeIn": true }] }
    ],
    "crossParticipantSetting": [
      { "from": "caller", "to": "callee", "gainDb": -32 },
      { "from": "callee", "to": "caller", "gainDb": -32 }
    ],
    "participantSettings": [
      { "participant": "caller", "sttLanguage": "<caller_language>" },
      { "participant": "callee", "sttLanguage": "en-US" }
    ]
  }
}
```

`gainDb: -32` is mute. The cross-participant mute is what stops each party hearing the far end's raw voice underneath the translation. Maximum is 2 players; a participant absent from a player's targets is muted for that player.

Send `startRecognition` per participant to begin receiving their audio:

```json
{ "type": "event", "name": "startRecognition", "activityParams": { "targetParticipant": "caller" } }
```

Required bot parameters for agent-assist calls: `bargeIn: true`, `connectOnPrompt: false`, `userNoInputGiveUpTimeoutMS: 0`.

### 7.5 Language handling

**Code mapping is not a pass-through.** Live Translate expects BCP-47 codes from Google's published table, and several are region-qualified in ways an upstream ISO 639-1 selection won't produce: `pt-BR` vs `pt-PT`, `zh-Hans` vs `zh-Hant`, `no`/`nb`. Build an explicit mapping table from whatever the virtual agent emits to a validated Live Translate code. Reject anything unmapped rather than guessing — a wrong code produces confidently wrong audio.

**The allowlist is a product control, not a technical one.** Live Translate claims 70+ languages, but quality will not be uniform, and the escalation gate should only route languages that have been measured and approved. The allowlist is owned by the customer and grows as languages qualify in M4. Default deny.

**Tiered validation for the POC:**

| Tier | Scope | Depth |
|---|---|---|
| 1 | The single highest-volume language | Full M4 evaluation, live call testing, latency distribution |
| 2 | Next 3–4 by traffic volume | Offline evaluation only, go/no-go on the allowlist |
| 3 | Everything else | Not validated; not on the allowlist |

Pick Tier 1 and Tier 2 from the customer's actual traffic mix, not from what's convenient to test.

**Session A is language-independent, and that is the main engineering consequence of this requirement.** The caller→English direction takes no per-language configuration at all. Everything that varies by caller — the target code on Session B, `sttLanguage` on the caller participant, and the allowlist check at the routing gate — is a single parameter threaded from call initiation. Do not let language awareness spread beyond those three places.

### 7.4 `eval-harness`

Offline batch tool, independent of telephony. Streams recorded audio files into Live Translate and captures translated audio plus both transcripts. Basis for G1.

Reference: the command-line translation example in `github.com/google-gemini/gemini-live-api-examples` already streams a remote audio URL into the model and prints transcripts with language codes.

## 8. Critical constraint — concurrent playback

**The AudioCodes docs state that only one Play Stream can be active at a time**, and that playback operations run sequentially even when targeting different players. A single VAIC session therefore cannot stream translated audio in both directions simultaneously: whoever speaks first owns the channel until their translation drains.

This is the highest-risk item in the POC. Resolve before committing to an architecture.

| Option | Approach | Trade-off |
|---|---|---|
| A | AudioCodes permits two concurrent Play Streams on different players | Cleanest; requires vendor confirmation |
| B | Two VAIC sessions per call, one per direction | Doubles sessions, more moving parts |
| C | Accept half-duplex for the POC | Ships now; conflicts with G2 under overlap |
| D | FreeSWITCH bridge — two independent parked legs | Constraint disappears; loses hold/transfer/SIPREC for free |

**Build the bridge so the playback target is an abstraction.** The Gemini session management, pacing, and buffering must not care whether output goes to a VAIC Play Stream or a FreeSWITCH channel. If option D becomes necessary, only the transport adapter changes.

For option D, evaluate `mod_audio_fork` and `wiringai/mod_earshot` (full-duplex WebSocket audio for FreeSWITCH).

## 9. Milestones

**M0 — Lab standing up**
Live Hub account with credit, phone number provisioned, bot connection configured with voice streaming enabled, echo bot from `ac-api-samples` answering a real call. Acceptance: you call a number and hear your own voice echoed.

**M1 — One-way translation**
Replace the echo handler with a single Live Translate session. Speak Spanish, hear English. Acceptance: translated audio begins before the speaker finishes their sentence; time-to-first-audio recorded.

**M2 — Two-way on a two-party call**
Second session, player configuration, cross-participant mute. Two softphones. Acceptance: neither party hears the far end's raw voice; both directions translate; the concurrency constraint from §8 is characterized with measurements.

**M3 — Agent Assist integration**
Route an escalated call through the bridge with the SIPREC fork on the agent-side leg. Acceptance: Agent Assist produces transcripts and suggestions as it does today, with no configuration change; conversation ID stitches from the VA phase to the agent phase.

**M4 — Evaluation**
Run 20–30 real recorded calls in the Tier 1 language through the eval harness at telephony audio quality, plus a smaller offline batch per Tier 2 language (§7.5). Acceptance: scored quality report plus latency distribution plus failure-mode tally for Tier 1; go/no-go allowlist decision per Tier 2 language. Include at least a few calls with code-switching into English, to settle the `echo_target_language` trade-off in §7.2.

M4 is independent of M0–M3 and should run in parallel from day one.

## 10. Acceptance criteria

**Latency**
- Time from speech onset to first translated audio out: measured and reported per utterance
- Component breakdown isolated: network to Gemini, model first-chunk, bridge processing, VAIC playout
- No utterance-level buffering anywhere in the bridge

**Audio integrity**
- No raw far-end voice audible to either party
- No clicks, gaps, or underruns during continuous speech
- Playback paced to real time, verified against `playStream.mark.reached` timing

**Agent Assist**
- Every currently-enabled feature produces output on a translated call
- Conversation ID continuous from virtual agent through to human agent
- Agent-side stream joins the existing conversation as `HUMAN_AGENT`, not as a new conversation

**Robustness**
- Bridge process restart mid-call: `session.resume` reattaches without dropping the call
- Bridge unreachable at escalation: call routes to the existing queue; never drops
- Hold, resume, and transfer behave correctly

**Portability**
- Zero code differences between Live Hub and VAIC-E; configuration only. Documented as a deployment diff.

## 11. Instrumentation

Log per call, structured, with the conversation ID as key:

- Timestamped events for every Bot API message in and out
- Timestamped Gemini send and receive, with byte counts
- `input_transcription` and `output_transcription` with language codes
- Derived: time-to-first-audio per utterance, playout underruns, session restarts
- Both raw source audio and translated audio, retained for review

The latency numbers this produces are the primary artifact for the Google engineering conversation. Treat instrumentation as a deliverable, not a debugging aid.

## 12. Open questions

Blocking:
1. Can two Play Streams be active concurrently when targeting different players? (§8)
2. Does Live Hub's voice streaming use an identical wire protocol to VAIC-E's WebSocket mode? (G5)

Non-blocking:
3. What VAIC version is the customer on — is it 3.24.1+, required for `raw/lpcm16_24`?
4. Does interactive agent assist work on Live Hub, or is it VAIC-E only?
5. Mechanism for carrying caller language and conversation ID across the escalation transfer — custom SIP headers require explicit message-manipulation rules on the SBC, or fall back to DNIS-per-language.

## 13. Known model limitations to design around

From Google's documentation:

- **Voice replication is inconsistent.** Voices may shift after long pauses, assign the wrong gender based on how speech starts, or get stuck during rapid multi-speaker exchange.
- **Language detection struggles** with heavy accents and similar languages — Spanish/Portuguese specifically. Documented as affecting the input transcript rather than the translation itself, but verify on real audio. This is a live risk given an open caller-language set: Spanish, Portuguese, Catalan, and Galician are all on the supported list.
- **Quality will vary by language**, and the 70+ figure is a capability claim, not a uniform quality guarantee. Treat the allowlist in §7.5 as the control.
- **Background audio** is filtered but not perfectly.
- **Preview status.** `gemini-3.5-live-translate-preview` is public preview with no SLA.

## 14. Out-of-scope items to note, not solve

- Recordings capture synthesized English rather than the customer's actual words. Production will need a second SIPREC session on the customer-side leg. Note in the POC report; do not build.
- Sentiment and QA scoring will run against translated text.
- Agent needs a screen indicator that the call is interpreted, plus guidance on shorter turns. Training and UI, not POC scope.

## 15. References

**Google**
- Live Translate API: `https://ai.google.dev/gemini-api/docs/live-api/live-translate`
- Agent Platform variant: `https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-5-live-translate`
- Examples: `github.com/google-gemini/gemini-live-api-examples`
- Bidi-SAC: `https://cloud.google.com/agent-assist/docs/bidi-stream-api`

**AudioCodes**
- Bot API WebSocket mode: `https://techdocs.audiocodes.com/voice-ai-connect/Content/Bot-API/ac-bot-api-mode-websocket.htm`
- Agent assist and interactive agent assist: `https://techdocs.audiocodes.com/voice-ai-connect/Content/VAIG_Combined/agent-assist.htm`
- Reference servers: `github.com/ac-voice-ai/ac-api-samples`
- SDK: `@audiocodes/ac-bot-api`
