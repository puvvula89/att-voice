import asyncio
import json
import logging

from fastapi.testclient import TestClient

from adapter.cxas_adapter import run_cxas_turn, log_association, EMPTY_TURN_FALLBACK
from adapter.server import app, get_cxas_agent


class FakeAgent:
    """Stands in for a Vertex agent engine: records call kwargs, yields preset
    events from async_stream_query (or raises)."""

    def __init__(self, events=None, raise_exc=None):
        self._events = events or []
        self._raise = raise_exc
        self.calls = []

    async def async_stream_query(self, **kwargs):
        self.calls.append(kwargs)
        if self._raise:
            raise self._raise
        for ev in self._events:
            yield ev


def _run(coro):
    return asyncio.run(coro)


def _client(agent):
    app.dependency_overrides[get_cxas_agent] = lambda: agent
    return TestClient(app)


# --- core: run_cxas_turn -----------------------------------------------------

def test_run_turn_returns_flattened_text_and_session_id():
    agent = FakeAgent([
        {"type": "session_info", "session_id": "sess-1", "resumed": False},
        {"actions": {"stateDelta": {"pending_ui": {"stage_intent": "line_selector"}}}},
        {"content": {"role": "model", "parts": [{"text": "Which line?"}]}},
    ])
    result = _run(run_cxas_turn(agent, customer_id="cust-9", utterance="upgrade"))
    assert result["response_text"] == "Which line?"
    assert result["session_id"] == "sess-1"


def test_run_turn_forwards_customer_id_and_omits_session_id_when_absent():
    agent = FakeAgent([{"type": "session_info", "session_id": "s"}])
    _run(run_cxas_turn(agent, customer_id="cust-9", utterance="hi"))
    assert agent.calls[0]["user_id"] == "cust-9"
    msg = agent.calls[0]["message"]
    assert "hi" in msg and "[channel: ivr]" in msg
    assert "session_id" not in agent.calls[0]


def test_run_turn_forwards_session_id_when_given():
    agent = FakeAgent([{"type": "session_info", "session_id": "s2"}])
    _run(run_cxas_turn(agent, customer_id="cust-9", utterance="hi", session_id="s2"))
    assert agent.calls[0]["session_id"] == "s2"


# --- empty-turn guard: never hand CXAS dead air ------------------------------

def test_run_turn_empty_agent_output_returns_fallback():
    """Fresh session where the agent only stages UI (no model text) -> the caller
    must still hear something, not silence."""
    agent = FakeAgent([
        {"type": "session_info", "session_id": "sess-1"},
        {"actions": {"stateDelta": {"pending_ui": {"stage_intent": "line_selector"}}}},
    ])
    result = _run(run_cxas_turn(agent, customer_id="c", utterance="upgrade"))
    assert result["response_text"] == EMPTY_TURN_FALLBACK
    assert result["empty_turn"] is True
    assert result["session_id"] == "sess-1"  # session still resolved


def test_run_turn_nonempty_output_not_flagged_empty():
    agent = FakeAgent([
        {"type": "session_info", "session_id": "s"},
        {"content": {"role": "model", "parts": [{"text": "Which line?"}]}},
    ])
    result = _run(run_cxas_turn(agent, customer_id="c", utterance="upgrade"))
    assert result["response_text"] == "Which line?"
    assert result["empty_turn"] is False


# --- sentiment: model-supplied, injected into the ADK message ---------------

def test_run_turn_injects_sentiment_envelope_into_message():
    agent = FakeAgent([
        {"type": "session_info", "session_id": "s"},
        {"content": {"role": "model", "parts": [{"text": "ok"}]}},
    ])
    result = _run(run_cxas_turn(
        agent, customer_id="c", utterance="this is broken",
        sentiment={"label": "frustrated", "score": 0.8},
    ))
    msg = agent.calls[0]["message"]
    assert "this is broken" in msg
    assert "caller_sentiment" in msg and "frustrated" in msg
    assert result["sentiment"] == {"label": "frustrated", "score": 0.8}


def test_run_turn_no_sentiment_sends_plain_utterance():
    agent = FakeAgent([{"type": "session_info", "session_id": "s"}])
    result = _run(run_cxas_turn(agent, customer_id="c", utterance="hi"))
    msg = agent.calls[0]["message"]
    assert "hi" in msg and "[channel: ivr]" in msg
    assert "caller_sentiment" not in msg          # no sentiment -> no envelope
    assert result["sentiment"] is None


