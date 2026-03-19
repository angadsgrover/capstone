FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8001

ENV TRANSPORT_MODE=sse HOST=0.0.0.0 PORT=8001

CMD ["python", "-m", "aviation_weather_mcp_server"]
