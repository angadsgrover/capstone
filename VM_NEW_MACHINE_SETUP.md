# VM / New Machine Setup (Compatibility Guide)

This document is a compatibility wrapper.

The canonical cloud and new-machine deployment flow now lives at:
- [docs/CLOUD_DEPLOYMENT.md](./docs/CLOUD_DEPLOYMENT.md)

Use this page for a VM-focused fast path and links.

---

## Fast Path (Ubuntu VM)

```bash
# Install Docker + compose
sudo apt-get update && sudo apt-get install -y ca-certificates curl gnupg git
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker

# Deploy stack
git clone <your-repo-url>
cd capstone
cp .env.example .env
# Edit .env: LLM_API_KEY, BASE_URL, MODEL_CHOICE, POSTGRES_PASSWORD

docker compose up -d
```

---

## Canonical Sections

- Recommended specs: [docs/CLOUD_DEPLOYMENT.md](./docs/CLOUD_DEPLOYMENT.md#2-recommended-vm-specs)
- Host setup and firewall: [docs/CLOUD_DEPLOYMENT.md](./docs/CLOUD_DEPLOYMENT.md#3-host-setup-ubuntu)
- Deployment modes: [docs/CLOUD_DEPLOYMENT.md](./docs/CLOUD_DEPLOYMENT.md#5-compose-profiles-and-start-commands)
- Data disk strategy: [docs/CLOUD_DEPLOYMENT.md](./docs/CLOUD_DEPLOYMENT.md#7-data-placement-and-storage-migration)
- New machine migration: [docs/CLOUD_DEPLOYMENT.md](./docs/CLOUD_DEPLOYMENT.md#9-new-machine-migration-playbook)
- Troubleshooting: [docs/CLOUD_DEPLOYMENT.md](./docs/CLOUD_DEPLOYMENT.md#12-troubleshooting)

---

## Security Reminder

For public deployment, keep only 22, 80, and 443 publicly exposed.
Keep PostgreSQL, Redis, MCP ports, and internal service ports private.

Last updated: 2026-04-04
