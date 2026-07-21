# CXAS→ADK request/response adapter for Cloud Run.
# Built with its own context: `gcloud run deploy --source adapter`.
FROM python:3.12-slim

WORKDIR /app

COPY adapter-requirements.txt /app/adapter-requirements.txt
RUN pip install --no-cache-dir -r /app/adapter-requirements.txt

# The adapter package lives at /app/adapter (WORKDIR /app is on sys.path).
COPY __init__.py cxas_adapter.py flatten.py server.py /app/adapter/

ENV PORT=8080
EXPOSE 8080

# Shell form so $PORT (injected by Cloud Run) expands.
CMD exec uvicorn adapter.server:app --host 0.0.0.0 --port $PORT
