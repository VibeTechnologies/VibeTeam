#!/bin/bash
set -e

# Pull latest code from git if REPO_URL is set
if [ -n "$GIT_REPO_URL" ]; then
    echo "Pulling latest code from $GIT_REPO_URL (branch: ${GIT_BRANCH:-master})..."
    cd /app/repo
    git fetch origin
    git reset --hard origin/${GIT_BRANCH:-master}
    echo "Code updated to: $(git rev-parse --short HEAD)"
fi

# Execute the main command
exec "$@"
