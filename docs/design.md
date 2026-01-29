# VibeTeam Agent Microservices Architecture

**Version**: 2.3  
**Date**: January 28, 2026  
**Status**: Production

---

## Quick Start

### Run Tests

```bash
# Load environment
source .env

# Run all unit tests (fast, no LLM calls)
pytest tests/test_supervisor.py tests/test_tools.py tests/test_state.py -v

# Run benchmark tests (requires LLM, ~2 min)
pytest tests/e2e/test_benchmark.py -v

# Run framework comparison with LLM-as-judge
pytest tests/e2e/test_support_agent_sentry.py -v -s -k "compare_all"

# Run full test suite (excludes slow e2e)
pytest tests/ --ignore=tests/e2e/test_agent_services.py -v
```

### Run Benchmarks

```bash
# CLI benchmark (all frameworks)
python -m agents.benchmark \
    --frameworks autogen crewai openhands \
    --tasks sentry-weekly-summary

# Export results to JSON
pytest tests/e2e/test_benchmark.py -v --export-benchmark=results/benchmark.json
```

### System Readiness Check

```bash
# Quick check (endpoints only)
python readiness/check.py --quick

# Full check (includes k8s, Sentry, Langfuse)
python readiness/check.py --full
```

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
| **OpenHands** (Default) | Code generation, file manipulation, 100% benchmark success | Software engineering tasks, code review, general tasks |

The gateway selects the appropriate framework based on the task type or explicit request. **OpenHands is the default** due to its superior benchmark performance (100% success rate, 0.80 composite score).

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
- Default: Uses `DEFAULT_FRAMEWORK` env var (openhands - selected based on benchmark results)
- Role-based: Future - route based on task type

