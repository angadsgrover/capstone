# Cloud Deployment Guide (Canonical)

This is the single source of truth for Docker/Podman deployment on cloud VMs and new machines.

Legacy wrapper docs:
- [DOCKER_SETUP.md](../DOCKER_SETUP.md)
- [VM_NEW_MACHINE_SETUP.md](../VM_NEW_MACHINE_SETUP.md)

---

## Quick Start (TL;DR)

```bash
# Ubuntu 22.04/24.04
sudo apt-get update && sudo apt-get install -y ca-certificates curl gnupg git
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker

# Project setup
git clone <your-repo-url>
cd capstone
cp .env.example .env
# Edit .env: LLM_API_KEY, BASE_URL, MODEL_CHOICE, POSTGRES_PASSWORD

# Start core stack
docker compose up -d

# Optional HTTPS with Caddy overlay (set DOMAIN in .env first)
docker compose -f docker-compose.yml -f docker-compose.caddy.yml up -d
```

---

## 1. Scope and Runtime

Supported runtimes:
- Docker Compose v2 (`docker compose`)
- Podman Compose (`podman compose`)

If you use Podman, replace `docker compose` with `podman compose` in examples below.

---

## 2. Recommended VM Specs

| Workload | vCPU | RAM | Storage |
| --- | --- | --- | --- |
| Dev or demo | 2 | 4 GB | 50 GB SSD |
| Production | 4 | 8 GB | 100 GB SSD |
| High traffic | 8 | 16 GB | 200 GB SSD |

OS recommendations:
- Ubuntu 22.04/24.04 LTS for cloud VMs
- macOS or Linux for local machines

---

## 3. Host Setup (Ubuntu)

### 3.1 Install container engine

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg git

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

sudo usermod -aG docker $USER
newgrp docker

docker --version
docker compose version
```

### 3.2 Baseline firewall

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

Also configure your cloud firewall/security group accordingly.

---

## 4. Project Configuration

```bash
git clone <your-repo-url>
cd capstone
cp .env.example .env
```

Minimum required `.env` values:

```bash
LLM_API_KEY=sk-...
BASE_URL=https://openrouter.ai/api/v1
MODEL_CHOICE=qwen/qwen3-8b
POSTGRES_PASSWORD=change_to_a_strong_password
```

Common optional values:

```bash
# Auth and CORS hardening
CORS_ALLOW_ORIGINS=https://your-frontend.example.com
REQUIRE_AUTH_SUBJECT=true
AUTH_VERIFICATION_MODE=jwt
JWT_JWKS_URL=https://your-idp.example.com/.well-known/jwks.json
JWT_ISSUER=https://your-idp.example.com/
JWT_AUDIENCE=capstone-agent-api

# Request guards
MAX_REQUEST_BYTES=1048576
MAX_INPUT_CHARS=12000

# Optional graph profile
NEO4J_PASSWORD=change_to_a_strong_neo4j_password

# Optional memory/tracing
MEM0_LONG_TERM_ENABLED=true
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=ls-...
```

---

## 5. Compose Profiles and Start Commands

### 5.1 Core stack (default)

```bash
docker compose up -d
```

### 5.2 Development extras (Adminer)

```bash
docker compose --profile dev up -d
```

### 5.3 HTTPS overlay with Caddy

```bash
# Set DOMAIN in .env first
docker compose -f docker-compose.yml -f docker-compose.caddy.yml up -d
```

### 5.4 AGE + Neo4j graph profile

```bash
# First build AGE-enabled postgres image
docker compose -f docker-compose.yml -f docker-compose.graph.yml build postgres

# Start with graph overlay
docker compose -f docker-compose.yml -f docker-compose.graph.yml --profile graph up -d
```

---

## 6. Verify Deployment

```bash
docker compose ps
docker compose logs --tail=200 agent
```

Expected URLs:
- Frontend: `http://localhost:80`
- API docs: `http://localhost:8000/docs`
- Adminer (dev profile): `http://localhost:8080`
- Neo4j Browser (graph profile): `http://localhost:7474`

---

## 7. Data Placement and Storage Migration

### Option A (macOS easiest): move Docker Desktop disk image

Use Docker Desktop settings to move the disk image to external storage.

