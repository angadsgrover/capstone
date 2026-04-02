# Cloud Deployment Guide

Complete guide for deploying to Azure VM, DigitalOcean, or any Linux VM.

---

## Quick Start (TL;DR)

```bash
# On your VM (Ubuntu 22.04/24.04)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker
# OR install Podman: sudo apt-get install -y podman podman-compose

git clone <your-repo>
cd capstone
cp .env.example .env
# Edit .env with your API keys

# Development (HTTP only)
docker compose up -d

# Production (HTTPS with auto-cert)
echo "DOMAIN=your-domain.com" >> .env
docker compose -f docker-compose.yml -f docker-compose.caddy.yml up -d
```

---

### Podman-compatible commands

All compose workflows in this repo work with either engine:

```bash
# Docker
docker compose up -d

# Podman
podman compose up -d
```

`start.py --docker` already auto-detects Docker/Podman. Makefile targets also auto-detect and use the available engine.

---

## 1. Platform Comparison

| Feature | Azure VM | DigitalOcean Droplet | 
|---------|----------|---------------------|
| **Min Cost** | ~$15/mo (B2s) | $12/mo (Basic 2GB) |
| **Recommended** | Standard_D2s_v3 ($70/mo) | Premium Intel 4GB ($24/mo) |
| **Secret Management** | Azure Key Vault | DO Encrypted Secrets |
| **Managed DB Option** | Azure PostgreSQL Flexible | DO Managed PostgreSQL |
| **Networking** | NSG (complex) | Firewall (simple) |
| **Best For** | Enterprise/AD integration | Simplicity/cost |

### Recommended VM Specs

| Workload | vCPUs | RAM | Storage |
|----------|-------|-----|---------|
| Dev/Demo | 2 | 4GB | 50GB SSD |
| Production | 4 | 8GB | 100GB SSD |
| High Traffic | 8 | 16GB | 200GB SSD |

---

## 2. Initial VM Setup

### 2.1 Install Docker (Ubuntu)

```bash
# Update and install prerequisites
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg git

# Add Docker GPG key and repository
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Run Docker without sudo
sudo usermod -aG docker $USER
newgrp docker

# Verify
docker --version
docker compose version
```

### 2.2 Configure Firewall

```bash
# Ubuntu UFW
sudo ufw allow 22/tcp   # SSH
sudo ufw allow 80/tcp   # HTTP
sudo ufw allow 443/tcp  # HTTPS
sudo ufw enable

# Azure: Also configure Network Security Group (NSG)
# DigitalOcean: Also configure Cloud Firewall
```

---

## 3. Deployment Options

### Option A: Direct Docker Compose (Recommended for simplicity)

**Pros**: Full control, no extra overhead, easy debugging
**Cons**: Manual SSL setup, no GUI

```bash
# Clone and configure
git clone <your-repo>
cd capstone
cp .env.example .env
nano .env  # Set your secrets

# Start (development, HTTP only)
docker compose up -d

# Start (production, with HTTPS)
# First, set DOMAIN in .env
docker compose -f docker-compose.yml -f docker-compose.caddy.yml up -d

# View logs
docker compose logs -f

# Update deployment
git pull
docker compose build
docker compose up -d
```

### Option B: Dokploy (Recommended for GUI management)

