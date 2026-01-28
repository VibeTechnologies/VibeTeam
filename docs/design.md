# VibeTeam Agent Microservices Architecture

**Version**: 2.0  
**Date**: January 2026  
**Status**: Implementation In Progress

---

## Overview

This document describes the architecture for VibeTeam's multi-framework agent microservices, replacing the previous CronJob-based approach with long-running services that support:

1. **Separate agent microservices** - Each framework (AutoGen, CrewAI) runs in its own container
2. **Dynamic task scheduling** - Agents can schedule future tasks (e.g., "message customer in 1 hour")
3. **Human-in-the-loop** - Agents can wait for human input without consuming idle resources

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     External Events                              │
│  GitHub Webhooks │ Slack Events │ API Requests │ Scheduled      │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                  vibeteam-gateway (FastAPI)                      │
│  - Routes to agent services   - WebSocket streaming              │
│  - GitHub/Slack webhooks      - REST API                         │
└──────────┬───────────────────────────────┬──────────────────────┘
           │                               │
     ┌─────┴─────┐                   ┌─────┴─────┐
     ▼           ▼                   ▼           ▼
┌─────────┐ ┌─────────┐       ┌───────────┐ ┌──────────┐
│ autogen │ │ crewai  │       │ scheduler │ │ postgres │
│  -svc   │ │  -svc   │       │   -svc    │ │          │
│ :8080   │ │ :8080   │       │  :8080    │ │  :5432   │
└─────────┘ └─────────┘       └───────────┘ └──────────┘
     │           │                   │           ▲
     └───────────┴───────────────────┴───────────┘
                         │
                    PostgreSQL
                 (sessions + tasks)
```

---

## Technology Choices

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Agent Framework | AutoGen (primary), CrewAI (secondary) | Best Azure OpenAI compatibility |
| Scheduler | APScheduler v4 | Simple, async, PostgreSQL backend |
| Sessions | PostgreSQL | Single database for all state |
| Database | In-cluster PostgreSQL | Simple, cost-effective for k3s |
| API Framework | FastAPI | Async, automatic OpenAPI docs |
| HTTP Client | httpx | Async HTTP for inter-service calls |

---

## Components

### 1. Agent Microservices (autogen-svc, crewai-svc)

Each agent service is a FastAPI application exposing:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check |
| `/run` | POST | Execute task synchronously |
| `/run/stream` | POST | Execute task with SSE streaming |
| `/sessions/{id}` | GET | Get session history |

**Request Schema:**
```json
{
  "task": "Fix issue #123: Login button not working",
  "context_type": "issue",
  "context_id": "123",
  "session_id": "optional-resume-session"
}
```

**Response Schema:**
```json
{
  "response": "I've analyzed the issue and created PR #456...",
  "session_id": "ses_abc123",
  "agents_used": ["SoftwareEngineer"],
  "metadata": {
    "framework": "autogen",
    "tokens_used": 1234,
    "latency_ms": 5600
  }
}
```

### 2. Scheduler Service (scheduler-svc)

APScheduler with PostgreSQL backend for task persistence.

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check |
| `/tasks` | POST | Schedule a new task |
| `/tasks` | GET | List scheduled tasks |
| `/tasks/{id}` | GET | Get task details |
| `/tasks/{id}` | DELETE | Cancel a scheduled task |

**Schedule Request:**
```json
{
  "task": "Follow up with customer about ticket #789",
  "run_at": "2026-01-28T15:00:00Z",
  "agent_service": "autogen-svc",
  "context_type": "email",
  "context_id": "msg-xyz"
}
```

**Agent Tool Integration:**

Agents can schedule tasks via the `schedule_task` tool:
```python
@tool
def schedule_task(
    task: str,
    delay_hours: int = 0,
    delay_minutes: int = 0,
) -> str:
    """Schedule a task for future execution."""
    # Calls scheduler-svc API
