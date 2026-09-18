# Live Call Translation — AudioCodes + Gemini Live Translate

Two people on an ordinary phone call speaking different languages, each hearing the
other in their own. A WebSocket bridge sits behind AudioCodes VoiceAI Connect, crosses
two Gemini Live Translate sessions between the legs, and measures every hop so the
delay can be shown rather than described.

Everything in this folder deploys as one stack. You edit a single `.env` file and run
one command. No project, service, or account identifiers are hardcoded in the source.

Scope and milestones: `live-translation-poc-prd.md`.

---

## Architecture

Two independent one-way paths, each running left to right. They share the same
infrastructure but never touch: separate phone calls, separate translation sessions,
separate timings.

```
  CALLER PATH   ·   the caller speaks Hindi, the agent hears English

  ┌───────────┐   ┌────────────┐   ┌───────────┐   ┌────────────┐   ┌────────────┐   ┌───────────┐
  │  Caller   │──►│ AudioCodes │──►│  Bridge   │──►│   Gemini   │──►│ AudioCodes │──►│   Agent   │
  │  speaks   │   │  Live Hub  │   │ session A │   │ translate  │   │  Live Hub  │   │   hears   │
  │  Hindi    │   │            │   │           │   │   to en    │   │            │   │  English  │
  └───────────┘   └────────────┘   └───────────┘   └────────────┘   └────────────┘   └───────────┘


  AGENT PATH   ·   the agent speaks English, the caller hears their own language

  ┌───────────┐   ┌────────────┐   ┌───────────┐   ┌────────────┐   ┌────────────┐   ┌───────────┐
  │   Agent   │──►│ AudioCodes │──►│  Bridge   │──►│   Gemini   │──►│ AudioCodes │──►│  Caller   │
  │  speaks   │   │  Live Hub  │   │ session B │   │ translate  │   │  Live Hub  │   │   hears   │
  │  English  │   │            │   │           │   │ to caller  │   │            │   │   Hindi   │
  └───────────┘   └────────────┘   └───────────┘   └────────────┘   └────────────┘   └───────────┘


  Both paths run at once, on one Cloud Run service, which also serves the console:

                    ┌───────────────────────────────────────────────┐
                    │  Bridge · Cloud Run                           │
                    │    session A  caller → agent                  │
                    │    session B  agent → caller                  │
                    │    /console/  live transcript and latency     │
                    └───────────────────────────────────────────────┘
```

| Component | What it does |
|---|---|
| **Phones** | Two ordinary phone calls. Each person speaks their own language and hears the other in theirs. |
| **AudioCodes Live Hub** | Answers the calls off the public phone network and streams the audio to the bridge. Pairs the two calls: first in is the caller, second is the agent. |
| **Bridge** (Cloud Run) | Runs one translation session per direction, sends each speaker's audio to the model, plays the result to the other person, and times every step. |
| **Gemini Live Translate** | Speech in, translated speech out, in one step. Detects the source language itself and keeps the speaker's voice. |
| **Console** | A web page showing the call as it happens and the latency breakdown afterwards. Served by the bridge. |

### What the timings cover

The bridge can only time the part it can see. The phone network carries no clock it
can read, so the first and last legs are estimated separately.

```
   speaks ──►  telephony  ──►  BRIDGE  ──►  MODEL  ──►  BRIDGE  ──►  telephony  ──► hears
               (not timed)     └──────────  measured  ──────────┘    (not timed)
```

| Hop | Meaning |
|---|---|
| Send buffer | Audio waiting for a full chunk before it goes to the model |
| Model | Gemini producing the first translated audio |
| Forward | Handing that audio back to AudioCodes |

To measure the two untimed legs, place a call with `TRANSLATOR=echo` and time the
round trip acoustically.

### Code layout