def test_post_forwards_model_sentiment_fields():
    """The CES model supplies sentiment in the tool call; the adapter builds the
    envelope from it and echoes it back — no sentiment model call in the adapter."""
    agent = FakeAgent([
        {"type": "session_info", "session_id": "s"},
        {"content": {"role": "model", "parts": [{"text": "ok"}]}},
    ])
    app.dependency_overrides[get_cxas_agent] = lambda: agent
    try:
        r = TestClient(app).post("/cxas/turn", json={
            "customer_id": "c", "utterance": "terrible service",
            "caller_sentiment_label": "angry", "caller_sentiment_score": 0.9,
        })
        assert r.status_code == 200
        assert r.json()["sentiment"] == {"label": "angry", "score": 0.9}
        assert "angry" in agent.calls[0]["message"]   # envelope reached the ADK message
    finally:
        app.dependency_overrides.clear()


def test_post_without_sentiment_fields_sends_plain():
    agent = FakeAgent([
        {"type": "session_info", "session_id": "s"},
        {"content": {"role": "model", "parts": [{"text": "ok"}]}},
    ])
    app.dependency_overrides[get_cxas_agent] = lambda: agent
    try:
        r = TestClient(app).post(
            "/cxas/turn", json={"customer_id": "c", "utterance": "hello"}
        )
        assert r.status_code == 200
        assert r.json()["sentiment"] is None
        assert "caller_sentiment" not in agent.calls[0]["message"]
    finally:
        app.dependency_overrides.clear()


# --- route: POST /cxas/turn --------------------------------------------------

def test_post_returns_payload_without_ui():
    agent = FakeAgent([
        {"type": "session_info", "session_id": "sess-1"},
        {"actions": {"stateDelta": {"pending_ui": {"stage_intent": "line_selector"}}}},
        {"content": {"role": "model", "parts": [{"text": "Which line?"}]}},
    ])
    client = _client(agent)
    try:
        r = client.post("/cxas/turn", json={"customer_id": "c1", "utterance": "upgrade"})
        assert r.status_code == 200
        body = r.json()
        assert body["response_text"] == "Which line?"
        assert body["session_id"] == "sess-1"
        assert "pending_ui" not in body
    finally:
        app.dependency_overrides.clear()


def test_post_missing_customer_id_returns_400():
    client = _client(FakeAgent([]))
    try:
        r = client.post("/cxas/turn", json={"utterance": "hi"})
        assert r.status_code == 400
    finally:
        app.dependency_overrides.clear()


def test_post_agent_error_returns_speakable_fallback():
    client = _client(FakeAgent(raise_exc=RuntimeError("boom")))
    try:
        r = client.post("/cxas/turn", json={"customer_id": "c1", "utterance": "hi"})
        assert r.status_code == 200
        body = r.json()
        assert body["response_text"]  # non-empty fallback line to speak
        assert body.get("error") is True
    finally:
        app.dependency_overrides.clear()


# --- T6: correlation logging -------------------------------------------------

def test_log_association_has_all_fields():
    rec = log_association(
        customer_id="c1", session_id="s1", correlation_id="corr-1", turn=2
    )
    assert rec["customer_id"] == "c1"
    assert rec["session_id"] == "s1"
    assert rec["correlation_id"] == "corr-1"
    assert rec["turn"] == 2
    assert rec["channel"] == "ivr"
    assert rec["error"] is False


def test_log_association_mints_correlation_id_when_absent():
    rec = log_association(customer_id="c1", session_id="s1")
    assert rec["correlation_id"]  # non-empty minted id


def test_log_association_emits_structured_log(caplog):
    with caplog.at_level(logging.INFO, logger="cxas.association"):
        log_association(customer_id="c1", session_id="s1", correlation_id="corr-9")
    lines = [r.getMessage() for r in caplog.records if r.name == "cxas.association"]
    assert lines
    payload = json.loads(lines[0])
    assert payload["correlation_id"] == "corr-9"


def test_post_emits_association_with_resolved_session_id(caplog):
    agent = FakeAgent([
        {"type": "session_info", "session_id": "sess-1"},
        {"content": {"role": "model", "parts": [{"text": "Which line?"}]}},
    ])
    client = _client(agent)
    try:
        with caplog.at_level(logging.INFO, logger="cxas.association"):
            r = client.post(
                "/cxas/turn",
                json={"customer_id": "c1", "utterance": "hi", "correlation_id": "corr-1", "turn": 3},
            )
        assert r.status_code == 200
        lines = [x.getMessage() for x in caplog.records if x.name == "cxas.association"]
        assert lines
        payload = json.loads(lines[0])
        assert payload["customer_id"] == "c1"
        assert payload["session_id"] == "sess-1"
        assert payload["correlation_id"] == "corr-1"
        assert payload["turn"] == 3
        assert payload["channel"] == "ivr"
    finally:
        app.dependency_overrides.clear()
