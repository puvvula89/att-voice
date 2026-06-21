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
