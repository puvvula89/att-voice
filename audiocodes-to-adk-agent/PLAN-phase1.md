# Phase 1 — Steering Relay ↔ Multi-Platform Agents — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a steering relay that greets a caller, classifies intent on the first utterance, and seamlessly hands the live voice channel to the right specialist agent — across two GCP platforms (ADK + Gemini Live, and CX Agent Studio) — as one linear conversation, driven by a local harness (no AudioCodes yet).

**Architecture:** The relay core is port-agnostic on both sides. A `MediaGateway` port abstracts the caller side (Phase 1 = `HarnessGateway`, a local mic WebSocket; Phase 2 = AudioCodes). An `AgentSession` port abstracts the agent side, with three implementations: `AdkLiveSession` (in-process `run_live`, used for unit smoke + local dev), `AeAdkSession` (bidi connection to the ADK agents **deployed on Agent Engine**), and `CesBidiSession` (`BidiRunSession` WebSocket to CX Agent Studio). The three ADK agents (greeter, internet, phone-upgrade) are hosted in **one multi-agent Agent Engine app** that selects the agent per call by an `agent_key` in the bidi first message — so all three share the engine's session store by `session_id` automatically (no separate `SESSION_ENGINE_ID`). A steering loop opens a greeter agent, watches for an intent signal, then closes it and opens the routed specialist seeded from a relay-owned session-of-record — with no re-greeting. The factory uses `AeAdkSession` when an Agent Engine id is configured, falling back to in-process `AdkLiveSession` otherwise.

**Tech Stack:** Python 3.12, `google-adk==2.1.0`, `google-genai` (1.x via adk), Gemini Live (`gemini-live-2.5-flash-native-audio` on Vertex), Vertex AI Agent Engine (custom bidi app, `AgentServerMode.EXPERIMENTAL`), CX Agent Studio (`google.cloud.ces.v1` `BidiRunSession`), FastAPI + `uvicorn`, `websocket-client` (CES), `vertexai` client (AE bidi), `pytest`.

## Global Constraints

- **ADK pin:** `google-adk==2.1.0` exactly (2.2.0 regresses Vertex Live resume via genai 2.x). Do NOT pin `google-genai` — let adk resolve 1.x.
- **Python:** 3.12 (Agent Engine has no 3.14 base image; keep parity).
- **Live model:** `LIVE_MODEL` env, default `gemini-live-2.5-flash-native-audio` (Vertex/ADC). `GOOGLE_GENAI_USE_VERTEXAI=TRUE`.
- **Audio (Phase 1):** caller side is **16 kHz PCM16 LE** (harness mic), agent output is **24 kHz PCM16 LE**. No 8 kHz telephony resampling in Phase 1 (that is Phase 2 / AudioCodes). Input blobs MUST carry the rate: `mime_type="audio/pcm;rate=16000"`.
- **One linear conversation:** specialists MUST continue without re-greeting or "welcome back". Greeter goes silent at handoff.
- **Agent Engine deploy (Phase 1):** ADK agents ship to ONE multi-agent Agent Engine app. Custom bidi app class (`register_operations -> {"bidi_stream": ["bidi_stream_query"]}`), `agent_server_mode=AgentServerMode.EXPERIMENTAL`, `extra_packages` as RELATIVE paths (`["relay", "agents"]`), `python_version="3.12"`, `cloudpickle==3.1.2`. Deploy idempotently (update-or-create by `display_name`). Hold the `vertexai.Client` for the whole connection lifetime (GC closes its httpx client otherwise).
- **No tooling footprint** in committed artifacts: neutral professional naming, no co-author trailers, no tool/plugin names in paths. Outputs may be shared externally.
- **Env loading:** call `load_dotenv()` at the very top of any standalone entrypoint BEFORE importing modules that read env (standalone uvicorn does not auto-load `.env`).
- **TDD scope:** pure-Python units (ports, session record, router, steering loop) are test-first with pytest. Streaming/agent/relay/client are integration-verified via smoke scripts + a manual end-to-end run.

---

## File Structure

```
audiocodes-to-adk-agent/
  relay/
    __init__.py
    ports.py                 # MediaGateway, AgentSession protocols + event dataclasses
    session_record.py        # SessionRecord: id, caller, intent, turns; context summary
    session_resolve.py       # resolve_session (copied from proven module)
    router.py                # intent -> AgentSpec registry (backend = adk | ces)
    steering.py              # run_call(): greeter -> intent -> swap to specialist
    server.py                # FastAPI: harness WS endpoint -> steering
    agent_app.py             # AE multi-agent bidi app (register_operations/bidi_stream_query)
    agents_runtime/
      __init__.py
      adk_live.py            # AdkLiveSession (in-process run_live; dev + smoke)
      ae_live.py             # AeAdkSession (bidi to ADK agents on Agent Engine)
      ces_bidi.py            # CesBidiSession (AgentSession over BidiRunSession)
      factory.py             # make_factory(...) -> (key, record) -> AgentSession
    gateways/
      __init__.py
      harness.py             # HarnessGateway (MediaGateway over a browser WS)
  agents/
    __init__.py
    intent_tool.py           # classify_intent FunctionTool + after_tool_callback
    greeter.py               # greeter/router LlmAgent
    internet.py              # internet specialist LlmAgent
    phone_upgrade.py         # phone-upgrade specialist LlmAgent
    registry.py              # ADK_AGENTS dict {key -> agent} (shared by app + factory)
  deploy/
    deploy_agent_engine.py   # idempotent update-or-create of the ADK bidi app
    destroy.sh               # tear down the engine
  harness/
    client.html              # minimal mic client (capture 16k, play 24k)
    serve.py                 # static server with no-store headers
  scripts/
    smoke_adk_live.py        # drive AdkLiveSession (in-process) with a text turn
    smoke_ae_live.py         # drive AeAdkSession against the deployed engine
    smoke_ces_bidi.py        # drive CesBidiSession with a WAV
  tests/
    test_ports.py
    test_session_record.py
    test_router.py
    test_steering.py
  requirements.txt
  relay-requirements.txt
  .env.example
  README.md
```

---

### Task 1: Module scaffold, dependencies, env

**Files:**
- Create: `audiocodes-to-adk-agent/requirements.txt`
- Create: `audiocodes-to-adk-agent/relay-requirements.txt`
- Create: `audiocodes-to-adk-agent/.env.example`
- Create: `audiocodes-to-adk-agent/relay/__init__.py`, `relay/agents_runtime/__init__.py`, `relay/gateways/__init__.py`, `agents/__init__.py`
- Create: `audiocodes-to-adk-agent/tests/__init__.py`

**Interfaces:**
- Produces: an importable package layout and a working `pytest` run (0 tests).

- [ ] **Step 1: Create dependency files**

`requirements.txt`:
```
google-cloud-aiplatform[agent_engines]
google-adk==2.1.0
google-genai
cloudpickle==3.1.2
fastapi
uvicorn[standard]
websockets
websocket-client
python-dotenv
pytest
```

`relay-requirements.txt`:
```
fastapi
uvicorn[standard]
python-dotenv
google-cloud-aiplatform
google-adk==2.1.0
websockets
websocket-client
```

- [ ] **Step 2: Create `.env.example`**

```
GOOGLE_GENAI_USE_VERTEXAI=TRUE
GOOGLE_CLOUD_PROJECT=your-project
GOOGLE_CLOUD_LOCATION=us-central1
LIVE_MODEL=gemini-live-2.5-flash-native-audio
LIVE_VOICE=Charon
# CX Agent Studio (billing)
CES_APP=projects/your-project/locations/us/apps/your-app
CES_LOCATION=us
```

- [ ] **Step 3: Create empty package files**

Create each `__init__.py` listed above as an empty file, plus `tests/__init__.py`.

- [ ] **Step 4: Install and verify collection**

Run: `cd audiocodes-to-adk-agent && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt && pytest -q`
Expected: pip succeeds; pytest prints `no tests ran` (exit 5) or `0 passed` — no import/collection errors.

- [ ] **Step 5: Commit**

```bash
git add audiocodes-to-adk-agent/requirements.txt audiocodes-to-adk-agent/relay-requirements.txt audiocodes-to-adk-agent/.env.example audiocodes-to-adk-agent/relay audiocodes-to-adk-agent/agents audiocodes-to-adk-agent/tests
git commit -m "chore: scaffold audiocodes steering relay module"
```

---

### Task 2: Ports — event types and protocols

**Files:**
- Create: `audiocodes-to-adk-agent/relay/ports.py`
- Test: `audiocodes-to-adk-agent/tests/test_ports.py`

**Interfaces:**
- Produces:
  - Agent-side events: `AgentAudio(pcm: bytes)`, `AgentTranscript(role: str, text: str, final: bool)`, `AgentIntent(intent: str)`, `AgentEnd()`.
  - Caller-side events: `CallerAudio(pcm: bytes)`, `CallerEnd()`.
  - Protocols: `MediaGateway` (`events()`, `send_audio(pcm)`, `transfer(uri)`, `end()`), `AgentSession` (`open(record)`, `send_audio(pcm)`, `events()`, `close()`).

