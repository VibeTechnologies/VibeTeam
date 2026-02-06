# VibeTeam Agent Instructions

Instructions for AI agents working on the VibeTeam repository.

## Agent Roles and Responsibilities

Each agent has specific service ownership and handoff responsibilities. See individual agent instructions for details:

| Agent | Persona | Instructions | Primary Services |
|-------|---------|--------------|------------------|
| **SupportEngineer** | Grace | [agents/SupportEngineer/AGENTS.md](agents/SupportEngineer/AGENTS.md) | Gmail, Sentry, Customer Requests |
| **ReleaseEngineer** | Einstein | [agents/ReleaseEngineer/AGENTS.md](agents/ReleaseEngineer/AGENTS.md) | API endpoints, k3s cluster, CI/CD |
| **SoftwareEngineer** | Alex | [agents/SoftwareEngineer/AGENTS.md](agents/SoftwareEngineer/AGENTS.md) | VibeBrowser repos, code review |
| **ProductManager** | Jordan | [agents/ProductManager/AGENTS.md](agents/ProductManager/AGENTS.md) | GitHub Issues, PRDs, roadmap |
| **MarketingManager** | Sam | [agents/MarketingManager/AGENTS.md](agents/MarketingManager/AGENTS.md) | Status page, docs, announcements |

## Service Ownership Matrix

