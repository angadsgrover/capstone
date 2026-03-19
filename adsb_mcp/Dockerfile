FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY server.py db.py ./
COPY tools/ tools/

RUN pip install --no-cache-dir fastmcp>=2.10.2 httpx>=0.27.0 beautifulsoup4>=4.12.0

EXPOSE 8003

ENV TRANSPORT_MODE=sse HOST=0.0.0.0 PORT=8003

CMD ["python", "server.py", "--sse", "--host", "0.0.0.0", "--port", "8003"]
