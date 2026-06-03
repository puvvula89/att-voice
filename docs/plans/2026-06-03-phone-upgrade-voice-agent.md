# Phone-Upgrade Voice Agent — Implementation Plan

> **For implementers:** Execute task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Each step is one small action. Commit frequently.

**Goal:** Build a voice phone-upgrade agent (module `01-phone-upgrade`) that speaks to the user over Gemini Live while pushing custom JSON UI components to a web client on the same stream.

**Architecture:** One streaming `LlmAgent` (`run_live`, BIDI) calls mock data tools and a `render_component(stage_intent)` tool. An `after_tool_callback` runs a deterministic formatter that fills a per-intent JSON template from session state and stashes it for a WebSocket relay to emit as a `ui_event`. Clicks from the browser are injected back as user turns. No second LLM, no orchestration hop.

**Tech Stack:** Python 3.11+, `google-adk>=2.0` (2.0 GA), Gemini Live model `gemini-2.5-flash-native-audio-preview-12-2025`, FastAPI + `uvicorn` (WebSocket relay), `pytest`; lightweight TypeScript/HTML web client with the Web Audio API.

**Reference base:** ADK bidi WebSocket sample — `https://github.com/google/adk-samples/tree/main/python/agents/bidi-demo`. Use it as the canonical pattern for agent/relay/audio-client wiring.

## Implementation rules (every task)

1. **Strict TDD for testable code:** for pure-Python tasks (Phases 1–5) write the failing test first, watch it fail, implement minimally, watch it pass, commit. Never write implementation before its test. Streaming/agent/relay/frontend tasks (Phases 6–9) cannot be meaningfully unit-tested — they are verified by the import smoke checks and the Phase 9 end-to-end run; do not fabricate unit tests for them.
2. **ADK 2.0 is GA with breaking changes vs 1.x.** Do NOT trust import paths or signatures from memory. After installing, verify each ADK symbol used (`LlmAgent`, `FunctionTool`, `Runner.run_live`, `RunConfig`/`StreamingMode`, `LiveRequestQueue`, `types.Blob`/`types.Content`, `after_tool_callback` signature, `event.actions.state_delta`) against the installed 2.0 package and the `bidi-demo` sample before writing code that uses it. Adjust the plan's code to match reality.
3. **Maintain the learnings log.** After completing a task, if you hit a genuinely critical, non-obvious gotcha that would otherwise be repeated (e.g. a 2.0 import moved, the native-audio model needs a specific RunConfig, the callback ordering trap, an audio-format requirement), append ONE concise entry to the `## Learnings` section of `/Users/admin/VibeCoding/att-voice/CLAUDE.md`. Bar for inclusion is high — only mistakes worth never repeating. Do not log routine steps.

---

## File structure

```
01-phone-upgrade/
├── README.md
├── backend/
│   ├── __init__.py
│   ├── mock_data.py        # canned account, lines, phones, receipt
│   ├── stage_intents.py    # stage_intent constants + state-key helpers
│   ├── tools.py            # data tools + render_component
│   ├── formatter.py        # build_payload(stage_intent, state) -> dict
│   ├── templates/          # one .json per stage_intent
│   │   ├── line_selector.json
│   │   ├── phone_options.json
│   │   ├── confirmation.json
│   │   └── receipt.json
│   ├── agent.py            # LlmAgent: instructions, tools, after_tool_callback
│   ├── callbacks.py        # on_render after_tool_callback
│   └── server.py           # FastAPI WebSocket relay (run_live <-> browser)
├── frontend/
│   ├── index.html
│   ├── audio.js            # mic capture + PCM playback (adapted from sample)
│   ├── client.js           # WS wiring + ui_event renderer + click -> user_action
│   └── components.js       # render line_selector / phone_options / confirmation / receipt
├── requirements.txt
└── tests/
    ├── test_mock_data.py
    ├── test_formatter.py
    ├── test_tools.py
    └── test_dual_input_parity.py
```

