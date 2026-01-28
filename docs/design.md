# VibeTeam Agent Microservices Architecture

**Version**: 2.2  
**Date**: January 2026  
**Status**: Complete

---

## Overview

VibeTeam is a multi-framework AI agent system that automates software engineering workflows. The architecture consists of:

1. **Three agent frameworks** - AutoGen, CrewAI, and OpenHands running as separate microservices
2. **Centralized gateway** - Routes webhooks and API requests to appropriate agents
3. **Task scheduler** - APScheduler with PostgreSQL for persistent job scheduling
4. **Session persistence** - PostgreSQL database for conversation history

This replaces the previous CronJob-based approach with long-running services that support dynamic task scheduling and human-in-the-loop workflows.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     External Events                                          │
│  GitHub Webhooks │ Slack Events │ Sentry Alerts │ REST API                   │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                  vibeteam-gateway (FastAPI)                                  │
│  - Routes to agent services   - WebSocket streaming                          │
│  - GitHub/Slack/Sentry hooks  - REST API at /api/*                           │
└──────────┬───────────────────────┬───────────────────────┬──────────────────┘
           │                       │                       │
     ┌─────┴─────┐           ┌─────┴─────┐           ┌─────┴─────┐
     ▼           ▼           ▼           ▼           ▼           ▼
┌─────────┐ ┌─────────┐ ┌───────────┐ ┌───────────┐ ┌──────────┐
│ autogen │ │ crewai  │ │ openhands │ │ scheduler │ │ postgres │
│  -svc   │ │  -svc   │ │   -svc    │ │   -svc    │ │          │
│ :8080   │ │ :8080   │ │  :8080    │ │  :8080    │ │  :5432   │
└─────────┘ └─────────┘ └───────────┘ └───────────┘ └──────────┘
     │           │            │              │            ▲
     └───────────┴────────────┴──────────────┴────────────┘
                              │
                         PostgreSQL
                      (sessions + tasks)
```

---

## Design Decisions

### Why Three Agent Frameworks?

| Framework | Strengths | Best For |
|-----------|-----------|----------|
| **AutoGen** | Multi-agent conversations, tool calling | Complex workflows requiring agent collaboration |
| **CrewAI** | Role-based crews, structured output | Defined processes with clear responsibilities |
| **OpenHands** | Code generation, file manipulation | Software engineering tasks, code review |

The gateway selects the appropriate framework based on the task type or explicit request.

### Why Microservices vs Monolith?

1. **Independent scaling** - Each framework has different resource needs
2. **Isolation** - Framework-specific dependencies don't conflict
3. **Resilience** - One framework failure doesn't affect others
4. **Deployment flexibility** - Update frameworks independently

### Why APScheduler vs Kubernetes CronJobs?

1. **Dynamic scheduling** - Agents can schedule follow-up tasks at runtime
2. **Persistence** - Jobs survive pod restarts via PostgreSQL
3. **Visibility** - REST API for job management
4. **Flexibility** - Supports cron, interval, and one-time triggers

### Why PostgreSQL?

1. **Session continuity** - Agents resume conversations across restarts
2. **Single database** - Simplifies operations (vs Redis + SQLite)
3. **APScheduler support** - Built-in SQLAlchemy data store
4. **k3s compatible** - Works with local-path storage class

---

## Components

### 1. Agent Microservices

Each agent service (autogen-svc, crewai-svc, openhands-svc) is a FastAPI application:

**Endpoints:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check (liveness/readiness probes) |
| `/run` | POST | Execute task synchronously |
| `/run/stream` | POST | Execute task with SSE streaming |
| `/sessions/{id}` | GET | Get session by ID |
| `/sessions` | GET | List sessions with optional prefix filter |

**Request Schema (`/run`):**
```json
{
  "task": "Analyze Sentry errors from the past week",
  "role": "support_engineer",
  "context_type": "api",
  "context_id": "optional-session-key"
}
```

**Response Schema:**
```json
{
  "response": "I found 15 errors this week...",
  "session_id": "abc123",
  "session_key": "autogen:support_engineer:api:abc123",
  "framework": "autogen",
  "agents_used": ["SupportEngineer"],
  "metadata": {
    "latency_ms": 5600,
    "message_count": 2
  }
}
```

**Agent Roles:**

| Role | Description |
|------|-------------|
| `support_engineer` | Handles Sentry errors, customer support, health monitoring |
| `release_engineer` | Manages releases, changelogs, version bumps |
| `marketing_manager` | Creates release announcements, social content |
| `software_engineer` | Triages issues, reviews PRs, writes code |

### 2. Gateway Service (vibeteam-gateway)

Central entry point for all external events:

**Endpoints:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Gateway health with downstream service status |
| `/webhook` | POST | GitHub webhook handler |
| `/slack/events` | POST | Slack event handler |
| `/sentry/webhook` | POST | Sentry issue/error alerts |
| `/api/run` | POST | Manual task execution |
| `/api/schedule` | POST | Schedule a task |
| `/api/sessions` | GET | List sessions |

**Framework Selection:**
- Explicit: Pass `framework` parameter in request
- Default: Uses `DEFAULT_FRAMEWORK` env var (autogen)
- Role-based: Future - route based on task type

### 3. Scheduler Service (scheduler-svc)

APScheduler with PostgreSQL persistence:

**Endpoints:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check with job count |
| `/tasks` | POST | Schedule a new task |
| `/tasks` | GET | List all scheduled tasks |
| `/tasks/{id}` | GET | Get task details |
| `/tasks/{id}` | DELETE | Cancel a scheduled task |
| `/tasks/{id}/run` | POST | Execute task immediately |

**Schedule Request:**
```json
{
  "task": "Follow up with customer about ticket #789",
  "run_at": "2026-01-28T15:00:00Z",
  "agent_service": "autogen-svc",
  "role": "support_engineer",
  "context_type": "scheduled"
}
```

**Default Recurring Tasks (CronJob replacements):**

| Job ID | Schedule | Description |
|--------|----------|-------------|
| `support-emails` | `*/15 * * * *` | Process Gmail inbox |
| `product-analysis` | `0 */2 * * *` | Analyze feature requests |
| `release-check` | `0 9 * * *` | Check pending releases |
| `health-check` | `*/5 * * * *` | Monitor Sentry/Langfuse |
| `issue-triage` | `0 */4 * * *` | Triage GitHub issues |

### 4. PostgreSQL Database

**Tables:**

| Table | Purpose |
|-------|---------|
| `sessions` | Agent conversation history |
| `apscheduler_*` | APScheduler job storage (auto-created) |

**Session Schema:**
```sql
CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key VARCHAR(255) UNIQUE NOT NULL,
    framework VARCHAR(50) NOT NULL,
    role VARCHAR(50),
    context_type VARCHAR(50),
    context_id VARCHAR(255),
    messages JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

