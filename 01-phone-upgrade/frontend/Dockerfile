# Static frontend for Cloud Run. Cloud Run terminates TLS at the edge, so the
# external URL is https (secure context → mic/getUserMedia works) while the
# container serves plain http on $PORT.
FROM python:3.12-slim
WORKDIR /app
COPY . /app
ENV PORT=8080
EXPOSE 8080
CMD exec python -m http.server $PORT
