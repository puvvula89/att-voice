"""Text-driven conversation smoke for the ADK agents (greeter + specialists).

Drives an agent's Live session with TYPED turns instead of audio and reads back
the agent's transcribed replies + tool events (intent / end). This exercises the
real agent definitions (prompts, tools, callbacks) deterministically — no browser,
no audio files — so classification, confirm-before-switch, and teardown sequencing
can be verified and iterated on quickly.

NOTE: input is text but the native-audio model still replies in audio; we read the
output transcription for its words. Turn-taking over text is cleaner than over
audio, so this validates conversation LOGIC; audio turn-timing still needs a voice
check.

Run from the module root:  python tests/smoke/smoke_conversation.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv
load_dotenv()

import asyncio

from google.adk.sessions import InMemorySessionService
from google.genai import types

from relay.agent_channels import AdkLiveSession
from relay.call_session import SessionRecord
from agents.registry import ADK_AGENTS


class Driver:
    """Drives one agent over run_live with scripted text turns."""

    def __init__(self, agent, session_service):
        self.sess = AdkLiveSession(agent, session_service)
        self.agent_final = []   # final agent utterances, in order
        self._agent_buf = ""
        self.intents = []       # intents emitted (classify_intent)
        self.tool_end = False   # end_call fired
        self.ended = False
        self._task = None

    async def open(self, record):
        await self.sess.open(record)
        self._task = asyncio.create_task(self._drain())

    async def _drain(self):
        async for ev in self.sess.events():
            n = type(ev).__name__
            if n == "AgentTranscript" and ev.role == "agent":
                if ev.final:
                    self.agent_final.append(ev.text)
                    self._agent_buf = ""
                else:
                    self._agent_buf += ev.text
            elif n == "AgentIntent":
                self.intents.append(ev.intent)
            elif n == "AgentEnd":
                self.ended = True
                break

    async def say(self, text, settle=9.0):
        """Send a user turn (None = just read the opening); return the agent's reply
        text plus any intent/end_call that fired DURING this turn."""
        n_final = len(self.agent_final)
        n_intent = len(self.intents)
        end_before = self.tool_end_seen()
        if text is not None:
            self.sess._queue.send_content(
                types.Content(role="user", parts=[types.Part(text=text)])
            )
        # Wait for a new final agent utterance (or end) to land, then a beat for
        # any trailing tool event in the same turn.
        deadline = settle
        step = 0.25
        while deadline > 0:
            if len(self.agent_final) > n_final or self.ended:
                break
            await asyncio.sleep(step)
            deadline -= step
        await asyncio.sleep(1.0)  # let a same-turn tool event arrive
        reply = " ".join(self.agent_final[n_final:]) or self._agent_buf
        new_intent = self.intents[n_intent:]
        return {
            "reply": reply.strip(),
            "intent": new_intent[-1] if new_intent else None,
            "ended": self.ended,
        }

    def tool_end_seen(self):
        return self.ended

    async def close(self):
        await self.sess.close()
        if self._task:
            self._task.cancel()


def show(turn, user, res):
    print(f"\n[{turn}] USER: {user if user is not None else '(call opens)'}")
    print(f"     AGENT: {res['reply'] or '(no words)'}")
    flags = []
    if res["intent"]:
        flags.append(f"classify_intent={res['intent']}")
    if res["ended"]:
        flags.append("END_CALL FIRED")
    if flags:
        print(f"     >>> {'  '.join(flags)}")


async def scenario_greeter():
    print("=" * 70)
    print("SCENARIO 1 — Greeter: vague input must NOT classify until confirmed")
    print("=" * 70)
    d = Driver(ADK_AGENTS["greeter"], InMemorySessionService())
    await d.open(SessionRecord(session_id=None, caller="texttest"))
    show("open", None, await d.say(None))                       # greeting
    show("u1", "I need to troubleshoot something",
         await d.say("I need to troubleshoot something"))        # expect: a question, NO intent
    show("u2", "my wifi keeps dropping",
         await d.say("my wifi keeps dropping"))                  # expect: a CONFIRM question, NO intent
    show("u3", "yes that's right",
         await d.say("yes that's right"))                        # expect: classify_intent=internet
    print("\nCHECK: intent should appear ONLY at u3 (after confirmation).")
    print("intents seen, in order:", d.intents)
    await d.close()


async def scenario_specialist_close():
    print("\n" + "=" * 70)
    print("SCENARIO 2 — Internet specialist: must NOT end_call before caller answers")
    print("=" * 70)
    d = Driver(ADK_AGENTS["internet"], InMemorySessionService())
    await d.open(SessionRecord(session_id=None, caller="texttest"))
    show("open", None, await d.say(None))                       # handoff opener (acknowledges issue)
    show("u1", "the modem light is off",
         await d.say("the modem light is off"))
    show("u2", "I unplugged it and it's back online now",
         await d.say("I unplugged it and it's back online now"))  # likely triggers "anything else?"
    print("\n     ^ if END_CALL FIRED here (before the caller declined), that's the premature bug.")
    show("u3", "no, that's all",
         await d.say("no, that's all"))                          # expect: closing line + END_CALL
    print("\nCHECK: end_call should fire ONLY at u3, with the closing line.")
    await d.close()


async def main():
    await scenario_greeter()
    await scenario_specialist_close()


asyncio.run(main())
