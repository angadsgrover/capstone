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

## Optional LangChain/LangGraph Backend

The frontend can call a LangChain/LangGraph-compatible run endpoint directly instead of `POST /api/agent`.

Set these environment variables (for example in `.env.local`):

```bash
VITE_LANGCHAIN_ENABLED=true
VITE_LANGCHAIN_BASE_URL=https://your-agent-server.example.com
VITE_LANGCHAIN_RUN_ENDPOINT=/runs/wait
VITE_LANGCHAIN_ASSISTANT_ID=assistant_xxx
VITE_LANGCHAIN_API_KEY=your_token_if_required
```

When enabled, chat requests try LangChain first and automatically fall back to the local agent API if LangChain is unreachable or misconfigured.

Planning-aware fields/events handled by the UI:

- `route`
- `plan`
- `execution_trace`
- `thinking`
- `tool_start` / `tool_end`

## Voice Chat Tuning (TTS)

The voice assistant uses browser speech synthesis with improved handling:
- Preferred voice selection by name/language
- Chunked playback for long responses (fewer cut-offs)
- Duplicate-speech suppression for rapid updates
- Persistent auto-speak preference in browser local storage

Optional frontend environment variables (for example in `.env.local`):

```bash
VITE_LIVEKIT_AUTO_SPEAK=true
VITE_TTS_VOICE_NAME=Microsoft Aria Online (Natural) - English (United States)
VITE_TTS_LANG=en-US
VITE_TTS_RATE=0.96
VITE_TTS_PITCH=1.0
VITE_TTS_VOLUME=1.0
```

Notes:
- `VITE_TTS_VOICE_NAME` is best-effort and depends on voices available in the user's browser/OS.
- If the exact voice is not found, the app falls back to high-quality English voices and then language/default voices.

Optional neural TTS output (server-generated audio):

```bash
VITE_NEURAL_TTS_ENABLED=true
VITE_NEURAL_TTS_PREFER=true
VITE_NEURAL_TTS_MODEL=gpt-4o-mini-tts
VITE_NEURAL_TTS_VOICE=alloy
VITE_NEURAL_TTS_FORMAT=mp3
```

Neural TTS calls `POST /api/tts` and falls back to browser TTS automatically if neural synthesis fails or is unavailable.

## Important Paths

- `src/components/chat`: chat rendering and stream handling
- `src/components/workflow`: route/tool/step visualization
- `src/components/visualizations`: weather/safety/flight visuals
- `src/shared/services`: API clients and SSE parsers
- `src/shared/types`: request/response/event contracts
