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
