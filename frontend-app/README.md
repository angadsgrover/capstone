# Frontend App (Vite + React 19)

This app is the operator UI for the Aviation Intelligence Platform. It provides chat, workflow telemetry, logs, and pilot-oriented visualizations.

## Capabilities

- Streaming chat responses
- Workflow timeline and graph visualization
- Tool-call and reasoning trace rendering
- Multi-step planning visibility (Phase 15)
- Pilot-friendly dashboards and trends (Phase 13)
- Performance-focused UI patterns such as virtualized logs and split views (Phase 14)

## Stack

- Vite + React 19 + TypeScript
- ReactFlow for workflow visualization
- Zustand for state management
- Tailwind-based styling and reusable UI components

## Run Locally

From `frontend-app`:

```bash
npm install
npm run dev
```

Production build:

```bash
npm run build
npm run preview
```

## API Contracts Consumed

- `POST /api/agent`
- `GET /api/agent/stream`
- `POST /api/agent/execute`
- `GET /api/agent/events`

Planning-aware fields/events handled by the UI:

- `route`
- `plan`
- `execution_trace`
- `thinking`
- `tool_start` / `tool_end`

## Important Paths

- `src/components/chat`: chat rendering and stream handling
- `src/components/workflow`: route/tool/step visualization
- `src/components/visualizations`: weather/safety/flight visuals
- `src/shared/services`: API clients and SSE parsers
- `src/shared/types`: request/response/event contracts
