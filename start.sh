#!/bin/bash
set -e

echo "=========================================="
echo "Starting Natural Language Workflow Engine"
echo "=========================================="

# Start FastAPI in background
echo "Starting FastAPI backend on port 8000..."
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# Wait for backend to be healthy
echo "Waiting for backend health check..."
for i in {1..30}; do
    if curl -s http://localhost:8000/api/health > /dev/null 2>&1; then
        echo "FastAPI backend is ready!"
        break
    fi
    sleep 1
done

# Graceful termination handler
trap "kill -TERM $BACKEND_PID 2>/dev/null" SIGTERM SIGINT

# Start Streamlit in foreground
echo "Starting Streamlit frontend on port 8501..."
streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true &
FRONTEND_PID=$!

# Wait for either process to exit
wait -n $BACKEND_PID $FRONTEND_PID
EXIT_CODE=$?

kill -TERM $BACKEND_PID 2>/dev/null || true
kill -TERM $FRONTEND_PID 2>/dev/null || true
exit $EXIT_CODE
