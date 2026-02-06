# VibeTeam Agents Docker Image
# Pulls latest code from git on startup for rapid iteration

FROM python:3.12-slim

WORKDIR /app

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install GitHub CLI for agent operations
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && apt-get update \
    && apt-get install -y gh \
    && rm -rf /var/lib/apt/lists/*

# Install uv for dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Clone repository (will be updated on startup)
ARG GIT_REPO_URL=https://github.com/VibeTechnologies/VibeTeam.git
ARG GIT_BRANCH=master
RUN git clone --depth 1 --branch ${GIT_BRANCH} ${GIT_REPO_URL} /app/repo

WORKDIR /app/repo

# Install dependencies with uv
RUN uv sync --frozen --no-dev

# Copy entrypoint script
COPY scripts/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Set environment
ENV PATH="/app/repo/.venv/bin:$PATH"
ENV PYTHONPATH="/app/repo"
ENV GIT_REPO_URL=${GIT_REPO_URL}
ENV GIT_BRANCH=${GIT_BRANCH}

# Expose gateway port
EXPOSE 8080

# Entrypoint pulls latest code, then runs command
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "vibeteam.gateway.server"]
