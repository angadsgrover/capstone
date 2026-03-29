# Future Roadmap & Improvements

## Overview

This document outlines the strategic roadmap for enhancing the Aviation Intelligence Platform beyond the current implementation (Phases 1-8). Each enhancement is categorized by priority, estimated effort, and expected impact.

---

## ✅ Completed Features (Phases 1-9, 13-15)

- [x] **Phase 1**: Vite + React 19 frontend with streaming UI
- [x] **Phase 2**: LangGraph orchestrator with 4 specialist agents
- [x] **Phase 3**: PostgreSQL + pgvector RAG search
- [x] **Phase 4**: METAR/TAF ingestion pipeline
- [x] **Phase 5**: Apache AGE graph database (optional)
- [x] **Phase 6**: OpenRouter embeddings support
- [x]  **Phase 7**: Dual-memory system (Mem0 Cloud short-term + long-term)
- [x] **Phase 8**: Redis caching + React Native mobile guide
- [x] **Phase 9**: Hybrid BM25 + vector RAG reranking (exact-match uplift with bounded over-fetch)
- [x] **Phase 13**: Advanced visualizations (airport map data, trends, flight paths, safety heatmap)
- [x] **Phase 14**: Performance optimizations (DB index/view, code-splitting, log virtualization, Redis pipeline helpers)
- [x] **Phase 15**: Advanced multi-step agent planning (plan-and-execute graph, planning telemetry, frontend multi-step support)

---

## Phase 9: BM25 Re-ranker for Hybrid Search (Implemented)

### Goal
Combine **BM25 keyword search** with **semantic vector search** for improved RAG retrieval accuracy.

### Current Limitation
Pure vector search sometimes misses exact keyword matches (e.g., "EGLL" vs "Heathrow").

### Implementation Status
- Hybrid reranking is now implemented in `agent/tools/rag_search.py`
- Pipeline: vector over-fetch -> BM25 lexical scoring -> weighted normalized blend -> top-k return
- Performance safeguards:
  - bounded over-fetch (`RAG_HYBRID_OVERFETCH_FACTOR`, `RAG_HYBRID_OVERFETCH_CAP`)
  - fixed output limit cap (existing tool cap retained)
  - graceful fallback to semantic-only ranking if BM25 is unavailable
  - no frontend API contract changes required

### Implementation
```python
# agent/tools/hybrid_search.py
from rank_bm25 import BM25Okapi

class HybridSearchTool:
    def search(self, query: str, limit: int = 5):
        # 1. Vector search (pgvector)
        vector_results = await db.rag_search(embedding, limit=20)  # Over-fetch

        # 2. BM25 keyword search
        bm25_scores = bm25.get_scores(tokenize(query))

        # 3. Re-rank by combining scores
        combined = [
            {**r, "score": 0.7 * r["similarity"] + 0.3 * bm25_scores[i]}
            for i, r in enumerate(vector_results)
        ]

        # 4. Return top-k
        return sorted(combined, key=lambda x: x["score"], reverse=True)[:limit]
```

**Benefits**:
- ✅ 15-20% improvement in retrieval accuracy
- ✅ Better exact-match handling (ICAO codes, flight numbers)
- ✅ Complementary strengths (semantic + lexical)

**Effort**: 2-3 days
**Priority**: High
**Dependencies**: `rank-bm25` package

---

## Phase 10: Time-Series Weather Forecasting

### Goal
Store and forecast weather trends (wind, temperature, visibility) per airport using historical METAR data.

### Use Cases
- "What's the typical wind speed at EGLL in January?"
- "Forecast next 6 hours based on last 24 hours of METAR"
- "Show me wind trends for the past week"

### Implementation

**Database** (new table):
```sql
CREATE TABLE weather_timeseries (
    id SERIAL PRIMARY KEY,
    icao VARCHAR(4),
    timestamp TIMESTAMPTZ,
    wind_speed INT,
    wind_direction INT,
    temperature INT,
    visibility INT,
    flight_category VARCHAR(10)  -- VFR, MVFR, IFR, LIFR
);

CREATE INDEX idx_weather_ts ON weather_timeseries (icao, timestamp DESC);
```

