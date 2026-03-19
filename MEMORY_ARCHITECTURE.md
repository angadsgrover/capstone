# Dual-Memory Architecture

## Overview

The aviation assistant implements a sophisticated **dual-memory system** that combines:

1. **Short-term Memory (mem0)**: Recent conversational context, user preferences, session-specific facts
2. **Long-term Memory (cognee)**: Persistent knowledge graphs, domain expertise, safety documents

This architecture mirrors human cognitive systems: working memory for immediate context and long-term storage for accumulated knowledge.

```
┌─────────────────────────────────────────────────────────────────┐
│ Agent Query                                                      │
└────────────────────┬────────────────────────────────────────────┘
                     │
      ┌──────────────┴──────────────┐
      │                             │
      ▼                             ▼
┌─────────────────┐           ┌─────────────────┐
│ Short-term      │           │ Long-term       │
│ Memory (mem0)   │           │ Memory (cognee) │
├─────────────────┤           ├─────────────────┤
│ • Last N turns  │           │ • Knowledge     │
│ • User prefs    │           │   graphs        │
│ • Session facts │           │ • Safety docs   │
│ • Recency       │           │ • Entities      │
│   (ephemeral)   │           │ • Relationships │
│                 │           │   (persistent)  │
├─────────────────┤           ├─────────────────┤
│ Storage:        │           │ Storage:        │
│ PostgreSQL      │           │ PostgreSQL      │
│ + pgvector      │           │ + pgvector      │
│                 │           │ + Neo4j (opt)   │
└─────────────────┘           └─────────────────┘
      │                             │
      └──────────────┬──────────────┘
                     │
                     ▼
            Combined Context
         (System Prompt Injection)
                     │
                     ▼
           Specialist LLM Agent
```

---

## Component Breakdown

### 1. Short-term Memory (mem0)

**Purpose**: Store recent conversational context for continuity across turns.

**What it stores**:
- User's recent questions and responses
- Preferences stated in current session ("use metric units", "focus on EGLL")
- Intermediate facts discovered during conversation
- Session-scoped context (expires when session ends)

