"""Run next_step locally against the catalog with stub get_variable/set_variable."""
import json, re, sys
src = open(sys.argv[1]).read()
code = re.search(r"NEXT_STEP = '''(.*?)'''", src, re.S).group(1).replace("\\\\n", "\\n")
store = {}
g = {"get_variable": store.get, "set_variable": store.__setitem__}
exec(code, g)
cat = {}
for d in ["iphone-13", "moto-g-2025"]:
    for t in json.load(open(f"knowledge/catalog/{d}.json"))["tutorials"]:
        cat[(d, t["id"])] = {"paths": t["paths"]}
def load(d, *ids):
    store["steps_by_id"] = json.dumps({i: cat[(d, i)] for i in ids})
ns = g["next_step"]
W = "156126-wi-fi-connection-issues-or-slowdowns"; P = "feature_power_on-powering-your-iphone-on-and-off"
load("iphone-13", W)
for _ in range(3): r = ns(W)
r = ns(W); print("4 first:", r)
r = ns(W, caller_confirmed=True); print("4 same call confirm (should warn again? warned==4 so passes):", {k: r[k] for k in r if k != "text"})
load("iphone-13", W, P)
r = ns(P); print("link step1:", {k: r.get(k) for k in ("step", "of", "heading", "needs_confirmation")})
while not r.get("finished"):
    r = ns(P, caller_confirmed=r.get("needs_confirmation", False))
    print("  link:", {k: r.get(k) for k in ("step", "heading", "needs_confirmation", "finished", "return_to")})
r = ns(W); print("back on main:", r.get("step"), r.get("heading"))
print("walk:", store["walk"])
M = "156118-can-t-make-or-receive-calls"
load("moto-g-2025", M); store.pop("walk")
r = {}
while not r.get("needs_choice"):
    r = ns(M); print("  moto:", r.get("step"), r.get("heading"), r.get("needs_choice"))
print("question:", r["question"], r["choices"])
r = ns(M, choice=r["choices"][-1]); print("after choice:", r.get("step"), r.get("heading"), r.get("of"))
