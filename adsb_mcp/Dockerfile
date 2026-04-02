FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# Install from pyproject.toml (includes fastmcp, httpx, beautifulsoup4)
COPY pyproject.toml .
COPY adsb_mcp_server/ adsb_mcp_server/
RUN pip install --no-cache-dir .

EXPOSE 8003

ENV TRANSPORT_MODE=sse HOST=0.0.0.0 PORT=8003

# Health check for production
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:8003/sse || exit 1

CMD ["python", "-m", "adsb_mcp_server"]