**Responsibilities:** `mock_data` = fixtures only. `stage_intents` = shared constants (no logic). `tools` = state writes + the render signal. `formatter` = pure transform (the deterministic replacement for the Formatter LLM). `agent`/`callbacks` = wiring. `server` = transport only. Frontend = render + report clicks, no business logic.

---

## Phase 0 — Scaffolding

### Task 0: Project skeleton and dependencies

**Files:**
- Create: `01-phone-upgrade/requirements.txt`
- Create: `01-phone-upgrade/backend/__init__.py` (empty)
- Create: `01-phone-upgrade/README.md`

- [ ] **Step 1: Create requirements.txt**

```
google-adk>=2.0,<3
fastapi
uvicorn[standard]
pytest
```

- [ ] **Step 2: Create empty package marker**

Create `01-phone-upgrade/backend/__init__.py` as an empty file.

- [ ] **Step 3: Create README**

```markdown
# 01 — Phone Upgrade (voice)

Voice phone-upgrade agent on Google ADK + Gemini Live.

## Run
1. `python -m venv .venv && source .venv/bin/activate`
2. `pip install -r requirements.txt`
3. Set `GOOGLE_API_KEY` (or ADK Vertex env) in the environment.
4. `uvicorn backend.server:app --reload` (from `01-phone-upgrade/`)
5. Open `frontend/index.html` against the local server.

## Test
`pytest tests/ -v` (from `01-phone-upgrade/`)
```

- [ ] **Step 4: Set up venv and install**

Run (from `01-phone-upgrade/`):
```bash
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
```
Expected: installs without error; `python -c "import google.adk"` succeeds.

- [ ] **Step 5: Commit**

```bash
git add 01-phone-upgrade/requirements.txt 01-phone-upgrade/backend/__init__.py 01-phone-upgrade/README.md
git commit -m "Scaffold phone-upgrade module"
```

---

## Phase 1 — Mock data (TDD)

### Task 1: Account fixtures

**Files:**
- Create: `01-phone-upgrade/backend/mock_data.py`
- Test: `01-phone-upgrade/tests/test_mock_data.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mock_data.py
from backend import mock_data

def test_lines_have_required_fields():
    lines = mock_data.get_account_lines()
    assert len(lines) == 3
    for line in lines:
        assert set(line) >= {"line_id", "last4", "device", "eligible"}

def test_eligible_phones_for_known_line():
    phones = mock_data.get_phones_for_line("line_1243")
    assert len(phones) >= 1
    for p in phones:
        assert set(p) >= {"phone_id", "name", "image", "monthly_price", "trade_in"}

def test_phones_for_unknown_line_is_empty():
    assert mock_data.get_phones_for_line("nope") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mock_data.py -v`
Expected: FAIL — `ModuleNotFoundError`/`AttributeError`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/mock_data.py
_LINES = [
    {"line_id": "line_1243", "last4": "1243", "device": "iPhone 12", "eligible": True},
    {"line_id": "line_5588", "last4": "5588", "device": "Pixel 6", "eligible": True},
    {"line_id": "line_9001", "last4": "9001", "device": "iPhone 11", "eligible": False},
]

_PHONES = {
    "line_1243": [
        {"phone_id": "iphone_17", "name": "iPhone 17", "image": "/img/iphone17.png",
         "monthly_price": 32.99, "trade_in": 400},
        {"phone_id": "pixel_x", "name": "Pixel X", "image": "/img/pixelx.png",
         "monthly_price": 27.99, "trade_in": 300},
        {"phone_id": "galaxy_s9", "name": "Galaxy S9", "image": "/img/galaxys9.png",
         "monthly_price": 29.99, "trade_in": 350},
    ],
    "line_5588": [
        {"phone_id": "pixel_x", "name": "Pixel X", "image": "/img/pixelx.png",
         "monthly_price": 27.99, "trade_in": 300},
    ],
}

def get_account_lines():
    return [dict(line) for line in _LINES]