**Recommended Framework:** OpenHands achieved 100% success rate (3/3 tasks) with 0.80 composite score in benchmarks. See [research.md Section 16](research.md#16-updated-benchmark-results-multi-task-evaluation-january-28-2026) for detailed analysis.

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
| **Quality** | LLM-as-judge score (0-5), Feedback |
| **Tool Usage** | Tools called, Tool call count, Tool accuracy |
| **Cost** | Input tokens, Output tokens, Total tokens |

---

## Evaluation Framework: LLM-as-Judge

### Overview

VibeTeam uses **LLM-as-Judge** for objective agent evaluation. This approach:
- Compares all framework responses **side-by-side** in a single prompt
- Scores each response on a **0-5 scale**
- Provides **written feedback** explaining strengths/weaknesses
- Declares a **winner** with reasoning

### Why LLM-as-Judge?

| Approach | Pros | Cons |
|----------|------|------|
| **Response length** | Simple | Longer ≠ better |
| **Latency** | Measurable | Faster ≠ better quality |
| **Regex patterns** | Deterministic | Misses semantic quality |
| **LLM-as-Judge** ✅ | Semantic understanding, explains reasoning | Costs extra API call |

### Scoring Rubric (0-5 Scale)

| Score | Meaning |
|-------|---------|
| 0 | Failed completely, error, or refused to answer |
| 1 | Attempted but mostly wrong or unhelpful |
| 2 | Partially correct but missing key elements |
| 3 | Acceptable, addresses main points adequately |
| 4 | Good, comprehensive and accurate |
| 5 | Excellent, exceeds expectations with actionable insights |

### Evaluation Criteria

The judge evaluates each response on:
- **Accuracy**: Is the information correct and not hallucinated?
- **Completeness**: Does it address all parts of the task?
- **Usefulness**: Is the response actionable and helpful?
- **Clarity**: Is it well-organized and easy to understand?

### Implementation

```python
# agents/benchmark.py

@dataclass
class ComparativeScore:
    framework: str
    score: int  # 0-5 scale
    feedback: str

@dataclass
class ComparativeResult:
    task: str
    scores: dict[str, ComparativeScore]  # framework -> score
    winner: str
    reasoning: str
    judge_model: str
    evaluation_time_ms: int

class ComparativeEvaluator:
    """Evaluates multiple agent responses side-by-side using LLM-as-judge."""
    
    async def evaluate(
        self,
        task: str,
        responses: dict[str, str],  # framework -> response text
    ) -> ComparativeResult:
        # Sends all 3 responses to judge LLM
        # Returns scores, feedback, winner, and reasoning
```

### Judge Prompt Template

```
You are an expert evaluator comparing AI agent responses.

TASK:
{task}

AGENT RESPONSES:

=== AUTOGEN ===
{autogen_response}

=== CREWAI ===
{crewai_response}

=== OPENHANDS ===
{openhands_response}

Score each agent from 0-5. Return JSON:
{
  "autogen": {"score": 0, "feedback": "..."},
  "crewai": {"score": 0, "feedback": "..."},
  "openhands": {"score": 0, "feedback": "..."},
  "winner": "framework_name",
  "reasoning": "Why this framework won"
}
```

### Running Evaluation

```bash
# Run E2E test with LLM-as-judge evaluation
pytest tests/e2e/test_support_agent_sentry.py -v -s -k "compare_all"

# Run benchmark CLI
python -m agents.benchmark \
    --frameworks autogen crewai openhands \
    --tasks sentry-weekly-summary
```

### Example Evaluation Report

```
======================================================================
CROSS-FRAMEWORK SENTRY SUMMARY COMPARISON
======================================================================

Task: Provide a summary of Sentry issues for this week...

>>> Testing AUTOGEN...
    Status: PASS
    Latency: 1438ms
    Response length: 49 chars

>>> Testing CREWAI...
    Status: PASS
    Latency: 4648ms
    Response length: 1268 chars

>>> Testing OPENHANDS...
    Status: PASS
    Latency: 3537ms
    Response length: 1235 chars

======================================================================
LLM-AS-JUDGE EVALUATION
======================================================================

Judge Model: gpt-4.1-mini
Evaluation Time: 2135ms

Scores:
--------------------------------------------------
  AUTOGEN: 0/5
    Feedback: Failed to provide relevant information regarding unresolved issues.
  CREWAI: 4/5 WINNER
    Feedback: Comprehensive summary with actionable insights, could improve clarity.
  OPENHANDS: 4/5
    Feedback: Detailed report with patterns, but lacked specific issue links.
--------------------------------------------------

WINNER: CREWAI
Reasoning: CrewAI provided a more detailed and actionable report.

======================================================================
PERFORMANCE METRICS
======================================================================

Total frameworks tested: 3
Passed validation: 3
Failed validation: 0

Latency:
  Average: 3208ms
  Fastest: autogen (1438ms)

Per-Framework Results:
  [PASS] autogen: 1438ms, 49 chars, Score: 0/5
  [PASS] crewai: 4648ms, 1268 chars, Score: 4/5
  [PASS] openhands: 3537ms, 1235 chars, Score: 4/5

======================================================================
FINAL VERDICT: CREWAI wins with score 4/5
======================================================================
```

### Key Findings

**Latest Benchmark Results (January 28, 2026):**

| Framework | Success Rate | Avg Latency | Avg Composite | Winner |
|-----------|--------------|-------------|---------------|--------|
| **OpenHands** | 3/3 (100%) | 4744ms | **0.81** | :trophy: |
| CrewAI | 1/3 (33%) | 5594ms | 0.26 | |
| AutoGen | 1/3 (33%) | 3972ms | 0.23 | |

**Per-Task Results:**

| Task | AutoGen | CrewAI | OpenHands |
|------|---------|--------|-----------|
| `sentry-weekly-summary` | PASS (0.72) | PASS (0.80) | **PASS (0.85)** |
| `github-issue-triage` | FAIL | FAIL | **PASS (0.80)** |
| `release-notes` | PASS (0.70) | PASS (0.77) | **PASS (0.79)** |

**Key Insight**: OpenHands is the clear winner with 100% success rate across all tasks. AutoGen and CrewAI both fail on `github-issue-triage` task but perform well on Sentry summaries and release notes.

### Alternatives Considered

| Framework | Purpose | Why Not Used |
|-----------|---------|--------------|
| **DeepEval** | LLM evaluation | Adds dependency, overkill for comparison |
| **Ragas** | RAG evaluation | Designed for retrieval, not agents |
| **LangSmith** | LangChain tracing | Framework-specific |
| **Braintrust** | Eval platform | SaaS dependency |
| **Custom regex** | Pattern matching | Misses semantic quality |

We chose **native LLM-as-judge** because:
1. Zero external dependencies
2. Uses existing Azure OpenAI infrastructure
3. Simple 0-5 scoring is easy to interpret
4. Comparative format reduces position bias

---

## Predefined Benchmark Tasks

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

## Slack-Based Agent Communication

### Overview

In addition to the centralized gateway architecture, VibeTeam supports **decentralized agent communication via Slack**. This enables agents to coordinate autonomously like a real team - posting updates, @mentioning each other, and responding to requests without human orchestration.

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Slack Workspace                                      │
│                         #ai-team channel                                     │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
          ┌────────────────────────┼────────────────────────┐
          │                        │                        │
          ▼                        ▼                        ▼
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│  Support Agent   │    │   SWE Agent      │    │  Release Agent   │
│  (Polling loop)  │    │  (Polling loop)  │    │  (Polling loop)  │
│                  │    │                  │    │                  │
│  Watches:        │    │  Watches:        │    │  Watches:        │
│  - Sentry alerts │    │  - @swe mentions │    │  - @release      │
│  - @support      │    │  - Bug reports   │    │  - Version bumps │
└────────┬─────────┘    └────────┬─────────┘    └────────┬─────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     External Services                                        │
│  Sentry API  │  GitHub API  │  Gmail API  │  Langfuse                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Why Slack-Based Communication?

| Aspect | Centralized (SwarmOrchestrator) | Decentralized (Slack) |
|--------|--------------------------------|----------------------|
| **Control** | Supervisor routes all messages | Agents decide autonomously |
| **Visibility** | Internal memory only | Human-readable Slack thread |
| **Scaling** | Single process | Multiple independent pods |
| **Debugging** | Logs only | Visible conversation history |
| **Human-in-loop** | Requires API call | Natural @mention in Slack |

### SlackConnector Integration

The `SlackConnector` (`vibeteam/connectors/slack.py`) provides all primitives needed for agent communication:

```python
from vibeteam.connectors.slack import SlackConnector

slack = SlackConnector()

# Post message
slack.post_message("#ai-team", "Found 3 critical errors in Sentry")

# @mention another agent
slack.mention_agent("#ai-team", "swe", "Can you investigate GraphRecursionError?")

# Check if message is for this agent
if slack.is_mention_for_agent(message, "swe"):
    # Handle the request
    response = await agent.run(message.text)
    slack.post_message("#ai-team", response, thread_ts=message.ts)

# Get channel history
messages = slack.get_channel_history("#ai-team", limit=20)
```

### Agent Polling Pattern

Each agent runs as an independent service with a polling loop:

```python
# scripts/run_slack_agent.py
async def agent_session(agent_key: str, channel: str = "#ai-team"):
    """Run an agent that polls Slack for messages."""
    slack = SlackConnector()
    agent = create_agent(agent_key)
    processed_ts = set()

    while True:
        messages = slack.get_channel_history(channel, limit=20)
        
        for msg in messages:
            # Skip already processed or own messages
            if msg.ts in processed_ts or msg.is_bot:
                continue
            
            # Check if this message is for us
            if slack.is_mention_for_agent(msg, agent_key):
                response = await agent.run(msg.text)
                slack.post_message(channel, response, thread_ts=msg.ts)
                processed_ts.add(msg.ts)
        
        await asyncio.sleep(5)  # Poll every 5 seconds
```

### Kubernetes Deployment for Slack Agents

Each Slack-connected agent runs as a separate deployment:

```yaml
# k8s/base/slack-agents.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: slack-support-agent
  namespace: vibeteam
spec:
  replicas: 1
  selector:
    matchLabels:
      app: slack-support-agent
  template:
    spec:
      containers:
      - name: agent
        image: ghcr.io/vibetechnologies/vibeteam:latest
        command: ["python", "scripts/run_slack_agent.py"]
        args: ["--agent", "support", "--channel", "#ai-team"]
        env:
        - name: SLACK_BOT_TOKEN
          valueFrom:
            secretKeyRef:
              name: vibeteam-secrets
              key: SLACK_BOT_TOKEN
        - name: AZURE_API_KEY
          valueFrom:
            secretKeyRef:
              name: vibeteam-secrets
              key: AZURE_API_KEY
```

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `SLACK_BOT_TOKEN` | Bot OAuth token (xoxb-...) | Yes |
| `SLACK_DEFAULT_CHANNEL` | Default channel for messages | No (#ai-team) |
| `SLACK_AGENT_SWE` | Slack user ID for SWE agent | No |
| `SLACK_AGENT_SUPPORT` | Slack user ID for Support agent | No |
| `SLACK_AGENT_RELEASE` | Slack user ID for Release agent | No |

### Example Workflow: Sentry Error → Slack → GitHub Issue

```
1. Support Agent polls Sentry, finds critical error
   └─→ Posts to #ai-team: "Found GraphRecursionError affecting 50 users. @swe"

2. SWE Agent sees @swe mention
   └─→ Reads error details, creates GitHub issue
   └─→ Replies in thread: "Created issue #456. Will investigate root cause."

3. Support Agent sees reply
   └─→ Updates Sentry issue with GitHub link
   └─→ Posts: "Linked to GitHub. Monitoring for resolution."
```

### Comparison: Current vs Slack-Based Architecture

| Feature | Current (Gateway) | Slack-Based |
|---------|------------------|-------------|
| Entry point | REST API / Webhooks | Slack channel |
| Agent discovery | Hardcoded services | @mention routing |
| State sharing | PostgreSQL + SharedState | Slack thread context |
| Human oversight | Logs / Metrics | Live Slack channel |
| Deployment | Gateway + 3 services | N independent agents |

### Implementation Status

| Component | Status |
|-----------|--------|
| `SlackConnector` | ✅ Complete |
| `mention_agent()` / `is_mention_for_agent()` | ✅ Complete |
| `scripts/run_slack_agent.py` | 🔄 In Progress |
| K8s Slack agent deployments | ⏳ Planned |
| Events API (push vs polling) | ⏳ Planned |

---

## Related Documents

- [Framework Comparison (E2E Test Results)](FRAMEWORK_COMPARISON.md)
- [Multi-Framework Agent Comparison](multi-framework-agent-comparison.md)
- [Research Design](research.md)
- [Progress Tracking](progress.md)
- [Requirements](requirements.md)
- [Readiness Playbook](../readiness/playbook.md)

---

## Troubleshooting

### Common Issues and Solutions

#### 1. Azure API Credentials Empty in Pods

**Symptom**: Agents return 500 errors with "Connection error" in logs.

**Diagnosis**:
```bash
kubectl exec -n vibeteam deployment/autogen-svc -- \
  sh -c 'echo "API_KEY length: $(echo -n "$AZURE_API_KEY" | wc -c)"'
# If returns 0, credentials are empty
```

**Fix**:
```bash
# Patch the secret directly
source .env
kubectl patch secret vibeteam-secrets -n vibeteam --type='json' -p="[
  {\"op\": \"replace\", \"path\": \"/data/AZURE_API_KEY\", \"value\": \"$(echo -n "$AZURE_API_KEY" | base64)\"},
  {\"op\": \"replace\", \"path\": \"/data/AZURE_API_BASE\", \"value\": \"$(echo -n "$AZURE_API_BASE" | base64)\"}
]"

# Restart pods to pick up changes
kubectl rollout restart deployment/autogen-svc deployment/crewai-svc deployment/openhands-svc -n vibeteam
```

**Root Cause**: GitHub Actions secrets may not be set, causing empty values during deployment.

**Prevention**: Ensure GitHub repository has `AZURE_API_KEY` and `AZURE_API_BASE` secrets configured:
```bash
gh secret set AZURE_API_KEY < <(echo -n "$AZURE_API_KEY")
gh secret set AZURE_API_BASE < <(echo -n "$AZURE_API_BASE")
```

#### 2. Module Import Error in Docker Containers

**Symptom**: `ModuleNotFoundError: No module named 'vibeteam.agents'`

**Diagnosis**:
```bash
kubectl exec -n vibeteam deployment/autogen-svc -- \
  python -c "from vibeteam.connectors.sentry import SentryConnector; print('OK')"
```

**Fix**: The `vibeteam/__init__.py` must use conditional imports:
```python
# Allow standalone connector usage in Docker containers
try:
    from vibeteam.agents import ...
except ImportError:
    logger.debug("Running in connector-only mode")
```

**Root Cause**: Docker images only include `vibeteam/connectors/`, not the full package.

#### 3. SENTRY_AUTH_TOKEN Not Configured

**Symptom**: AutoGen/CrewAI return "SENTRY_AUTH_TOKEN not configured" error.

**Fix**: Add to K8s deployment manifest:
```yaml
env:
  - name: SENTRY_AUTH_TOKEN
    valueFrom:
      secretKeyRef:
        name: vibeteam-secrets
        key: SENTRY_AUTH_TOKEN
```

Apply and restart:
```bash
kubectl apply -k k8s/base/ -n vibeteam
kubectl rollout restart deployment/autogen-svc deployment/crewai-svc -n vibeteam
```

#### 4. CI/CD Deploys with Empty Secrets

**Symptom**: After CI/CD deployment, secrets are reset to empty values.

**Cause**: The deploy workflow recreates `vibeteam-secrets` from GitHub Actions secrets on every deployment.

**Fix**: Ensure all required secrets are set in GitHub repository:
```bash
# Required secrets
gh secret set AZURE_API_KEY
gh secret set AZURE_API_BASE
gh secret set SENTRY_AUTH_TOKEN
gh secret set PAT_TOKEN  # GitHub token
```

### Health Check Commands

```bash
# All pods running
kubectl get pods -n vibeteam

# Service health
curl http://localhost:8080/health  # via port-forward

# Verify env vars in pod
kubectl exec -n vibeteam deployment/autogen-svc -- env | grep -E "AZURE|SENTRY"

# Check logs
kubectl logs -n vibeteam deployment/autogen-svc --tail=50

# Test import
kubectl exec -n vibeteam deployment/autogen-svc -- \
  python -c "from vibeteam.connectors.sentry import SentryConnector; print('OK')"
```

---

## Changelog

### v2.4 (January 28, 2026)
- Added Quick Start section with test and benchmark commands
- Updated benchmark results: OpenHands wins with 100% success rate (0.81 composite)
- Fixed AutoGen Sentry API issue (`statsPeriod` parameter validation)
- All 3 frameworks now pass `sentry-weekly-summary` and `release-notes` tasks

### v2.3 (January 28, 2026)
- Added SENTRY_AUTH_TOKEN to all agent K8s manifests
- Fixed `vibeteam/__init__.py` for standalone connector imports
- Added troubleshooting section with common issues and solutions
- Documented GitHub secrets requirements for CI/CD

### v2.2 (January 27, 2026)
- Added agent benchmarking system documentation
- Added CI/CD pipeline details
- Added Dockerfile structure documentation

### v2.1 (January 26, 2026)
- Initial microservices architecture documentation
- Three-framework deployment (AutoGen, CrewAI, OpenHands)
- PostgreSQL session persistence
