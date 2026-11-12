FROM python:3.12-slim
WORKDIR /app
COPY server.py index.html ./
COPY assets ./assets
ENV PORT=8080
CMD ["python", "server.py"]