- [ ] **Step 1: Write the failing test**

`tests/test_ports.py`:
```python
from relay.ports import (
    AgentAudio, AgentTranscript, AgentIntent, AgentEnd,
    CallerAudio, CallerEnd,
)


def test_agent_events_construct():
    assert AgentAudio(b"\x00\x01").pcm == b"\x00\x01"
    t = AgentTranscript(role="agent", text="hi", final=True)
    assert (t.role, t.text, t.final) == ("agent", "hi", True)
    assert AgentIntent(intent="billing").intent == "billing"
    assert isinstance(AgentEnd(), AgentEnd)


def test_caller_events_construct():
    assert CallerAudio(b"abc").pcm == b"abc"
    assert isinstance(CallerEnd(), CallerEnd)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ports.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'relay.ports'`.

- [ ] **Step 3: Write minimal implementation**

`relay/ports.py`:
```python
from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Protocol, runtime_checkable


# --- agent-side events (channel #2: relay <- agent) ---
@dataclass
class AgentAudio:
    pcm: bytes              # PCM16 LE, 24 kHz


@dataclass
class AgentTranscript:
    role: str               # "user" | "agent"
    text: str
    final: bool


@dataclass
class AgentIntent:
    intent: str             # e.g. "internet" | "phone_upgrade" | "billing"


@dataclass
class AgentEnd:
    pass


# --- caller-side events (WS #1: relay <- caller) ---
@dataclass
class CallerAudio:
    pcm: bytes              # PCM16 LE, 16 kHz (Phase 1 harness)


@dataclass
class CallerEnd:
    pass


@runtime_checkable
class MediaGateway(Protocol):
    """Caller-side media channel. Phase 1: harness; Phase 2: AudioCodes."""

    def events(self) -> AsyncIterator: ...
    async def send_audio(self, pcm: bytes) -> None: ...
    async def transfer(self, uri: str) -> None: ...
    async def end(self) -> None: ...


@runtime_checkable
class AgentSession(Protocol):
    """One backend voice channel (ADK Live or CES bidi)."""

    async def open(self, record) -> None: ...
    async def send_audio(self, pcm: bytes) -> None: ...
    def events(self) -> AsyncIterator: ...
    async def close(self) -> None: ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ports.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add relay/ports.py tests/test_ports.py
git commit -m "feat: relay ports and event types"
```

---

### Task 3: Session-of-record

**Files:**
- Create: `audiocodes-to-adk-agent/relay/session_record.py`
- Test: `audiocodes-to-adk-agent/tests/test_session_record.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `SessionRecord(session_id: str, caller: str = "")` with `.intent: str | None`, `.turns: list[Turn]`, methods `add_turn(role: str, text: str)`, `set_intent(intent: str)`, `transcript_text() -> str`, `context_summary() -> str`. `Turn(role: str, text: str)`.

- [ ] **Step 1: Write the failing test**

`tests/test_session_record.py`:
```python
from relay.session_record import SessionRecord


def test_add_turn_and_transcript():
    r = SessionRecord(session_id="X", caller="+15551234567")
    r.add_turn("user", "my internet is down")
    r.add_turn("agent", "let's take a look")
    r.add_turn("user", "")  # empty ignored
    assert len(r.turns) == 2
    assert r.transcript_text() == "user: my internet is down\nagent: let's take a look"


def test_set_intent():
    r = SessionRecord(session_id="X")
    assert r.intent is None
    r.set_intent("billing")
    assert r.intent == "billing"


def test_context_summary_includes_intent_and_transcript():
    r = SessionRecord(session_id="X")
    r.set_intent("billing")
    r.add_turn("user", "I have a question about my bill")
    s = r.context_summary()
    assert "billing" in s
    assert "question about my bill" in s
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_session_record.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'relay.session_record'`.

- [ ] **Step 3: Write minimal implementation**

`relay/session_record.py`:
```python
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Turn:
    role: str   # "user" | "agent"
    text: str