---

## Kubernetes Deployment

### Resource Overview

| Resource Type | Name | Replicas | Purpose |
|--------------|------|----------|---------|
| Deployment | `autogen-svc` | 1 | AutoGen agent server |
| Deployment | `crewai-svc` | 1 | CrewAI agent server |
| Deployment | `openhands-svc` | 1 | OpenHands agent server |
| Deployment | `scheduler-svc` | 1 | APScheduler server |
| Deployment | `vibeteam-gateway` | 1 | Gateway/webhook receiver |
| StatefulSet | `postgres` | 1 | PostgreSQL database |
| PVC | `postgres-pvc` | - | 10Gi persistent storage |

### Resource Limits

| Component | Memory (req/limit) | CPU (req/limit) |
|-----------|-------------------|-----------------|
| Agent services | 512Mi / 1Gi | 250m / 500m |
| Scheduler | 256Mi / 512Mi | 100m / 200m |
| Gateway | 256Mi / 512Mi | 100m / 500m |
| PostgreSQL | 256Mi / 512Mi | 100m / 500m |

### Services (ClusterIP)

| Service | Port | Target |
|---------|------|--------|
| `autogen-svc` | 8080 | autogen pods |
| `crewai-svc` | 8080 | crewai pods |
| `openhands-svc` | 8080 | openhands pods |
| `scheduler-svc` | 8080 | scheduler pods |
| `vibeteam-gateway` | 8080 | gateway pods |
| `postgres` | 5432 | postgres pods |

