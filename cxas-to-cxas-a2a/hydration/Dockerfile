# Private Cloud Run service invoked by the CES service agent over OIDC.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app
ENV PORT=8080
EXPOSE 8080
# Single worker: the gRPC client is built at import so the warm instance pays
# channel setup during startup CPU boost, not on the caller's first turn.
CMD exec uvicorn server:app --host 0.0.0.0 --port $PORT --workers 1