@dataclass
class SessionRecord:
    """Relay-owned canonical record of one call, keyed by session_id.

    The session-of-record stitches continuity across platforms: ADK specialists
    inherit it via a shared session service; the CES specialist is seeded from
    context_summary() through historical context.
    """

    session_id: str
    caller: str = ""
    intent: str | None = None
    turns: list[Turn] = field(default_factory=list)

    def add_turn(self, role: str, text: str) -> None:
        if text:
            self.turns.append(Turn(role, text))

    def set_intent(self, intent: str) -> None:
        self.intent = intent

    def transcript_text(self) -> str:
        return "\n".join(f"{t.role}: {t.text}" for t in self.turns)

    def context_summary(self) -> str:
        intent = self.intent or "unknown"
        return (
            f"Caller intent: {intent}.\n"
            f"Prior conversation so far:\n{self.transcript_text()}"
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_session_record.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add relay/session_record.py tests/test_session_record.py
git commit -m "feat: session-of-record"
```

---

### Task 4: Router

**Files:**
- Create: `audiocodes-to-adk-agent/relay/router.py`
- Test: `audiocodes-to-adk-agent/tests/test_router.py`

**Interfaces:**
- Produces: `AgentSpec(key: str, backend: str, display: str)` (frozen); `REGISTRY: dict[str, AgentSpec]` with keys `internet`, `phone_upgrade`, `billing`; `GREETER_KEY = "greeter"`; `DEFAULT_KEY = "internet"`; `route(intent: str) -> AgentSpec`.

- [ ] **Step 1: Write the failing test**

`tests/test_router.py`:
```python
from relay.router import route, REGISTRY, DEFAULT_KEY


def test_known_intents_route_to_correct_backend():
    assert route("internet").backend == "adk"
    assert route("phone_upgrade").backend == "adk"
    assert route("billing").backend == "ces"


def test_intent_is_normalized():
    assert route("  Billing ").key == "billing"


def test_unknown_intent_falls_back_to_default():
    assert route("nonsense").key == DEFAULT_KEY
    assert route("").key == DEFAULT_KEY


def test_registry_covers_three_specialists():
    assert set(REGISTRY) == {"internet", "phone_upgrade", "billing"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_router.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'relay.router'`.

- [ ] **Step 3: Write minimal implementation**

`relay/router.py`:
```python
from __future__ import annotations

from dataclasses import dataclass

GREETER_KEY = "greeter"
DEFAULT_KEY = "internet"


@dataclass(frozen=True)
class AgentSpec:
    key: str
    backend: str   # "adk" | "ces"
    display: str


REGISTRY: dict[str, AgentSpec] = {
    "internet": AgentSpec("internet", "adk", "Internet support"),
    "phone_upgrade": AgentSpec("phone_upgrade", "adk", "Phone upgrade"),
    "billing": AgentSpec("billing", "ces", "Billing"),
}


def route(intent: str) -> AgentSpec:
    """Map a greeter-emitted intent string to a specialist. Unknown -> default."""
    key = (intent or "").strip().lower()
    return REGISTRY.get(key, REGISTRY[DEFAULT_KEY])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_router.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add relay/router.py tests/test_router.py
git commit -m "feat: intent router registry"
```

---

### Task 5: Steering loop (orchestration, fake-tested)

**Files:**
- Create: `audiocodes-to-adk-agent/relay/steering.py`
- Test: `audiocodes-to-adk-agent/tests/test_steering.py`

**Interfaces:**
- Consumes: `MediaGateway`, `AgentSession` (Task 2); `SessionRecord` (Task 3); `route`, `GREETER_KEY` (Task 4).
- Produces: `async def run_call(gateway, agent_factory, record) -> None`, where `agent_factory(key: str, record: SessionRecord) -> AgentSession`. Behavior: open greeter; forward `CallerAudio`→agent and `AgentAudio`→gateway; on `AgentTranscript` append to record; on `AgentIntent` close current agent, `route()`, open specialist (no re-greet), continue; end on `AgentEnd`/`CallerEnd`.

- [ ] **Step 1: Write the failing test**

`tests/test_steering.py`:
```python
import asyncio

from relay.session_record import SessionRecord
from relay.ports import (
    AgentAudio, AgentTranscript, AgentIntent, AgentEnd,
    CallerAudio, CallerEnd,
)
from relay.steering import run_call


def _run(coro):
    return asyncio.run(coro)


class FakeGateway:
    """Emits a scripted caller event sequence; records audio sent to caller."""

    def __init__(self, events):
        self._events = list(events)
        self.sent = []
        self.ended = False

    async def events(self):
        for e in self._events:
            yield e
            await asyncio.sleep(0)

    async def send_audio(self, pcm):
        self.sent.append(pcm)

    async def transfer(self, uri):
        pass

    async def end(self):
        self.ended = True


class FakeAgent:
    """Scriptable agent session. Records opens and audio received."""

    def __init__(self, key, scripted):
        self.key = key
        self._scripted = list(scripted)
        self.opened_with = None
        self.received = []
        self.closed = False

    async def open(self, record):
        self.opened_with = record

    async def send_audio(self, pcm):
        self.received.append(pcm)

    async def events(self):
        for e in self._scripted:
            yield e
            await asyncio.sleep(0)

    async def close(self):
        self.closed = True


def test_greeter_classifies_then_swaps_to_specialist():
    # Greeter greets, then emits an intent; specialist greets-continues and ends.
    greeter = FakeAgent("greeter", [
        AgentTranscript("agent", "How can I help?", True),
        AgentIntent("billing"),
    ])
    billing = FakeAgent("billing", [
        AgentTranscript("agent", "Let's look at your bill", True),
        AgentEnd(),
    ])
    made = {}

    def factory(key, record):
        a = greeter if key == "greeter" else billing
        made[key] = a
        return a

    gateway = FakeGateway([CallerAudio(b"hi"), CallerEnd()])
    record = SessionRecord(session_id="X")

    _run(run_call(gateway, factory, record))

    # Greeter was opened and closed; billing was routed and opened.
    assert greeter.closed is True
    assert billing.opened_with is record
    # Intent recorded; transcripts captured across BOTH agents.
    assert record.intent == "billing"
    assert "How can I help?" in record.transcript_text()
    assert "Let's look at your bill" in record.transcript_text()


def test_unknown_intent_routes_to_default():
    greeter = FakeAgent("greeter", [AgentIntent("garbled")])
    internet = FakeAgent("internet", [AgentEnd()])

    def factory(key, record):
        return greeter if key == "greeter" else internet

    gateway = FakeGateway([CallerEnd()])
    record = SessionRecord(session_id="X")
    _run(run_call(gateway, factory, record))
    assert internet.opened_with is record  # default specialist opened
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_steering.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'relay.steering'`.

- [ ] **Step 3: Write minimal implementation**

`relay/steering.py`:
```python
from __future__ import annotations

import asyncio

from relay.ports import (
    AgentAudio, AgentTranscript, AgentIntent, AgentEnd,
    CallerAudio, CallerEnd,
)
from relay.router import route, GREETER_KEY
from relay.session_record import SessionRecord


async def run_call(gateway, agent_factory, record: SessionRecord) -> None:
    """Drive one call: greeter -> intent -> seamless swap to specialist.

    agent_factory(key, record) -> AgentSession. The same record is passed to
    every agent so context carries (ADK shares the session; CES is seeded from it).
    """
    done = asyncio.Event()
    state = {"agent": None, "swap_to": None}

    async def caller_to_agent():
        async for ev in gateway.events():
            if isinstance(ev, CallerAudio):
                agent = state["agent"]
                if agent is not None:
                    await agent.send_audio(ev.pcm)
            elif isinstance(ev, CallerEnd):
                break
        done.set()

    async def agent_to_caller():
        # Loop across agents: greeter first, then whatever swap is requested.
        key = GREETER_KEY
        while True:
            agent = agent_factory(key, record)
            await agent.open(record)
            state["agent"] = agent
            swap = None
            async for ev in agent.events():
                if isinstance(ev, AgentAudio):
                    await gateway.send_audio(ev.pcm)
                elif isinstance(ev, AgentTranscript):
                    if ev.final:
                        record.add_turn(ev.role, ev.text)
                elif isinstance(ev, AgentIntent):
                    record.set_intent(ev.intent)
                    swap = route(ev.intent).key
                    break  # greeter goes silent; close below and open specialist
                elif isinstance(ev, AgentEnd):
                    swap = None
                    break
            await agent.close()
            state["agent"] = None
            if swap is None:
                break
            key = swap  # open specialist next iteration; NO re-greet handled by prompt
        done.set()

    task_in = asyncio.create_task(caller_to_agent())
    task_out = asyncio.create_task(agent_to_caller())
    await done.wait()
    for t in (task_in, task_out):
        t.cancel()
    await asyncio.gather(task_in, task_out, return_exceptions=True)
    await gateway.end()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_steering.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Run the full unit suite**

Run: `pytest -q`
Expected: PASS (all unit tests from Tasks 2–5).

- [ ] **Step 6: Commit**

```bash
git add relay/steering.py tests/test_steering.py
git commit -m "feat: steering loop with seamless greeter->specialist swap"
```

---

### Task 6: Greeter agent + intent tool

**Files:**
- Create: `audiocodes-to-adk-agent/agents/intent_tool.py`
- Create: `audiocodes-to-adk-agent/agents/greeter.py`

**Interfaces:**
- Consumes: ADK `LlmAgent`, `FunctionTool`.
- Produces:
  - `classify_intent(intent: str) -> dict` (FunctionTool fn) and `on_intent(tool, args, tool_context, tool_response)` after-tool callback that sets `tool_context.state["intent"] = args["intent"]`.
  - `build_greeter(model: str) -> LlmAgent` and `greeter_agent` (built with `LIVE_MODEL`). Agent name `"greeter"`.

- [ ] **Step 1: Write the intent tool + callback**

`agents/intent_tool.py`:
```python
from __future__ import annotations

VALID_INTENTS = ("internet", "phone_upgrade", "billing")


def classify_intent(intent: str) -> dict:
    """Record the caller's intent. Call this once you know what the caller needs.

    intent must be one of: internet, phone_upgrade, billing.
    """
    return {"status": "classified", "intent": intent}


def on_intent(tool, args, tool_context, tool_response):
    """after_tool_callback: stage the intent into session state for the relay.

    The relay reads it from the run_live event's actions.state_delta.intent.
    """
    if tool.name == "classify_intent":
        tool_context.state["intent"] = args.get("intent", "")
    return None
```

- [ ] **Step 2: Write the greeter agent**

`agents/greeter.py`:
```python
from __future__ import annotations

import os

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool

from agents.intent_tool import classify_intent, on_intent

LIVE_MODEL = os.environ.get("LIVE_MODEL", "gemini-live-2.5-flash-native-audio")

INSTRUCTIONS = """You are a friendly AT&T phone-line greeter. Keep it brief.

Opening:
- The conversation opens with a "(call_start)" signal. When you receive it, say
  exactly: "Thanks for calling AT&T. How can I help you today?" Never read the
  "(call_start)" signal aloud, and never call a tool during the greeting.

Routing:
- Listen to the caller's first request. As soon as you understand what they need,
  call classify_intent with exactly one of: "internet" (service/connectivity
  issues), "phone_upgrade" (new phone / upgrade eligibility), "billing"
  (charges, payments, bill questions).
- Do NOT try to solve the problem yourself and do NOT say you are transferring.
  Just call classify_intent. A specialist takes over seamlessly.
- If unsure, ask ONE short clarifying question, then classify.

Keep replies to one or two short sentences.
"""


def build_greeter(model: str) -> LlmAgent:
    return LlmAgent(
        name="greeter",
        model=model,
        description="Greets the caller and classifies intent.",
        instruction=INSTRUCTIONS,
        tools=[FunctionTool(func=classify_intent)],
        after_tool_callback=on_intent,
    )


greeter_agent = build_greeter(LIVE_MODEL)
```

- [ ] **Step 3: Smoke-check the build**

Run: `cd audiocodes-to-adk-agent && python -c "from agents.greeter import greeter_agent; print(greeter_agent.name, [t for t in greeter_agent.tools])"`
Expected: prints `greeter ...` with one tool listed, no import error.

- [ ] **Step 4: Commit**

```bash
git add agents/intent_tool.py agents/greeter.py
git commit -m "feat: greeter agent with intent classification tool"
```

---

### Task 7: Internet + phone-upgrade specialist agents

**Files:**
- Create: `audiocodes-to-adk-agent/agents/internet.py`
- Create: `audiocodes-to-adk-agent/agents/phone_upgrade.py`

**Interfaces:**
- Produces: `build_internet(model) -> LlmAgent` + `internet_agent`; `build_phone_upgrade(model) -> LlmAgent` + `phone_upgrade_agent`. Agent names `"internet"`, `"phone_upgrade"`.

- [ ] **Step 1: Write the internet agent**

`agents/internet.py`:
```python
from __future__ import annotations

import os

from google.adk.agents import LlmAgent

LIVE_MODEL = os.environ.get("LIVE_MODEL", "gemini-live-2.5-flash-native-audio")

INSTRUCTIONS = """You are an AT&T internet-support specialist. You have just been
handed a call that is already in progress — the caller has already been greeted and
has told us their issue (it is in your context).

CRITICAL: Do NOT greet, do NOT say "hello", do NOT say "welcome" or "welcome back",
and do NOT re-introduce yourself. Continue the existing conversation as if you were
the same voice. Open by acknowledging their internet issue and asking one concrete
troubleshooting question. Keep replies to one or two short sentences. This is a
connectivity demo; a couple of helpful turns is enough.
"""


def build_internet(model: str) -> LlmAgent:
    return LlmAgent(
        name="internet",
        model=model,
        description="AT&T internet-support specialist.",
        instruction=INSTRUCTIONS,
    )


internet_agent = build_internet(LIVE_MODEL)
```

- [ ] **Step 2: Write the phone-upgrade agent**

`agents/phone_upgrade.py`:
```python
from __future__ import annotations

import os

from google.adk.agents import LlmAgent

LIVE_MODEL = os.environ.get("LIVE_MODEL", "gemini-live-2.5-flash-native-audio")

INSTRUCTIONS = """You are an AT&T phone-upgrade specialist. You have just been handed
a call already in progress — the caller has been greeted and stated their need (in
your context).

CRITICAL: Do NOT greet, do NOT say "welcome" or "welcome back", and do NOT
re-introduce yourself. Continue as the same voice. Open by acknowledging they want
to look at an upgrade and ask one concrete question (e.g. which line, or current
phone). Keep replies to one or two short sentences. This is a connectivity demo.
"""


def build_phone_upgrade(model: str) -> LlmAgent:
    return LlmAgent(
        name="phone_upgrade",
        model=model,
        description="AT&T phone-upgrade specialist.",
        instruction=INSTRUCTIONS,
    )


phone_upgrade_agent = build_phone_upgrade(LIVE_MODEL)
```

- [ ] **Step 3: Smoke-check both build**

Run: `cd audiocodes-to-adk-agent && python -c "from agents.internet import internet_agent; from agents.phone_upgrade import phone_upgrade_agent; print(internet_agent.name, phone_upgrade_agent.name)"`
Expected: prints `internet phone_upgrade`.

- [ ] **Step 4: Commit**

```bash
git add agents/internet.py agents/phone_upgrade.py
git commit -m "feat: internet and phone-upgrade specialist agents"
```

---

### Task 8: AdkLiveSession adapter

**Files:**
- Create: `audiocodes-to-adk-agent/relay/agents_runtime/adk_live.py`
- Create: `audiocodes-to-adk-agent/scripts/smoke_adk_live.py`

**Interfaces:**
- Consumes: `AgentSession` shape (Task 2); `SessionRecord` (Task 3); the agents (Tasks 6–7); ADK `Runner`, `LiveRequestQueue`, `RunConfig`, `InMemorySessionService`.
- Produces: `class AdkLiveSession` with `__init__(self, agent, session_service, voice: str = "Charon")`, `open(record)`, `send_audio(pcm)`, `events()` (async generator yielding `AgentAudio`/`AgentTranscript`/`AgentIntent`/`AgentEnd`), `close()`. The relay passes ONE shared `InMemorySessionService` to all `AdkLiveSession`s so ADK agents share the session by `record.session_id`.

- [ ] **Step 1: Write the adapter**

`relay/agents_runtime/adk_live.py`:
```python
from __future__ import annotations

import asyncio

from relay.ports import AgentAudio, AgentTranscript, AgentIntent, AgentEnd
from relay.session_record import SessionRecord

APP_NAME = "att_steering"


class AdkLiveSession:
    """AgentSession over ADK run_live (Gemini Live). One per agent activation.

    All AdkLiveSessions in a call share the SAME session_service + session_id, so a
    specialist inherits the greeter's turns (ADK shared session).
    """

    def __init__(self, agent, session_service, voice: str = "Charon"):
        self._agent = agent
        self._session_service = session_service
        self._voice = voice
        self._queue = None
        self._session_id = None

    def _run_config(self):
        from google.adk.agents.run_config import RunConfig, StreamingMode
        from google.genai import types
        return RunConfig(
            streaming_mode=StreamingMode.BIDI,
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self._voice)
                )
            ),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            input_audio_transcription=types.AudioTranscriptionConfig(),
        )

    async def open(self, record: SessionRecord) -> None:
        from google.adk.agents.live_request_queue import LiveRequestQueue
        from google.genai import types
        from relay.session_resolve import resolve_session  # see Step 2 note

        session, _ = await resolve_session(
            self._session_service, APP_NAME, record.caller or "caller", record.session_id
        )
        self._session_id = session.id
        record.session_id = session.id
        self._queue = LiveRequestQueue()
        # Greeter is told (call_start); specialists are told (handoff) so they
        # continue WITHOUT re-greeting (reinforced by their instructions).
        nudge = "(call_start)" if self._agent.name == "greeter" else "(handoff)"
        self._queue.send_content(
            types.Content(role="user", parts=[types.Part(text=nudge)])
        )

    async def send_audio(self, pcm: bytes) -> None:
        from google.genai import types
        if self._queue is not None:
            self._queue.send_realtime(
                types.Blob(data=pcm, mime_type="audio/pcm;rate=16000")
            )

    async def events(self):
        from google.adk.runners import Runner
        runner = Runner(
            app_name=APP_NAME, agent=self._agent, session_service=self._session_service
        )
        async for event in runner.run_live(
            user_id="caller",
            session_id=self._session_id,
            live_request_queue=self._queue,
            run_config=self._run_config(),
        ):
            ev = event.model_dump(exclude_none=True, by_alias=True, mode="json")

            # Intent staged by the greeter's after_tool_callback.
            actions = ev.get("actions") or {}
            delta = actions.get("stateDelta") or actions.get("state_delta") or {}
            if delta.get("intent"):
                yield AgentIntent(delta["intent"])

            # Transcripts (deltas then a cumulative final).
            for key, role in (
                ("inputTranscription", "user"), ("input_transcription", "user"),
                ("outputTranscription", "agent"), ("output_transcription", "agent"),
            ):
                tr = ev.get(key)
                if tr and tr.get("text"):
                    yield AgentTranscript(role, tr["text"], bool(tr.get("finished")))

            # Audio (base64 inline_data in content parts).
            content = ev.get("content") or {}
            for part in content.get("parts") or []:
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    import base64
                    b64 = inline["data"].replace("-", "+").replace("_", "/")
                    yield AgentAudio(base64.b64decode(b64))

        yield AgentEnd()

    async def close(self) -> None:
        if self._queue is not None:
            self._queue.close()
            self._queue = None
```

- [ ] **Step 2: Add the shared session_resolve helper**

Copy `resolve_session` into this module's package by creating `relay/session_resolve.py` with the exact contents of `shared-session-voice-and-chat/backend/session_resolve.py` (the `resolve_session`, `_safe_get`, `_latest_session_id` functions — proven and unchanged).

Run: `cd audiocodes-to-adk-agent && python -c "from relay.session_resolve import resolve_session; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Write the smoke script**

`scripts/smoke_adk_live.py`:
```python
from dotenv import load_dotenv
load_dotenv()

import asyncio

from google.adk.sessions import InMemorySessionService
from google.genai import types

from agents.greeter import greeter_agent
from relay.agents_runtime.adk_live import AdkLiveSession
from relay.session_record import SessionRecord


async def main():
    svc = InMemorySessionService()
    sess = AdkLiveSession(greeter_agent, svc)
    record = SessionRecord(session_id=None)  # let ADK create one
    await sess.open(record)
    # Inject a typed turn instead of audio to keep the smoke text-only.
    sess._queue.send_content(
        types.Content(role="user", parts=[types.Part(text="my internet is down")])
    )
    seen = []
    async for ev in sess.events():
        seen.append(type(ev).__name__)
        if len(seen) > 8:
            break
    await sess.close()
    print("events:", seen)


asyncio.run(main())
```

- [ ] **Step 4: Run the smoke (requires Vertex ADC)**

Run: `cd audiocodes-to-adk-agent && . .venv/bin/activate && python scripts/smoke_adk_live.py`
Expected: prints `events: [...]` including `AgentTranscript` and/or `AgentIntent` (the greeter should classify "internet"). No traceback.

- [ ] **Step 5: Commit**

```bash
git add relay/agents_runtime/adk_live.py relay/session_resolve.py scripts/smoke_adk_live.py
git commit -m "feat: AdkLiveSession adapter over run_live"
```

---

### Task 9: CES billing agent + CesBidiSession adapter

**Files:**
- Create: `audiocodes-to-adk-agent/relay/agents_runtime/ces_bidi.py`
- Create: `audiocodes-to-adk-agent/scripts/smoke_ces_bidi.py`

**Interfaces:**
- Consumes: `AgentSession` shape (Task 2); `SessionRecord` (Task 3); `websocket-client`, `google.auth`.
- Produces: `class CesBidiSession` with `__init__(self, app: str, location: str = "us", input_rate: int = 16000, output_rate: int = 24000)`, `open(record)`, `send_audio(pcm)`, `events()` (yields `AgentAudio`/`AgentTranscript`/`AgentEnd`), `close()`.

**Prerequisite — build the billing agent in CX Agent Studio (one-time, console/API):**
1. In the CX Agent Studio console, create an app (a generative playbook agent) named e.g. `att-billing`. Give it a short instruction: *"You are an AT&T billing specialist. The call is already in progress — do NOT greet or say welcome; continue the conversation, acknowledge the billing question, and ask one concrete question. One or two short sentences."*
2. Note the app resource name `projects/{p}/locations/{loc}/apps/{app}` → set `CES_APP` in `.env`.
3. Ensure ADC has `roles/ces.user` (or equivalent) on the project.

- [ ] **Step 1: Write the adapter**

`relay/agents_runtime/ces_bidi.py`:
```python
from __future__ import annotations

import asyncio
import base64
import json
import queue as _queue
import threading
import uuid

import google.auth
import google.auth.transport.requests
import websocket  # websocket-client

from relay.ports import AgentAudio, AgentTranscript, AgentEnd
from relay.session_record import SessionRecord


class CesBidiSession:
    """AgentSession over CX Agent Studio (CES) BidiRunSession WebSocket."""

    def __init__(self, app: str, location: str = "us",
                 input_rate: int = 16000, output_rate: int = 24000):
        self._app = app
        self._location = location
        self._input_rate = input_rate
        self._output_rate = output_rate
        self._ws = None
        self._out: _queue.Queue = _queue.Queue()
        self._thread = None

    def _token(self) -> str:
        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        creds.refresh(google.auth.transport.requests.Request())
        return creds.token

    async def open(self, record: SessionRecord) -> None:
        session_id = record.session_id or str(uuid.uuid4())
        record.session_id = session_id
        uri = (
            f"wss://ces.googleapis.com/ws/google.cloud.ces.v1.SessionService/"
            f"BidiRunSession/locations/{self._location}"
        )
        headers = [f"Authorization: Bearer {self._token()}"]
        config = {
            "config": {
                "session": f"{self._app}/sessions/{session_id}",
                "inputAudioConfig": {
                    "audioEncoding": "LINEAR16",
                    "sampleRateHertz": self._input_rate,
                },
                "outputAudioConfig": {
                    "audioEncoding": "LINEAR16",
                    "sampleRateHertz": self._output_rate,
                },
                # Seed prior conversation so the billing agent continues mid-call.
                # NOTE: confirm the Message field names against the ces.v1 proto in
                # Step 3 — adjust if the smoke shows the context is ignored.
                "historicalContexts": [
                    {"author": "USER", "text": record.context_summary()}
                ],
            }
        }

        def on_open(ws):
            ws.send(json.dumps(config))

        def on_message(ws, message):
            self._out.put(message)

        def on_close(ws, *a):
            self._out.put(None)

        self._ws = websocket.WebSocketApp(
            uri, header=headers,
            on_open=on_open, on_message=on_message, on_close=on_close,
        )
        self._thread = threading.Thread(target=self._ws.run_forever, daemon=True)
        self._thread.start()

    async def send_audio(self, pcm: bytes) -> None:
        if self._ws is not None:
            msg = {"realtimeInput": {"audio": base64.b64encode(pcm).decode("ascii")}}
            self._ws.send(json.dumps(msg))

    async def events(self):
        loop = asyncio.get_event_loop()
        while True:
            message = await loop.run_in_executor(None, self._out.get)
            if message is None:
                break
            data = json.loads(message)
            out = data.get("sessionOutput") or {}
            rec = data.get("recognitionResult") or {}
            if rec.get("transcript"):
                yield AgentTranscript("user", rec["transcript"], False)
            if out.get("text"):
                yield AgentTranscript("agent", out["text"], bool(out.get("turnCompleted")))
            if out.get("audio"):
                yield AgentAudio(base64.b64decode(out["audio"]))
            if data.get("endSession"):
                break
        yield AgentEnd()

    async def close(self) -> None:
        if self._ws is not None:
            try:
                self._ws.close()
            finally:
                self._ws = None
```

- [ ] **Step 2: Write the smoke script**

`scripts/smoke_ces_bidi.py`:
```python
from dotenv import load_dotenv
load_dotenv()

import asyncio
import os
import wave

from relay.agents_runtime.ces_bidi import CesBidiSession
from relay.session_record import SessionRecord


async def main():
    app = os.environ["CES_APP"]
    sess = CesBidiSession(app=app, location=os.environ.get("CES_LOCATION", "us"))
    record = SessionRecord(session_id=None, caller="+15550000000")
    record.set_intent("billing")
    record.add_turn("user", "I have a question about my bill")
    await sess.open(record)

    # Stream a 16kHz mono PCM16 WAV in ~20ms chunks (record a short "hello" first).
    with wave.open("scripts/sample_16k.wav", "rb") as w:
        assert w.getframerate() == 16000 and w.getsampwidth() == 2
        while True:
            frames = w.readframes(320)
            if not frames:
                break
            await sess.send_audio(frames)
            await asyncio.sleep(0.02)

    seen = []
    async for ev in sess.events():
        seen.append(type(ev).__name__)
        if len(seen) > 10:
            break
    await sess.close()
    print("events:", seen)


asyncio.run(main())
```

- [ ] **Step 3: Run the smoke (requires CES app + ADC + a sample WAV)**

Record a short 16 kHz mono WAV at `scripts/sample_16k.wav` (e.g. say "hi, about my bill").
Run: `cd audiocodes-to-adk-agent && . .venv/bin/activate && python scripts/smoke_ces_bidi.py`
Expected: prints `events: [...]` with `AgentTranscript` and `AgentAudio`. If transcripts show the agent re-greeting, the `historicalContexts` shape is wrong — fix the field names per the ces.v1 `Message` proto and re-run.

- [ ] **Step 4: Commit**

```bash
git add relay/agents_runtime/ces_bidi.py scripts/smoke_ces_bidi.py
git commit -m "feat: CesBidiSession adapter over BidiRunSession"
```

---

### Task 9A: ADK agent registry + Agent Engine bidi app

**Files:**
- Create: `audiocodes-to-adk-agent/agents/registry.py`
- Create: `audiocodes-to-adk-agent/relay/agent_app.py`

**Interfaces:**
- Consumes: the three agents (Tasks 6–7); `relay.session_resolve` (Task 8); ADK `Runner`, `LiveRequestQueue`, `RunConfig`, `VertexAiSessionService`.
- Produces:
  - `ADK_AGENTS: dict[str, LlmAgent]` keyed `greeter`/`internet`/`phone_upgrade`.
  - `class SteeringApp` with `set_up()`, `register_operations() -> {"bidi_stream": ["bidi_stream_query"]}`, and `async bidi_stream_query(request_queue)`. First queue item: `{"user_id", "session_id", "agent_key"}`. Yields a `session_info` dict then `run_live` events (`model_dump(by_alias)`).

- [ ] **Step 1: Write the registry**

`agents/registry.py`:
```python
from __future__ import annotations

from agents.greeter import greeter_agent
from agents.internet import internet_agent
from agents.phone_upgrade import phone_upgrade_agent

# Shared by the Agent Engine app and the local factory.
ADK_AGENTS = {
    "greeter": greeter_agent,
    "internet": internet_agent,
    "phone_upgrade": phone_upgrade_agent,
}
```

- [ ] **Step 2: Write the Agent Engine bidi app**

`relay/agent_app.py`:
```python
from __future__ import annotations

import asyncio
import base64
import os
from typing import Any

APP_NAME = "att_steering"


class SteeringApp:
    """One multi-agent Agent Engine app. Selects the agent per call by agent_key;
    all agents share the engine's session store by session_id (no SESSION_ENGINE_ID)."""

    def set_up(self) -> None:
        from google.adk.sessions import VertexAiSessionService
        from agents.registry import ADK_AGENTS

        engine_id = (
            os.environ.get("SESSION_ENGINE_ID")
            or os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID")
        )
        self._session_service = VertexAiSessionService(
            project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
            location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
            agent_engine_id=engine_id,
        )
        self._agents = ADK_AGENTS
        self._voice = os.environ.get("LIVE_VOICE", "Charon")

    def register_operations(self):
        return {"bidi_stream": ["bidi_stream_query"]}

    def _run_config(self):
        from google.adk.agents.run_config import RunConfig, StreamingMode
        from google.genai import types
        return RunConfig(
            streaming_mode=StreamingMode.BIDI,
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self._voice)
                )
            ),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            input_audio_transcription=types.AudioTranscriptionConfig(),
        )

    async def bidi_stream_query(self, request_queue: "asyncio.Queue[Any]"):
        from google.adk.agents.live_request_queue import LiveRequestQueue
        from google.adk.runners import Runner
        from google.genai import types
        from relay.session_resolve import resolve_session

        first = await request_queue.get()
        user_id = (first or {}).get("user_id", "caller")
        req_sid = (first or {}).get("session_id")
        agent_key = (first or {}).get("agent_key", "greeter")
        agent = self._agents.get(agent_key, self._agents["greeter"])

        session, resumed = await resolve_session(
            self._session_service, APP_NAME, user_id, req_sid
        )
        yield {"type": "session_info", "session_id": session.id, "resumed": resumed}

        live_queue = LiveRequestQueue()
        nudge = "(call_start)" if agent_key == "greeter" else "(handoff)"
        live_queue.send_content(
            types.Content(role="user", parts=[types.Part(text=nudge)])
        )

        async def pump():
            while True:
                msg = await request_queue.get()
                if msg is None:
                    continue
                if msg.get("type") == "audio":
                    pcm = base64.b64decode(msg["data"])
                    live_queue.send_realtime(
                        types.Blob(data=pcm, mime_type="audio/pcm;rate=16000")
                    )
                elif msg.get("type") == "end":
                    live_queue.close()
                    return

        pump_task = asyncio.create_task(pump())
        runner = Runner(
            app_name=APP_NAME, agent=agent, session_service=self._session_service
        )
        try:
            async for event in runner.run_live(
                user_id=user_id,
                session_id=session.id,
                live_request_queue=live_queue,
                run_config=self._run_config(),
            ):
                yield event.model_dump(exclude_none=True, by_alias=True, mode="json")
        finally:
            pump_task.cancel()
            live_queue.close()