| Service | Primary Owner | Escalation Path |
|---------|--------------|-----------------|
| **api.vibebrowser.app** | ReleaseEngineer | → SoftwareEngineer (code bugs) |
| **api-dev.vibebrowser.app** | ReleaseEngineer | → SoftwareEngineer (code bugs) |
| **portal.vibebrowser.app** | ReleaseEngineer | → SoftwareEngineer (code bugs) |
| **GenAI Gateway** | ReleaseEngineer | → SoftwareEngineer (code bugs) |
| **Gmail (support@)** | SupportEngineer | → ProductManager (roadmap questions) |
| **Sentry** | SupportEngineer | → ReleaseEngineer (infra) / SoftwareEngineer (code) |
| **Langfuse** | SupportEngineer | → SoftwareEngineer (LLM issues) |
| **GitHub Issues** | ProductManager | → SoftwareEngineer (implementation) |
| **GitHub Actions CI/CD** | ReleaseEngineer | → SoftwareEngineer (test failures) |
| **Customer Requests (#322)** | SupportEngineer | → ProductManager (prioritization) |
| **Status Page** | MarketingManager | ← ReleaseEngineer (incident info) |
| **Documentation** | MarketingManager | ← SoftwareEngineer (technical review) |

## Production Action Ownership

**CRITICAL: Only ReleaseEngineer can modify the production cluster.**

| Action | Owner | Others |
|--------|-------|--------|
| **Rollback deployments** | ReleaseEngineer ONLY | SupportEngineer investigates, hands off |
| **Restart pods** | ReleaseEngineer ONLY | SupportEngineer identifies need, hands off |
| **Scale deployments** | ReleaseEngineer ONLY | SupportEngineer detects load, hands off |
| **kubectl apply** | ReleaseEngineer ONLY | SoftwareEngineer provides manifests |
| **kubectl get/logs** (read-only) | All agents | Investigation only |

### Investigation vs Action Flow

```
Customer reports issue
        ↓
SupportEngineer INVESTIGATES:
  - Check Sentry (pre-injected data)
  - Run kubectl get pods, events, logs (READ-ONLY)
  - Identify root cause
        ↓
If action needed:
        ↓
Hand off to ReleaseEngineer with findings
        ↓
ReleaseEngineer ACTS:
  - Rollback: kubectl rollout undo
  - Restart: kubectl rollout restart
  - Scale: kubectl scale
        ↓
Report action taken
```

## Handoff Decision Tree

When an agent receives a request, they should use this decision tree:

```
Is this a customer email/complaint?
  → SupportEngineer investigates (kubectl read-only + Sentry)
  → If action needed: hand off to ReleaseEngineer
  
Is this an infrastructure outage (API down, 5xx, health check failing)?
  → SupportEngineer investigates first
  → ReleaseEngineer takes action (rollback/restart)
  
Is this a code bug or feature request?
  → SoftwareEngineer implements
  
Is this a prioritization or roadmap question?
  → ProductManager decides
  
Does this need public communication?
  → MarketingManager drafts
```

## Task Completion Policy

**A task is not complete until it is verified end-to-end.** After deploying code changes that affect agent behavior:

1. **Always run the evaluation** to verify the fix works:
   ```bash
   uv run python scripts/eval_slack_e2e.py --scenario <relevant_scenario> --channel C0AATPSADB8
   ```

2. **Check the evaluation report** for:
   - Agent response received (no timeout)
   - Response quality meets threshold
   - No new errors introduced

3. **If evaluation fails**, debug and iterate until it passes

Do not consider infrastructure or agent code changes complete based solely on:
- Successful deployment
- Unit tests passing
- Manual spot checks

The evaluation script is the source of truth for agent functionality.

## System Readiness

Before running VibeTeam agents or after infrastructure changes, verify system readiness by following the playbook:

1. Read the playbook: `readiness/playbook.md`
2. Execute each check command
3. Interpret results using the evaluation criteria
4. Produce a report using the template at the end

The playbook allows for intelligent judgment on ambiguous cases.

## Repository Structure

```
VibeTeam/
  agents/              # Multi-framework agent implementations
    autogen/           # AutoGen agents (planned)
    crewai/            # CrewAI agents (planned)
    openhands/         # OpenHands agents (active)
    opencode/          # OpenCode agents (experimental)
  vibeteam/            # Main package
    connectors/        # External service integrations
    lib/               # Test harness for multi-agent scenarios
  readiness/           # System readiness checks
    playbook.md        # GenAI evaluation playbook
  docs/                # Documentation
    requirements.md    # System requirements and agent roles
    design.md          # Architecture and design decisions
  scripts/             # Utility scripts
  tests/               # Test files
  config/              # Configuration files
```

## Documentation

- **[docs/requirements.md](docs/requirements.md)** - System requirements, agent roles, and responsibilities
- **[docs/design.md](docs/design.md)** - Architecture, routing logic, and design decisions

## Key Connectors

| Connector | Purpose |
|-----------|---------|
| `GitHubConnector` | Issues, PRs, code review |
| `SlackConnector` | Slack messaging and threads |
| `DiscordConnector` | Discord messaging and threads |
| `SentryConnector` | Error tracking |
| `LangfuseConnector` | LLM observability |
| `HealthConnector` | Endpoint monitoring |
| `GmailConnector` | Email processing |

## Deployment

### Quick Deploy (Recommended)

Deploy using kustomize overlays:

```bash
# Dev environment (with git-sync for hot reload)
kubectl apply -k k8s/overlays/dev

# Production environment
kubectl apply -k k8s/overlays/prod
```

### Kustomize Structure

```
k8s/
  base/                    # Base manifests
    kustomization.yaml     # Resources: RBAC, services, deployments
    agent-rbac.yaml        # ServiceAccount + RBAC for kubectl access
    openhands-svc.yaml     # OpenHands agent deployment
    vibeteam-gateway.yaml  # Gateway routing webhooks to agents
    ...
  overlays/
    dev/                   # Dev overlay (git-sync sidecar)
      kustomization.yaml
      openhands-svc-patch.yaml
    prod/                  # Production overlay
```

### Build & Push Docker Images

Images are built automatically by GitHub Actions on push to master.
Manual build (requires Docker):

```bash
# Build OpenHands image
docker build -f agents/openhands/Dockerfile -t ghcr.io/vibetechnologies/vibeteam-openhands:latest .
docker push ghcr.io/vibetechnologies/vibeteam-openhands:latest
```

### Restart Deployments

After config changes, restart to pick up new values:

```bash
kubectl rollout restart deployment/openhands-svc -n vibeteam
kubectl rollout status deployment/openhands-svc -n vibeteam --timeout=120s
```

### Required Kubernetes Secrets

Create or update the `vibeteam-secrets` secret:

```bash
kubectl create secret generic vibeteam-secrets -n vibeteam \
  --from-literal=AZURE_API_KEY="..." \
  --from-literal=AZURE_API_BASE="https://YOUR-RESOURCE.openai.azure.com/" \
  --from-literal=AZURE_OPENAI_DEPLOYMENT="gpt-5.2" \
  --from-literal=GITHUB_TOKEN="..." \
  --from-literal=SENTRY_AUTH_TOKEN="..." \
  --dry-run=client -o yaml | kubectl apply -f -
```

### Scripts

| Script | Purpose |
|--------|---------|
| `scripts/deploy-dev.sh` | Build dev images and deploy to cluster |
| `scripts/eval_slack_e2e.py` | End-to-end evaluation of agent responses |

## Environment Variables

Required in `.env` (for local development and evaluation):
```
# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://YOUR-RESOURCE.openai.azure.com/
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_DEPLOYMENT=gpt-5.2
AZURE_API_VERSION=2024-08-01-preview

# Legacy names (also supported)
AZURE_API_KEY=${AZURE_OPENAI_API_KEY}
AZURE_API_BASE=${AZURE_OPENAI_ENDPOINT}

# GitHub
GITHUB_TOKEN=
```

Optional:
```
# Slack
SLACK_BOT_TOKEN=
SLACK_SIGNING_SECRET=

# Discord
DISCORD_BOT_TOKEN=

# Database
DATABASE_URL=postgresql://...

# Monitoring
SENTRY_AUTH_TOKEN=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=

# Evaluation
BENCHMARK_JUDGE_MODEL=gpt-5.2  # Override judge model for evals
```

## Model Configuration

VibeTeam uses Azure OpenAI. The model name format is `azure/gpt-5.2` (with dot).

**Current deployment:** `gpt-5.2` on `vibebrowser-dev.openai.azure.com`

## kubectl Access for Agents

Agents have kubectl installed and RBAC configured for cluster access:

- **ServiceAccount:** `vibeteam-agent`
- **ClusterRole:** `vibeteam-agent-readonly` (read-only access to all resources)
- **Role:** `vibeteam-agent-ops` (write access in `vibeteam` namespace for incident response)

Agents can run kubectl commands to investigate infrastructure issues:
```bash
kubectl get pods -n vibeteam
kubectl logs deployment/openhands-svc -n vibeteam --tail=50
kubectl describe pod <pod-name> -n vibeteam
```

## Customer Requests

Feature requests are tracked in GitHub Issue #322 (VibeTechnologies/VibeWebAgent).
Use `GitHubConnector.get_customer_requests_table()` to read/update.

## Current Work

**Active Issue: #38** - Deploy VibeTeam to Kubernetes and verify integrations
https://github.com/VibeTechnologies/VibeTeam/issues/38
