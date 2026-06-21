# att-voice

A voice-agent reference project built on Google ADK and the Gemini Live API. It demonstrates
how to run natural, low-latency voice agents that drive a live web UI on the **same stream** —
no second LLM and no orchestration hop. The repo is organized as one numbered folder per use
case, each independently runnable. One section per folder below.

## shared-session-voice-and-chat

A phone-upgrade agent in two channels (**voice** and **chat**) that share one session.

- **Voice + chat** — speak naturally or type; the voice agent always replies in native audio, the chat channel answers in text.
- **Shared flow** — both channels drive the same on-screen steps: line picker → phone options → confirmation → receipt.
- **Dual input** — advance by voice, by typing, or by clicking the cards.
- **Deterministic UI** — the model picks when and which template to render via a `render_component` tool call; a formatter fills it from session state, so the model never hand-writes UI.
- **MCP data** — account, lines, phones, pricing, and order data served over MCP.
- **Local or cloud** — runs locally (relay in-process) or on the cloud (Agent Engine + Cloud Run).

See [`shared-session-voice-and-chat/README.md`](shared-session-voice-and-chat/README.md) for setup, architecture, and deploy.