```

- [ ] **Step 3: Smoke-check the imports**

Run: `cd audiocodes-to-adk-agent && python -c "from relay.agent_app import SteeringApp; from agents.registry import ADK_AGENTS; print(sorted(ADK_AGENTS), SteeringApp().register_operations())"`
Expected: prints `['greeter', 'internet', 'phone_upgrade'] {'bidi_stream': ['bidi_stream_query']}`.

- [ ] **Step 4: Commit**

```bash
git add agents/registry.py relay/agent_app.py
git commit -m "feat: ADK agent registry and Agent Engine bidi app"
```

---

### Task 9B: Deploy the ADK app to Agent Engine

**Files:**
- Create: `audiocodes-to-adk-agent/deploy/deploy_agent_engine.py`
- Create: `audiocodes-to-adk-agent/deploy/destroy.sh`
- Modify: `audiocodes-to-adk-agent/.env.example` (add `STAGING_BUCKET`, `AE_ENGINE_ID`)

**Interfaces:**
- Consumes: `SteeringApp` (Task 9A). Reuses the proven idempotent update-or-create pattern.
- Produces: a deployed Agent Engine resource (`projects/.../reasoningEngines/{id}`); its full resource name printed and set as `AE_ENGINE_ID`.

- [ ] **Step 1: Add deploy env to `.env.example`**

Append to `.env.example`:
```
# Agent Engine (ADK agents)
STAGING_BUCKET=your-bucket-name
AE_ENGINE_ID=
```

- [ ] **Step 2: Write the deploy script**

`deploy/deploy_agent_engine.py`:
```python
from dotenv import load_dotenv
load_dotenv()

