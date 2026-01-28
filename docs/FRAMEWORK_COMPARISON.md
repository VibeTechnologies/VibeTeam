# Agent Framework Comparison

This document compares the three agent frameworks implemented in VibeTeam.

## Overview

| Framework | Service | Port | Status |
|-----------|---------|------|--------|
| AutoGen | autogen-svc | 8080 | Production |
| CrewAI | crewai-svc | 8080 | Production |
| OpenHands | openhands-svc | 8080 | Production |

## Architecture

All three frameworks are deployed as FastAPI microservices behind a unified gateway:

```
                        vibeteam-gateway
                              |
         +--------------------+--------------------+
         |                    |                    |
    autogen-svc          crewai-svc         openhands-svc
         |                    |                    |
         +--------------------+--------------------+
                              |
                         postgres
                    (session storage)
```

## Framework Selection

Use the `framework` parameter in API requests:

```bash
# AutoGen (default)
curl -X POST /api/run -d '{"task": "...", "framework": "autogen"}'

# CrewAI
curl -X POST /api/run -d '{"task": "...", "framework": "crewai"}'

# OpenHands
curl -X POST /api/run -d '{"task": "...", "framework": "openhands"}'
```

## E2E Test Results (Sentry Issue Scenario)

Task: "Analyze Sentry error: TypeError in UserService"

| Framework | Response Time | Response Quality |
|-----------|--------------|------------------|
| AutoGen | ~800ms | Attempts Sentry connector integration |
| CrewAI | ~5.6s | Full analysis with suggested fix |
| OpenHands | ~4.3s | Step-by-step debugging guide |

## Framework Characteristics

### AutoGen
- **Strengths**: Multi-agent collaboration, tool integration
- **Best for**: Complex workflows requiring multiple agents
- **Session**: Supports persistent sessions via PostgreSQL

### CrewAI
- **Strengths**: Role-based crews, structured outputs
- **Best for**: Well-defined tasks with clear roles
- **Session**: Supports persistent sessions via PostgreSQL

### OpenHands
- **Strengths**: Code execution, sandboxed environments
- **Best for**: Tasks requiring actual code execution
- **Session**: Supports persistent sessions via PostgreSQL
- **Note**: Requires pydantic>=2.11.3 (isolated from other frameworks)

## Available Roles

All frameworks support these agent roles:
- `support_engineer` - Customer support, Sentry triage, email handling
- `release_engineer` - Deployments, CI/CD, infrastructure
- `software_engineer` - Code review, implementation, debugging
- `product_manager` - Requirements, roadmap, prioritization
- `marketing_manager` - Content, announcements, social media

## API Endpoints

Each service exposes identical endpoints:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/run` | POST | Execute task |
| `/run/stream` | POST | Execute with SSE streaming |
| `/sessions` | GET | List sessions |
| `/sessions/{id}` | GET | Get session details |

## Deployment

All services are deployed to Kubernetes:

```bash
kubectl get pods -n vibeteam
# autogen-svc-xxx     1/1     Running
# crewai-svc-xxx      1/1     Running
# openhands-svc-xxx   1/1     Running
```

## Environment Variables

Required for all agent services:
- `AZURE_API_KEY` - Azure OpenAI API key
- `AZURE_API_BASE` - Azure OpenAI endpoint
- `DATABASE_URL` - PostgreSQL connection string
- `GITHUB_TOKEN` - GitHub API token (for repo operations)

## Switching Default Framework

Set in `vibeteam-gateway` deployment:

```yaml
env:
  - name: DEFAULT_FRAMEWORK
    value: "autogen"  # or "crewai" or "openhands"
```