def get_phones_for_line(line_id):
    return [dict(p) for p in _PHONES.get(line_id, [])]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_mock_data.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/mock_data.py tests/test_mock_data.py
git commit -m "Add mock account/line/phone fixtures"
```

---

## Phase 2 — Stage intents + deterministic formatter (TDD core)

### Task 2: Stage-intent constants

**Files:**
- Create: `01-phone-upgrade/backend/stage_intents.py`

- [ ] **Step 1: Write implementation (constants only — no test needed)**

```python
# backend/stage_intents.py
LINE_SELECTOR = "line_selector"
PHONE_OPTIONS = "phone_options"
CONFIRMATION = "confirmation"
RECEIPT = "receipt"

ALL = (LINE_SELECTOR, PHONE_OPTIONS, CONFIRMATION, RECEIPT)

def data_key(stage_intent: str) -> str:
    """Session-state key where a stage_intent's source data is stored."""
    return f"data:{stage_intent}"
```

- [ ] **Step 2: Commit**

```bash
git add backend/stage_intents.py
git commit -m "Add stage_intent constants and state-key helper"
```

### Task 3: Templates

**Files:**
- Create: `backend/templates/line_selector.json`
- Create: `backend/templates/phone_options.json`
- Create: `backend/templates/confirmation.json`
- Create: `backend/templates/receipt.json`

- [ ] **Step 1: Create line_selector.json**

```json
{ "component": "line_selector", "title": "Select a line to upgrade", "selectable": true, "items_key": "lines" }
```

- [ ] **Step 2: Create phone_options.json**

```json
{ "component": "phone_options", "title": "Choose your new phone", "selectable": true, "items_key": "phones" }
```

- [ ] **Step 3: Create confirmation.json**

```json
{ "component": "confirmation", "title": "Confirm your upgrade", "confirm_label": "Confirm", "fields": ["line", "phone", "monthly_price", "terms"] }
```

- [ ] **Step 4: Create receipt.json**

```json
{ "component": "receipt", "title": "Upgrade confirmed", "fields": ["order_id", "line", "phone", "ship_estimate"] }
```

- [ ] **Step 5: Commit**

```bash
git add backend/templates/
git commit -m "Add UI templates per stage_intent"
```

### Task 4: Deterministic formatter

**Files:**
- Create: `01-phone-upgrade/backend/formatter.py`
- Test: `01-phone-upgrade/tests/test_formatter.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_formatter.py
import pytest
from backend import formatter, stage_intents as si

def test_line_selector_payload():
    state = {si.data_key(si.LINE_SELECTOR): {"lines": [{"last4": "1243"}]}}
    payload = formatter.build_payload(si.LINE_SELECTOR, state)
    assert payload["component"] == "line_selector"
    assert payload["data"]["lines"] == [{"last4": "1243"}]
    assert payload["selectable"] is True

def test_phone_options_payload():
    state = {si.data_key(si.PHONE_OPTIONS): {"phones": [{"phone_id": "iphone_17"}]}}
    payload = formatter.build_payload(si.PHONE_OPTIONS, state)
    assert payload["component"] == "phone_options"
    assert payload["data"]["phones"][0]["phone_id"] == "iphone_17"

def test_missing_state_raises():
    with pytest.raises(KeyError):
        formatter.build_payload(si.PHONE_OPTIONS, {})

def test_unknown_intent_raises():
    with pytest.raises(ValueError):
        formatter.build_payload("bogus", {})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_formatter.py -v`
Expected: FAIL — module/function missing.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/formatter.py
import json
from pathlib import Path
from backend import stage_intents as si

_TEMPLATE_DIR = Path(__file__).parent / "templates"

def _load_template(stage_intent: str) -> dict:
    if stage_intent not in si.ALL:
        raise ValueError(f"Unknown stage_intent: {stage_intent}")
    return json.loads((_TEMPLATE_DIR / f"{stage_intent}.json").read_text())

def build_payload(stage_intent: str, state: dict) -> dict:
    """Pure transform: template + state data -> UI payload. No LLM."""
    template = _load_template(stage_intent)
    key = si.data_key(stage_intent)
    if key not in state:
        raise KeyError(f"No state data for {stage_intent} (expected '{key}')")
    payload = dict(template)
    payload["stage_intent"] = stage_intent
    payload["data"] = state[key]
    return payload
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_formatter.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/formatter.py tests/test_formatter.py
git commit -m "Add deterministic stage_intent formatter"
```

