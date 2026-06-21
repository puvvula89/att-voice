import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv
load_dotenv()

import asyncio

from google.adk.sessions import InMemorySessionService
from google.genai import types

from agents.greeter import greeter_agent
from relay.agent_channels import AdkLiveSession
from relay.call_session import SessionRecord


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