[Dokploy](https://dokploy.com) is a free, open-source Vercel/Netlify alternative.

**Pros**: Nice GUI, auto-SSL, webhooks, multiple projects
**Cons**: Extra resource usage (~300MB RAM)

```bash
# Install Dokploy (one-liner)
curl -sSL https://dokploy.com/install.sh | sh

# Access at http://your-ip:3000
# Create project, add your repo, configure env vars in UI
```

### Option C: Coolify

Similar to Dokploy but more feature-rich (and heavier).

```bash
curl -fsSL https://cdn.coollabs.io/coolify/install.sh | bash
# Access at http://your-ip:8000
```

### Comparison

| Feature | Direct Docker | Dokploy | Coolify |
|---------|---------------|---------|---------|
| Resource Usage | Minimal | ~300MB | ~500MB |
| Setup Time | 5 min | 10 min | 15 min |
| Auto SSL | Via Caddy overlay | ✅ Built-in | ✅ Built-in |
| GUI Dashboard | ❌ | ✅ | ✅ |
| Git Webhooks | Manual | ✅ | ✅ |
| Learning Curve | Low | Low | Medium |
| **Recommendation** | Small teams | Most users | Power users |

---

## 4. Secret Management

### Level 1: `.env` File (Development/Small Deployments)

```bash
# Create .env from template
cp .env.example .env
chmod 600 .env  # Restrict permissions

# Never commit .env to git (already in .gitignore)
```

### Level 2: Cloud Provider Secrets

**Azure Key Vault:**
```bash
# Create Key Vault
az keyvault create --name aviation-kv --resource-group aviation-rg

# Store secrets
az keyvault secret set --vault-name aviation-kv --name LLM-API-KEY --value "sk-..."

# Retrieve in deployment script
export LLM_API_KEY=$(az keyvault secret show --vault-name aviation-kv --name LLM-API-KEY --query value -o tsv)
```

**DigitalOcean Encrypted Environment:**
```bash
# In App Platform or via doctl
doctl apps create-deployment <app-id> --env LLM_API_KEY=sk-...
```

### Level 3: HashiCorp Vault (Enterprise)

```bash
# Install Vault
# ...
# Store secrets
vault kv put secret/aviation LLM_API_KEY="sk-..." POSTGRES_PASSWORD="..."

# Retrieve
export LLM_API_KEY=$(vault kv get -field=LLM_API_KEY secret/aviation)
```

### Level 4: SOPS with age (GitOps-friendly)

```bash
# Install age and sops
brew install age sops  # or apt-get

# Generate key
age-keygen -o ~/.config/sops/age/keys.txt

# Encrypt .env
sops --encrypt --age $(cat ~/.config/sops/age/keys.txt | grep public | cut -d: -f2) .env > .env.enc

# Decrypt on server
sops --decrypt .env.enc > .env
```

---

## 5. Production Checklist

### Security
- [ ] Strong, unique passwords (POSTGRES_PASSWORD, NEO4J_PASSWORD)
- [ ] `.env` has `chmod 600` and is in `.gitignore`
- [ ] SSH restricted to specific IPs
- [ ] Only ports 80, 443, 22 exposed
- [ ] Auto security updates enabled

### Performance
- [ ] Using production compose overlay (`docker-compose.prod.yml`)
- [ ] Resource limits configured
- [ ] Log rotation enabled (json-file driver with max-size)

### Reliability
- [ ] Container restart policies (`restart: unless-stopped` or `always`)
- [ ] Health checks configured
- [ ] Automated backups for PostgreSQL volume

### Monitoring
- [ ] LangSmith tracing enabled
- [ ] Container logs accessible
- [ ] Disk space monitoring

---

## 6. Quick Commands Reference

```bash
# Start production stack
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Start with HTTPS
docker compose -f docker-compose.yml -f docker-compose.caddy.yml up -d

# Start full stack (all options)
docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.caddy.yml up -d

# View all logs
docker compose logs -f

# View specific service
docker compose logs -f agent

# Check health
docker compose ps
curl -s http://localhost/api/health | jq

# Restart single service
docker compose restart agent

# Update and redeploy
git pull
docker compose build
docker compose up -d

# Backup PostgreSQL
docker run --rm -v capstone_pgdata:/src -v $(pwd)/backups:/dest alpine tar czf /dest/pgdata-$(date +%F).tar.gz -C /src .

# Clean up old images
docker system prune -af
```

---

## 7. Troubleshooting

### Container won't start
```bash
docker compose logs <service-name>
docker compose ps
```

### Can't reach from internet
1. Check cloud firewall/security group
2. Check VM firewall: `sudo ufw status`
3. Verify service is running: `docker compose ps`

### SSL certificate issues (Caddy)
1. Verify domain DNS points to server IP
2. Check Caddy logs: `docker compose logs caddy`
3. Ensure ports 80 and 443 are open

### Out of disk space
```bash
df -h
docker system df
docker system prune -af  # Remove unused images
```

---

## 8. Cost Optimization Tips

1. **Start small**: 2 vCPU / 4GB RAM is enough for dev/demo
2. **Reserved instances**: Save 30-60% on Azure/DigitalOcean
3. **Managed PostgreSQL**: Consider only for production (adds $15-30/mo)
4. **Spot/Preemptible**: Not recommended for this stack (stateful)
5. **CDN**: Add Cloudflare (free tier) for static assets
