# VibeTeam Agents Docker Image
# Multi-stage build for smaller image size

FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
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

# Copy package files
COPY pyproject.toml uv.lock README.md ./
COPY vibeteam/ ./vibeteam/
COPY agents/ ./agents/
COPY scripts/ ./scripts/
COPY docs/ ./docs/

# Install dependencies with uv
RUN uv sync --frozen --no-dev

# Production stage
FROM python:3.12-slim

WORKDIR /app

# Install runtime dependencies (git for agent operations, curl for health checks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy GitHub CLI from builder
COPY --from=builder /usr/bin/gh /usr/bin/gh
COPY --from=builder /usr/share/keyrings/githubcli-archive-keyring.gpg /usr/share/keyrings/

# Copy uv and virtual environment from builder
COPY --from=builder /usr/local/bin/uv /usr/local/bin/uv
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY --from=builder /app/vibeteam ./vibeteam
COPY --from=builder /app/agents ./agents
COPY --from=builder /app/scripts ./scripts
COPY --from=builder /app/docs ./docs
COPY --from=builder /app/pyproject.toml ./

# Set environment
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app"

# Create non-root user
RUN useradd -m -u 1000 vibeteam
USER vibeteam

# Expose gateway port
EXPOSE 8080

# Default command runs the gateway server
# Override with different commands for CLI usage or agent scripts
ENTRYPOINT ["python", "-m", "vibeteam.gateway.server"]
CMD []
