# OpenRouter Embeddings Configuration Guide

This project uses **OpenRouter's unified embeddings API** for all embedding operations (RAG search, mem0 memory, ingestion pipeline). This provides access to  **multiple embedding models** from different providers with a single API key.

## Why OpenRouter Embeddings?

| Feature | Benefit |
|---------|---------|
| **Multi-provider** | Access models from OpenAI, Cohere, Mistral, Nomic, NVIDIA, etc. |
| **Cost optimization** | Choose cheaper models (nomic, mistral) vs premium (OpenAI large) |
| **Speed vs quality** | Trade off embedding dimensions (768 vs 3072) for speed |
| **Single API key** | Use same key for both chat + embeddings (or override separately) |
| **Fallback routing** | Automatic provider switching if one is overloaded |
| **Batch processing** | Efficient multi-text embedding in one request |

## Quick Setup

### 1. Default Setup (Recommended for Most Users)

No extra configuration needed! By default:
- Embeddings use your existing `LLM_API_KEY` and `BASE_URL`
- Model: `openai/text-embedding-3-small` (1536 dims, fast, cheap)

```bash
# Just run with your existing .env
docker compose up -d
```

### 2. Switch to a Different Embedding Model

Edit `.env`:

```bash
# Use Cohere embeddings (1024 dims, often faster)
EMBED_MODEL=cohere/embed-english-v3.0

# Use Nomic embeddings (768 dims, very lightweight)
EMBED_MODEL=nomic/nomic-embed-text-v1.5

# Use OpenAI large (3072 dims, highest quality)
EMBED_MODEL=openai/text-embedding-3-large

# Use Mistral embeddings (1024 dims)
EMBED_MODEL=mistralai/mistral-embed
```

Restart agent container:
```bash
docker compose restart agent
```

### 3. Use Direct OpenAI (Not Through OpenRouter)

Edit `.env`:

```bash
EMBED_API_KEY=sk-proj-your-openai-key  # separate OpenAI key
EMBED_BASE_URL=https://api.openai.com/v1
EMBED_MODEL=text-embedding-3-small
```

This is useful if:
- You have a direct OpenAI account and want to avoid OpenRouter
- You need enterprise OpenAI features
- Your OpenRouter account doesn't have embedding credits

### 4. Use Multimodal Embeddings (Images + Text)

For combining text and image understanding:

```bash
EMBED_MODEL=nvidia/llama-nemotron-embed-vl-1b-v2
```

**Note**: Multimodal models are slower and pricier; only use if you need image support.

---

## Available Models on OpenRouter

| Model | Provider | Dims | Speed | Cost | Use Case |
|-------|----------|------|-------|------|----------|
| **text-embedding-3-small** | OpenAI | 1536 | ⚡⚡ | 💰 | ⭐ Default, balanced |
| **text-embedding-3-large** | OpenAI | 3072 | ⚡ | 💰💰 | Premium quality |
| **embed-english-v3.0** | Cohere | 1024 | ⚡⚡ | 💰 | Fast alternative |
| **mistral-embed** | Mistral | 1024 | ⚡⚡ | 💰 | Lightweight |
| **nomic-embed-text-v1.5** | Nomic | 768 | ⚡⚡⚡ | 💰 | Ultra-fast, local-friendly |
| **text-embedding-ada-002** | OpenAI | 1536 | ⚡ | 💰💰 | Legacy (not recommended) |
| **llama-nemotron-embed-vl-1b-v2** | NVIDIA | 1152 | ⚡ | 💰💰 | Multimodal (images+text) |

**Full list**: https://openrouter.ai/models?fmt=cards&output_modalities=embeddings

---

## How It's Used in the Project

### 1. RAG Search Tool (`agent/tools/rag_search.py`)

```python
from tools.rag_search import make_rag_search_tool

rag_tool = make_rag_search_tool(db)  # Uses EMBED_MODEL for queries

# Behind the scenes:
# - User query → embedded with EMBED_MODEL
# - Compared against pgvector database (cosine similarity)
# - Returns top-k relevant METAR/TAF/safety records
```

### 2. Ingestion Pipeline (`agent/ingestion/`)

```python
from ingestion.embedder import embed_and_store

# METAR ingestor automatically embeds new observations
await embed_and_store(db, "metar", raw_metar_text)

# Runs every 30 min via APScheduler
# Uses EMBED_MODEL for all new METAR/TAF/safety records
```

### 3. Long-Term Memory (`agent/memory.py`)

```python
# mem0 uses the configured EMBED_MODEL to:
# - Extract facts from conversations
# - Store memories in pgvector
# - Retrieve relevant facts before inference
```

---

## Environment Variables Reference

| Variable | Default | Example | Notes |
|----------|---------|---------|-------|
| `LLM_API_KEY` | — | `sk-...` | Your OpenRouter or OpenAI key |
| `BASE_URL` | — | `https://openrouter.ai/api/v1` | Chat LLM provider |
| `EMBED_API_KEY` | `$LLM_API_KEY` | `sk-...` | Override to use different provider |
| `EMBED_BASE_URL` | `$BASE_URL` | `https://api.openai.com/v1` | Override to use direct OpenAI |
| `EMBED_MODEL` | `openai/text-embedding-3-small` | `cohere/embed-english-v3.0` | Embedding model ID |

### Example: Cost-Optimized Setup