### Secrets

| Secret | Keys |
|--------|------|
| `postgres-secret` | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `DATABASE_URL` |
| `vibeteam-secrets` | `AZURE_API_KEY`, `AZURE_API_BASE`, `GITHUB_TOKEN`, `SENTRY_AUTH_TOKEN`, `LANGFUSE_*` |
| `ghcr-pull-secret` | Docker registry credentials |
| `github-app-secret` | `app-id`, `private-key`, `installation-id` (optional) |
| `gmail-oauth-secrets` | `gmail-credentials.json`, `gmail-token.json` (optional) |

### Kustomize Structure

```
k8s/
├── base/
│   ├── kustomization.yaml      # Main kustomization
│   ├── postgres.yaml           # StatefulSet + PVC + Secret
│   ├── vibeteam-gateway.yaml   # Gateway deployment + service
│   ├── autogen-svc.yaml        # AutoGen deployment + service
│   ├── crewai-svc.yaml         # CrewAI deployment + service
│   ├── openhands-svc.yaml      # OpenHands deployment + service
│   ├── scheduler-svc.yaml      # Scheduler deployment + service
│   └── frameworks/             # Legacy (deprecated)
└── overlays/
    └── prod/
        └── kustomization.yaml  # Production patches
```

---

## CI/CD Pipeline

### GitHub Actions Workflow (`.github/workflows/deploy.yml`)

**Triggers:**
- Push to `master` or `main` branch
- Changes to: `vibeteam/**`, `agents/**`, `k8s/**`, `Dockerfile`, `pyproject.toml`
- Manual `workflow_dispatch`

**Build Job (matrix strategy):**

| Image | Dockerfile | Context |
|-------|------------|---------|
| `vibeteam` | `Dockerfile` | `.` |
| `vibeteam-autogen` | `agents/autogen/Dockerfile` | `.` |
| `vibeteam-crewai` | `agents/crewai/Dockerfile` | `.` |
| `vibeteam-openhands` | `agents/openhands/Dockerfile` | `.` |
| `vibeteam-scheduler` | `agents/scheduler/Dockerfile` | `.` |

**Image Tags:**
- `ghcr.io/vibetechnologies/vibeteam-<name>:<sha>` (short SHA)
- `ghcr.io/vibetechnologies/vibeteam-<name>:latest` (default branch)
- `ghcr.io/vibetechnologies/vibeteam-<name>:<branch>`

**Deploy Job:**
1. Configure kubectl with `KUBECONFIG` secret
2. Create/update namespace `vibeteam`
3. Create pull secret `ghcr-pull-secret`
4. Create `vibeteam-secrets` from GitHub secrets
5. Update image tags in manifests (sed with SHA)
6. Apply via `kubectl apply -k k8s/base/`
7. Wait for rollout status

### Dockerfile Structure

Each agent Dockerfile uses multi-stage builds:

```dockerfile
# Builder stage - install dependencies
FROM python:3.12-slim AS builder
COPY agents/<framework>/requirements.txt ./
RUN pip install -r requirements.txt
COPY agents/ ./agents/
COPY vibeteam/__init__.py ./vibeteam/
COPY vibeteam/connectors/ ./vibeteam/connectors/

# Production stage - minimal runtime
FROM python:3.12-slim
COPY --from=builder /usr/local/lib/python3.12/site-packages ...
COPY --from=builder /app/agents /app/agents
COPY --from=builder /app/vibeteam /app/vibeteam
CMD ["python", "-m", "uvicorn", "agents.<framework>.server:app", ...]
```

**Key inclusions:**
- `agents/shared/` - Common database, tools, utilities
- `agents/config.py` - Configuration management
- `vibeteam/connectors/` - Sentry, Langfuse, GitHub, Gmail connectors

---

## File Structure

