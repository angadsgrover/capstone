# Aviation and Weather Agent

## Overview

This system provides advanced workflow orchestration and visualization for weather data using Pydantic AI based Agent and Model Context Protocol (MCP) servers. It integrates aviation and Hong Kong climate data, supports multi-agent reasoning, and offers a modern Next.js based frontend for text based interaface with the agent.

---

### How to Use the Chat Interface

1. **Start the frontend** (see setup below).
2. Open [http://localhost:3000](http://localhost:3000) in your browser.
3. The chat panel appears on the right side of the dashboard.
4. Type your question (e.g., "What's the current weather at Hong Kong International Airport?") and press **Send**.
5. The agent's response will appear in the chat window.

### Integration with Workflow Visualization

- The chat interface is tightly integrated with the workflow visualizer.
- When you submit a query, the backend orchestrates the workflow, and the visualizer updates in real time to show each step (e.g., data retrieval, analysis, response).
- This provides transparency into how the agent processes your request.

### Example Usage

- Ask: `What weather warnings are active in Hong Kong?`
- The agent responds in the chat, and the workflow diagram updates to show the steps taken.
- You can interactively explore different queries and see both the conversation and the workflow execution.

### Dependencies & Setup

- The chat interface uses React, Next.js, and CopilotKit UI components.
- All dependencies are included in `frontend-app/package.json`.
- No additional setup is required beyond the standard frontend installation:
  ```bash
  cd frontend-app
  npm install
  npm run dev
  ```
- The chat UI communicates with the backend via `/api/agent`.

---
## 1. Setup Instructions

### Backend (LangGraph Orchestration)

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Ensure both MCP servers are available:
   - Aviation Weather MCP Server: `/path/to/aviation-weather-mcp-python`
   - HK Climate MCP Server: `/path/to/hk-climate-mcp-server-python`
3. Set up environment variables in `.env`:
   ```
   LLM_API_KEY=your_api_key_here
   MODEL_CHOICE=gpt-4o-mini
   BASE_URL=https://api.openai.com/v1
   ```
4. Update `mcp_config.json` with MCP server module paths if needed.

### Frontend (Next.js/CopilotKit)

1. Install dependencies:
   ```bash
   npm install
   ```
2. Start the frontend:
   ```bash
   npm run dev
   ```

---

## 2. Configuration & Environment Variables

- `.env` (backend):  
  - `LLM_API_KEY` – API key for LLM provider  
  - `MODEL_CHOICE` – Model name (e.g., gpt-4o-mini)  
  - `BASE_URL` – LLM API base URL

- `mcp_config.json` (backend):  
  - Defines MCP server commands and arguments.
  - Update the `PYTHON_PATH` in the json file based on your local relative path.


## 3. Usage Instructions

- **Run backend orchestration:**
  ```bash
  python main.py
  ```
- **Access frontend:**
  Open [http://localhost:3000](http://localhost:3000) (or configured port).

### Interacting with the Agent via Web UI

- Use the chat panel on the right to send questions to the agent.
- Example queries:
  - "What's the current weather at Hong Kong International Airport?"
  - "Compare aviation weather with general HK weather conditions"
  - "What weather warnings are active in Hong Kong?"
- The agent's response will appear in the chat window, and the workflow visualization will update to show each step taken.