import os

import vertexai
from vertexai import types as vtypes

from relay.agent_app import SteeringApp

PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
BUCKET = os.environ["STAGING_BUCKET"]
DISPLAY_NAME = "att-steering-adk"

ENV_VARS = {
    "GOOGLE_GENAI_USE_VERTEXAI": "TRUE",
    "LIVE_MODEL": os.environ.get("LIVE_MODEL", "gemini-live-2.5-flash-native-audio"),
    "LIVE_VOICE": os.environ.get("LIVE_VOICE", "Charon"),
}

cfg = vtypes.AgentEngineConfig(
    display_name=DISPLAY_NAME,
    description="ADK multi-agent steering app (greeter + specialists), Live/bidi.",
    staging_bucket=f"gs://{BUCKET}",
    requirements=[
        "google-cloud-aiplatform[agent_engines]",
        "google-adk==2.1.0",
        "cloudpickle==3.1.2",
        "websockets",
    ],
    extra_packages=["relay", "agents"],   # RELATIVE → importable on remote
    python_version="3.12",
    agent_server_mode=vtypes.AgentServerMode.EXPERIMENTAL,
    env_vars=ENV_VARS,
)

client = vertexai.Client(project=PROJECT, location=LOCATION)
existing = next(
    (e for e in client.agent_engines.list()
     if getattr(e.api_resource, "display_name", "") == DISPLAY_NAME),
    None,
)
app = SteeringApp()
if existing is not None:
    name = existing.api_resource.name
    print(f"Updating {name.split('/')[-1]} in place... (~several minutes)")
    engine = client.agent_engines.update(name=name, agent=app, config=cfg)
