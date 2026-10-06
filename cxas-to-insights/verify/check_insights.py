"""Check where a conversation landed, end to end.

Reports three things:
  1. The app's logging settings (the gates that control whether anything is kept).
  2. The conversation in CES conversation history, with its `source`.
  3. The same conversation in Insights, fetched from the regional endpoint.

A CES conversation appears in Insights under the SAME id as the CES session, with
the full transcript, turn count, labels and analysis. If (3) is empty while (2)
shows a LIVE conversation, the cause is almost always the endpoint/location pair
— see README "Verify it worked".

Run:
    python verify/check_insights.py [SESSION_ID]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ces_client import (  # noqa: E402
    APP_ID, CES_ROOT, INSIGHTS_HOST, INSIGHTS_LOCATION, INSIGHTS_ROOT, PROJECT, call,
)


def main():
    wanted = sys.argv[1] if len(sys.argv) > 1 else None

    print("=" * 70)
    print("1. App logging gates")
    print("=" * 70)
    app = call("GET", f"{CES_ROOT}/apps/{APP_ID}")
    ls = app.get("loggingSettings") or {}
    cls = ls.get("conversationLoggingSettings") or {}
    mas = ls.get("metricAnalysisSettings") or {}
    print(f"  disableConversationLogging : {cls.get('disableConversationLogging', False)}"
          "   <- must be False/absent")
    print(f"  retentionWindow            : {cls.get('retentionWindow', '(default 365d)')}")
    print(f"  llmMetricsOptedOut         : {mas.get('llmMetricsOptedOut', False)}"
          "   <- must be False/absent for AI metrics")

    print()
    print("=" * 70)
    print("2. CES conversation history")
    print("=" * 70)
    r = call("GET", f"{CES_ROOT}/apps/{APP_ID}/conversations")
    convs = r.get("conversations", [])
    if not convs:
        print("  (none — a conversation is only written once the session completes)")
    for c in convs:
        cid = c.get("name", "").split("/")[-1]
        mark = " <-- " if wanted and cid == wanted else ""
        print(f"  {cid}  source={c.get('source')}  turns={c.get('turnCount')}  "
              f"deployment={(c.get('deployment') or 'none').split('/')[-1]}{mark}")
    live = [c for c in convs if c.get("source") == "LIVE"]
    print(f"\n  LIVE: {len(live)} of {len(convs)}. "
          "Only LIVE conversations are reported on by Insights.")

    print()
    print("=" * 70)
    print(f"3. Insights conversations ({INSIGHTS_HOST}, location={INSIGHTS_LOCATION})")
    print("=" * 70)
    ins = call("GET", f"{INSIGHTS_ROOT}/conversations?pageSize=50")
    if "__err" in ins:
        print(f"  HTTP {ins['__err']}: {ins['__body'][:220]}")
        if "Location Mismatch" in ins.get("__body", ""):
            print("\n  -> Endpoint/location mismatch. The host prefix must match the")
            print("     location in the path: us -> us-contactcenterinsights.googleapis.com.")
            print("     Only `global` is served by the unprefixed host.")
    else:
        found = ins.get("conversations", [])
        print(f"  {len(found)} conversation(s)")
        for c in found:
            cid = c.get("name", "").split("/")[-1]
            mark = " <-- " if wanted and cid == wanted else ""
            print(f"  {cid}  medium={c.get('medium')}  turns={c.get('turnCount')}  "
                  f"agentId={c.get('agentId')}{mark}")
        if wanted:
            hit = [c for c in found if c.get("name", "").endswith(f"/{wanted}")]
            print(f"\n  {wanted}: {'FOUND in Insights' if hit else 'not in Insights yet'}")
        if not found:
            print("  Empty. Check: source=LIVE above, correct location, and that the")
            print("  session has ended (ingestion lags the last turn).")

    print()
    print("=" * 70)
    print("4. The same view in the console")
    print("=" * 70)
    print(f"  https://ccai.cloud.google.com/insights/projects/{PROJECT}")
    print("  or: CX Agent Studio -> your app -> Monitor -> View Conversations")
    print("  Sign in as the account that holds the Insights role — a browser")
    print("  defaulting to a different Google account shows 'Access Denied'.")


if __name__ == "__main__":
    main()