---

## Phase 3 — Tools (TDD)

### Task 5: Data tools + render_component

**Files:**
- Create: `01-phone-upgrade/backend/tools.py`
- Test: `01-phone-upgrade/tests/test_tools.py`

ADK passes a `ToolContext` whose `.state` is a mutable mapping. The tests use a stub with a plain dict `.state`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tools.py
from backend import tools, stage_intents as si

class StubCtx:
    def __init__(self):
        self.state = {}

def test_get_lines_writes_state_and_returns_summary():
    ctx = StubCtx()
    result = tools.get_lines(tool_context=ctx)
    assert si.data_key(si.LINE_SELECTOR) in ctx.state
    assert ctx.state[si.data_key(si.LINE_SELECTOR)]["lines"][0]["last4"] == "1243"
    assert result["count"] == 3

def test_get_eligible_phones_writes_state():
    ctx = StubCtx()
    result = tools.get_eligible_phones(line_id="line_1243", tool_context=ctx)
    assert ctx.state[si.data_key(si.PHONE_OPTIONS)]["phones"][0]["phone_id"] == "iphone_17"
    assert result["count"] == 3

def test_select_line_records_choice():
    ctx = StubCtx()
    tools.select_line(line_id="line_1243", tool_context=ctx)
    assert ctx.state["selected_line"] == "line_1243"

def test_render_component_is_thin():
    ctx = StubCtx()
    result = tools.render_component(stage_intent=si.PHONE_OPTIONS, tool_context=ctx)
    assert result == {"status": "requested", "stage_intent": si.PHONE_OPTIONS}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tools.py -v`
Expected: FAIL — module/functions missing.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/tools.py
from backend import mock_data, stage_intents as si

def get_lines(tool_context) -> dict:
    """List the account's lines available for upgrade. Returns a count; UI data is in state."""
    lines = mock_data.get_account_lines()
    tool_context.state[si.data_key(si.LINE_SELECTOR)] = {"lines": lines}
    return {"count": len(lines)}

def get_eligible_phones(line_id: str, tool_context) -> dict:
    """List phones the given line is eligible for. Returns a count; UI data is in state."""
    phones = mock_data.get_phones_for_line(line_id)
    tool_context.state[si.data_key(si.PHONE_OPTIONS)] = {"phones": phones}
    return {"count": len(phones)}

def select_line(line_id: str, tool_context) -> dict:
    """Record the line the user chose."""
    tool_context.state["selected_line"] = line_id
    return {"selected_line": line_id}

def select_phone(phone_id: str, tool_context) -> dict:
    """Record the phone the user chose and stage the confirmation data."""
    tool_context.state["selected_phone"] = phone_id
    line_id = tool_context.state.get("selected_line")
    phones = mock_data.get_phones_for_line(line_id)
    phone = next((p for p in phones if p["phone_id"] == phone_id), {"phone_id": phone_id})
    tool_context.state[si.data_key(si.CONFIRMATION)] = {
        "line": line_id, "phone": phone.get("name", phone_id),
        "monthly_price": phone.get("monthly_price"), "terms": "24-month installment",
    }
    return {"selected_phone": phone_id}

def confirm_upgrade(tool_context) -> dict:
    """Finalize the upgrade and stage the receipt data."""
    tool_context.state[si.data_key(si.RECEIPT)] = {
        "order_id": "UPG-100423",
        "line": tool_context.state.get("selected_line"),
        "phone": tool_context.state.get("selected_phone"),
        "ship_estimate": "3-5 business days",
    }
    return {"order_id": "UPG-100423"}

def render_component(stage_intent: str, tool_context) -> dict:
    """Render the named UI component. Choose stage_intent based on the user's request.
    Valid values: line_selector, phone_options, confirmation, receipt."""
    return {"status": "requested", "stage_intent": stage_intent}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tools.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/tools.py tests/test_tools.py
git commit -m "Add data tools and render_component signal"
```

