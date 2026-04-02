FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# Install from pyproject.toml (includes fastmcp, aiohttp)
COPY pyproject.toml .
COPY hk_climate_mcp_server/ hk_climate_mcp_server/
RUN pip install --no-cache-dir .

EXPOSE 8002

ENV TRANSPORT_MODE=sse HOST=0.0.0.0 PORT=8002

# Health check for production
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:8002/sse || exit 1

CMD ["python", "-m", "hk_climate_mcp_server"]
