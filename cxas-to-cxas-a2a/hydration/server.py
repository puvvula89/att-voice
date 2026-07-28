"""Hydration service — gives a CXAS agent the context of a prior conversation.

WHY THIS EXISTS
    A CXAS `python_function` tool is fully network-isolated: no google client
    libraries, no credentials, and DNS resolution fails outright (verified by
    probe). So a tool can never fetch conversation history itself. External reach
    has to go through an OpenAPI toolset pointed at a real service — this one.

    The service holds credentials and network, reads the prior conversation with
    AgentServiceClient.get_conversation, condenses it, and returns a short summary
    the agent can act on.

WHY A SUMMARY, NOT RAW TURNS
    Replaying a dozen verbatim turns into a voice context steers the model badly
    and costs latency. We return a compact digest plus the last few exchanges.

KEY FACT
    conversation id == session id. The UUID the web client names in the bidi
    config frame (`{app}/sessions/{uuid}`) is readable afterwards as
    `{app}/conversations/{uuid}`.

Runs on Cloud Run, private, invoked by the CES service agent over OIDC.
"""
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
_log = logging.getLogger("cxas.hydration")

PROJECT = os.environ.get("CXAS_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("CXAS_LOCATION", "us")
APP_ID = os.environ.get("VOICE_APP_ID", "cxas-voice-and-chat")
APP = f"projects/{PROJECT}/locations/{LOCATION}/apps/{APP_ID}"

# How many recent exchanges to quote back verbatim.
RECENT_TURNS = int(os.environ.get("HYDRATION_RECENT_TURNS", "6"))
MAX_CHARS = int(os.environ.get("HYDRATION_MAX_CHARS", "1200"))

app = FastAPI()

# Client is built once at import (not per request) so the warm instance pays the
# gRPC channel setup during startup CPU boost, not on the caller's first turn.
_client = None


def _client_once():
    global _client
    if _client is None:
        from google.cloud import ces_v1beta
        from google.api_core import client_options as co
        # SCRAPI targets the GLOBAL endpoint; the region lives in the resource
        # path, not a hostname prefix.
        _client = ces_v1beta.AgentServiceClient(
            client_options=co.ClientOptions(api_endpoint="ces.googleapis.com")
        )
    return _client


class HydrateRequest(BaseModel):
    # The prior conversation to load. In testing this is the UUID the web client
    # used; in production your lookup resolves it from the customer id / ANI.
    conversation_id: str = ""
    # Optional: carried through for logging/correlation only.
    customer_id: str = ""


class HydrateResponse(BaseModel):
    found: bool
    summary: str
    turn_count: int = 0
    topic: str = ""
    # WHY found=false, for humans reading logs or curling the service. The agent
    # ignores this; it exists because every failure mode used to look identical
    # from the outside — "no history" and "the service cannot read history" both
    # returned a bare found=false, so a misconfigured deployment looked like a
    # customer with nothing to resume.
    #   ok | no_conversation_id | not_found | permission_denied | empty | error
    reason: str = ""


# Where a chunk's words can live. `transcript` is the one that matters and the one
# that is easy to miss: on this app almost every turn is SPOKEN, and spoken turns —
# both the caller's ASR and the agent's TTS — arrive as `transcript`. Only typed
# turns use `text`. Reading `text` alone silently drops the entire conversation
# except whatever the customer happened to type, which looks like "there was no
# history" rather than like a bug. Verified against a real conversation.
_TEXT_KEYS = ("text", "transcript")


def _text_of(message: Dict[str, Any]) -> str:
    """Pull plain text out of a message's chunks, whatever shape it arrives in."""
    parts: List[str] = []
    for chunk in message.get("chunks") or []:
        for key in _TEXT_KEYS:
            value = chunk.get(key)
            if value and isinstance(value, str):
                parts.append(value)
                break  # one rendering per chunk, never both
    if not parts and message.get("text"):
        parts.append(message["text"])
    return " ".join(p.strip() for p in parts if p).strip()


# Openers that carry no subject matter. A conversation whose only customer turn is
# one of these has no topic worth naming back to them.
_EMPTY_OPENERS = {
    "hello", "hi", "hey", "yo", "hiya", "howdy",
    "good morning", "good afternoon", "good evening",
    "hello there", "hi there", "test", "testing", "hello?", "are you there",
}


def _is_meaningful(text: str) -> bool:
    """True if an utterance is substantive enough to quote back as the topic."""
    cleaned = text.strip().strip(".,!?").lower()
    if not cleaned or cleaned in _EMPTY_OPENERS:
        return False
    # One or two words is a name or a greeting, not a described problem.
    return len(cleaned.split()) >= 3


def _condense(conv: Dict[str, Any]) -> HydrateResponse:
    """Turn a Conversation into a short digest the agent can speak from."""
    exchanges: List[str] = []
    for turn in conv.get("turns") or []:
        for m in turn.get("messages") or []:
            text = _text_of(m)
            if not text:
                continue
            role = (m.get("role") or "").lower()
            who = "Customer" if role in ("user", "human", "1") else "Agent"
            exchanges.append(f"{who}: {text}")

    if not exchanges:
        return HydrateResponse(found=False, summary="", turn_count=0, reason="empty")

    recent = exchanges[-RECENT_TURNS:]
    # First customer utterance is the best one-line topic proxy — but only if it
    # actually says something. A conversation that opened with "hello" and went
    # nowhere yields topic="hello", and the agent dutifully asks "are you calling
    # about your previous hello?". Better to return no topic and let the agent
    # fall back to a plain welcome-back than to name a non-topic.
    topic = ""
    for exchange in exchanges:
        if not exchange.startswith("Customer:"):
            continue
        candidate = exchange.split(":", 1)[1].strip()
        if _is_meaningful(candidate):
            topic = candidate
            break

    summary = "\n".join(recent)
    if len(summary) > MAX_CHARS:
        summary = summary[-MAX_CHARS:]

    return HydrateResponse(
        found=True,
        summary=summary,
        turn_count=int(conv.get("turn_count") or len(exchanges)),
        topic=topic[:160],
        reason="ok",
    )


@app.post("/hydrate", response_model=HydrateResponse)
def hydrate(req: HydrateRequest) -> HydrateResponse:
    """Return a digest of a prior conversation, or found=false if there is none.

    An empty conversation_id is the NORMAL no-history case (the CXAS variable
    defaults to empty), so it returns found=false rather than an error — the
    agent then just greets normally.
    """
    cid = (req.conversation_id or "").strip()
    if not cid:
        return HydrateResponse(found=False, summary="", turn_count=0,
                               reason="no_conversation_id")

    name = cid if cid.startswith("projects/") else f"{APP}/conversations/{cid}"
    try:
        conv = _client_once().get_conversation(request={"name": name})
        from google.cloud.ces_v1beta.types import Conversation
        data = Conversation.to_dict(conv)
        out = _condense(data)
        _log.info("hydrate ok conversation=%s turns=%s found=%s reason=%s",
                  cid, out.turn_count, out.found, out.reason)
        return out
    except Exception as e:
        # Every failure degrades to "no prior context" so the call still goes
        # through — but they are NOT the same problem, and reporting them
        # identically hides a broken deployment behind a plausible-looking
        # "this customer has no history".
        from google.api_core import exceptions as gexc

        if isinstance(e, (gexc.PermissionDenied, gexc.Forbidden, gexc.Unauthenticated)):
            # Configuration fault, not a data outcome. Loud, and named.
            _log.error(
                "hydrate PERMISSION DENIED reading conversation=%s as this service's "
                "runtime service account. get_conversation needs ces.conversations.get, "
                "which is in roles/ces.viewer (NOT roles/ces.client). Grant it: "
                "gcloud projects add-iam-policy-binding %s --member "
                "serviceAccount:<runtime-sa> --role roles/ces.viewer. Detail: %s",
                cid, PROJECT, str(e)[:200])
            reason = "permission_denied"
        elif isinstance(e, gexc.NotFound):
            # Normal: unknown id, or an id from a DIFFERENT app or project. This
            # service only ever looks under APP.
            _log.warning("hydrate miss conversation=%s not found under %s", cid, APP)
            reason = "not_found"
        else:
            _log.warning("hydrate error conversation=%s: %s: %s",
                         cid, type(e).__name__, str(e)[:200])
            reason = "error"

        return HydrateResponse(found=False, summary="", turn_count=0, reason=reason)


@app.get("/healthz")
def healthz():
    return {"ok": True, "app": APP}