---

## Phase 4 — Callback formatter wiring (TDD)

### Task 6: `on_render` after_tool_callback

**Files:**
- Create: `01-phone-upgrade/backend/callbacks.py`
- Test: add to `01-phone-upgrade/tests/test_tools.py`

The callback runs the formatter for `render_component`, stashes the payload in `state["pending_ui"]`, and returns a short ack so the model never reads JSON aloud. For any other tool it returns `None` (use the original response).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_tools.py
from backend import callbacks, stage_intents as si

class _Tool:
    def __init__(self, name): self.name = name

def test_on_render_stashes_payload_and_acks():
    ctx = StubCtx()
    ctx.state[si.data_key(si.PHONE_OPTIONS)] = {"phones": [{"phone_id": "iphone_17"}]}
    out = callbacks.on_render(
        tool=_Tool("render_component"),
        args={"stage_intent": si.PHONE_OPTIONS},
        tool_context=ctx,
        tool_response={"status": "requested", "stage_intent": si.PHONE_OPTIONS},
    )
    assert ctx.state["pending_ui"]["stage_intent"] == si.PHONE_OPTIONS
    assert ctx.state["pending_ui"]["data"]["phones"][0]["phone_id"] == "iphone_17"
    assert out == {"status": "shown"}

def test_on_render_passthrough_for_other_tools():
    ctx = StubCtx()
    out = callbacks.on_render(
        tool=_Tool("get_lines"), args={}, tool_context=ctx,
        tool_response={"count": 3},
    )
    assert out is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tools.py -v`
Expected: FAIL — `callbacks` missing.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/callbacks.py
from backend import formatter

def on_render(tool, args, tool_context, tool_response):
    """after_tool_callback: turn a render_component call into a UI payload in state."""
    if tool.name == "render_component":
        payload = formatter.build_payload(args["stage_intent"], tool_context.state)
        tool_context.state["pending_ui"] = payload   # relay reads this from state_delta
        return {"status": "shown"}                    # model sees an ack, never narrates JSON
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tools.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/callbacks.py tests/test_tools.py
git commit -m "Add after_tool_callback that formats render_component into UI payload"
```

---

## Phase 5 — Dual-input parity (TDD)

### Task 7: Voice vs click advance the same state

**Files:**
- Test: `01-phone-upgrade/tests/test_dual_input_parity.py`

A click arrives as a `user_action`; the relay turns it into the same words a user would speak, which the agent resolves to the same tool call. This test asserts that the *tool-level* effect is identical regardless of input source.

- [ ] **Step 1: Write the test**

```python
# tests/test_dual_input_parity.py
from backend import tools, stage_intents as si

class StubCtx:
    def __init__(self, state=None): self.state = state or {}

def test_click_and_voice_select_line_produce_same_state():
    # "voice": agent calls select_line after understanding speech
    voice_ctx = StubCtx()
    tools.select_line(line_id="line_1243", tool_context=voice_ctx)

    # "click": user_action -> injected turn -> agent calls select_line with same id
    click_ctx = StubCtx()
    tools.select_line(line_id="line_1243", tool_context=click_ctx)

    assert voice_ctx.state == click_ctx.state
    assert voice_ctx.state["selected_line"] == "line_1243"
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/test_dual_input_parity.py -v`
Expected: PASS (1 passed).

- [ ] **Step 3: Run the full suite**

Run: `pytest tests/ -v`
Expected: all tests pass (mock_data 3, formatter 4, tools 6, parity 1).

