# VM / New Machine Setup Guide

This guide covers deploying the project on:
- A brand-new laptop/desktop
- A cloud VM (AWS EC2, GCP Compute Engine, Azure VM, DigitalOcean, etc.)

It focuses on Docker-first deployment with reliable, repeatable steps.

---

## 1. Recommended Target Specs

Minimum:
- 4 vCPU
- 8 GB RAM
- 50 GB SSD

Recommended for smoother LLM + ingestion workloads:
- 8 vCPU
- 16 GB RAM
- 100+ GB SSD

OS:
- Ubuntu 22.04/24.04 LTS (recommended for cloud VM)
- macOS (for local machines)

---

## 2. Install Base Dependencies

## Ubuntu VM

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg git

# Docker Engine + Compose plugin
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo $VERSION_CODENAME) stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Optional: run docker without sudo
sudo usermod -aG docker $USER
newgrp docker
```

Verify:

```bash
docker --version
docker compose version
```

---

## 3. Clone and Configure Project

```bash
git clone <your-repo-url>
cd capstone
cp .env.example .env
```

Edit `.env` with required values:

```bash
LLM_API_KEY=sk-...
BASE_URL=https://openrouter.ai/api/v1
MODEL_CHOICE=qwen/qwen3-8b
POSTGRES_PASSWORD=use_a_strong_password
```

If using graph profile, also set:

```bash
NEO4J_PASSWORD=use_another_strong_password
```

---

## 4. Start Services

Core deployment:

```bash
docker compose up -d
```

Optional dev profile (Adminer):

```bash
docker compose --profile dev up -d
```

Optional graph profile:

```bash
docker compose -f docker-compose.yml -f docker-compose.graph.yml --profile graph up -d
```

Verify:

```bash
docker compose ps
docker compose logs --tail=100 agent
```

---

## 5. Networking and Security (Cloud VM)

For public deployment, expose only what you need.

Recommended inbound ports:
- `80/tcp` (HTTP)
- `443/tcp` (HTTPS)
- `22/tcp` (SSH, restricted by IP allowlist)

Avoid exposing directly to internet:
- PostgreSQL `5432`
- Redis `6379`
- MCP service ports
- Internal service-to-service ports

Because this stack fronts traffic through `frontend` (nginx), keeping only 80/443 open is usually enough.

---

## 6. Production Hardening Checklist

- Use strong, unique secrets in `.env`
- Keep `.env` out of git
- Restrict SSH to specific source IP ranges
- Enable automatic OS security updates
- Configure regular backups for PostgreSQL volume
- Add monitoring/alerting for container restarts and disk usage

Ubuntu basics:

```bash
sudo apt-get install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

---

## 7. Persisting Data on Separate Disk (Cloud VM)

If your VM has an attached data disk, mount it and place project data there.

Example mount path:

```bash
sudo mkdir -p /data/capstone
sudo chown -R $USER:$USER /data/capstone
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

Set in `.env`:

```bash
DATA_ROOT=/data/capstone
```

Run with override:

```bash
docker compose -f docker-compose.yml -f docker-compose.storage.yml up -d
```

---

## 8. Access Patterns

### Single VM, direct HTTP
- URL: `http://<vm-public-ip>`
- API docs: `http://<vm-public-ip>:8000/docs` (only if port opened)

### Preferred: reverse proxy + TLS
- Put Caddy/Nginx in front
- Serve HTTPS at your domain
- Forward app traffic to stack

If needed, add a dedicated reverse-proxy service and keep app services internal-only.

---

## 9. Operational Commands

Update code and redeploy:

```bash
git pull
docker compose build
docker compose up -d
```

View logs:

```bash
docker compose logs -f agent
docker compose logs -f frontend
docker compose logs -f postgres
```

Restart single service:

```bash
docker compose restart agent
```

Stop all:

```bash
docker compose down
```

---

## 10. Backup and Restore (VM)

Backup PostgreSQL volume:

```bash
mkdir -p backups

docker run --rm \
  -v capstone_pgdata:/source \
  -v "$PWD/backups:/backup" \
  alpine sh -c "cd /source && tar czf /backup/pgdata_$(date +%F).tar.gz ."
```

Restore:

```bash
docker compose down

docker run --rm \
  -v capstone_pgdata:/target \
  -v "$PWD/backups:/backup" \
  alpine sh -c "cd /target && rm -rf ./* && tar xzf /backup/pgdata_YYYY-MM-DD.tar.gz -C /target"

docker compose up -d
```

---

## 11. New Machine Migration Playbook

Use this flow when moving from old machine to new machine:

1. On old machine: create PostgreSQL (and optional Redis/Neo4j) backups.
2. Copy backup archives to new machine (scp/rsync/object storage).
3. On new machine: clone repo, set `.env`, start stack once, stop stack.
4. Restore backups into volumes.
5. Start stack and validate endpoints.

Validation commands:

```bash
docker compose ps
curl -s http://localhost:8000/docs > /dev/null && echo "API OK"
curl -s http://localhost:80 > /dev/null && echo "Frontend OK"
```

---

## 12. Common Cloud VM Issues

### Out of disk

```bash
df -h
docker system df
```

Cleanup unused Docker artifacts:

```bash
docker system prune -af
```

### Containers healthy but site not reachable

- Check cloud security group / firewall rules
- Confirm VM-level firewall (`ufw`) allows 80/443
- Verify service is bound and running via `docker compose ps`

### Slow startup after reboot

- Pull latest images and rebuild if needed
- Check VM CPU credits (burstable instance types)
- Verify attached disk is mounted before Docker starts