| Path | Purpose |
|---|---|
| `bridge/server.py` | FastAPI app: `/audiocodes-ws`, call pairing, session wiring |
| `bridge/audiocodes_gateway.py` | Bot API protocol: handshake, userStream in, playStream out, hangup |
| `bridge/translator.py` | One Live Translate session per direction |
| `bridge/call.py` | Runs a direction, crosses a pair, closes idle playStreams |
| `bridge/audio_transcode.py` | Coder negotiation and PCM/μ-law conversion |
| `bridge/metrics.py` | Utterance detection, per-hop timings, event log, recordings |
| `bridge/settings.py` | Caller language, shared between the console and the bridge |
| `bridge/echo.py` / `bridge/dialout.py` / `bridge/pairing.py` | M0 echo, outbound dial, leg pairing |
| `console/` | Live transcript and latency dashboard |
| `deploy/cloudrun.sh` | Deploy, pull logs, tear down |
| `tests/` | Unit tests and a fake VoiceAI Connect client (`tests/smoke/`) |

---

## Prerequisites

- A Google Cloud project with billing, and `gcloud` authenticated
- An AudioCodes Live Hub account with a phone number and credit
- Two phones (the lab setup pairs two inbound calls)
- Python 3.12

---

## Setup & deploy

### 1. Authenticate

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
```

### 2. Enable the required APIs (once per project)

```bash
gcloud services enable aiplatform.googleapis.com run.googleapis.com \
  cloudbuild.googleapis.com artifactregistry.googleapis.com
```

Cloud Build runs as the default compute service account, which needs build
permissions on a new project:

```bash
NUM=$(gcloud projects describe YOUR_PROJECT_ID --format='value(projectNumber)')
for ROLE in cloudbuild.builds.builder logging.logWriter \
            artifactregistry.writer storage.objectAdmin; do
  gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
    --member "serviceAccount:${NUM}-compute@developer.gserviceaccount.com" \
    --role "roles/${ROLE}"
done
```

### 3. Create a virtual environment and install dependencies

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q
```

### 4. Configure `.env`

```bash
cp .env.example .env
```

| Variable | Notes |
|---|---|
| `AUDIOCODES_TOKEN` | Any secret; the same value goes on the Live Hub bot connection |
| `GOOGLE_CLOUD_PROJECT` | Your project |
| `GOOGLE_CLOUD_LOCATION` | `global` — Live Translate is served from the global endpoint |
| `LIVE_TRANSLATE_MODEL` | `gemini-3.5-live-translate-preview` |
| `CALLER_LANGUAGE` | Starting language for the caller leg; the console can change it |
| `AGENT_MODE` | `dialin` (two inbound calls) \| `dialout` \| `loopback` |
| `ECHO_TO_AGENT` | Leave `false` — see *Echo and crosstalk* below |

`.env` is gitignored. Rotate `AUDIOCODES_TOKEN` if it has ever been pasted anywhere,
and move it to Secret Manager before this leaves the lab.

### 5. Deploy

```bash
./deploy/cloudrun.sh up
```

It creates a dedicated service account with `roles/aiplatform.user`, builds the
container, and deploys with startup CPU boost, CPU always allocated, and
`min-instances=1`. It prints:

```
Bot URL:   wss://<service>.run.app/audiocodes-ws
Live call: https://<service>.run.app/console/
Dashboard: https://<service>.run.app/console/dashboard
```

`max-instances` is pinned to 1 on purpose: the two call legs are paired **in process**,
so a second instance would never see the first leg.

### 6. Point Live Hub at it

| Setting | Value |
|---|---|
| API type | WebSocket |
| Bot URL | the `wss://…/audiocodes-ws` printed above |
| Token | the same value as `AUDIOCODES_TOKEN` |
| Voice streaming | **enabled** |

Then add a call routing rule sending your number to that bot connection. Opening the
Bot URL in a browser should return `{"type":"ac-bot-api","success":true}`.

### 7. Place a call