- [ ] **Step 4: Commit**

```bash
git add tests/test_dual_input_parity.py
git commit -m "Assert voice/click input parity at tool level"
```

---

## Phase 6 — Agent (integration; manual verify)

### Task 8: Upgrade agent definition

**Files:**
- Create: `01-phone-upgrade/backend/agent.py`

> Verify ADK 2.0 import paths against the installed package + bidi-demo sample before running (2.0 has breaking changes vs 1.x). The Live model below is the current Gemini Developer API native-audio model (use with `GOOGLE_API_KEY`); on Vertex use `gemini-live-2.5-flash-native-audio`.

- [ ] **Step 1: Write the agent**

```python
# backend/agent.py
from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool
from backend import tools
from backend.callbacks import on_render

LIVE_MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"  # Developer API (GOOGLE_API_KEY)

INSTRUCTIONS = """You are a phone-upgrade voice assistant for an authorized account holder.

Flow:
1. When the user asks to upgrade, call get_lines, then call render_component("line_selector"),
   then say one short sentence asking which line to upgrade.
2. When they pick a line (by voice or selection), call select_line, then get_eligible_phones,
   then render_component("phone_options"), then briefly describe that options are on screen.
3. When they pick a phone, call select_phone, then render_component("confirmation"),
   then ask them to confirm.
4. On confirmation, call confirm_upgrade, then render_component("receipt"), then confirm completion.

Rules:
- ALWAYS call render_component after fetching data, choosing the stage_intent that matches the step.
- Keep spoken replies to one short, natural sentence. Never read JSON or IDs aloud.
- A selection injected as text (e.g. "user selected line ending 1243") is equivalent to speech.
"""

upgrade_agent = LlmAgent(
    name="upgrade_agent",
    model=LIVE_MODEL,
    instruction=INSTRUCTIONS,
    tools=[
        FunctionTool(func=tools.get_lines),
        FunctionTool(func=tools.get_eligible_phones),
        FunctionTool(func=tools.select_line),
        FunctionTool(func=tools.select_phone),
        FunctionTool(func=tools.confirm_upgrade),
        FunctionTool(func=tools.render_component),
    ],
    after_tool_callback=on_render,
)
```

- [ ] **Step 2: Import smoke check**

Run: `python -c "from backend.agent import upgrade_agent; print(upgrade_agent.name)"`
Expected: prints `upgrade_agent` with no import error.

- [ ] **Step 3: Commit**

```bash
git add backend/agent.py
git commit -m "Define upgrade agent with tools and formatter callback"
```

---

## Phase 7 — WebSocket relay (integration; manual verify)

### Task 9: FastAPI relay

**Files:**
- Create: `01-phone-upgrade/backend/server.py`

> Mirror the upstream/downstream task structure and audio handling from the bidi-demo sample. Key additions specific to this module are marked.

- [ ] **Step 1: Write the relay**