**Forecasting** (Prophet or statsmodels):
```python
from prophet import Prophet

def forecast_wind(icao: str, hours: int = 6):
    # Fetch last 7 days of METAR
    df = await db.fetch_timeseries(icao, days=7)

    # Train Prophet model
    model = Prophet()
    model.fit(df[["timestamp", "wind_speed"]])

    # Forecast next N hours
    future = model.make_future_dataframe(periods=hours, freq='H')
    forecast = model.predict(future)

    return forecast[["ds", "yhat", "yhat_lower", "yhat_upper"]]
```

**Frontend** (Chart.js or Recharts):
```tsx
<LineChart data={forecastData}>
  <Line dataKey="wind_speed" stroke="blue" />
  <Line dataKey="forecast" stroke="red" strokeDasharray="5 5" />
</LineChart>
```

**Benefits**:
- ✅ Predictive insights for flight planning
- ✅ Trend analysis (seasonal patterns)
- ✅ Anomaly detection (unusual weather events)

**Effort**: 1 week
**Priority**: Medium
**Dependencies**: Prophet/statsmodels, timeseries DB schema

---

## Phase 11: Webhooks & Real-Time Alerts

### Goal
Push notifications for critical events (weather warnings, safety alerts, flight delays).

### Architecture
```
┌──────────────┐       ┌───────────────┐       ┌──────────────┐
│ Ingestion    │  -->  │ Event Broker  │  -->  │ Webhook      │
│ (METAR/TAF)  │       │ (Redis Pub/   │       │ Dispatcher   │
│              │       │  Sub or Kafka)│       │              │
└──────────────┘       └───────────────┘       └──────┬───────┘
                                                       │
                                    ┌──────────────────┼──────────────────┐
                                    │                  │                  │
                              ┌─────▼─────┐     ┌─────▼─────┐     ┌─────▼─────┐
                              │ Email     │     │ Slack     │     │ Push      │
                              │           │     │           │     │ Notification│
                              └───────────┘     └───────────┘     └───────────┘
```

### Implementation

**Event Detection**:
```python
# agent/ingestion/metar_ingestor.py
async def ingest_metar(icao: str):
    new_metar = fetch_metar(icao)
    old_metar = await db.get_latest_metar(icao)

    # Detect significant changes
    if new_metar["flight_category"] == "LIFR" and old_metar["flight_category"] != "LIFR":
        await event_bus.publish("weather_warning", {
            "icao": icao,
            "type": "LIFR_alert",
            "message": f"{icao} deteriorated to LIFR conditions"
        })
```

**Webhook Dispatcher**:
```python
# agent/webhooks.py
async def dispatch_webhook(event: dict):
    for subscriber in await db.get_subscribers(event["type"]):
        try:
            await httpx.post(subscriber["url"], json=event, timeout=5)
        except Exception as e:
            logger.error("Webhook failed: %s", e)
```

**Subscription Management**:
```bash
POST /api/webhooks/subscribe
{
  "url": "https://my-app.com/webhook",
  "events": ["weather_warning", "safety_alert"],
  "filters": {"icao": ["EGLL", "KJFK"]}  # Optional: filter by airport
}
```

**Benefits**:
- ✅ Real-time alerting for critical events
- ✅ Integrations (Slack, email, PagerDuty)
- ✅ Proactive notifications (vs reactive queries)

**Effort**: 1 week
**Priority**: Medium
**Dependencies**: Redis Pub/Sub or Kafka

---

## Phase 12: RBAC (Role-Based Access Control)

### Goal
Multi-tenant deployments with role-based permissions (Admin, Pilot, Dispatcher, Read-Only).

### Use Cases
- **Airlines**: Each airline has isolated data
- **Flight Schools**: Instructors see all, students see own data
- **APIs**: Public endpoints (read-only) vs private (write)

### Implementation

**Database** (new tables):
```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE,
    password_hash VARCHAR(255),
    role VARCHAR(50),  -- admin, pilot, dispatcher, readonly
    tenant_id INT REFERENCES tenants(id)
);

CREATE TABLE tenants (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Row-level security (RLS) policies
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON conversations
    USING (tenant_id = current_setting('app.tenant_id')::INT);
```

**Authentication** (FastAPI):
```python
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer

security = HTTPBearer()

async def get_current_user(token: str = Depends(security)) -> User:
    payload = jwt.decode(token.credentials, SECRET_KEY)
    user = await db.get_user(payload["user_id"])
    if not user:
        raise HTTPException(401, "Invalid token")
    return user

@app.post("/api/agent")
async def chat_endpoint(
    request: Request,
    user: User = Depends(get_current_user)
):
    # Check permissions
    if user.role not in ["admin", "pilot", "dispatcher"]:
        raise HTTPException(403, "Insufficient permissions")

    # Set tenant context
    await db.execute("SET app.tenant_id = $1", user.tenant_id)

    # Normal endpoint logic...
```