```
VibeTeam/
├── agents/
│   ├── __init__.py
│   ├── config.py               # AgentConfig class
│   ├── sessions.py             # Session management
│   ├── metrics.py              # Metrics collection
│   ├── benchmark.py            # Benchmarking system
│   ├── shared/
│   │   ├── db.py               # PostgreSQL connection
│   │   ├── scheduler_tools.py  # schedule_task tool
│   │   └── docs_tools.py       # Documentation search
│   ├── autogen/
│   │   ├── server.py           # FastAPI server
│   │   ├── team.py             # AutoGenTeam class
│   │   ├── support_engineer.py # SupportEngineer agent
│   │   ├── release_engineer.py
│   │   ├── marketing_manager.py
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   ├── crewai/
│   │   ├── server.py
│   │   ├── crew.py
│   │   ├── support_engineer.py
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   ├── openhands/
│   │   ├── server.py
│   │   ├── support_engineer.py
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   └── scheduler/
│       ├── server.py           # APScheduler + FastAPI
│       ├── Dockerfile
│       └── requirements.txt
├── vibeteam/
│   ├── __init__.py
│   ├── connectors/
│   │   ├── sentry.py           # SentryConnector
│   │   ├── langfuse.py         # LangfuseConnector
│   │   ├── github.py           # GitHubConnector
│   │   ├── gmail.py            # GmailConnector
│   │   └── health.py           # HealthConnector
│   └── gateway/
│       ├── server.py           # Gateway FastAPI app
│       └── routes/
│           ├── github.py       # /webhook
│           ├── slack.py        # /slack/events
│           ├── sentry.py       # /sentry/webhook
│           └── api.py          # /api/*
├── k8s/
│   ├── base/
│   │   ├── kustomization.yaml
│   │   ├── postgres.yaml
│   │   ├── vibeteam-gateway.yaml
│   │   ├── autogen-svc.yaml
│   │   ├── crewai-svc.yaml
│   │   ├── openhands-svc.yaml
│   │   └── scheduler-svc.yaml
│   └── overlays/prod/
├── tests/
│   └── e2e/
│       ├── test_support_agent_sentry.py  # Framework comparison test
│       └── test_benchmark.py             # Benchmark test suite
├── docs/
│   ├── design.md               # This document
│   ├── research.md             # Framework research
│   └── FRAMEWORK_COMPARISON.md # E2E test results
├── .github/workflows/
│   ├── deploy.yml              # Build and deploy
│   └── ci.yml                  # Tests and linting
└── readiness/
    ├── check.py                # Automated readiness checks
    └── playbook.md             # Manual evaluation playbook
```

---

## Environment Variables

### All Agent Services

| Variable | Description | Required |
|----------|-------------|----------|
| `DATABASE_URL` | PostgreSQL connection string | Yes |
| `AZURE_API_KEY` | Azure OpenAI API key | Yes |
| `AZURE_API_BASE` | Azure OpenAI endpoint | Yes |
| `AZURE_API_VERSION` | API version (2024-08-01-preview) | No |
| `GITHUB_TOKEN` | GitHub personal access token | Yes |
| `SENTRY_AUTH_TOKEN` | Sentry API token | No |
| `LANGFUSE_PUBLIC_KEY` | Langfuse observability | No |
| `LANGFUSE_SECRET_KEY` | Langfuse observability | No |

### Gateway Only

| Variable | Description |
|----------|-------------|
| `AUTOGEN_SERVICE_URL` | http://autogen-svc:8080 |
| `CREWAI_SERVICE_URL` | http://crewai-svc:8080 |
| `OPENHANDS_SERVICE_URL` | http://openhands-svc:8080 |
| `SCHEDULER_SERVICE_URL` | http://scheduler-svc:8080 |
| `DEFAULT_FRAMEWORK` | Default agent framework |
| `GITHUB_WEBHOOK_SECRET` | Webhook signature verification |
| `SLACK_SIGNING_SECRET` | Slack request signing |
| `SLACK_BOT_TOKEN` | Slack bot OAuth token |

---

## Dependencies

