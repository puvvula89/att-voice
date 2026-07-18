"""CXAS → ADK request/response adapter (Cloud Run service).

Exposes a single HTTP endpoint the CXAS OpenAPI tool calls per IVR turn. It runs
one turn against the shared chat Agent Engine (via ``async_stream_query``),
flattens the event stream to one speakable reply, and returns it with the
resolved session id. Self-contained: this use case is request/response only —
no WebSocket/voice relay lives here.

Env: GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION, CHAT_AGENT_ENGINE_NAME,
GOOGLE_GENAI_USE_VERTEXAI=TRUE.
"""
from dotenv import load_dotenv
load_dotenv()

import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from adapter.cxas_adapter import run_cxas_turn, log_association

CHAT_AGENT_ENGINE_NAME = os.environ.get("CHAT_AGENT_ENGINE_NAME")
_CXAS_FALLBACK = "I'm sorry, I'm having trouble right now. Please hold for a moment."
_log = logging.getLogger("cxas.server")

_cxas_client = None
_cxas_agent = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Pre-init the heavy chat-engine handle during container startup, NOT on the
    first request. Fetching it is a network round-trip that made a cold first turn
    slow enough to blow the CES tool-call timeout; building it here moves that cost
    into boot (with startup CPU boost) so the first real request is fast. Failure is
    non-fatal — the request-time Depends still lazily builds it, so the container
    always becomes ready. (Sentiment is now supplied by the CES model in the tool
    call, so there is no sentiment client to warm.)"""
    try:
        get_cxas_agent()
        _log.info("adapter warm: chat-engine handle ready")
    except Exception as e:  # never block startup on warm-up
        _log.warning("adapter warm-up skipped: %s", e)
    yield


app = FastAPI(lifespan=lifespan)


def get_cxas_agent():
    """Lazily build and cache the chat agent engine handle. Held at module level
    so its httpx client is not GC'd between requests."""
    global _cxas_client, _cxas_agent
    if _cxas_agent is None:
        import vertexai
        _cxas_client = vertexai.Client(
            project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
            location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
        )
        _cxas_agent = _cxas_client.agent_engines.get(name=CHAT_AGENT_ENGINE_NAME)
    return _cxas_agent


class CxasTurnIn(BaseModel):
    customer_id: str | None = None
    utterance: str = ""
    session_id: str | None = None
    # Caller sentiment for THIS turn, assessed by the CES steering model (no extra
    # model call here). Absent -> no sentiment envelope is added to the ADK message.
    caller_sentiment_label: str | None = None
    caller_sentiment_score: float | None = None
    correlation_id: str | None = None
    turn: int | None = None


@app.get("/healthz")
def healthz():
    return {"ok": True}


def _sentiment_from(body: "CxasTurnIn"):
    """Build the sentiment dict from the model-supplied fields, or None if absent."""
    if not body.caller_sentiment_label:
        return None
    return {"label": body.caller_sentiment_label, "score": body.caller_sentiment_score}


@app.post("/cxas/turn")
async def cxas_turn(
    body: CxasTurnIn,
    agent=Depends(get_cxas_agent),
):
    if not body.customer_id:
        raise HTTPException(status_code=400, detail="customer_id required")
    try:
        result = await run_cxas_turn(
            agent,
            customer_id=body.customer_id,
            utterance=body.utterance,
            session_id=body.session_id,
            sentiment=_sentiment_from(body),
        )
        log_association(
            customer_id=body.customer_id,
            session_id=result.get("session_id"),
            correlation_id=body.correlation_id,
            turn=body.turn,
            sentiment=result.get("sentiment"),
        )
        return result
    except Exception:
        # Never drop the caller: return a speakable fallback.
        log_association(
            customer_id=body.customer_id,
            session_id=body.session_id,
            correlation_id=body.correlation_id,
            turn=body.turn,
            error=True,
        )
        return {"response_text": _CXAS_FALLBACK, "session_id": body.session_id, "error": True}
