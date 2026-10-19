FROM python:3.12-slim
WORKDIR /app
COPY support_mcp/requirements.txt support_mcp/requirements.txt
RUN pip install --no-cache-dir -r support_mcp/requirements.txt
COPY support_mcp/ support_mcp/
COPY knowledge/__init__.py knowledge/catalog.py knowledge/steps.py knowledge/content_store.py knowledge/
ENV PORT=8080
CMD ["sh", "-c", "uvicorn support_mcp.server:app --host 0.0.0.0 --port ${PORT}"]
