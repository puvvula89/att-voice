"""Spaced E2E probe of the steering tree. Waits for CES quota cooldown, then runs
one session with delays between turns to stay under the run_session rate limit.
Greeting (Concierge) -> upgrade (transfer to Sales Master) -> follow-up (ADK reply).
"""
import os, sys, time
from cxas_scrapi.core.sessions import Sessions

PROJECT = os.environ.get("CXAS_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("CXAS_LOCATION", "us")
APP_ID = os.environ.get("CXAS_APP_ID", "att-ivr-steering")
APP = f"projects/{PROJECT}/locations/{LOCATION}/apps/{APP_ID}"

def main():
    print("cooldown 180s for CES quota...", flush=True)
    time.sleep(180)
    s = Sessions(app_name=APP)
    sid = s.create_session_id()
    print("session:", sid, flush=True)

    def say(text, gap=20):
        for attempt in range(4):
            try:
                r = s.run(sid, text=text)
                out = s.get_agent_text_from_outputs(r.outputs)
                print(f"\nCALLER: {text}\nAGENT : {out!r}", flush=True)
                # trail: authors + tool calls to see transfers/tool use
                for o in getattr(r, "outputs", []):
                    au = getattr(o, "author", None) or getattr(o, "agent", None)
                    fc = getattr(o, "function_call", None)
                    if au or fc:
                        print("   trail:", au, fc and getattr(fc, "name", fc), flush=True)
                time.sleep(gap)
                return
            except Exception as e:
                if "RESOURCE_EXHAUSTED" in str(e) or "429" in str(e):
                    print(f"   429, backoff {30*(attempt+1)}s", flush=True)
                    time.sleep(30 * (attempt + 1))
                    continue
                raise
        print("   gave up after retries", flush=True)

    say("Hi")
    say("I want to upgrade my iPhone")
    say("What deals do you have on the iPhone 16?")
    say("Thanks, that's all")
    print("\nPROBE DONE", flush=True)

if __name__ == "__main__":
    main()
