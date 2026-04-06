# Docker Setup and Operations (Compatibility Guide)

This document is a compatibility wrapper.

The canonical deployment guide now lives at:
- [docs/CLOUD_DEPLOYMENT.md](./docs/CLOUD_DEPLOYMENT.md)

Use this page for quick Docker-focused jump links.

---

## Quick Commands

```bash
# Start core stack
docker compose up -d

# Start with dev profile (Adminer)
docker compose --profile dev up -d

# Start with HTTPS overlay
docker compose -f docker-compose.yml -f docker-compose.caddy.yml up -d

# Start with graph overlay
# (build AGE image once first)
docker compose -f docker-compose.yml -f docker-compose.graph.yml build postgres
docker compose -f docker-compose.yml -f docker-compose.graph.yml --profile graph up -d
```

---

## Where To Go In Canonical Docs

- Runtime and prerequisites: [docs/CLOUD_DEPLOYMENT.md](./docs/CLOUD_DEPLOYMENT.md#1-scope-and-runtime)
- Host setup and firewall: [docs/CLOUD_DEPLOYMENT.md](./docs/CLOUD_DEPLOYMENT.md#3-host-setup-ubuntu)
- Environment variables: [docs/CLOUD_DEPLOYMENT.md](./docs/CLOUD_DEPLOYMENT.md#4-project-configuration)
- Storage migration: [docs/CLOUD_DEPLOYMENT.md](./docs/CLOUD_DEPLOYMENT.md#7-data-placement-and-storage-migration)
- Backup and restore: [docs/CLOUD_DEPLOYMENT.md](./docs/CLOUD_DEPLOYMENT.md#8-backup-and-restore)
- Troubleshooting: [docs/CLOUD_DEPLOYMENT.md](./docs/CLOUD_DEPLOYMENT.md#12-troubleshooting)

---

## Notes

- Podman users can replace `docker compose` with `podman compose`.
- This wrapper intentionally avoids duplicating long-form deployment instructions.

Last updated: 2026-04-04
