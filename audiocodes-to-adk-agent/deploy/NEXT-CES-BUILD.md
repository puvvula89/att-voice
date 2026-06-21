# Next session — build the CES billing app via the `ces-mcp` tools

Working note (untracked). Goal: create the CX Agent Studio billing app, capture its
resource name into `.env` as `CES_APP`, re-run `deploy/deploy_all.sh` to wire the
billing route into the deployed relay.

## Preconditions (already done last session)
- `ces.googleapis.com` enabled on `REDACTED_PROJECT`; account `ykalekhya@gmail.com` is Owner.
- `ces-mcp` registered in Claude Code (local scope, `https://ces.googleapis.com/mcp`,
  ADC bearer + `x-goog-user-project: REDACTED_PROJECT`). 60 tools.
- Relay deployed: `wss://att-steering-relay-qehx377roa-uc.a.run.app/ws`;
  Agent Engine `…/reasoningEngines/REDACTED_ENGINE_ID`. `AE_ENGINE_ID` in `.env`.

## Before restarting Claude (run in your shell)
Refresh the MCP token so it isn't expired at session start (no browser needed — ADC
already set up; `print-access-token` mints a fresh one from the stored refresh token):

```
claude mcp add --transport http --scope local ces-mcp https://ces.googleapis.com/mcp \
  -H "Authorization: Bearer $(gcloud auth application-default print-access-token)" \
  -H "x-goog-user-project: REDACTED_PROJECT"
```

Then restart Claude Code and say "build the billing app".

If any `create_*` call returns PERMISSION_DENIED / a scope error, re-auth ADC with the
CES scope (browser) and re-run the command above:
```
gcloud auth application-default login \
  --scopes=https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/ces
```
(The relay's runtime BidiRunSession uses plain `cloud-platform`, so this is only for the
MCP write tools, if needed.)

## What the relay requires (from relay/agents_runtime/ces_bidi.py)
- `CES_APP` must be the **full app resource name**: `projects/REDACTED_PROJECT/locations/us/apps/{APP_ID}`
  (the adapter does `f"{CES_APP}/sessions/{session_id}"`).
- `CES_LOCATION=us` (the BidiRunSession location; already in `.env`).
- The app needs a **published deployment** — BidiRunSession runs the app's live
  deployment (the bidi `SessionConfig` only carries `session`, no explicit deployment).
- Bidi I/O: input LINEAR16 @16k, output LINEAR16 @24k; server emits
  `recognition_result` / `session_output` (text+audio, `turn_completed`) / `end_session`.

## Build sequence (with `ces-mcp` tools loaded)
1. `list_apps` (project `REDACTED_PROJECT`, location `us`) — check if a billing app already exists; reuse if so (idempotent).
2. Inspect input schemas first: read the tool descriptions for `create_app`, `create_agent`, `create_deployment` (and `update_agent`) — fill fields from the schema, don't guess.
3. `create_app` — display name e.g. "ATT Billing"; location `us`.
4. `create_agent` in that app — the billing specialist. Instructions (voice, brief):
   - "You are AT&T's billing specialist on a phone call. The caller was already
     greeted and routed to you MID-CALL — do NOT greet, welcome, or re-introduce.
     Continue the conversation naturally from where it left off."
   - "Help with billing: explain charges/fees, due dates, payment options, autopay,
     paperless. Keep replies short and conversational for speech."
   - "If prior context is provided, acknowledge it and pick up the thread."
   - Set a voice (match the demo's `Charon` tone if a voice field exists).
5. `create_deployment` — publish so BidiRunSession can run the app.
6. Capture the app resource name → set in `.env`:
   `CES_APP=projects/REDACTED_PROJECT/locations/us/apps/{APP_ID}` (gitignored; never commit).
7. Re-run `bash deploy/deploy_all.sh` — it redeploys the relay with `CES_APP` set, wiring
   the billing route. (Idempotent: AE updates in place, Cloud Run updates the service.)

## Verify
- Browser/mic 4-route e2e: greeter → internet / phone_upgrade / **billing**, seamless,
  no re-greet on handoff (load-bearing check #1: greeter turns persist into the shared
  ADK session; #2: CES `historicalContexts` field names are honored — confirm the seeded
  context actually reaches the billing agent; adjust ces_bidi.py field names if ignored).
- Optional: `scripts/smoke_ces_bidi.py`.

## Design intent (DESIGN.md §2/§3)
Specialists "just answer enough to show the channel is live and context arrived" — no
deep billing business logic. The point is the seamless linear handoff across platforms.
