# Container for the RELAY (the websocket bridge in backend/relay.py).
#
# Two Dockerfiles live in this bundle, and which one gets used is decided by the
# build context passed to `gcloud run deploy --source`:
#   * THIS file, at the bundle root  -> the relay        (deploy --source .)
#   * frontend/Dockerfile            -> the static UI    (deploy --source frontend)
# It sits at the root because it needs BOTH backend/ and relay-requirements.txt,
# and a build context cannot reach above itself.
#
# Auth: the relay mints an ADC access token for the CXAS websocket, so on Cloud
# Run it authenticates as the runtime service account — no key material, nothing
# baked into the image. That account needs CXAS access on the app.
FROM python:3.12-slim
WORKDIR /app

COPY relay-requirements.txt /app/relay-requirements.txt
RUN pip install --no-cache-dir -r relay-requirements.txt

COPY backend /app/backend

ENV PORT=8080
EXPOSE 8080
# One worker: sessions are held in memory per connection, so a second worker
# would strand browsers on whichever process did not accept their socket.
CMD exec uvicorn backend.relay:app --host 0.0.0.0 --port $PORT --workers 1
