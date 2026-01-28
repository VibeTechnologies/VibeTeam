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

This skill instructs OpenCode to evaluate VibeTeam agents using the existing `agents/benchmark.py` module. OpenCode runs the agents, collects responses, and reports results in a standardized table format.

## How This Skill Works

1. OpenCode runs each agent (AutoGen, CrewAI, OpenHands) with the given task
2. OpenCode calls `ComparativeEvaluator` from `agents/benchmark.py` to score responses
3. OpenCode presents results in the table format below

**OpenCode uses `agents/benchmark.py` directly - no new code needed.**

---

## Required Output Format

After running evaluation, present results in this table format:

### Evaluation Results Table

| Framework | Input | Output (truncated) | Score | Feedback | Recommendations |
|-----------|-------|-------------------|-------|----------|-----------------|
| AutoGen | {task} | {first 100 chars}... | 4/5 | Good accuracy, used GitHub tools correctly | Add issue labels, include timestamps |
| CrewAI | {task} | {first 100 chars}... | 3/5 | Partial response, missing issue details | Use get_issue for full details |
| OpenHands | {task} | {first 100 chars}... | 5/5 | Excellent, used gh CLI effectively | None - met all criteria |

### Summary

| Metric | Value |
|--------|-------|
| **Winner** | OpenHands |
| **Reasoning** | Best tool usage and response completeness |
| **Judge Model** | gpt-5-2 |
| **Eval Time** | 2341ms |

---

## Evaluation Workflow

### Step 1: Run Agents

```python
# OpenCode executes this using agents/benchmark.py
import asyncio
from agents.autogen.software_engineer import AutoGenSoftwareEngineer
from agents.crewai.software_engineer import CrewAISoftwareEngineer
from agents.openhands.software_engineer import OpenHandsSoftwareEngineer

TASK = "List the 3 most recent open GitHub issues"

async def run_agents():
    responses = {}
    for name, cls in [
        ("autogen", AutoGenSoftwareEngineer),
        ("crewai", CrewAISoftwareEngineer),
        ("openhands", OpenHandsSoftwareEngineer),
    ]:
        agent = cls()
        result = await agent.run_async(task=TASK)
        responses[name] = result.get("response", "")
    return responses

responses = asyncio.run(run_agents())
```

### Step 2: Evaluate with benchmark.py

```python
from agents.benchmark import ComparativeEvaluator

evaluator = ComparativeEvaluator()
result = await evaluator.evaluate(task=TASK, responses=responses)
```

### Step 3: Format Output Table

Extract from `result`:
- `result.scores["autogen"].score` - Score (0-5)
- `result.scores["autogen"].feedback` - Feedback text
- `result.winner` - Winning framework
- `result.reasoning` - Why winner was chosen

---

## Scoring Scale

| Score | Meaning |
|-------|---------|
| 0 | Failed completely, error, or refused |
| 1 | Attempted but mostly wrong |
| 2 | Partial, missing key elements |
| 3 | Acceptable, main points addressed |
| 4 | Good, comprehensive and accurate |
| 5 | Excellent, exceeds expectations |

---

## CLI Alternative

OpenCode can also run the benchmark CLI:

```bash
cd ~/workspace/vibebrowser/VibeTeam
set -a && source .env && set +a
python -m agents.benchmark --tasks github-issue-triage --frameworks autogen crewai openhands
```

Available predefined tasks:
- `sentry-weekly-summary`
- `github-issue-triage`
- `release-notes`

---

## Environment Setup

Required before running:
```bash
cd ~/workspace/vibebrowser/VibeTeam
set -a && source .env && set +a
```

Environment variables used by `benchmark.py`:
- `AZURE_OPENAI_API_KEY` - Azure API key
- `AZURE_OPENAI_ENDPOINT` - Azure endpoint
- `AZURE_OPENAI_DEPLOYMENT` - Model deployment (default: gpt-5-2)
- `BENCHMARK_JUDGE_MODEL` - Judge model (default: same as deployment)

---

## Example Full Output

When OpenCode runs this skill, output should look like:

```
## Agent Evaluation: List GitHub Issues

### Input
List the 3 most recent open GitHub issues in VibeTechnologies/VibeWebAgent

### Results

| Framework | Output (truncated) | Score | Feedback | Recommendations |
|-----------|-------------------|-------|----------|-----------------|
| AutoGen | Here are the 3 most recent issues: #325 Browser crash on... | 4/5 | Accurate data, good formatting | Add direct links to issues |
| CrewAI | I found 3 open issues in the repository... | 4/5 | Complete list with details | Include creation dates |
| OpenHands | # GitHub Issues\n\n1. **#325** - Browser crash... | 5/5 | Excellent markdown formatting, links included | None |

### Summary

| Metric | Value |
|--------|-------|
| **Winner** | OpenHands |
| **Reasoning** | Best formatting with actionable links and complete details |
| **Judge Model** | gpt-5-2 |
| **Eval Time** | 2341ms |

### Recommendations by Framework

**AutoGen:**
- Add direct GitHub links to each issue
- Include issue labels in output

**CrewAI:**
- Add creation/update timestamps
- Format as markdown for better readability

**OpenHands:**
- No improvements needed for this task
```

---

## Key Files

| File | Purpose |
|------|---------|
| `agents/benchmark.py` | Core benchmark module with `ComparativeEvaluator`, `QualityEvaluator` |
| `agents/autogen/*.py` | AutoGen agent implementations |
| `agents/crewai/*.py` | CrewAI agent implementations |
| `agents/openhands/*.py` | OpenHands agent implementations |