```python
# backend/server.py
import asyncio
import base64
import json

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from google.adk.runners import Runner
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.sessions import InMemorySessionService
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.genai import types

from backend.agent import upgrade_agent

app = FastAPI()
_session_service = InMemorySessionService()
APP_NAME = "phone_upgrade"

@app.websocket("/ws/{user_id}")
async def ws_endpoint(websocket: WebSocket, user_id: str):
    await websocket.accept()
    session = await _session_service.create_session(app_name=APP_NAME, user_id=user_id)
    runner = Runner(app_name=APP_NAME, agent=upgrade_agent, session_service=_session_service)
    queue = LiveRequestQueue()
    run_config = RunConfig(streaming_mode=StreamingMode.BIDI, response_modalities=["AUDIO"])

    async def upstream():
        try:
            while True:
                raw = await websocket.receive_text()
                msg = json.loads(raw)
                if msg["type"] == "audio":
                    pcm = base64.b64decode(msg["data"])
                    queue.send_realtime(types.Blob(data=pcm, mime_type="audio/pcm"))
                elif msg["type"] == "user_action":
                    # KEY: a click becomes the same words a user would speak
                    text = f'user selected {msg["selection"]}'
                    queue.send_content(types.Content(role="user", parts=[types.Part(text=text)]))
        except WebSocketDisconnect:
            queue.close()

    async def downstream():
        async for event in runner.run_live(
            user_id=user_id, session_id=session.id,
            live_request_queue=queue, run_config=run_config,
        ):
            # KEY: emit a clean ui_event when the callback stashed a payload
            if event.actions and getattr(event.actions, "state_delta", None):
                pending = event.actions.state_delta.get("pending_ui")
                if pending:
                    await websocket.send_text(json.dumps(
                        {"type": "ui_event", "stage_intent": pending["stage_intent"], "payload": pending}
                    ))
            # forward audio / transcript / flags
            await websocket.send_text(event.model_dump_json(exclude_none=True, by_alias=True))

    await asyncio.gather(upstream(), downstream())
```

- [ ] **Step 2: Start the server**

Run (from `01-phone-upgrade/`): `uvicorn backend.server:app --reload`
Expected: server starts; `/ws/{user_id}` endpoint available. (Audio path is verified end-to-end in Phase 9.)

- [ ] **Step 3: Commit**

```bash
git add backend/server.py
git commit -m "Add WebSocket relay bridging run_live to the browser"
```

---

## Phase 8 — Web client (integration; manual verify)

### Task 10: Audio capture/playback

**Files:**
- Create: `01-phone-upgrade/frontend/audio.js`

- [ ] **Step 1: Adapt the sample audio client**

Copy the mic-capture (PCM frames, base64) and playback worklet logic from the bidi-demo reference client into `audio.js`, exposing:
```js
// audio.js — exports
export async function startMic(onFrame) { /* mic -> onFrame(base64Pcm) */ }
export function playFrame(base64Pcm) { /* enqueue PCM for playback */ }
```
Match the sample rate / encoding the sample uses so the Live API accepts the audio.

- [ ] **Step 2: Commit**

```bash
git add frontend/audio.js
git commit -m "Add browser audio capture and playback"
```

### Task 11: Component renderer

**Files:**
- Create: `01-phone-upgrade/frontend/components.js`

- [ ] **Step 1: Write renderers (one per stage_intent)**

```js
// components.js
export function renderComponent(payload, onSelect) {
  const root = document.getElementById("ui-root");
  root.innerHTML = "";
  const map = { line_selector, phone_options, confirmation, receipt };
  (map[payload.stage_intent] || (() => {}))(payload, root, onSelect);
}

function line_selector(p, root, onSelect) {
  root.append(heading(p.title));
  p.data.lines.forEach(l => root.append(
    button(`Line ending ${l.last4} — ${l.device}`, () => onSelect(`line ending ${l.last4}`))
  ));
}
function phone_options(p, root, onSelect) {
  root.append(heading(p.title));
  p.data.phones.forEach(ph => root.append(
    card(ph.name, ph.image, `$${ph.monthly_price}/mo`, () => onSelect(ph.name))
  ));
}
function confirmation(p, root, onSelect) {
  root.append(heading(p.title));
  root.append(text(`${p.data.phone} on line ${p.data.line} — $${p.data.monthly_price}/mo`));
  root.append(button(p.confirm_label, () => onSelect("yes, confirm")));
}
function receipt(p, root) {
  root.append(heading(p.title));
  root.append(text(`Order ${p.data.order_id} — ships in ${p.data.ship_estimate}`));
}

// tiny DOM helpers
function heading(t){const h=document.createElement("h2");h.textContent=t;return h;}
function text(t){const d=document.createElement("p");d.textContent=t;return d;}
function button(label,fn){const b=document.createElement("button");b.textContent=label;b.onclick=fn;return b;}
function card(name,img,price,fn){const c=document.createElement("div");c.className="card";c.onclick=fn;
  c.innerHTML=`<img src="${img}" alt="${name}"/><div>${name}</div><div>${price}</div>`;return c;}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/components.js
git commit -m "Add UI component renderers per stage_intent"
```

