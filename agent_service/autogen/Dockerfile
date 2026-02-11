# AutoGen Agent Service Dockerfile
# Python 3.12 with AutoGen framework - FastAPI Server Mode

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
COPY agents/shared/ ./agents/shared/
COPY agents/autogen/ ./agents/autogen/

# Copy vibeteam connectors (for Sentry, Langfuse, etc.)
COPY vibeteam/__init__.py ./vibeteam/
COPY vibeteam/connectors/ ./vibeteam/connectors/

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
COPY --from=builder /usr/local/bin/uvicorn /usr/local/bin/uvicorn

# Copy application code
COPY --from=builder /app/agents /app/agents
COPY --from=builder /app/vibeteam /app/vibeteam

# Create non-root user
RUN useradd -m -u 1000 vibeteam
USER vibeteam

# Environment variables (override at runtime)
ENV AZURE_API_KEY=""
ENV AZURE_API_BASE=""
ENV AZURE_API_VERSION="2024-08-01-preview"
ENV DATABASE_URL=""
ENV PYTHONPATH="/app"
ENV PORT="8080"
ENV HOST="0.0.0.0"

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run the FastAPI server
CMD ["python", "-m", "uvicorn", "agents.autogen.server:app", "--host", "0.0.0.0", "--port", "8080"]
