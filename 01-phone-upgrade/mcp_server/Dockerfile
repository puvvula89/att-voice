# MCP data-tool server for Cloud Run. Build context = this directory
# (mcp_server/), so the package is copied to /app/mcp_server and runs as a
# module: `python -m mcp_server.server`.
FROM python:3.12-slim

WORKDIR /app

# Install deps first for layer caching.
COPY requirements.txt /app/mcp_server/requirements.txt
RUN pip install --no-cache-dir -r /app/mcp_server/requirements.txt

# Copy the package.
COPY . /app/mcp_server/

# Cloud Run injects $PORT (8080); server.py reads it and binds 0.0.0.0.
ENV PORT=8080
EXPOSE 8080

CMD ["python", "-m", "mcp_server.server"]
