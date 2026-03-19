FROM python:3.12-slim

WORKDIR /app

# Install system deps for asyncpg + psycopg2 builds
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Strip local editable installs that only exist in the dev venv;
# the agent connects to MCP servers via SSE in Docker, no local import needed.
RUN sed '/aviation_weather_mcp_server\|hk_climate_mcp_server/d' requirements.txt \
    > requirements.docker.txt \
    && pip install --no-cache-dir -r requirements.docker.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
