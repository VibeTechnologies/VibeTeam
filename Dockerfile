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

# Copy package files
COPY pyproject.toml README.md ./
COPY vibeteam/ ./vibeteam/

# Install package
RUN pip install --no-cache-dir -e .

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
COPY --from=builder /usr/share/keyrings/githubcli-archive-keyring.gpg /usr/share/keyrings/

# Copy installed packages
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/vibeteam /usr/local/bin/vibeteam

# Copy application code
COPY --from=builder /app/vibeteam /app/vibeteam
COPY --from=builder /app/pyproject.toml /app/

# Create non-root user
RUN useradd -m -u 1000 vibeteam
USER vibeteam

# Expose gateway port
EXPOSE 8080

# Default command runs the gateway server
# Override with different commands for CLI usage
ENTRYPOINT ["python", "-m", "vibeteam.gateway.server"]
CMD []