With `AGENT_MODE=dialin`, dial the number from **two** phones. The first becomes the
caller, the second the agent; translation starts once both are up. Open the live page
and watch the transcript as you speak.

---

## Console

| Page | Shows |
|---|---|
| `/console/` | The call in progress. Each turn crosses from the speaker's lane to the other side, carrying the time it took. The conversation ID is picked up automatically. |
| `/console/dashboard` | One finished call, by conversation ID: how much of the delay is the model, and how much is ours. |

**Caller language** is a picker in the top bar, Hindi by default. A translation session
is opened when a call starts, so a change applies to the **next** call, not the one in
progress. The choice is stored next to the recordings and shared with the bridge.

### Running it locally

The console is a separate process locally, so nothing it does shares an event loop with
the audio path:

```bash
.venv/bin/uvicorn bridge.server:app --port 8080     # bridge
.venv/bin/uvicorn console.app:app --port 8081       # console, in a second shell
ngrok http 8080                                     # tunnel for Live Hub
```

The ngrok URL changes on every restart; update the bot connection when it does. On
Cloud Run the console is mounted into the bridge service instead (`SERVE_CONSOLE=true`),
because a separate service cannot read the bridge's filesystem.

### Reading a cloud call locally

Every timing event is written to stdout as well as to disk, so Cloud Logging has the
full record even though the container's filesystem does not survive:

```bash
./deploy/cloudrun.sh logs 30m
```

That rebuilds `recordings/<conversation>/events.jsonl` on your machine, and the local
console opens it like any other call.

---

## Behaviour worth knowing

### Voice matching cannot be turned off

Live Translate replicates the speaker's voice. `prebuilt_voice_config` is accepted and
silently ignored; `replicated_voice_config` is rejected outright (`The 'voice clone'
feature is not supported for model gemini_v4xs_s2st_streaming`). A fixed output voice
would mean discarding the model's audio and synthesizing from `output_audio_transcription`
instead, at the cost of an extra hop.

### Echo and crosstalk

Keep `ECHO_TO_AGENT=false`. With echo on, the caller leg also reproduces English it
hears — including the agent's voice bleeding in from the room — and real translations
queue behind that work. In one lab call this pushed caller-to-agent from ~3 s to 8–11 s
and it never recovered.

Related: if the two handsets can hear each other, each leg picks up the other's
translated audio and it appears in the transcript. Use headphones or separate rooms.

### Platform gotchas, all verified

- A call rings until the bot sends a playStream, so the bridge plays 200 ms of silence
  to answer (`ANSWER_PROMPT`).
- The userStream is continuous, so utterances are found by energy, not by turn events.
- Live Translate emits continuous silent audio. Silence must never open or extend a
  playStream, or VoiceAI Connect withholds the caller's microphone.
- VoiceAI Connect stops the userStream during playback unless the bridge sends a
  `config` activity with `sessionParams.bargeIn=true`.
- 100 ms send chunks are Google's documented recommendation; smaller chunks trade
  throughput for latency that the guidance says is not worth it.

---

## Teardown

```bash
./deploy/cloudrun.sh down
```

Deletes the Cloud Run service, removes the `roles/aiplatform.user` binding, and deletes
the service account. `min-instances=1` bills while idle, so tear it down when you are
finished.

Stop the local processes too:

```bash
pkill -f "bridge.server:app"; pkill -f "console.app:app"; pkill ngrok
```

Container images stay in Artifact Registry. Remove them if you want a clean project:

```bash
gcloud artifacts repositories delete cloud-run-source-deploy \
  --location YOUR_REGION --project YOUR_PROJECT_ID
```

The Live Hub bot connection and routing rule are deleted in the AudioCodes console.

---

## Tests

```bash
.venv/bin/python -m pytest -q
```

`tests/smoke/smoke_audiocodes.py` drives the bridge with a fake VoiceAI Connect client,
so the protocol path can be exercised without placing a call.