```toml
# Agent services (requirements.txt)
fastapi>=0.109.0
uvicorn[standard]>=0.27.0
httpx>=0.26.0
sqlalchemy>=2.0.0
asyncpg>=0.29.0
pydantic>=2.0.0

# AutoGen specific
autogen-agentchat>=0.4.0

# CrewAI specific  
crewai>=0.30.0

# OpenHands specific
openhands>=0.5.0

# Scheduler specific
apscheduler>=4.0.0a4
```

---

## Agent Benchmarking

VibeTeam includes a comprehensive benchmarking system to evaluate agent performance across frameworks.

### Metrics Collected

| Category | Metrics |
|----------|---------|
| **Speed** | Latency (ms), Time-to-first-token |
| **Quality** | Accuracy, Completeness, Actionability, Clarity, Relevance, Efficiency |
| **Tool Usage** | Tools called, Tool call count, Tool accuracy |
| **Cost** | Input tokens, Output tokens, Total tokens |

### Composite Score

Each benchmark result generates a composite score (0-1) combining:
- **Quality (60%)**: LLM-as-judge evaluation across 6 dimensions
- **Speed (25%)**: Normalized latency (faster = higher score)
- **Efficiency (15%)**: Token usage (fewer = higher score)

### Running Benchmarks

```bash
# Run benchmark via pytest
pytest tests/e2e/test_benchmark.py -v -s

# Run specific task
pytest tests/e2e/test_benchmark.py -v -s -k "sentry"

# Run from CLI
python -m agents.benchmark \
    --frameworks autogen crewai openhands \
    --tasks sentry-weekly-summary \
    --output results/benchmark.json
```

### Predefined Benchmark Tasks

| Task ID | Description | Role |
|---------|-------------|------|
| `sentry-weekly-summary` | Summarize Sentry issues | support_engineer |
| `github-issue-triage` | Triage open GitHub issues | software_engineer |
| `release-notes` | Generate release notes | release_engineer |

### Quality Evaluation (LLM-as-Judge)

The `QualityEvaluator` uses a separate LLM call to score responses:

```python
from agents.benchmark import Benchmark, SENTRY_SUMMARY_TASK

benchmark = Benchmark(
    frameworks=["autogen", "crewai", "openhands"],
    evaluate_quality=True,  # Enable LLM-as-judge
)

results = await benchmark.run([SENTRY_SUMMARY_TASK])
report = benchmark.generate_report(results)
```

### Example Benchmark Report

```
======================================================================
AGENT BENCHMARK REPORT
Generated: 2026-01-28T06:45:00+00:00
======================================================================

TASK: sentry-weekly-summary
--------------------------------------------------
  OPENHANDS:
    Status:     [PASS]
    Latency:    5858ms
    Tokens:     1500
    Quality:    0.85
    Composite:  0.72
  
  CREWAI:
    Status:     [PASS]
    Latency:    5196ms
    Tokens:     1200
    Quality:    0.80
    Composite:  0.68

======================================================================
SUMMARY BY FRAMEWORK
======================================================================
OPENHANDS:
  Success Rate:    1/1 (100%)
  Avg Latency:     5858ms
  Avg Quality:     0.85
  Avg Composite:   0.72

--------------------------------------------------
WINNER: OPENHANDS (composite score: 0.72)
--------------------------------------------------
```

### Integration with CI

Benchmarks can run in CI to detect performance regressions:

```yaml
# In .github/workflows/ci.yml
- name: Run Benchmarks
  run: |
    pytest tests/e2e/test_benchmark.py \
      -v --export-benchmark=results/benchmark.json
    
- name: Upload Benchmark Results
  uses: actions/upload-artifact@v4
  with:
    name: benchmark-results
    path: results/benchmark.json
```

---

## Related Documents

- [Framework Comparison (E2E Test Results)](FRAMEWORK_COMPARISON.md)
- [Multi-Framework Agent Comparison](multi-framework-agent-comparison.md)
- [Research Design](research.md)
- [Progress Tracking](progress.md)
- [Requirements](requirements.md)
- [Readiness Playbook](../readiness/playbook.md)
