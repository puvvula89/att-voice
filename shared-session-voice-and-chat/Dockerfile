# FastAPI WebSocket relay for Cloud Run (Agent Engine proxy mode).
FROM python:3.12-slim

WORKDIR /app

COPY relay-requirements.txt /app/relay-requirements.txt
RUN pip install --no-cache-dir -r /app/relay-requirements.txt

COPY backend /app/backend

ENV PORT=8080
EXPOSE 8080

# Shell form so $PORT (injected by Cloud Run) expands.
CMD exec uvicorn backend.server:app --host 0.0.0.0 --port $PORT
