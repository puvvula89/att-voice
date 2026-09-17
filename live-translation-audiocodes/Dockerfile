FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY bridge /app/bridge

ENV PORT=8080
EXPOSE 8080
CMD exec uvicorn bridge.server:app --host 0.0.0.0 --port $PORT