```

### 3. Gateway Service (vibeteam-gateway)

Routes external events to appropriate agent services.

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check |
| `/webhook` | POST | GitHub webhook handler |
| `/slack/events` | POST | Slack event handler |
| `/api/run` | POST | Manual task invocation |
| `/api/schedule` | POST | Schedule a task |

**Environment Variables:**
```bash
AUTOGEN_SERVICE_URL=http://autogen-svc:8080
CREWAI_SERVICE_URL=http://crewai-svc:8080
SCHEDULER_SERVICE_URL=http://scheduler-svc:8080
DEFAULT_FRAMEWORK=autogen
```

### 4. PostgreSQL Database

**Tables:**

| Table | Purpose |
|-------|---------|
| `sessions` | Agent conversation history |
| `apscheduler_jobs` | APScheduler job storage (auto-created) |
| `task_results` | Historical task execution results |

**Session Schema:**
```sql
CREATE TABLE sessions (
    id UUID PRIMARY KEY,
    key VARCHAR(255) UNIQUE,  -- "autogen:support:issue:123"
    framework VARCHAR(50),
    role VARCHAR(50),
    context_type VARCHAR(50),
    context_id VARCHAR(255),
    messages JSONB,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

---

## Kubernetes Resources

### Deployments

| Name | Image | Replicas | Resources |
|------|-------|----------|-----------|
| `autogen-svc` | `vibeteam-autogen:latest` | 1 | 512Mi/1Gi, 250m/500m |
| `crewai-svc` | `vibeteam-crewai:latest` | 1 | 512Mi/1Gi, 250m/500m |
| `scheduler-svc` | `vibeteam-scheduler:latest` | 1 | 256Mi/512Mi, 100m/200m |
| `vibeteam-gateway` | `vibeteam:latest` | 1 | 256Mi/512Mi, 100m/200m |

### StatefulSets

| Name | Image | Replicas | Storage |
|------|-------|----------|---------|
| `postgres` | `postgres:16-alpine` | 1 | 10Gi PVC |

### Services

| Name | Type | Port | Target |
|------|------|------|--------|
| `autogen-svc` | ClusterIP | 8080 | autogen-svc:8080 |
| `crewai-svc` | ClusterIP | 8080 | crewai-svc:8080 |
| `scheduler-svc` | ClusterIP | 8080 | scheduler-svc:8080 |
| `postgres` | ClusterIP | 5432 | postgres:5432 |
| `vibeteam-gateway` | ClusterIP | 8080 | vibeteam-gateway:8080 |

### Secrets

| Name | Keys |
|------|------|
| `postgres-secret` | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` |
| `vibeteam-secrets` | (existing) `AZURE_API_KEY`, `GITHUB_TOKEN`, etc. |

---

## File Structure

```
agents/
├── autogen/
│   ├── __init__.py
│   ├── server.py           # FastAPI server (NEW)
│   ├── team.py             # AutoGenTeam class
│   ├── release_engineer.py
│   ├── marketing_manager.py
│   ├── support_engineer.py
│   ├── Dockerfile          # Updated for server mode
│   └── requirements.txt    # Updated with fastapi, etc.
├── crewai/
│   ├── __init__.py
│   ├── server.py           # FastAPI server (NEW)
│   ├── crew.py
│   ├── release_engineer.py
│   ├── marketing_manager.py
│   ├── support_engineer.py
│   ├── Dockerfile
│   └── requirements.txt
├── scheduler/
│   ├── __init__.py         # NEW
│   ├── server.py           # APScheduler + FastAPI (NEW)
│   ├── models.py           # SQLAlchemy models (NEW)
│   ├── Dockerfile          # NEW
│   └── requirements.txt    # NEW
├── shared/
│   ├── __init__.py
│   ├── db.py               # Database connection (NEW)
│   ├── scheduler_tools.py  # schedule_task tool (NEW)
│   ├── docs_tools.py       # Existing
│   └── ...
└── config.py

vibeteam/
├── gateway/
│   ├── __init__.py         # NEW
│   ├── server.py           # Refactored from webhook (NEW)
│   └── routes/
│       ├── __init__.py
│       ├── github.py       # GitHub webhook handlers
│       ├── slack.py        # Slack event handlers
│       └── api.py          # REST API
├── webhook/                # DEPRECATED -> gateway
└── ...

k8s/
├── base/
│   ├── kustomization.yaml  # Updated
│   ├── postgres.yaml       # NEW
│   ├── autogen-svc.yaml    # NEW
│   ├── crewai-svc.yaml     # NEW
│   ├── scheduler-svc.yaml  # NEW
│   ├── vibeteam-gateway.yaml # Renamed from webhook
│   └── ...
└── overlays/
    └── prod/
        └── kustomization.yaml
```

---

## Implementation Phases

### Phase 1: Infrastructure (PostgreSQL)
- [ ] Create `k8s/base/postgres.yaml` with StatefulSet
- [ ] Create `k8s/base/postgres-secret.yaml` template
- [ ] Apply to cluster and verify

### Phase 2: Agent Microservices
- [ ] Create `agents/autogen/server.py` with FastAPI
- [ ] Create `agents/crewai/server.py` with FastAPI
- [ ] Create `agents/shared/db.py` for PostgreSQL sessions
- [ ] Update `agents/autogen/Dockerfile` to run server
- [ ] Update `agents/crewai/Dockerfile` to run server
- [ ] Build and push Docker images
- [ ] Create k8s deployments
- [ ] Test agent services independently

### Phase 3: Scheduler Service
- [ ] Create `agents/scheduler/` module
- [ ] Create `agents/scheduler/server.py` with APScheduler
- [ ] Create `agents/scheduler/Dockerfile`
- [ ] Create `agents/shared/scheduler_tools.py`
- [ ] Add `schedule_task` tool to agent toolsets
- [ ] Build and push scheduler image
- [ ] Create k8s deployment
- [ ] Test scheduling workflow

### Phase 4: Gateway Refactor
- [ ] Create `vibeteam/gateway/` module
- [ ] Move webhook logic to `vibeteam/gateway/server.py`
- [ ] Update routing to call agent services via HTTP
- [ ] Update main Dockerfile
- [ ] Build and push gateway image
- [ ] Create k8s deployment (rename webhook)
- [ ] Test end-to-end webhooks

### Phase 5: Migration
- [ ] Deploy new architecture alongside old
- [ ] Create scheduled tasks for periodic jobs:
  - Support emails: every 15 minutes
  - PM analysis: every 2 hours
  - Release check: daily at 9am UTC
  - SRE health: every 5 minutes
  - SWE issues: every 4 hours
- [ ] Verify scheduled tasks execute correctly
- [ ] Remove old CronJobs
- [ ] Update documentation

### Phase 6: CI/CD
- [ ] Update `.github/workflows/ci.yml` for new images
- [ ] Add build steps for autogen-svc, crewai-svc, scheduler-svc
- [ ] Test CI pipeline

---

## Dependencies

```toml
# pyproject.toml additions
dependencies = [
    # API server
    "fastapi>=0.109.0",
    "uvicorn[standard]>=0.27.0",
    # HTTP client
    "httpx>=0.26.0",
    # Database
    "sqlalchemy>=2.0.0",
    "asyncpg>=0.29.0",
    # Scheduler
    "apscheduler>=4.0.0a4",
]
```

---

## Environment Variables

### All Services

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `AZURE_API_KEY` | Azure OpenAI API key |
| `AZURE_API_BASE` | Azure OpenAI endpoint |
| `AZURE_API_VERSION` | Azure API version |
| `GITHUB_TOKEN` | GitHub access token |

### Gateway Only

| Variable | Description |
|----------|-------------|
| `AUTOGEN_SERVICE_URL` | URL to autogen-svc |
| `CREWAI_SERVICE_URL` | URL to crewai-svc |
| `SCHEDULER_SERVICE_URL` | URL to scheduler-svc |
| `DEFAULT_FRAMEWORK` | Default agent framework |
| `GITHUB_WEBHOOK_SECRET` | GitHub webhook signature secret |
| `SLACK_SIGNING_SECRET` | Slack request signature secret |
| `SLACK_BOT_TOKEN` | Slack bot OAuth token |

---

## Migration from CronJobs

Current CronJobs to migrate:

| CronJob | Schedule | New Scheduled Task |
|---------|----------|-------------------|
| `support-engineer` | `*/15 * * * *` | Every 15 minutes |
| `product-manager` | `0 */2 * * *` | Every 2 hours |
| `release-engineer` | `0 9 * * *` | Daily at 9am UTC |
| `reliability-engineer` | `*/5 * * * *` | Every 5 minutes |
| `software-engineer` | `0 */4 * * *` | Every 4 hours |

These will be registered in the scheduler database on first deployment.

---

## Related Documents

- [Multi-Framework Agent Comparison](multi-framework-agent-comparison.md)
- [Research Design](research.md)
- [Progress Tracking](progress.md)
- [Requirements](requirements.md)