**Frontend** (JWT storage):
```typescript
// Login
const { token } = await fetch("/api/auth/login", {
  method: "POST",
  body: JSON.stringify({ email, password })
}).then(r => r.json());

localStorage.setItem("auth_token", token);

// Authenticated requests
fetch("/api/agent", {
  headers: {
    "Authorization": `Bearer ${token}`
  }
});
```

**Benefits**:
- ✅ Multi-tenant support
- ✅ Secure API access
- ✅ Audit trails (who accessed what)

**Effort**: 2 weeks
**Priority**: Low (unless multi-tenant needed)
**Dependencies**: JWT library, password hashing (bcrypt)

---

## Phase 13: Advanced Visualizations

### Goal
Interactive charts, maps, and dashboards for weather/flight data.

### Visualizations

**1. Airport Map** (Leaflet or Mapbox):
```tsx
import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet';

<MapContainer center={[51.5, 0]} zoom={6}>
  <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
  {airports.map(airport => (
    <Marker key={airport.icao} position={[airport.lat, airport.lon]}>
      <Popup>{airport.name} - {airport.weather}</Popup>
    </Marker>
  ))}
</MapContainer>
```

**2. Weather Trends** (Recharts):
```tsx
<LineChart data={metarHistory}>
  <XAxis dataKey="timestamp" />
  <YAxis />
  <Line dataKey="wind_speed" stroke="#8884d8" />
  <Line dataKey="temperature" stroke="#82ca9d" />
  <Tooltip />
</LineChart>
```

**3. Flight Paths** (ReactFlow or D3):
```tsx
// Show aircraft trajectory from ADS-B data
<ReactFlow nodes={flightPath} edges={routes}>
  <Background />
  <Controls />
</ReactFlow>
```

**4. Safety Incident Heatmap** (Apache ECharts):
```tsx
<HeatMap
  data={incidentsByLocation}
  colorScale={['#00ff00', '#ff0000']}  // green (safe) → red (dangerous)
/>
```

**Benefits**:
- ✅ Better data exploration
- ✅ Spatial insights (map-based)
- ✅ Trend identification

**Effort**: 1 week
**Priority**: Medium
**Dependencies**: Leaflet/Mapbox, Recharts/ECharts

---

## Phase 14: Performance Optimizations

### 1. Query Optimization

**PostgreSQL**:
- Partial indexes for hot queries:
  ```sql
  CREATE INDEX idx_metar_recent ON metar_history (icao, obs_time DESC)
  WHERE obs_time > NOW() - INTERVAL '7 days';
  ```
- Materialized views for aggregations:
  ```sql
  CREATE MATERIALIZED VIEW airport_stats AS
  SELECT icao, AVG(wind_speed) as avg_wind, COUNT(*) as metar_count
  FROM metar_history
  GROUP BY icao;
  ```

**Redis**:
- Connection pooling (already done)
- Pipelining for batch operations:
  ```python
  pipe = redis.pipeline()
  for key in keys:
      pipe.get(key)
  results = await pipe.execute()
  ```

### 2. LLM Optimization

**Prompt caching** (Anthropic, OpenAI):
```python
# Cache system prompt (static)
response = await llm.ainvoke([
    SystemMessage(content=AVIATION_PROMPT, cache_control={"type": "ephemeral"}),
    HumanMessage(content=user_query)
])
```

**Parallel tool calls** (LangGraph):
```python
# Execute multiple tools concurrently
from langgraph.prebuilt import ToolNode

tool_node = ToolNode(tools, parallel=True)  # Run tools in parallel
```

### 3. Frontend Optimization

**Code splitting**:
```typescript
// Lazy load heavy components
const WorkflowView = lazy(() => import('./components/workflow/WorkflowView'));
const LogsView = lazy(() => import('./components/logs/LogsView'));
```

**Virtual scrolling** (react-window):
```tsx
import { FixedSizeList } from 'react-window';

<FixedSizeList height={600} itemCount={events.length} itemSize={50}>
  {({ index, style }) => (
    <div style={style}>{events[index]}</div>
  )}
</FixedSizeList>
```

