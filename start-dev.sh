#!/bin/bash
# Start the Agent service in the background
cd ./agent
source .venv/bin/activate
source .env
echo "Starting Agent and Server on port 8000..."
python -m uvicorn server:app --host 0.0.0.0 --port 8000 &
AGENT_PID=$!

# Wait a moment for the server to start
sleep 15

# Start the frontend
cd ../frontend-app
echo "Starting frontend on port 3000..."
npm run dev

# Kill the Agent service when the script exits
trap 'kill $AGENT_PID' EXIT