else:
    print("Creating Agent Engine... (~several minutes)")
    engine = client.agent_engines.create(agent=app, config=cfg)

print("AE_ENGINE_ID:", engine.api_resource.name)
```

- [ ] **Step 3: Write the teardown script**

`deploy/destroy.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail
: "${GOOGLE_CLOUD_PROJECT:?}"; : "${GOOGLE_CLOUD_LOCATION:=us-central1}"
python - <<'PY'
import os, vertexai
c = vertexai.Client(project=os.environ["GOOGLE_CLOUD_PROJECT"],
                    location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"))
for e in c.agent_engines.list():
    if getattr(e.api_resource, "display_name", "") == "att-steering-adk":
        print("deleting", e.api_resource.name)
        c.agent_engines.delete(name=e.api_resource.name, force=True)
PY
```

- [ ] **Step 4: Deploy (run from the MODULE ROOT so relative extra_packages resolve)**

Run: `cd audiocodes-to-adk-agent && . .venv/bin/activate && python deploy/deploy_agent_engine.py`
Expected: prints `AE_ENGINE_ID: projects/.../locations/.../reasoningEngines/<id>` after several minutes. Copy that value into `.env` as `AE_ENGINE_ID`.
(If it fails with `code 13 INTERNAL`, that's a known per-create platform flake — wait ~15 min and re-run; the script updates in place once an engine exists.)

- [ ] **Step 5: Commit**

```bash
git add deploy/deploy_agent_engine.py deploy/destroy.sh .env.example
git commit -m "feat: idempotent Agent Engine deploy for ADK steering app"
```

---

### Task 9C: AeAdkSession adapter (connect to deployed engine)

**Files:**
- Create: `audiocodes-to-adk-agent/relay/agents_runtime/ae_live.py`
- Create: `audiocodes-to-adk-agent/scripts/smoke_ae_live.py`

**Interfaces:**
- Consumes: events (Task 2); `SessionRecord` (Task 3); the deployed engine (Task 9B); `vertexai` client bidi connect.
- Produces: `class AeAdkSession` with `__init__(self, engine: str, agent_key: str, project: str, location: str = "us-central1")`, `open(record)`, `send_audio(pcm)`, `events()`, `close()`. On `session_info` it writes the engine's real `session_id` back onto `record` so the next specialist reuses it (shared session in the engine). Holds the `vertexai.Client` for the connection lifetime.

- [ ] **Step 1: Write the adapter**

`relay/agents_runtime/ae_live.py`:
```python
from __future__ import annotations

import base64

from relay.ports import AgentAudio, AgentTranscript, AgentIntent, AgentEnd
from relay.session_record import SessionRecord


class AeAdkSession:
    """AgentSession over an ADK agent deployed on Agent Engine (bidi_stream_query)."""

    def __init__(self, engine: str, agent_key: str, project: str,
                 location: str = "us-central1"):
        self._engine = engine
        self._agent_key = agent_key
        self._project = project
        self._location = location
        self._client = None
        self._cm = None
        self._conn = None
        self._record = None

    async def open(self, record: SessionRecord) -> None:
        import vertexai
        self._record = record
        # Hold the Client for the whole connection (GC closes its httpx client).
        self._client = vertexai.Client(project=self._project, location=self._location)
        self._cm = self._client.aio.live.agent_engines.connect(
            agent_engine=self._engine,
            config={"class_method": "bidi_stream_query", "include_all_fields": True},
        )
        self._conn = await self._cm.__aenter__()
        await self._conn.send({
            "user_id": record.caller or "caller",
            "session_id": record.session_id,
            "agent_key": self._agent_key,
        })

    async def send_audio(self, pcm: bytes) -> None:
        if self._conn is not None:
            await self._conn.send(
                {"type": "audio", "data": base64.b64encode(pcm).decode("ascii")}
            )

    async def events(self):
        while True:
            try:
                resp = await self._conn.receive()
            except Exception:
                break
            if not resp:
                break
            ev = resp.get("bidiStreamOutput", resp) if isinstance(resp, dict) else {}
            if not isinstance(ev, dict):
                continue
            if ev.get("type") == "session_info":
                if ev.get("session_id"):
                    self._record.session_id = ev["session_id"]  # share across agents
                continue
            actions = ev.get("actions") or {}
            delta = actions.get("stateDelta") or actions.get("state_delta") or {}
            if delta.get("intent"):
                yield AgentIntent(delta["intent"])
            for key, role in (
                ("inputTranscription", "user"), ("input_transcription", "user"),
                ("outputTranscription", "agent"), ("output_transcription", "agent"),
            ):
                tr = ev.get(key)
                if tr and tr.get("text"):
                    yield AgentTranscript(role, tr["text"], bool(tr.get("finished")))
            content = ev.get("content") or {}
            for part in content.get("parts") or []:
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    b64 = inline["data"].replace("-", "+").replace("_", "/")
                    yield AgentAudio(base64.b64decode(b64))
        yield AgentEnd()

    async def close(self) -> None:
        try:
            if self._conn is not None:
                await self._conn.send({"type": "end"})
        except Exception:
            pass
        try:
            if self._cm is not None:
                await self._cm.__aexit__(None, None, None)
        finally:
            self._cm = None
            self._conn = None
            self._client = None
```

- [ ] **Step 2: Write the smoke script**

`scripts/smoke_ae_live.py`:
```python
from dotenv import load_dotenv
load_dotenv()

import asyncio
import os
import wave

from relay.agents_runtime.ae_live import AeAdkSession
from relay.session_record import SessionRecord


async def main():
    sess = AeAdkSession(
        engine=os.environ["AE_ENGINE_ID"],
        agent_key="greeter",
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
    )
    record = SessionRecord(session_id=None, caller="+15550000000")
    await sess.open(record)

    # Stream a 16kHz mono PCM16 WAV (say "my internet is down").
    with wave.open("scripts/sample_16k.wav", "rb") as w:
        assert w.getframerate() == 16000 and w.getsampwidth() == 2
        while True:
            frames = w.readframes(320)
            if not frames:
                break
            await sess.send_audio(frames)
            await asyncio.sleep(0.02)

    seen = []
    async for ev in sess.events():
        seen.append(type(ev).__name__)
        if len(seen) > 12:
            break
    await sess.close()
    print("session_id:", record.session_id)
    print("events:", seen)


asyncio.run(main())
```

- [ ] **Step 3: Run the smoke (requires deployed engine + ADC + sample WAV)**

Run: `cd audiocodes-to-adk-agent && . .venv/bin/activate && python scripts/smoke_ae_live.py`
Expected: prints a real `session_id` and `events:` including `AgentTranscript` and/or `AgentIntent`. No `RuntimeError: ... client has been closed` (that would mean the `vertexai.Client` wasn't held).

- [ ] **Step 4: Commit**

```bash
git add relay/agents_runtime/ae_live.py scripts/smoke_ae_live.py
git commit -m "feat: AeAdkSession adapter for ADK agents on Agent Engine"
```

---

### Task 10: Agent factory

**Files:**
- Create: `audiocodes-to-adk-agent/relay/agents_runtime/factory.py`

**Interfaces:**
- Consumes: `ADK_AGENTS` (Task 9A); `AdkLiveSession` (Task 8); `AeAdkSession` (Task 9C); `CesBidiSession` (Task 9).
- Produces: `make_factory(*, session_service, ces_app, ces_location, ae_engine, project, ae_location, voice) -> (key, record) -> AgentSession`. ADK keys → `AeAdkSession` when `ae_engine` is set, else in-process `AdkLiveSession`; `billing` → `CesBidiSession`.

- [ ] **Step 1: Write the factory**

`relay/agents_runtime/factory.py`:
```python
from __future__ import annotations

from relay.agents_runtime.adk_live import AdkLiveSession
from relay.agents_runtime.ae_live import AeAdkSession
from relay.agents_runtime.ces_bidi import CesBidiSession

from agents.registry import ADK_AGENTS


def make_factory(*, session_service=None, ces_app: str, ces_location: str = "us",
                 ae_engine: str = "", project: str = "",
                 ae_location: str = "us-central1", voice: str = "Charon"):
    """Return agent_factory(key, record) -> AgentSession.

    ADK keys -> AeAdkSession when ae_engine is set (agents deployed on Agent
    Engine), else in-process AdkLiveSession (local dev). billing -> CesBidiSession.
    """

    def factory(key, record):
        if key in ADK_AGENTS:
            if ae_engine:
                return AeAdkSession(engine=ae_engine, agent_key=key,
                                    project=project, location=ae_location)
            return AdkLiveSession(ADK_AGENTS[key], session_service, voice=voice)
        if key == "billing":
            return CesBidiSession(app=ces_app, location=ces_location)
        # Unknown key should not happen (router defaults), but fail safe to internet.
        if ae_engine:
            return AeAdkSession(engine=ae_engine, agent_key="internet",
                                project=project, location=ae_location)
        return AdkLiveSession(ADK_AGENTS["internet"], session_service, voice=voice)

    return factory
```

- [ ] **Step 2: Smoke-check the wiring (AE path)**

Run: `cd audiocodes-to-adk-agent && python -c "from relay.agents_runtime.factory import make_factory; from relay.session_record import SessionRecord; f=make_factory(ces_app='projects/p/locations/us/apps/a', ae_engine='projects/p/locations/us-central1/reasoningEngines/1', project='p'); print(type(f('greeter', SessionRecord('X'))).__name__, type(f('billing', SessionRecord('X'))).__name__)"`
Expected: prints `AeAdkSession CesBidiSession`.

- [ ] **Step 3: Commit**

```bash
git add relay/agents_runtime/factory.py
git commit -m "feat: agent factory mapping keys to platform adapters"
```

---

### Task 11: HarnessGateway + FastAPI server

**Files:**
- Create: `audiocodes-to-adk-agent/relay/gateways/harness.py`
- Create: `audiocodes-to-adk-agent/relay/server.py`

**Interfaces:**
- Consumes: ports (Task 2), steering `run_call` (Task 5), factory (Task 10), `SessionRecord` (Task 3).
- Produces:
  - `class HarnessGateway` implementing `MediaGateway` over a FastAPI `WebSocket`. Wire protocol (JSON text frames): in `{"type":"audio","data":<base64 pcm16 16k>}` / `{"type":"end"}`; out `{"type":"audio","data":<base64 pcm16 24k>}` / `{"type":"session_end"}`.
  - FastAPI `app` with `@app.websocket("/ws")` that builds a `SessionRecord`, a factory, and runs `run_call`.

- [ ] **Step 1: Write the harness gateway**

`relay/gateways/harness.py`:
```python
from __future__ import annotations

import base64
import json

from relay.ports import CallerAudio, CallerEnd


class HarnessGateway:
    """MediaGateway over a browser WebSocket (mic in 16k, speaker out 24k)."""

    def __init__(self, websocket):
        self._ws = websocket

    async def events(self):
        from fastapi import WebSocketDisconnect
        try:
            while True:
                msg = json.loads(await self._ws.receive_text())
                if msg.get("type") == "audio":
                    yield CallerAudio(base64.b64decode(msg["data"]))
                elif msg.get("type") == "end":
                    yield CallerEnd()
                    return
        except WebSocketDisconnect:
            yield CallerEnd()
            return

    async def send_audio(self, pcm: bytes) -> None:
        await self._ws.send_text(json.dumps(
            {"type": "audio", "data": base64.b64encode(pcm).decode("ascii")}
        ))

    async def transfer(self, uri: str) -> None:
        # Phase 1 has no telephony; log only. (Phase 2 AudioCodes implements this.)
        await self._ws.send_text(json.dumps({"type": "transfer", "uri": uri}))

    async def end(self) -> None:
        try:
            await self._ws.send_text(json.dumps({"type": "session_end"}))
        except Exception:
            pass
```

- [ ] **Step 2: Write the server**

`relay/server.py`:
```python
from dotenv import load_dotenv
load_dotenv()

import os
import uuid

from fastapi import FastAPI, WebSocket
from google.adk.sessions import InMemorySessionService

from relay.gateways.harness import HarnessGateway
from relay.agents_runtime.factory import make_factory
from relay.session_record import SessionRecord
from relay.steering import run_call

app = FastAPI()

# One shared session service for the whole process → all ADK agents (greeter +
# specialists) share a session by session_id, so context carries.
_session_service = InMemorySessionService()


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    gateway = HarnessGateway(websocket)
    record = SessionRecord(session_id=str(uuid.uuid4()), caller="harness")
    factory = make_factory(
        session_service=_session_service,
        ces_app=os.environ["CES_APP"],
        ces_location=os.environ.get("CES_LOCATION", "us"),
        ae_engine=os.environ.get("AE_ENGINE_ID", ""),
        project=os.environ.get("GOOGLE_CLOUD_PROJECT", ""),
        ae_location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
        voice=os.environ.get("LIVE_VOICE", "Charon"),
    )
    await run_call(gateway, factory, record)
```

- [ ] **Step 3: Smoke-run the server boot**

Run: `cd audiocodes-to-adk-agent && . .venv/bin/activate && uvicorn relay.server:app --port 8080 &` then `curl -s localhost:8080/healthz` then `kill %1`
Expected: `{"ok":true}`; no import errors on boot.

- [ ] **Step 4: Commit**

```bash
git add relay/gateways/harness.py relay/server.py
git commit -m "feat: harness gateway and relay websocket server"
```

---

### Task 12: Harness mic client + end-to-end run + README

**Files:**
- Create: `audiocodes-to-adk-agent/harness/client.html`
- Create: `audiocodes-to-adk-agent/harness/serve.py`
- Create: `audiocodes-to-adk-agent/README.md`

**Interfaces:**
- Consumes: relay `/ws` wire protocol (Task 11).
- Produces: a browser page that captures mic at 16 kHz PCM16, streams `{"type":"audio",...}`, and plays back 24 kHz `{"type":"audio",...}` frames.

- [ ] **Step 1: Write the client**

`harness/client.html`:
```html
<!doctype html>
<html>
<head><meta charset="utf-8"><title>Steering Harness</title></head>
<body style="font-family:system-ui;max-width:40rem;margin:3rem auto">
  <h2>AudioCodes Steering Harness</h2>
  <button id="start">Start call</button>
  <button id="end" disabled>End</button>
  <pre id="log"></pre>
<script>
const RELAY = (location.hostname === "localhost")
  ? "ws://localhost:8080/ws"
  : "wss://" + location.host.replace(/^[^.]*\./, "relay.") + "/ws";
let ws, actx, playCtx, micStream, proc, playTime = 0;
const log = m => document.getElementById("log").textContent += m + "\n";

async function start() {
  document.getElementById("start").disabled = true;
  document.getElementById("end").disabled = false;

  // Playback context at device default rate; resume on this user gesture.
  playCtx = new AudioContext();
  await playCtx.resume();
  playTime = playCtx.currentTime;

  ws = new WebSocket(RELAY);
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.type === "audio") playPcm24(m.data);
    else if (m.type === "session_end") { log("session_end"); stop(); }
  };
  ws.onopen = () => log("ws open");

  // Capture at 16 kHz.
  actx = new AudioContext({ sampleRate: 16000 });
  micStream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true }
  });
  const src = actx.createMediaStreamSource(micStream);
  proc = actx.createScriptProcessor(4096, 1, 1);
  src.connect(proc);
  proc.connect(actx.destination); // REQUIRED or onaudioprocess never fires
  proc.onaudioprocess = (ev) => {
    if (!ws || ws.readyState !== 1) return;
    const f32 = ev.inputBuffer.getChannelData(0);
    const i16 = new Int16Array(f32.length);
    for (let i = 0; i < f32.length; i++) {
      const s = Math.max(-1, Math.min(1, f32[i]));
      i16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    ws.send(JSON.stringify({ type: "audio", data: b64(new Uint8Array(i16.buffer)) }));
  };
}

