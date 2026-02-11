# OpenHands Agent Service Dockerfile
# Python 3.12+ required for OpenHands

FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install GitHub CLI for agent operations
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && apt-get update \
    && apt-get install -y gh \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY agents/openhands/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared agent code
COPY agents/__init__.py ./agents/
COPY agents/config.py ./agents/
COPY agents/sessions.py ./agents/
COPY agents/metrics.py ./agents/
COPY agents/shared/ ./agents/shared/
COPY agents/openhands/ ./agents/openhands/

# Production stage
FROM python:3.12-slim

WORKDIR /app

# Install runtime dependencies including kubectl
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    && KUBECTL_VERSION="v1.31.4" \
    && curl -LO "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" \
    && install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl \
    && rm kubectl \
    && rm -rf /var/lib/apt/lists/*

# Copy GitHub CLI from builder
COPY --from=builder /usr/bin/gh /usr/bin/gh

# Copy installed packages
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages

# Copy application code
COPY --from=builder /app/agents /app/agents

# Create non-root user
RUN useradd -m -u 1000 vibeteam
USER vibeteam

# Configure Git for the agent
# Note: gh auth setup-git requires authentication, so we configure the
# credential helper directly. At runtime, GITHUB_TOKEN env var enables gh auth.
RUN git config --global user.email "agent@vibebrowser.app" \
    && git config --global user.name "VibeTeam Agent" \
    && git config --global credential.https://github.com.helper '!/usr/bin/gh auth git-credential'

# Environment variables (override at runtime)
ENV AZURE_API_KEY=""
ENV AZURE_API_BASE=""
ENV AZURE_API_VERSION="2024-08-01-preview"
ENV PYTHONPATH="/app"
ENV GH_PAGER=""
ENV GH_NO_UPDATE_NOTIFIER="1"
ENV CI="true"

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Expose port
EXPOSE 8080

# Default command - run FastAPI server
CMD ["python", "-m", "agents.openhands.server"]