**Implementation**:
- **Library**: [mem0](https://github.com/mem0ai/mem0) (open-source)
- **Storage**: PostgreSQL with pgvector extension
- **Retrieval**: Semantic similarity search (embeddings)
- **Extraction**: LLM-powered fact extraction from conversations

**Key Features**:
- Automatic memory extraction from chat history
- Semantic search for relevant context
- Session-scoped (per user/thread)
- Lightweight, fast retrieval

**Use Cases**:
```python
# User: "What's the weather at Heathrow?"
# Agent: [fetches METAR for EGLL]

# User: "What about the TAF?"
# Short-term memory: "User recently asked about EGLL" → fetch TAF for EGLL
```

**Configuration**:
```bash
# .env
POSTGRES_DSN=postgresql://capstone:secret@localhost:5432/capstone
EMBED_MODEL=openai/text-embedding-3-small  # for semantic search
```

---

### 2. Long-term Memory (cognee)

**Purpose**: Build and query persistent knowledge graphs from domain documents.

**What it stores**:
- Aviation safety incidents (NTSB reports, ATSB bulletins)
- Regulatory documents (FAA circulars, EASA regulations)
- Technical knowledge (procedures, protocols, aircraft systems)
- Entity relationships (airports, aircraft, organizations, concepts)

**Implementation**:
- **Library**: [cognee](https://github.com/topoteretes/cognee)
- **Storage**:
  - PostgreSQL + pgvector (embeddings)
  - Neo4j (optional, enhances graph queries)
- **Retrieval**: Graph-based RAG (entities + relationships)
- **Extraction**: LLM-powered entity/relationship extraction

**Key Features**:
- Automatic knowledge graph construction from unstructured text
- Entity extraction (airports, aircraft, people, events)
- Relationship mapping (caused_by, located_at, involves)
- Temporal reasoning (track how knowledge evolves)
- Semantic + structural search

**Use Cases**:
```python
# User: "What are the common causes of runway incursions?"
# Long-term memory: Retrieve from ingested safety documents
# → "FAA data shows: 1) pilot deviations (60%), 2) vehicle deviations (20%)..."

# User: "Show me EGLL incidents"
# Long-term memory: Query graph for EGLL entity + all related incident nodes
```

**Configuration**:
```bash
# .env
POSTGRES_DSN=postgresql://capstone:secret@localhost:5432/capstone
COGNEE_ENABLED=true

# Optional: Neo4j for enhanced graph queries
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=changeme_neo4j
```

---

## Memory Integration Points

### 1. System Prompt Injection (Automatic)

**Every specialist agent invocation** includes relevant memories in the system prompt:

```python
# orchestrator.py _make_specialist_node()

system_prompt = AVIATION_PROMPT

# Fetch both memory types
memories = await memory_manager.search_combined(
    query=user_query,
    user_id=session_id,
    short_term_limit=3,   # Last 3 relevant conversation facts
    long_term_limit=2     # Top 2 relevant knowledge graph results
)

if memories:
    system_prompt += f"\n\n## Memory Context\n{memories}"

# Send to LLM
messages = [SystemMessage(content=system_prompt)] + conversation_history
```

**Output Format** (clearly labeled):
```
## Memory Context

## Recent Context (Short-term Memory)
- User prefers METAR in metric units
- Previously asked about EGLL weather
- Session started 10 minutes ago

## Domain Knowledge (Long-term Memory)
- EGLL (Heathrow) is a Category 1 airport with 2 parallel runways
- Common windshear zones: approach to runway 27L, departure from 09R
```

### 2. Explicit Knowledge Graph Tool

**Specialists can explicitly query long-term memory** via the `knowledge_graph_search` tool:

```python
# Tool definition (tools/cognee_search.py)
@tool
async def knowledge_graph_search(query: str, dataset: str = "aviation_knowledge") -> str:
    """
    Search long-term knowledge graph for domain expertise.

    Use for:
    - Safety procedures: "What are TCAS resolution advisory steps?"
    - Regulations: "FAA runway incursion reporting requirements"
    - Incident analysis: "Common causes of landing gear failures"
    """
    return await memory_manager.search_long_term(query, dataset)
```

**When LLM decides to use it**:
```
LLM reasoning: "User asks about runway incursion procedures.
This requires regulatory knowledge beyond my training data.
I'll use knowledge_graph_search tool."

Tool call: knowledge_graph_search(query="runway incursion prevention procedures")

Tool result:
"FAA AC 120-74B: Runway incursion prevention best practices include:
1. Enhanced situational awareness training
2. Read-back/hear-back procedures
..."
```

---

## Best Practices

### When to Use Each Memory Type

| Use Case | Memory Type | Reason |
|----------|-------------|--------|
| "What was the weather I asked about earlier?" | Short-term | Recent session context |
| "Use metric units" (user preference) | Short-term | Session-scoped preference |
| "What are TCAS alert procedures?" | Long-term | Domain knowledge |
| "Show me EGLL incidents" | Long-term | Persistent entity data |
| "Compare the two airports I mentioned" | Short-term | Recent conversation entities |
| "FAA runway marking standards" | Long-term | Regulatory knowledge |

### Memory Injection Strategy

**Automatic injection** (orchestrator.py):
- ✅ Inject memories **before** every specialist LLM call
- ✅ Limit short-term to 3 results (avoid context bloat)
- ✅ Limit long-term to 2 results (high-quality only)
- ✅ Clearly label memory sources in system prompt

**Tool-based retrieval**:
- ✅ Let LLM decide when to use `knowledge_graph_search` tool
- ✅ Use for explicit domain knowledge queries
- ✅ Retrieves fresh data, not limited by automatic injection

### Document Ingestion Best Practices

**What to ingest into long-term memory**:
- ✅ Safety documents (NTSB/ATSB reports, bulletins)
- ✅ Regulatory documents (AC, EASA regulations)
- ✅ Technical manuals (SOPs, checklists)
- ✅ Training materials

**What NOT to ingest**:
- ❌ Live weather data (use MCP tools instead)
- ❌ Real-time flight tracking (use ADSB MCP)
- ❌ Session-specific conversation (auto-handled by short-term)

**Ingestion workflow**:
```bash
# 1. Place documents in directory
mkdir -p safety_reports/
cp ntsb_*.txt safety_reports/

# 2. Use document ingestor
python -c "
from ingestion.document_ingestor import DocumentIngestor
from memory import DualMemoryManager

manager = DualMemoryManager()
await manager.init()

ingestor = DocumentIngestor(manager)
stats = await ingestor.ingest_directory('safety_reports/')
print(f'Ingested {stats[\"success\"]}/{stats[\"total\"]} documents')
"
```

**Via API**:
```bash
# Single document
curl -X POST http://localhost:8000/api/knowledge/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "text": "NTSB report content...",
    "metadata": {"source": "NTSB", "date": "2024-01-15"},
    "dataset": "aviation_knowledge"
  }'

# Batch
curl -X POST http://localhost:8000/api/knowledge/ingest-batch \
  -H "Content-Type: application/json" \
  -d '{
    "documents": [
      {"text": "...", "metadata": {...}},
      {"text": "...", "metadata": {...}}
    ],
    "dataset": "aviation_knowledge"
  }'
```

---

## API Endpoints

### Memory Status
```bash
GET /api/memory/status

Response:
{
  "short_term": {
    "available": true,
    "provider": "mem0",
    "description": "Recent conversational context"
  },
  "long_term": {
    "available": true,
    "provider": "cognee",
    "description": "Persistent knowledge graph"
  },
  "dual_memory": {
    "enabled": true,
    "both_available": true
  }
}
```

### Knowledge Graph Search
```bash
GET /api/knowledge/search?query=runway%20incursion&limit=5

Response:
{
  "query": "runway incursion",
  "dataset": "aviation_knowledge",
  "results": "1. FAA AC 120-74B: Runway incursion prevention...\n2. ..."
}
```

### Entity Retrieval
```bash
GET /api/knowledge/entity/EGLL

Response:
{
  "entity": {
    "name": "EGLL",
    "type": "airport",
    "location": "London, UK",
    "runways": ["09L/27R", "09R/27L"],
    "incidents": [...]
  }
}
```

### Document Ingestion
```bash
POST /api/knowledge/ingest
Content-Type: application/json

{
  "text": "document content...",
  "metadata": {"source": "...", "date": "..."},
  "dataset": "aviation_knowledge"
}

Response:
{"success": true, "dataset": "aviation_knowledge"}
```

---

## Performance Considerations

### Short-term Memory (mem0)
- **Latency**: ~50-100ms per search (embedding + pgvector query)
- **Capacity**: Unlimited (PostgreSQL table)
- **Retention**: Configurable per-session (default: ephemeral)

### Long-term Memory (cognee)
- **Latency**: ~100-300ms per search (graph traversal + embeddings)
- **Capacity**: Scales with PostgreSQL + optional Neo4j
- **Retention**: Persistent (never expires)

### Optimization Tips
1. **Limit results**: Keep short_term_limit=3, long_term_limit=2 in automatic injection
2. **Cache embeddings**: Reuse embeddings for repeated queries (future enhancement)
3. **Batch ingestion**: Use `ingest_batch` for multiple documents (10-50 at a time)
4. **Neo4j optional**: Use only if graph queries are critical (adds complexity)

---

## Troubleshooting

### Short-term memory not working
```bash
# Check PostgreSQL connection
psql $POSTGRES_DSN -c "SELECT COUNT(*) FROM embeddings WHERE source_type='conversation';"

# Check mem0 status
curl http://localhost:8000/api/memory/status | jq .short_term
```

### Long-term memory not working
```bash
# Check cognee status
curl http://localhost:8000/api/memory/status | jq .long_term

# Check if documents ingested
curl "http://localhost:8000/api/knowledge/search?query=test&limit=1"

# Check environment
echo $COGNEE_ENABLED  # should be "true"
```

### Knowledge graph empty
```bash
# Ingest sample document
curl -X POST http://localhost:8000/api/knowledge/ingest \
  -H "Content-Type: application/json" \
  -d '{"text": "EGLL (Heathrow) is a major international airport in London, UK."}'

# Verify
curl "http://localhost:8000/api/knowledge/entity/EGLL"
```

---

## Future Enhancements

1. **Automatic document ingestion**: Watch directory for new safety reports
2. **Re-ranker**: BM25 keyword + semantic rank for RAG results
3. **Memory pruning**: Auto-delete stale short-term memories
4. **Graph visualization**: UI for exploring knowledge graph
5. **Multi-modal**: Ingest images (runway diagrams, charts) via cognee
6. **Hybrid search**: Combine short-term + long-term in single query
7. **Memory consolidation**: Promote important short-term facts to long-term

---

## References

- [mem0 Documentation](https://docs.mem0.ai/)
- [cognee Documentation](https://cognee.ai/docs)
- [LangGraph Memory](https://langchain-ai.github.io/langgraph/how-tos/memory/manage-conversation-history/)
- [pgvector Guide](https://github.com/pgvector/pgvector)
- [Neo4j + LangChain](https://python.langchain.com/docs/integrations/graphs/neo4j_cypher)
