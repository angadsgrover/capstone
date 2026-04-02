# Dokploy Environment Deployment Guide

This guide explains what to deploy for this repository in Dokploy, which resources are required, and how to deploy safely to staging and production.

Reference docs:

- [Dokploy Core](https://docs.dokploy.com/docs/core)
- [Dokploy Docker Compose](https://docs.dokploy.com/docs/core/docker-compose)
- [Dokploy Environment Variables](https://docs.dokploy.com/docs/core/variables)
- [Dokploy Domains](https://docs.dokploy.com/docs/core/domains)
- [Dokploy Databases](https://docs.dokploy.com/docs/core/databases)

## Deployment Model

Use one Docker Compose service in Dokploy for this project.

Why this is the recommended model:

- The agent depends on three MCP services by compose service name.
- The frontend reverse-proxies `/api` to `agent:8000` internally.
- Internal networking and service discovery stay simple and stable.

Use Dokploy Docker Compose mode, not Stack mode, because this repository uses `build` contexts.

## Services and Resources

### Core Services

| Service | Required | Purpose | Internal Port | Suggested Resources |
| --- | --- | --- | --- | --- |
| frontend | Yes | React app served by nginx, proxies `/api` to agent | 80 | 0.5 CPU, 256-512 MB RAM |
| agent | Yes | FastAPI + LangGraph orchestration API | 8000 | 2 CPU, 2 GB RAM |
| agent-worker | Yes if `EXECUTION_MODE=queued` | Queue consumer for background runs | none exposed | 1 CPU, 1-2 GB RAM |
| mcp-aviation-wx | Yes | Aviation weather MCP server | 8001 | 0.5 CPU, 256-512 MB RAM |
| mcp-hk-climate | Yes | HK climate MCP server | 8002 | 0.5 CPU, 256-512 MB RAM |
| mcp-adsb | Yes | ADS-B MCP server | 8003 | 0.5 CPU, 256-512 MB RAM |
| postgres | Yes | Primary DB (conversation + RAG + pgvector) | 5432 | 1 CPU, 1-2 GB RAM |
| redis | Yes | Cache + event backend | 6379 | 0.5 CPU, 256-512 MB RAM |

### Optional Services

| Service | When to Enable | Notes |
| --- | --- | --- |
| neo4j | Only if graph features are required | Uses graph profile and `NEO4J_PASSWORD` |
| adminer | Never in production | Dev-only DB UI |
| caddy | Not needed in Dokploy | Dokploy already provides Traefik ingress/TLS |

### Persistent Storage

| Resource | Required | Backup Priority | Source |
| --- | --- | --- | --- |
| `pgdata` | Yes | High | PostgreSQL data |
| `redisdata` | Yes | Medium | Redis append-only state/cache |
| `neo4jdata` | Optional | Medium | Neo4j graph data |

Notes:

- Prefer named volumes for persistence and Dokploy backup compatibility.
- Avoid relying on repository bind mounts for critical runtime files during auto-redeploy.

## Environment Layout in Dokploy

Create one Dokploy project with at least two environments:

- staging
- production

Recommended variable scopes:

- Project-level: shared non-secret defaults.
- Environment-level: secrets and per-environment values.
- Service-level: only service-specific overrides.

### Project-level Shared Variables

Set shared defaults such as:

- `MODEL_CHOICE`
- `BASE_URL`
- `CACHE_ENABLED=true`
- `EVENT_BACKEND=redis`
- `EXECUTION_MODE=queued`
- `LANGSMITH_TRACING=true`
- `MEM0_LONG_TERM_ENABLED=true`

### Environment-level Variables (Secrets)

Set these in each environment (staging and production):

- `LLM_API_KEY`
- `POSTGRES_PASSWORD`
- `POSTGRES_DSN`
- `REDIS_URL`
- `MEM0_API_KEY` (if using Mem0)
- `LANGSMITH_API_KEY` (if using LangSmith)
- `NEO4J_PASSWORD` (if graph profile enabled)
- `JWT_*` values (if enabling JWT auth)

### Service-level Variables

Use only when needed, for example:

- `CORS_ALLOW_ORIGINS` on agent.
- `AGENT_PROCESS_MODE=worker` on agent-worker.

## Compose Preparation for Dokploy

Do not deploy with `docker-compose.caddy.yml` in Dokploy.

Reason:

- Dokploy already handles ingress and TLS with Traefik.
- A second edge proxy can create port and routing conflicts.

For Dokploy deployments:

- Start from `docker-compose.yml`.
- Apply production constraints from `docker-compose.prod.yml` where needed.
- Keep internal service DNS names unchanged (`agent`, `postgres`, `redis`, MCP names).

Important for this repository:

- `frontend` in base compose publishes `${FRONTEND_PORT:-80}:80`.
- In Dokploy, prefer internal container routing via Domains instead of exposing host ports.
- If deploying only `docker-compose.yml`, set `FRONTEND_PORT` to a non-80 host port in Dokploy variables (for example `18080`).

## Step-by-Step Deployment in Dokploy

1. Create project.

- Dokploy UI -> New Project -> name it (example: `capstone`).

1. Create environments.

- Add `staging` and `production` environments.
- Set environment-level secret variables for each.

1. Add Docker Compose service.

- Service type: Docker Compose.
- Source: Git repository.
- Branch: deployment branch (example: `main`).
- Mode: Docker Compose, not Stack.

1. Configure variables.

- Add project-level shared variables.
- Add environment-level secrets.
- Confirm compose references use `${VAR}` syntax.

1. Configure persistence.

- Keep named volumes for postgres and redis.
- Enable Dokploy volume backups for critical volumes.

1. Configure domains.

- Add app domain to frontend on container port `80`.
- Optionally add API domain to agent on container port `8000`.
- Enable HTTPS (LetsEncrypt).

Domain note for Dokploy Docker Compose:

- Compose domain changes require redeploy to take effect.

1. Deploy.

- Trigger first deployment and monitor logs per service.

1. Validate.

- Frontend loads successfully.
- `/api` calls through frontend reach the agent.
- Agent can connect to MCP services, postgres, and redis.

## Post-deploy Validation Commands

```bash
# Frontend domain
curl -I https://your-app-domain

# If API domain is exposed
curl -s https://your-api-domain/health
curl -s https://your-api-domain/ready

# If API only reachable through frontend
curl -s https://your-app-domain/api/health
curl -s https://your-app-domain/api/ready
```

## Recommended Production Sizing

Dokploy can run on smaller nodes, but this stack should start with:

- 4 vCPU
- 8 GB RAM
- 80-120 GB SSD

Scale `agent` and `agent-worker` first as traffic increases.

## Backup and Recovery

Minimum backup policy:

- Daily backup for `pgdata`.
- Optional but recommended backup for `redisdata`.
- Keep 7-14 restore points.

If Neo4j is enabled:

- Back up `neo4jdata` on the same cadence as postgres.

## Rollout Strategy

1. Deploy to staging first.
1. Validate chat flow, SSE streaming, tools, and MCP connectivity.
1. Promote the same commit to production.
1. Monitor logs and metrics across one traffic cycle.

## Common Pitfalls

1. Running `docker-compose.caddy.yml` in Dokploy.

- Causes duplicate ingress and port conflicts.

1. Publishing conflicting host ports.

- Prefer domain routing to container ports through Dokploy.
- If you see `Bind for 0.0.0.0:80 failed: port is already allocated`, set `FRONTEND_PORT=18080` (or another free port) and redeploy.

1. Missing secrets.

- Agent startup fails without `LLM_API_KEY`, `POSTGRES_PASSWORD`, `POSTGRES_DSN`, and `REDIS_URL`.

1. Stream/startup error with `Temporary failure in name resolution`.

- Verify `POSTGRES_DSN` host is reachable from the compose network (for local Dokploy Postgres use `postgres`).
- Verify `REDIS_URL` host is reachable from the compose network (for local Dokploy Redis use `redis`).
- Redeploy after variable changes so containers pick up new values.

1. Forgetting redeploy after compose-domain changes.

- Dokploy applies compose domain updates on redeploy.

1. Queue mode without worker.

- If `EXECUTION_MODE=queued`, keep `agent-worker` running.

## Quick Variable Checklist

Required:

- `LLM_API_KEY`
- `POSTGRES_PASSWORD`
- `POSTGRES_DSN`
- `REDIS_URL`
- `BASE_URL`
- `MODEL_CHOICE`

Strongly recommended:

- `CACHE_ENABLED=true`
- `EVENT_BACKEND=redis`
- `EXECUTION_MODE=queued`
- `FRONTEND_PORT=18080` (when using only `docker-compose.yml` in Dokploy)
- `CORS_ALLOW_ORIGINS=https://your-app-domain`

Optional integrations:

- `MEM0_API_KEY`
- `LANGSMITH_API_KEY`
- `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `LIVEKIT_URL`
- `JWT_*`

## Migrating Local Postgres Data to Dokploy Postgres

You can migrate your existing embeddings and chat data with a standard PostgreSQL dump and restore.

1. Create a local dump.

- Full database:
  - `pg_dump -Fc -h localhost -p 5432 -U capstone -d capstone -f capstone.dump`
- Data-only for selected tables (example):
  - `pg_dump -Fc --data-only -h localhost -p 5432 -U capstone -d capstone -t embeddings -t conversations -t metar_history -t taf_history -f capstone-data.dump`

1. Copy dump to Azure VM.

- `scp capstone.dump <azure-user>@<azure-vm-ip>:~/capstone.dump`

1. Find Dokploy Postgres container on the VM.

- `docker ps --format '{{.Names}}' | grep postgres`

1. Optional safety backup of remote DB.

- `docker exec <postgres-container-name> pg_dump -U capstone -d capstone -Fc -f /tmp/pre-restore.dump`

1. Restore into Dokploy Postgres.

- Full restore (replace existing objects):
  - `cat ~/capstone.dump | docker exec -i <postgres-container-name> pg_restore -U capstone -d capstone --clean --if-exists --no-owner --no-privileges`
- Data-only restore (append/update behavior depends on constraints):
  - `cat ~/capstone-data.dump | docker exec -i <postgres-container-name> pg_restore -U capstone -d capstone --no-owner --no-privileges`

1. Validate row counts.

- `docker exec -i <postgres-container-name> psql -U capstone -d capstone -c "SELECT COUNT(*) FROM embeddings;"`
- `docker exec -i <postgres-container-name> psql -U capstone -d capstone -c "SELECT COUNT(*) FROM conversations;"`

Notes:

- Ensure the target DB has `vector` extension installed (`CREATE EXTENSION IF NOT EXISTS vector;`).
- During restore, stop or scale down `agent` and `agent-worker` to avoid concurrent writes.
