"""Minimal Agent Engine bidi app — feasibility spike.

Question it answers: does Agent Engine's bidirectional transport preserve a
NESTED structured dict (mimicking ADK `event.actions.state_delta.pending_ui`)
through `connection.receive()`, or flatten/stringify it (as the generic doc
example `{'bidiStreamOutput': {'output': '...'}}` suggests)?

If the nested `pending_ui` survives intact, the relay can keep driving the
on-screen UI when the agent runs on Agent Engine (Topology B is viable).
"""
import asyncio
from typing import Any, AsyncIterable


class SpikeBidiApp:
    def set_up(self) -> None:
        pass

    def register_operations(self):
        # Bidi ops require EXPERIMENTAL server mode at deploy time.
        return {"bidi_stream": ["bidi_stream_query"]}

    async def bidi_stream_query(
        self, request_queue: "asyncio.Queue[Any]"
    ) -> AsyncIterable[Any]:
        while True:
            req = await request_queue.get()
            if req == "END":
                break
            # Mimic an ADK event carrying a UI state delta.
            yield {
                "marker": "SPIKE_OK",
                "echo": req,
                "actions": {
                    "state_delta": {
                        "pending_ui": {
                            "stage_intent": "demo",
                            "title": "Spike",
                            "options": [
                                {"id": "a", "label": "A"},
                                {"id": "b", "label": "B"},
                            ],
                        }
                    }
                },
            }
            yield {"turn_complete": True, "_end": True}
