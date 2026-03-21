FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install from pyproject.toml (includes fastmcp, aiohttp)
COPY pyproject.toml .
COPY aviation_weather_mcp_server/ aviation_weather_mcp_server/
RUN pip install --no-cache-dir .

EXPOSE 8001

ENV TRANSPORT_MODE=sse HOST=0.0.0.0 PORT=8001

CMD ["python", "-m", "aviation_weather_mcp_server"]
