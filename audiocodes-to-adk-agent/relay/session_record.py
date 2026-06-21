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
