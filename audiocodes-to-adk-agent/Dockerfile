# FastAPI WebSocket steering relay for Cloud Run.
# Proxies the caller channel to ADK agents (Agent Engine) and CES billing,
# running the greeter + intent-driven steering loop.
FROM python:3.12-slim

WORKDIR /app

COPY relay-requirements.txt /app/relay-requirements.txt
RUN pip install --no-cache-dir -r /app/relay-requirements.txt

# The relay imports both packages (relay.server -> relay.* -> agents.registry).
COPY relay /app/relay
COPY agents /app/agents

ENV PORT=8080
EXPOSE 8080

# Shell form so $PORT (injected by Cloud Run) expands.
CMD exec uvicorn relay.server:app --host 0.0.0.0 --port $PORT
