"""Local check: every step checkpoints; may_drop saves silently, drops still warns."""
import json, re, sys
code = re.search(r"NEXT_STEP = '''(.*?)'''", open(sys.argv[1]).read(), re.S).group(1).replace("\\\\n", "\\n")
store = {}; g = {"get_variable": store.get, "set_variable": store.__setitem__}; exec(code, g); ns = g["next_step"]
c = json.load(open(sys.argv[2]))
t = next(t for t in c["tutorials"] if t["title"] == "Troubleshooting why Wi-Fi calling isn't working")
store["steps_by_id"] = json.dumps({t["id"]: {"paths": t["paths"]}})
for i in range(6):
    r = ns(t["id"], caller_confirmed=True)
    print(r.get("step"), r.get("heading") or r["text"][:40] if "text" in r else "", "| warn" if r.get("needs_confirmation") else "",
          "| resume", json.loads(store["walk"]).get("resume"))