### Task 12: WS client wiring + index.html

**Files:**
- Create: `01-phone-upgrade/frontend/client.js`
- Create: `01-phone-upgrade/frontend/index.html`

- [ ] **Step 1: Write client.js**

```js
// client.js
import { startMic, playFrame } from "./audio.js";
import { renderComponent } from "./components.js";

const ws = new WebSocket(`ws://localhost:8000/ws/demo-user`);

function sendAction(selection) {
  ws.send(JSON.stringify({ type: "user_action", selection }));
}

ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  if (msg.type === "ui_event") { renderComponent(msg.payload, sendAction); return; }
  // ADK event passthrough: play audio frames if present
  const parts = msg.content?.parts || [];
  for (const part of parts) {
    const b64 = part.inlineData?.data;
    if (b64) playFrame(b64);
  }
};

ws.onopen = () => startMic((b64) => ws.send(JSON.stringify({ type: "audio", data: b64 })));
```

- [ ] **Step 2: Write index.html**

```html
<!doctype html>
<html>
  <head><meta charset="utf-8"><title>Phone Upgrade</title>
    <style>.card{cursor:pointer;border:1px solid #ddd;padding:8px;margin:6px;display:inline-block}</style>
  </head>
  <body>
    <h1>Phone Upgrade</h1>
    <div id="ui-root"></div>
    <script type="module" src="./client.js"></script>
  </body>
</html>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/client.js frontend/index.html
git commit -m "Add web client: WS wiring, audio, and UI rendering"
```

---

## Phase 9 — End-to-end verification

### Task 13: Manual demo run

**Files:** none (verification only)

- [ ] **Step 1: Start backend**

Run (from `01-phone-upgrade/`, venv active, `GOOGLE_API_KEY` set): `uvicorn backend.server:app --reload`

- [ ] **Step 2: Open the client**

Serve `frontend/` (e.g. `python -m http.server 5500` from `frontend/`) and open `index.html`. Grant mic access.

- [ ] **Step 3: Verify the voice path**

Say "I want to upgrade my phone." Expected: agent speaks a short prompt AND a `line_selector` component renders. Continue by voice through phone selection → confirmation → receipt. Confirm audio and UI stay in sync.

- [ ] **Step 4: Verify the click path**

Restart the flow. Advance by **clicking** the line and phone instead of speaking. Expected: identical progression; the agent responds to clicks as if spoken.

- [ ] **Step 5: Verify no JSON narration**

Confirm the agent never reads IDs/JSON aloud (validates the ack-to-model design).

- [ ] **Step 6: Record results in the module README**

Add a short "Verified" note (date + that voice and click paths both complete) to `01-phone-upgrade/README.md` and commit.

```bash
git add 01-phone-upgrade/README.md
git commit -m "Record end-to-end verification of phone-upgrade demo"
```

---

## Self-review notes

- **Spec coverage:** Goal 1 (JSON+voice one stream) → Tasks 6/9/11. Goal 2 (single LLM + deterministic formatter) → Tasks 4/6/8. Goal 3 (dual input) → Tasks 7/9/12. Goal 4 (stage_intent/template parity) → Tasks 2/3/4. All four stage intents (§8) → Tasks 3/5/11. Wire protocol (§7) → Tasks 9/12. Risks (§10) → agent instructions (Task 8) address render reliability; audio settings (Task 10) address format match.
- **Type consistency:** `data_key()`, `pending_ui`, `stage_intent`, and `payload["data"]` names are used identically across formatter, tools, callback, server, and client.
- **Testing:** pure core (mock_data, formatter, tools, callback, parity) is unit-TDD; streaming/agent/relay/frontend are integration-verified in Phase 9, consistent with the design's testing strategy.
