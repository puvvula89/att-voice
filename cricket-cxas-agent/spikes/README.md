# Spikes

Throwaway experiments that settled design questions. Nothing in `deploy/` or `bootstrap/` imports them.
Each script reads project settings from the `.env` passed on its command line and creates its own
`spike-*` resources; delete those when done.

## s1_mcp_auth

The platform calls a private Cloud Run MCP server with its service agent's ID token. No proxy is needed.

## s2_agent_search_walk

Find a tutorial with Agent Search, then walk it inside the agent.

| Script | Question | Result |
|---|---|---|
| `filters.py` | Does Agent Search find the right tutorial from title, summary and symptoms alone? | Top-1 38/42, top-3 41/42 with a device filter (local keyword search: 25/42, 32/42). Indexing the step text added nothing. |
| `tool_run.py`, `set_filter.py`, `one.py` | Do the same phrases work through the agent's data store tool, with its query rewriting? | Top-1 37/42, top-3 42/42. The device filter works when `device` is a declared app variable and the instruction says `device: ANY("{device}")`. |
| `guard.py` | Can an after-tool callback drop results for other phones and hide the step payload from the model? | Yes. Returning `{"answer": ...}` replaces what the model sees. It runs for every tool, so it returns None for anything else. |
| `walk.py`, `local_walk.py` | Can a Python tool walk the tutorial one step at a time, with branches, linked how-tos and a confirmation before call-ending steps? | Yes. Only a clear yes passes the call-ending gate. Records must be zlib-compressed: the tool silently drops results of about 16 KB. |
| `hydrate.py` | Does a new call resume from the dropped call's saved place? | Yes, when `walk` and `steps_by_id` are declared app variables. A tool cannot read undeclared variables sent at session start. |
| `local_risk.py` | Does a "might drop" step save the place without asking? | Yes. "Drops" and "might drop" steps save the place first; only "drops" steps ask the caller. Safe steps are not saved. |

Run order: `filters.py create`, `tool_run.py app`, `guard.py install`, `walk.py install`, `hydrate.py install`, then
the `run` commands. Clean up with `tool_run.py cleanup` and `filters.py cleanup`.

## s3_session_id

`probe.py`: can a callback see the current session id? Yes: `callback_context.session_id`.

The design that used it was dropped. A dropped call's conversation record proved too unreliable to resume from: one record held 2 of its 7 turns and never filled in.

## s4_mcp_args

`inject.py`: does a before-tool callback's change to an MCP tool's input reach the server? Yes.

That is how `save_progress` gets the caller's place without the model copying it.