Pros:
- zero compose changes
- applies to all containers

Cons:
- moves all Docker workloads

### Option B (per-project): storage override file

Create host directories:

```bash
mkdir -p /data/capstone/postgres /data/capstone/redis /data/capstone/neo4j
```

Create `docker-compose.storage.yml`:

```yaml
services:
  postgres:
    volumes:
      - ${DATA_ROOT}/postgres:/var/lib/postgresql/data
      - ./infra/init.sql:/docker-entrypoint-initdb.d/init.sql

  redis:
    volumes:
      - ${DATA_ROOT}/redis:/data

  neo4j:
    volumes:
      - ${DATA_ROOT}/neo4j:/data
```

Set `.env`:

```bash
DATA_ROOT=/data/capstone
```

Start with override:

```bash
docker compose -f docker-compose.yml -f docker-compose.storage.yml up -d
```

### One-time migration from named volumes

```bash
docker compose down

docker run --rm -v capstone_pgdata:/from -v /data/capstone/postgres:/to alpine sh -c "cd /from && cp -av . /to"
docker run --rm -v capstone_redisdata:/from -v /data/capstone/redis:/to alpine sh -c "cd /from && cp -av . /to"
docker run --rm -v capstone_neo4jdata:/from -v /data/capstone/neo4j:/to alpine sh -c "cd /from && cp -av . /to"

docker compose -f docker-compose.yml -f docker-compose.storage.yml up -d
```

---

## 8. Backup and Restore

### Backup PostgreSQL volume

```bash
mkdir -p backups

docker run --rm \
  -v capstone_pgdata:/source \
  -v "$PWD/backups:/backup" \
  alpine sh -c "cd /source && tar czf /backup/pgdata_$(date +%F).tar.gz ."
```

Optional Redis backup:

```bash
docker run --rm \
  -v capstone_redisdata:/source \
  -v "$PWD/backups:/backup" \
  alpine sh -c "cd /source && tar czf /backup/redisdata_$(date +%F).tar.gz ."
```

### Restore PostgreSQL volume

```bash
docker compose down

docker run --rm \
  -v capstone_pgdata:/target \
  -v "$PWD/backups:/backup" \
  alpine sh -c "cd /target && rm -rf ./* && tar xzf /backup/pgdata_YYYY-MM-DD.tar.gz -C /target"

docker compose up -d
```

---

## 9. New Machine Migration Playbook

1. On old machine, create database backups.
2. Transfer backups to new machine.
3. On new machine, run Sections 3-5 once.
4. Stop stack, restore backups, restart stack.
5. Validate health endpoints.

Validation:

```bash
docker compose ps
curl -s http://localhost:8000/docs > /dev/null && echo "API OK"
curl -s http://localhost:80 > /dev/null && echo "Frontend OK"
```

---

## 10. Day-2 Operations

```bash
# Start / stop
docker compose up -d
docker compose down

# Logs
docker compose logs -f agent
docker compose logs -f frontend
docker compose logs -f postgres

# Rebuild/redeploy
git pull
docker compose build
docker compose up -d

# Restart one service
docker compose restart agent
```

---

## 11. Production Hardening Checklist

- Use strong unique secrets (`POSTGRES_PASSWORD`, `NEO4J_PASSWORD`, API keys)
- Keep `.env` private (`chmod 600 .env`)
- Restrict SSH source IPs
- Expose only ports 22, 80, 443 publicly
- Keep DB/Redis/internal MCP ports private
- Enable automatic OS security updates
- Monitor disk usage and container restart loops

---

## 12. Troubleshooting

### Stack starts but service is unreachable

1. Check cloud firewall/security group.
2. Check UFW status (`sudo ufw status`).
3. Confirm containers are healthy (`docker compose ps`).

### Containers restart repeatedly

```bash
docker compose ps
docker compose logs --tail=200 agent
docker compose logs --tail=200 postgres
```

### Disk pressure

```bash
df -h
docker system df
docker system prune -af
```

### Caddy HTTPS issues

1. Verify DNS points to VM public IP.
2. Check caddy logs (`docker compose logs caddy`).
3. Ensure ports 80 and 443 are open.

---

Last updated: 2026-04-04
