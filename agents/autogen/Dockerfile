# AutoGen Agent Service Dockerfile
# Python 3.12 with AutoGen framework

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
COPY agents/autogen/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared agent code
COPY agents/__init__.py ./agents/
COPY agents/config.py ./agents/
COPY agents/sessions.py ./agents/
COPY agents/metrics.py ./agents/
COPY agents/autogen/ ./agents/autogen/

# Production stage
FROM python:3.12-slim

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
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

# Environment variables (override at runtime)
ENV AZURE_API_KEY=""
ENV AZURE_API_BASE=""
ENV AZURE_API_VERSION="2024-08-01-preview"
ENV PYTHONPATH="/app"

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "from agents.autogen import AutoGenReleaseEngineer; print('OK')"

# Default command - can be overridden
CMD ["python", "-c", "print('AutoGen agent service ready')"]
