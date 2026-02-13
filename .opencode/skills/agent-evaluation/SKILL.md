---
name: agent-evaluation
description: Instruct OpenCode to run VibeTeam agent benchmarks using agents/benchmark.py and report results in table format
license: MIT
compatibility: opencode
metadata:
  audience: developers
  workflow: evaluation
---

# Agent Evaluation Skill

OpenCode evaluates VibeTeam agents using `agents/benchmark.py` and reports results in table format.

## CRITICAL: Pre-Flight Deployment Verification

**Before running ANY evaluation**, you MUST verify that the deployed code matches the repo code.
Git-sync updates files on disk, but Python processes don't hot-reload — pods must be restarted.

### Step 1: Check deployed commit matches repo HEAD

```bash
# Get the commit SHA running in the cluster
export $( < .env )
DEPLOYED_SHA=$(kubectl exec deployment/vibeteam-gateway -n vibeteam -c gateway -- cat /code/.git/worktrees/*/HEAD 2>/dev/null)
LOCAL_SHA=$(git rev-parse origin/master)
echo "Deployed: $DEPLOYED_SHA"
echo "Repo:     $LOCAL_SHA"
```

If they differ, wait for git-sync (30s) or manually restart pods.

### Step 2: Verify the Python process loaded current code

```bash
# Check when the pod last started (Python loads modules at startup)
kubectl get pods -n vibeteam -l app=vibeteam-gateway -o jsonpath='{.items[*].status.containerStatuses[0].state.running.startedAt}'
kubectl get pods -n vibeteam -l app=openhands-svc -o jsonpath='{.items[*].status.containerStatuses[0].state.running.startedAt}'
```

If pods started BEFORE the latest commit, the Python process is running stale code. Restart:

```bash
kubectl rollout resume deployment/vibeteam-gateway -n vibeteam 2>/dev/null || true
kubectl rollout restart deployment/vibeteam-gateway -n vibeteam
kubectl rollout resume deployment/openhands-svc -n vibeteam 2>/dev/null || true
kubectl rollout restart deployment/openhands-svc -n vibeteam
kubectl rollout status deployment/vibeteam-gateway -n vibeteam --timeout=120s
kubectl rollout status deployment/openhands-svc -n vibeteam --timeout=120s
```

### Step 3: Verify specific code changes

If you changed a specific file (e.g., removed "Thinking..." messages), verify it's gone:

```bash
# Example: check that "Thinking..." is not in the deployed gateway code
kubectl exec deployment/vibeteam-gateway -n vibeteam -c gateway -- grep -rn "Thinking" /code/current/vibeteam/ 2>/dev/null
# Should return nothing
```

### Step 4: Pause rollouts before eval

```bash
kubectl rollout pause deployment/vibeteam-gateway -n vibeteam
kubectl rollout pause deployment/openhands-svc -n vibeteam
```

**Only proceed with evaluation after all checks pass.**

---

## Workflow

1. **Pre-flight checks** (see above) — verify deployed code matches repo
2. Run each agent (AutoGen, CrewAI, OpenHands) with the given task
3. Call `ComparativeEvaluator.evaluate()` from `agents/benchmark.py`
4. Present results in the table format below

---

## Required Output Format

### Evaluation Results

| Framework | Input | Output | Score | Feedback | Recommendations |
|-----------|-------|--------|-------|----------|-----------------|
| AutoGen | {task} | {first 100 chars}... | 4/5 | {judge feedback} | {specific improvements} |
| CrewAI | {task} | {first 100 chars}... | 3/5 | {judge feedback} | {specific improvements} |
| OpenHands | {task} | {first 100 chars}... | 5/5 | {judge feedback} | {specific improvements} |

### Summary

| Metric | Value |
|--------|-------|
| **Winner** | {framework name} |
| **Reasoning** | {why winner was chosen} |
| **Judge Model** | {model used, e.g. gpt-5-2} |
| **Eval Time** | {milliseconds} |

---

## Scoring Scale

| Score | Meaning |
|-------|---------|
| 0 | Failed/error/refusal |
| 1 | Mostly wrong |
| 2 | Partial, missing key elements |
| 3 | Acceptable |
| 4 | Good, comprehensive |
| 5 | Excellent |

---

## CLI Alternative

```bash
cd ~/workspace/vibebrowser/VibeTeam
set -a && source .env && set +a
python -m agents.benchmark --tasks github-issue-triage --frameworks autogen crewai openhands
```

Predefined tasks: `sentry-weekly-summary`, `github-issue-triage`, `release-notes`

---

## Key Files

| File | Purpose |
|------|---------|
| `agents/benchmark.py` | `ComparativeEvaluator`, `QualityEvaluator` |
| `agents/benchmark.py:286` | `QualityEvaluator` class |
| `agents/benchmark.py:459` | `ComparativeEvaluator` class |

---

## Environment

Required before running:
```bash
source .env
```

Variables: `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`