function playPcm24(b64data) {
  const std = b64data.replace(/-/g, "+").replace(/_/g, "/");
  const bytes = Uint8Array.from(atob(std), c => c.charCodeAt(0));
  const i16 = new Int16Array(bytes.buffer);
  const buf = playCtx.createBuffer(1, i16.length, 24000); // tag buffer at 24k
  const ch = buf.getChannelData(0);
  for (let i = 0; i < i16.length; i++) ch[i] = i16[i] / 0x8000;
  const node = playCtx.createBufferSource();
  node.buffer = buf;
  node.connect(playCtx.destination);
  const t = Math.max(playTime, playCtx.currentTime);
  node.start(t);
  playTime = t + buf.duration;
}

function stop() {
  document.getElementById("start").disabled = false;
  document.getElementById("end").disabled = true;
  try { ws && ws.send(JSON.stringify({ type: "end" })); } catch (e) {}
  try { proc && proc.disconnect(); } catch (e) {}
  try { micStream && micStream.getTracks().forEach(t => t.stop()); } catch (e) {}
  try { actx && actx.close(); } catch (e) {}
}

const b64 = (u8) => { let s = ""; for (const b of u8) s += String.fromCharCode(b); return btoa(s); };
document.getElementById("start").onclick = start;
document.getElementById("end").onclick = stop;
</script>
</body>
</html>
```

- [ ] **Step 2: Write the static server (no-store, dev)**

`harness/serve.py`:
```python
import http.server
import socketserver