```bash
# Chat: OpenRouter (cheap small model)
LLM_API_KEY=sk-openrouter-key
BASE_URL=https://openrouter.ai/api/v1
MODEL_CHOICE=qwen/qwen3-8b

# Embeddings: Direct Cohere (cheaper than OpenAI)
EMBED_API_KEY=sk-cohere-key
EMBED_BASE_URL=https://api.cohere.com
EMBED_MODEL=cohere/embed-english-v3.0
```

---

## Changing Embedding Models Without Rebuilding

### 1. Update `.env`

```bash
# Before
EMBED_MODEL=openai/text-embedding-3-small

# After (switch to lightweight model)
EMBED_MODEL=nomic/nomic-embed-text-v1.5
```

### 2. Restart Services

```bash
docker compose restart agent
```

**Note**: Existing embeddings in the database are NOT re-generated. Only new METAR/TAF from this point use the new model.

To regenerate all embeddings with new model:

```bash
# Clear embeddings table
docker compose exec postgres psql -U capstone -c "TRUNCATE embeddings;"

# Trigger re-ingestion
# (next METAR/TAF poll will regenerate)
```

---

## Cost Comparison (Rough Estimates)

Assuming processing **1,000 documents** (e.g., daily METAR for 10 airports × 100 days):

| Model | Dims | Cost | Speed | Quality |
|-------|------|------|-------|---------|
| text-embedding-3-small | 1536 | ~$0.02 | ⚡⚡ | ⭐⭐⭐ |
| nomic-embed-text-v1.5 | 768 | ~$0.001 | ⚡⚡⚡ | ⭐⭐ |
| cohere/embed-english-v3.0 | 1024 | ~$0.01 | ⚡⚡ | ⭐⭐⭐ |
| text-embedding-3-large | 3072 | ~$0.06 | ⚡ | ⭐⭐⭐⭐ |

*(Prices subject to change; check OpenRouter for current rates)*

---

## Troubleshooting

### "Embedding failed: 401 Unauthorized"

**Cause**: Invalid API key or model not available in your plan

**Solution**:
```bash
# Test API key
curl https://openrouter.ai/api/v1/embeddings \
  -H "Authorization: Bearer $LLM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model": "openai/text-embedding-3-small", "input": "test"}'

# Check available models
curl https://openrouter.ai/api/v1/embeddings/models \
  -H "Authorization: Bearer $LLM_API_KEY"
```

### "Model not found: xxx/yyy"

**Cause**: Model name is incorrect or not in your provider's catalog

**Solution**:
- Check model list: https://openrouter.ai/models?fmt=cards&output_modalities=embeddings
- Use correct format: `provider/model-name` (e.g., `openai/text-embedding-3-small`)

### "Embedding dimension mismatch"

**Cause**: Changed EMBED_MODEL but database still expects old dimension

**Solution** (for mem0):
```bash
# If using mem0 with different-dimension model, clear mem0 collection
docker compose down -v  # remove all volumes
docker compose up -d
```

For pgvector table, schema adjustment might be needed (advanced).

### "Ingestion is slow"

**Solution**: Use a faster model

```bash
# Switch to lightweight model (768 dims)
EMBED_MODEL=nomic/nomic-embed-text-v1.5

# Then restart
docker compose restart agent
```

---

## Best Practices

### 1. Start Small, Then Scale

```bash
# Development: use lightweight model
EMBED_MODEL=nomic/nomic-embed-text-v1.5

# Production: switch to higher quality
EMBED_MODEL=openai/text-embedding-3-small  # or text-embedding-3-large
```

### 2. Monitor Embedding Costs

Embeddings are called:
- Every 30 min for METAR polling (8 airports × ~150 tokens each)
- Every 60 min for TAF polling (8 airports × ~300 tokens each)
- Every user query (RAG search)

**Estimate**: ~50K tokens/day ingestion + query traffic ≈ $0.30-1.00/month

### 3. Batch Requests Where Possible

The ingestion pipeline already batches:
```python
# All 8 airports embedded in one request
await embed_text(metar_records)
```

### 4. Cache When Possible

METAR/TAF text is stable; don't re-embed identical content.

The ingestion pipeline uses `ON CONFLICT DO NOTHING`, so duplicates are skipped.

---

## Advanced: Using Multiple Embedding Models

For specialized use cases (e.g., safety narratives vs METAR text), you can run multiple instances:

```python
# Use different embedder for safety events
embedder_metar = openai.AsyncOpenAI(...)
embedder_safety = openai.AsyncOpenAI(...)

await embed_and_store(db, "metar", text, embedder=embedder_metar)
await embed_and_store(db, "safety", text, embedder=embedder_safety)
```

(Currently not implemented; requires code changes to `embedder.py`)

---

## Related Documentation

- [OpenRouter Embeddings API](https://openrouter.ai/docs/api/v1/embeddings) — official docs
- [RAG Search Tool](./agent/tools/rag_search.py) — source code
- [Ingestion Pipeline](./agent/ingestion/) — METAR/TAF processing
- [Memory Configuration](./agent/memory.py) — mem0 setup
- [Main README](./README.md) — performance tuning section

---

**Pro Tip**: Start with `openai/text-embedding-3-small` (default). If RAG search is too slow, switch to `nomic/nomic-embed-text-v1.5`. If quality degrades, upgrade to `openai/text-embedding-3-large`.
