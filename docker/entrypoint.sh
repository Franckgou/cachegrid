#!/bin/bash
# docker/entrypoint.sh
# Entrypoint script for CacheGrid container

set -e

# Default values
CACHEGRID_NODE_ID=${CACHEGRID_NODE_ID:-"node-1"}
CACHEGRID_MAX_SIZE=${CACHEGRID_MAX_SIZE:-10000}
CACHEGRID_MAX_MEMORY_MB=${CACHEGRID_MAX_MEMORY_MB:-512}
CACHEGRID_CLEANUP_INTERVAL=${CACHEGRID_CLEANUP_INTERVAL:-60}
CACHEGRID_LOG_LEVEL=${CACHEGRID_LOG_LEVEL:-"info"}
CACHEGRID_HOST=${CACHEGRID_HOST:-"0.0.0.0"}
CACHEGRID_PORT=${CACHEGRID_PORT:-8080}

# Export environment variables
export CACHEGRID_NODE_ID
export CACHEGRID_MAX_SIZE
export CACHEGRID_MAX_MEMORY_MB
export CACHEGRID_CLEANUP_INTERVAL
export CACHEGRID_LOG_LEVEL
export CACHEGRID_HOST
export CACHEGRID_PORT

echo "🚀 Starting CacheGrid with configuration:"
echo "  Node ID: $CACHEGRID_NODE_ID"
echo "  Max Size: $CACHEGRID_MAX_SIZE"
echo "  Max Memory: ${CACHEGRID_MAX_MEMORY_MB}MB"
echo "  Host: $CACHEGRID_HOST"
echo "  Port: $CACHEGRID_PORT"
echo "  Log Level: $CACHEGRID_LOG_LEVEL"

# Handle different startup modes
case "$1" in
    "api")
        echo "Starting CacheGrid API server..."
        cd /app
        exec python -m uvicorn src.cachegrid.api.server:app \
            --host $CACHEGRID_HOST \
            --port $CACHEGRID_PORT \
            --log-level $CACHEGRID_LOG_LEVEL
        ;;
    "test")
        echo "Running CacheGrid tests..."
        cd /app
        exec python -m pytest tests/ -v
        ;;
    *)
        echo "Usage: $0 {api|test}"
        echo "Starting API server by default..."
        cd /app
        exec python -m uvicorn src.cachegrid.api.server:app \
            --host $CACHEGRID_HOST \
            --port $CACHEGRID_PORT \
            --log-level $CACHEGRID_LOG_LEVEL
        ;;
esac