**Benefits**:
- ✅ 30-50% latency reduction
- ✅ Lower infrastructure costs
- ✅ Better user experience

**Effort**: 1 week
**Priority**: High
**Dependencies**: None

---

## Phase 15: Advanced Agent Capabilities

### 1. Multi-Turn Planning

**Goal**: Break complex queries into sub-tasks and execute sequentially.

**Example**:
```
User: "Compare weather at EGLL and KJFK, then find the best flight time."

Plan:
1. Get METAR/TAF for EGLL
2. Get METAR/TAF for KJFK
3. Analyze flight categories
4. Recommend optimal departure time
```

**Implementation** (LangGraph):
```python
class PlanExecuteState(TypedDict):
    plan: List[str]
    past_steps: List[Tuple[str, str]]
    response: str

def create_plan(state):
    # LLM generates step-by-step plan
    plan = await planner_llm.ainvoke(f"Break down: {state['input']}")
    return {"plan": parse_plan(plan)}

def execute_step(state):
    step = state["plan"][0]
    result = await executor_agent.ainvoke(step)
    return {
        "past_steps": [*state["past_steps"], (step, result)],
        "plan": state["plan"][1:]  # Remove completed step
    }

graph.add_node("plan", create_plan)
graph.add_node("execute", execute_step)
graph.add_conditional_edges("execute", lambda s: "execute" if s["plan"] else END)
```

### 2. Tool Composition

**Goal**: Agents can create new tools by composing existing ones.

**Example**:
```python
# Agent creates a composite tool
composite_tool = ToolComposer.create(
    name="get_full_weather_brief",
    steps=[
        ("lookup_airport_codes", {"location": "{location}"}),
        ("get_metar", {"icao": "{result[0].icao}"}),
        ("get_taf", {"icao": "{result[0].icao}"}),
        ("get_pireps", {"icao": "{result[0].icao}"}),
    ]
)
```

### 3. Self-Healing Agents

**Goal**: Agents recover from errors automatically.

**Example**:
```python
def execute_with_retry(tool, params, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await tool(**params)
        except Exception as e:
            if attempt < max_retries - 1:
                # Ask LLM to fix params
                fixed_params = await fixer_llm.ainvoke({
                    "error": str(e),
                    "params": params
                })
                params = fixed_params
            else:
                raise
```

**Benefits**:
- ✅ Handle complex queries
- ✅ Reduce manual intervention
- ✅ More autonomous agents

**Effort**: 2 weeks
**Priority**: Low
**Dependencies**: Advanced LangGraph patterns

---

## Priority Matrix

| Phase | Feature | Priority | Effort | Impact |
|-------|---------|----------|--------|--------|
| 9 | BM25 Re-ranker | ⭐⭐⭐ High | 2-3 days | +15-20% RAG accuracy |
| 10 | Time-Series Forecasting | ⭐⭐ Medium | 1 week | Predictive insights |
| 11 | Webhooks & Alerts | ⭐⭐ Medium | 1 week | Real-time notifications |
| 12 | RBAC | ⭐ Low | 2 weeks | Multi-tenancy |
| 13 | Advanced Visualizations | ⭐⭐ Medium | 1 week | Better UX |
| 14 | Performance Opts | ⭐⭐⭐ High | 1 week | 30-50% latency reduction |
| 15 | Advanced Agents | ⭐ Low | 2 weeks | Complex reasoning |

---

## Recommended Next Steps

**Immediate (1-2 weeks)**:
1. Performance optimizations (Phase 14) — quick wins
2. BM25 re-ranker (Phase 9) — improves RAG accuracy

**Short-term (1-2 months)**:
3. Time-series forecasting (Phase 10) — adds predictive capabilities
4. Advanced visualizations (Phase 13) — enhances UX
5. Webhooks & alerts (Phase 11) — real-time features

**Long-term (3+ months)**:
6. RBAC (Phase 12) — only if multi-tenancy needed
7. Advanced agents (Phase 15) — research/experimental

---

## Conclusion

The platform is production-ready with Phases 1-8 complete. Future enhancements focus on:
- **Performance** (caching, query optimization)
- **Intelligence** (BM25 re-ranker, forecasting)
- **User Experience** (visualizations, alerts, mobile)
- **Scale** (RBAC, multi-tenancy)

Each phase is modular and can be implemented independently. Prioritize based on user feedback and business requirements.
