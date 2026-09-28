#!/bin/bash
set -e

echo "=========================================="
echo "Starting Natural Language Workflow Engine"
echo "=========================================="

PORT=${PORT:-8501}
BACKEND_PORT=8000

echo "Starting FastAPI backend on port $BACKEND_PORT in background..."
uvicorn src.api.main:app --host 0.0.0.0 --port $BACKEND_PORT &
BACKEND_PID=$!

trap "kill -TERM $BACKEND_PID 2>/dev/null" SIGTERM SIGINT

echo "Starting Streamlit frontend on port $PORT..."
exec streamlit run app.py \
    --server.port "$PORT" \
    --server.address 0.0.0.0 \
    --server.headless true \
    --server.enableCORS false \
    --server.enableXsrfProtection false
