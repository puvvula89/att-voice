# Static frontend for Cloud Run. Cloud Run terminates TLS at the edge, so the
# external URL is https (secure context → mic/getUserMedia works) while the
# container serves plain http on $PORT.
FROM python:3.12-slim
WORKDIR /app
COPY . /app
ENV PORT=8080
EXPOSE 8080
# Custom no-store server (NOT `python -m http.server`): the unversioned entry
# points (index.html/chat.html/config.js) must never be cached, or a redeploy
# won't take effect until a hard refresh. See serve.py.
CMD exec python serve.py
