# Documentation Structure Guide

## Overview

This guide explains the purpose and audience of each documentation file in the project. Use this as a reference to find the right documentation for your needs.

---

## Core Documentation (Start Here)

### 📘 [README.md](./README.md)
**Purpose**: Main project overview and quick start guide
**Audience**: Everyone (new users, contributors, stakeholders)
**Content**:
- What the system does
- Quick start with Docker
- Quick start with local development
- Architecture overview diagram
- Feature highlights
- Testing procedures

**When to use**: First document to read when encountering the project

---

### 🚀 [QUICKSTART.md](./QUICKSTART.md)
**Purpose**: One-page quick reference for common commands
**Audience**: Developers who have already set up the project
**Content**:
- Docker commands (up/down/logs)
- Local development startup (5 terminals)
- Common API test curl commands
- Environment variable reference table
- Quick troubleshooting table

**When to use**: Daily development reference, when you need to quickly remember a command

---

## Detailed Setup Guides

### 🔧 [DEVELOPMENT.md](./DEVELOPMENT.md)
**Purpose**: Comprehensive local development guide
**Audience**: Developers working on the codebase locally (non-Docker)
**Content**:
- Python venv setup (shared .venv at repo root)
- MCP server startup procedures (3 servers on ports 8001/8002/8003)
- FastAPI server configuration
- Frontend (Vite) development server
- Database initialization
- Testing individual components
- Debugging LangGraph workflows
- Common development issues

**When to use**: Setting up local development environment, debugging issues, iterative development

---

### 🐳 [DOCKER_SETUP.md](./DOCKER_SETUP.md)
**Purpose**: Complete Docker operations and deployment guide
**Audience**: DevOps, deployment engineers, users preferring containerized setup
**Content**:
- First-time Docker setup
- Docker compose orchestration
- Optional AGE graph database setup
- Optional Neo4j setup (--profile graph)
- Volume management
- Data migration to larger drives
- Backup and restore procedures
- Production considerations

**When to use**: Docker deployment, moving data between drives, backup procedures, production setup

---

### 🖥️ [VM_NEW_MACHINE_SETUP.md](./VM_NEW_MACHINE_SETUP.md)
**Purpose**: Cloud VM and new machine deployment playbook
**Audience**: DevOps deploying to cloud VMs (AWS, GCP, Azure) or new physical machines
**Content**:
- Fresh Ubuntu/Debian VM setup from scratch
- System dependencies installation
- Docker installation and configuration
- Security hardening (firewall, SSH keys)
- Environment variable management
- Resource sizing recommendations
- Monitoring setup

**When to use**: Deploying to a new cloud VM, setting up a fresh production server

---

## Feature-Specific Documentation

### 🧠 [MEMORY_ARCHITECTURE.md](./MEMORY_ARCHITECTURE.md)
**Purpose**: Dual-memory system architecture (Mem0 Cloud short-term + long-term)
**Audience**: Developers working on memory/RAG features
**Content**:
- Short-term memory (mem0) architecture
- Long-term memory (Mem0 Cloud) architecture
- Knowledge graph design
- Memory integration with LangGraph
- Document ingestion pipeline
- API usage examples

**When to use**: Understanding or modifying memory systems, adding new knowledge sources

---

### 🔍 [EMBEDDINGS.md](./EMBEDDINGS.md)
**Purpose**: OpenRouter embeddings guide and best practices
**Audience**: Developers configuring embedding models
**Content**:
- Supported embedding models (OpenAI, Cohere, Mistral, nomic)
- Cost-performance tradeoffs
- Configuration via EMBED_MODEL env var
- Dimension compatibility (768-3072)
- Troubleshooting embedding issues
- Model selection guidelines

**When to use**: Choosing or switching embedding models, debugging RAG retrieval, optimizing costs

---

### ⚡ [CACHING.md](./CACHING.md)
**Purpose**: Redis caching architecture and performance tuning
**Audience**: Developers optimizing performance
**Content**:
- Redis layer architecture
- Cache key design
- TTL strategies
- Cache invalidation patterns
- Performance metrics (40-60% hit rate, 2-5x speedup)
- Monitoring and debugging cache behavior

**When to use**: Performance optimization, cache tuning, investigating cache-related issues

---

### 📱 [MOBILE_APP.md](./MOBILE_APP.md)
**Purpose**: React Native mobile app development guide
**Audience**: Mobile developers building iOS/Android apps
**Content**:
- Shared layer portability (types, services, state)
- Expo setup from scratch
- React Native Paper UI components
- Native equivalents for web components
- Platform-specific considerations
- EventSource polyfills for SSE streaming

**When to use**: Building a native mobile app that reuses the agent backend

---

## Strategic Planning Documents