PORT = 8000


class NoCache(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_header(self, key, value):
        if key.lower() in ("last-modified", "etag"):
            return
        super().send_header(key, value)


if __name__ == "__main__":
    with socketserver.TCPServer(("", PORT), NoCache) as httpd:
        print(f"harness at http://localhost:{PORT}/client.html")
        httpd.serve_forever()
```

- [ ] **Step 3: Run the full end-to-end demo**

Precondition: the ADK app is deployed (Task 9B) and `.env` has `AE_ENGINE_ID` set, plus `CES_APP`. With `AE_ENGINE_ID` present, the ADK agents run **on Agent Engine** and billing runs **on CES** — the cross-platform proof. (Unset `AE_ENGINE_ID` to fall back to in-process ADK for quick local checks.)

Terminal A: `cd audiocodes-to-adk-agent && . .venv/bin/activate && uvicorn relay.server:app --port 8080`
Terminal B: `cd audiocodes-to-adk-agent/harness && python serve.py`
Browser: open `http://localhost:8000/client.html`, click **Start call**, speak.

Verify each acceptance criterion:
- Greeter says "Thanks for calling AT&T. How can I help you today?"
- Say **"my internet is down"** → greeter goes silent → internet specialist continues **without re-greeting**.
- New call, say **"I want to upgrade my phone"** → routes to phone-upgrade specialist.
- New call, say **"I have a question about my bill"** → routes to the **CES billing** agent (different platform), continues without re-greeting.
- In each case the conversation sounds like one continuous voice (no "hello/welcome" at handoff).

Expected: all four routes work; handoffs are seamless. Note any audible gap at the swap for the §11 risk log.

- [ ] **Step 4: Write the README**

`README.md` documenting: what Phase 1 proves, architecture (ports + steering), how to run (env, ADC, CES app, the two servers + browser), the four demo routes, and a "Phase 2 next" pointer to add `AudioCodesGateway`. Keep neutral, no tooling references.

- [ ] **Step 5: Commit**

```bash
git add harness/client.html harness/serve.py README.md
git commit -m "feat: mic harness client and end-to-end Phase 1 demo"
```

---

## Self-Review

**Spec coverage:**
- Goal 2 (relay → any GCP platform, seamless): ADK on **Agent Engine** (Tasks 9A/9B/9C) + CES (Task 9) + steering/factory (5/10) + end-to-end (12). ✓
- ADK agents deployed on Agent Engine (folded into Phase 1): one multi-agent bidi app (9A), idempotent deploy (9B), `AeAdkSession` adapter (9C). ✓
- One VAIC bot / in-process steering: steering loop never re-routes telephony; swap is in-process (Task 5). ✓
- 3 specialists (internet, phone_upgrade ADK; billing CES): Tasks 7 + 9. ✓
- Greeter/router on first turn: Task 6. ✓
- Session-of-record + shared ADK session + CES historical seed: Tasks 3, 8 (shared `InMemorySessionService`), 9 (`historicalContexts`). ✓
- Linear conversation, no re-greet: specialist prompts (Task 7/9) + `(handoff)` nudge (Task 8). ✓
- `MediaGateway` port with harness now / AudioCodes later: Tasks 2, 11; Phase 2 is out of this plan. ✓
- Out of scope honored: no load test, no chat, no 8 kHz resample, no callback continuity. ✓

**Placeholder scan:** No "TBD"/"handle errors"/"similar to" — the one explicit note (CES `historicalContexts` field names) is a real verification step with working fallback config, not a code gap.

**Type consistency:** `AgentSession` methods (`open/send_audio/events/close`) consistent across `AdkLiveSession`, `CesBidiSession`, and `FakeAgent`. `agent_factory(key, record)` signature matches steering call and `make_factory`. Event types (`AgentAudio/Transcript/Intent/End`, `CallerAudio/End`) consistent across ports, adapters, steering, tests.

**Notes / follow-ons (not blockers):**
- ADK agents are deployed to Agent Engine (Tasks 9A–9C) and driven via `AeAdkSession`; the in-process `AdkLiveSession` (Task 8) is retained for unit smoke + a local fallback (factory uses it only when `AE_ENGINE_ID` is unset).
- The three ADK agents share one Agent Engine app and therefore one session store — context carries by `session_id` across the greeter→specialist swap with no `SESSION_ENGINE_ID` wiring.
- A short audible gap at greeter→specialist swap is the main risk to watch (§11). If present, add a one-line bridging clause to the greeter before it classifies.
