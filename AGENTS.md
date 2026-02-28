You are working on AI agentic team. Agent are implemented on OpenHands that runs as a service that host all the agents sessions. Gateways is used for integration with Slack. DeepEval is used to evaluate agent sessions. Use

```shell
export $( < .env); uv run python scripts/eval_slack_e2e.py --scenario support_400_errors --channel C0AATPSADB8 --timeout 600
```

to run an evaluation test.

Before running any test `export $( < .env )`

for example
```shell
export $( < .env ) && .venv/bin/python -m pytest tests/test_openhands_service_integration.py -v --run-integration -s
```

Each agent has specific service ownership and handoff responsibilities. Evry agent have their own skill sets, defined in aagents/<agent_name>/skills/<sill_name>/SKILL.md.

Do not ask for tokens, evrything inside .env, just export it `export $( < .env )`

### Merging to Master

**Merging to master is safe and expected during development.** Do NOT ask for permission to merge.

The live system uses `git-sync` with `--ref=master` and `--period=30s`, so changes must land on master to be picked up by the running pods. The standard workflow is:

1. Create a feature branch
2. Open a PR for traceability
3. Merge immediately (squash merge preferred)
4. Delete the feature branch

If running evals, pause rollouts first to prevent mid-eval restarts (see "Analyzing Evaluation Tests" section).

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

## Analyzing Evaluation Tests

### Running Evaluations

```bash
uv run python scripts/eval_slack_e2e.py --scenario support_400_errors --channel C0AATPSADB8 --timeout 600
uv run python scripts/eval_slack_e2e.py --list-scenarios
```

**Note:** Slack evals run against the dev environment. Unless explicitly requested, it is acceptable to skip evals/E2E tests and report: “No. I did not run evals or E2E tests.” This should not be treated as an issue.

# 2. Pause rollouts to prevent mid-eval restarts (git-sync can trigger rolling updates)
```shell
kubectl rollout pause deployment/vibeteam-gateway -n vibeteam
kubectl rollout pause deployment/openhands-svc -n vibeteam
```

### Understanding Evaluation Output

The eval script produces:
1. **Console output** - Real-time progress showing wait times and message detection
2. **Report file** - Detailed markdown in `results/eval_reports/eval_<scenario>_<timestamp>.md`

Key console indicators:
- `Gateway accepted: routing to ['support_engineer']` - Request reached gateway
- `New messages detected: N` - Agent responded
- `Handoff detected in response!` - Agent mentioned another role (e.g., @ReleaseEngineer)
- `Still waiting for handoff response...` - Waiting for secondary agent

### Evaluation Metrics

| Metric | Threshold | What It Measures |
|--------|-----------|------------------|
| **InvestigationQuality** | 0.6 | Did agent use internal tools (Sentry, kubectl) effectively? |
| **TaskCompletion** | 0.6 | Was the issue meaningfully progressed toward resolution? |

**Scoring guide for TaskCompletion:**
- **0.0-0.2**: Nothing investigated, circular handoffs
- **0.2-0.4**: Some diagnostic info but no progress
- **0.4-0.6**: Used tools but inconclusive findings
- **0.6-0.8**: Thorough investigation with actionable recommendation/handoff
- **0.8-1.0**: Complete investigation with concrete action taken

### Common Failure Modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `No agent response received` | Gateway restarted mid-request | Pause rollouts before eval |
| `401 PermissionDenied` on eval | Wrong Azure credentials in shell | `unset AZURE_OPENAI_*` before running |
| `Waiting...` forever | Agent service not processing | Check `kubectl logs deployment/openhands-svc` |
| Score below threshold | Agent didn't use kubectl/Sentry | Check task injection in `slack.py` |
| Handoff never completes | Gateway doesn't detect @mention | Check `parse_role_mentions()` in router |

### Debugging Failed Evaluations

1. **Read the report file** - Contains full conversation transcript
   ```bash
   cat results/eval_reports/eval_support_400_errors_*.md | tail -100
   ```

2. **Check gateway logs** for request processing:
   ```bash
   kubectl logs deployment/vibeteam-gateway -n vibeteam --tail=100 | grep -v "GET /health"
   ```

3. **Check agent logs** for tool execution:
   ```bash
   kubectl logs deployment/openhands-svc -n vibeteam --tail=200 | grep -v "GET /health"
   ```

4. **Verify the agent received correct instructions** - Check task injection in `vibeteam/gateway/routes/slack.py`

### After Successful Evaluation

Resume paused rollouts:
```bash
kubectl rollout resume deployment/vibeteam-gateway -n vibeteam
kubectl rollout resume deployment/openhands-svc -n vibeteam
```

## System Readiness

Before running VibeTeam agents or after infrastructure changes, verify system readiness by following the playbook:

1. Read the playbook: `readiness/playbook.md`
2. Execute each check command
3. Interpret results using the evaluation criteria
4. Produce a report using the template at the end

## Documentation

- **[docs/requirements.md](docs/requirements.md)** - System requirements, agent roles, and responsibilities
- **[docs/design.md](docs/design.md)** - Architecture, routing logic, and design decisions

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

## Model Configuration

VibeTeam uses Azure OpenAI. The model name format is `azure/gpt-5.2` (with dot).

Azure Responses API support requires `AZURE_API_VERSION >= 2025-03-01-preview`. `gpt-5.2-codex` is responses-only, so set `AZURE_API_VERSION=2025-04-01-preview` and `AZURE_ALLOW_RESPONSES_MODELS=true`. Ensure `AZURE_OPENAI_ENDPOINT` is the resource root (e.g., `https://<resource>.openai.azure.com/`), not `/openai` and not a full query URL.

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
