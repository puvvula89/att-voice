# Lab Inventory — Live Hub

Checked: 2026-09-14 (M0 echo verified on a live PSTN call)

| Item | Status | Notes |
|---|---|---|
| Live Hub account | Present | One bot connection, one phone number, one routing rule |
| Bot connection | Working | API type WebSocket, "Enable voice streaming" checked, bot configuration JSON empty |
| Bot URL | Local tunnel | `wss://<tunnel-host>/audiocodes-ws` during M0–M2 |
| Token | Reused | Same Bearer token as the earlier prototype; rotate before any shared deployment |
| Media formats offered | Confirmed | `raw/lpcm16_8, wav/lpcm16_8, raw/mulaw, wav/mulaw, raw/lpcm16, wav/lpcm16, raw/lpcm16_24, wav/lpcm16_24`. Bridge uses `raw/lpcm16` in, `raw/lpcm16_24` out (no resampling). |
| Start activity locale | `any-CI` | No language hint from the platform |
| Agent assist / callee participant | Unknown | Needed for M2 |
| Two bot connections on one call | Unknown | Blocking for M2 (option B) |

## Observed platform behavior

- **The call is answered only when the bot starts a playStream.** With no playback the call keeps ringing. The bridge plays 200 ms of silence after the `start` activity (`ANSWER_PROMPT=silence`).
- **Caller audio streams continuously**, silence included, from `userStream.start` until hangup. On one test call a single `userStream.start`/`stop` pair spanned the whole call. Do not treat the absence of chunks as end of speech.
- **The call does not need** `directSTT`/`directTTS` in the bot configuration JSON; the voice-streaming checkbox is sufficient.
