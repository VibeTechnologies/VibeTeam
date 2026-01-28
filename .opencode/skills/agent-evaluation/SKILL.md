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

## Workflow

1. Run each agent (AutoGen, CrewAI, OpenHands) with the given task
2. Call `ComparativeEvaluator.evaluate()` from `agents/benchmark.py`
3. Present results in the table format below

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
