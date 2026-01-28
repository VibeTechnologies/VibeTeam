---
name: agent-evaluation-direct
description: Evaluate VibeTeam agents by running tasks directly via scripts/run_agent.py and comparing responses
license: MIT
compatibility: opencode
metadata:
  audience: developers
  workflow: evaluation
---

# Agent Evaluation (Direct) Skill

Evaluate agents by running tasks directly and comparing responses. OpenCode submits tasks to each agent using `scripts/run_agent.py`, then evaluates results with `agents/benchmark.py`.

---

## Workflow

1. **Define task** - OpenCode determines the evaluation task
2. **Run agents** - Execute `scripts/run_agent.py` for each framework
3. **Collect responses** - Capture output from each agent
4. **Evaluate** - Use `ComparativeEvaluator` to score responses
5. **Report** - Present results in table format

---

## CLI Commands

Run single agent:
```bash
python scripts/run_agent.py autogen "List 3 GitHub issues"
python scripts/run_agent.py crewai "List 3 GitHub issues"
python scripts/run_agent.py openhands "List 3 GitHub issues"
```

Run all agents:
```bash
python scripts/run_agent.py all "List 3 GitHub issues"
```

JSON output (for parsing):
```bash
python scripts/run_agent.py autogen "List 3 GitHub issues" --json
```

Options:
- `--role` - Agent role: `software_engineer`, `support_engineer`, `release_engineer`
- `--json` - Output as JSON
- `--timeout` - Timeout in seconds (default: 180)

---

## Required Output Format

### Agent Responses

For each agent run, capture:

| Field | Description |
|-------|-------------|
| Framework | autogen, crewai, openhands |
| Task | The input task |
| Response | Agent's output |
| Latency | Time in ms |
| Success | true/false |

### Evaluation Results

| Framework | Input | Output | Score | Feedback | Recommendations |
|-----------|-------|--------|-------|----------|-----------------|
| AutoGen | {task} | {truncated}... | 4/5 | {feedback} | {improvements} |
| CrewAI | {task} | {truncated}... | 3/5 | {feedback} | {improvements} |
| OpenHands | {task} | {truncated}... | 5/5 | {feedback} | {improvements} |

### Summary

| Metric | Value |
|--------|-------|
| Winner | {framework} |
| Reasoning | {why} |
| Judge Model | {model} |
| Eval Time | {ms} |

---

## Evaluation Steps

### Step 1: Run Each Agent

```bash
# Run and capture output
python scripts/run_agent.py autogen "YOUR_TASK" --json > /tmp/autogen.json
python scripts/run_agent.py crewai "YOUR_TASK" --json > /tmp/crewai.json
python scripts/run_agent.py openhands "YOUR_TASK" --json > /tmp/openhands.json
```

Or run all at once:
```bash
python scripts/run_agent.py all "YOUR_TASK" --json
```

### Step 2: Evaluate Responses

Use `ComparativeEvaluator` from `agents/benchmark.py`:
- Extract `response` field from each agent's output
- Call `evaluator.evaluate(task, responses)`
- Format results into table

---

## Scoring Scale

| Score | Meaning |
|-------|---------|
| 0 | Failed/error |
| 1 | Mostly wrong |
| 2 | Partial |
| 3 | Acceptable |
| 4 | Good |
| 5 | Excellent |

---

## Example Tasks

| Task | Role |
|------|------|
| List 3 recent GitHub issues | software_engineer |
| Summarize Sentry errors this week | support_engineer |
| Generate release notes for v1.2.0 | release_engineer |
| Triage open PRs | software_engineer |
| Check CI status | release_engineer |

---

## Key Files

| File | Purpose |
|------|---------|
| `scripts/run_agent.py` | CLI to run agents with tasks |
| `agents/benchmark.py` | `ComparativeEvaluator` for scoring |
| `agents/autogen/*.py` | AutoGen agents |
| `agents/crewai/*.py` | CrewAI agents |
| `agents/openhands/*.py` | OpenHands agents |
