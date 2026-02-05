#!/bin/bash
# Development entrypoint that pulls fresh code from GitHub on startup
# This allows fast iteration without rebuilding Docker images

set -e

REPO_URL="${GITHUB_REPO_URL:-https://github.com/VibeTechnologies/VibeTeam.git}"
BRANCH="${GITHUB_BRANCH:-master}"
CODE_DIR="/app/code"

echo "=== VibeTeam CrewAI Dev Mode ==="
echo "Repo: $REPO_URL"
echo "Branch: $BRANCH"

# Clone or pull latest code
if [ -d "$CODE_DIR/.git" ]; then
    echo "Pulling latest changes..."
    cd "$CODE_DIR"
    git fetch origin
    git reset --hard "origin/$BRANCH"
else
    echo "Cloning repository..."
    git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$CODE_DIR"
fi

# Set up Python path to use fresh code
export PYTHONPATH="$CODE_DIR:$PYTHONPATH"

echo "Code updated at $(date)"
echo "Starting server..."

# Run the server with the fresh code
cd "$CODE_DIR"
exec python -m uvicorn agents.crewai.server:app --host 0.0.0.0 --port 8080