### 🗺️ [ROADMAP.md](./ROADMAP.md)
**Purpose**: Future enhancements and strategic direction
**Audience**: Product managers, tech leads, contributors planning new features
**Content**:
- Completed features (Phases 1-9, 13-15)
- Planned future phases:
  - Phase 10: Time-series weather forecasting
  - Phase 11: Multi-agent collaboration (agent-to-agent communication)
  - Phase 12: Voice interface (speech-to-text, text-to-speech)
  - Phase 16+: Agentic RAG, A/B testing, compliance module
- Effort estimates
- Priority rankings
- Dependencies

**When to use**: Planning new features, understanding project direction, contribution ideas

---

## Archived Documentation

### 📦 [docs/archived/](./docs/archived/)
**Purpose**: Historical planning documents no longer actively maintained
**Content**:
- `architecture_plan.md` - Original architecture planning (now implemented)

**When to use**: Historical reference, understanding original design decisions

---

## Package Management

### Python Dependencies

#### Agent Service
- **File**: [`agent/pyproject.toml`](./agent/pyproject.toml) (preferred)
- **File**: [`agent/requirements.txt`](./agent/requirements.txt) (Docker/pip)
- **Python Version**: >=3.10 (3.12 recommended)
- **Key Dependencies**:
  - LangChain/LangGraph: `langgraph>=1.0.0`, `langchain-openai>=1.0.0`
  - MCP Protocol: `mcp>=1.5.0`, `fastmcp>=2.10.2`
  - Database: `asyncpg>=0.29.0`, `redis>=5.0.0`
  - Memory/RAG: `mem0ai>=0.1.0`, `rank-bm25>=0.2.2`
  - Web: `fastapi>=0.128`, `uvicorn>=0.30.0`

#### MCP Servers
- **Aviation Weather**: [`aviation-weather-mcp-python/pyproject.toml`](./aviation-weather-mcp-python/pyproject.toml)
- **HK Climate**: [`hk-climate-mcp-server-python/pyproject.toml`](./hk-climate-mcp-server-python/pyproject.toml)
- **ADS-B**: [`adsb_mcp/pyproject.toml`](./adsb_mcp/pyproject.toml)
- **Common Dependencies**: `fastmcp>=2.10.2`, `aiohttp>=3.8.0`, `pytest>=8.0.0`

### JavaScript/TypeScript Dependencies

#### Frontend
- **File**: [`frontend-app/package.json`](./frontend-app/package.json)
- **Node Version**: >=22
- **Key Dependencies**:
  - React: `react@^19.2.3`, `react-dom@^19.2.3`
  - Routing: `react-router-dom@^7.8.0`
  - State: `zustand@^5.0.9`
  - UI: `react-markdown@^9.0.1`, `reactflow@^11.11.4`, `lucide-react@^0.577.0`
  - Styling: `tailwindcss@^4`, `class-variance-authority@^0.7.1`
  - Build: `vite@^5.0.10`, `@vitejs/plugin-react@^4.2.1`

---

## Documentation Maintenance

### When to Update
- **README.md**: When adding major features or changing quick start steps
- **DEVELOPMENT.md**: When local dev setup changes (new dependencies, new services)
- **QUICKSTART.md**: When adding new common commands or env variables
- **Feature docs** (MEMORY, CACHING, EMBEDDINGS): When modifying those systems
- **ROADMAP.md**: When completing phases or adding new strategic initiatives

### Style Guidelines
- Use clear headers (##, ###)
- Include code blocks with language hints (```bash, ```python)
- Add "Purpose" and "Audience" sections for major docs
- Keep examples up-to-date and tested
- Cross-reference related docs with links

### Documentation Review Checklist
- [ ] Links are not broken
- [ ] Code examples work as written
- [ ] Environment variable references are current
- [ ] Port numbers match deployment
- [ ] Commands have been tested
- [ ] Prerequisites are clearly stated

---

## Quick Reference Table

| Documentation | Purpose | Primary Audience |
|--------------|---------|------------------|
| README.md | Project overview + quick start | Everyone |
| QUICKSTART.md | One-page command reference | Active developers |
| DEVELOPMENT.md | Local dev setup guide | Contributors |
| DOCKER_SETUP.md | Docker deployment + operations | DevOps/deployment |
| VM_NEW_MACHINE_SETUP.md | Cloud VM setup | DevOps/infrastructure |
| MEMORY_ARCHITECTURE.md | Dual-memory system | Backend developers |
| EMBEDDINGS.md | Embedding model config | Backend developers |
| CACHING.md | Redis performance tuning | Backend developers |
| MOBILE_APP.md | React Native guide | Mobile developers |
| ROADMAP.md | Future plans | Product/tech leads |

---

## Getting Help

If you can't find what you need in the documentation:

1. **Development questions**: See [DEVELOPMENT.md](./DEVELOPMENT.md#troubleshooting)
2. **Docker issues**: See [DOCKER_SETUP.md](./DOCKER_SETUP.md#troubleshooting)
3. **Quick fixes**: See [QUICKSTART.md](./QUICKSTART.md#troubleshooting)
4. **Architecture questions**: Start with [README.md](./README.md#architecture)

---

*Last updated: 2026-03-22*
