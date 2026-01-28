---
name: researcher-evaluation
description: Technical playbook for GenAI agent evaluation using agents/benchmark.py with G-Eval methodology
license: MIT
compatibility: opencode
metadata:
  audience: developers
  workflow: evaluation
---

# Researcher Evaluation Skill

Technical playbook for evaluating GenAI agents. OpenCode uses `agents/benchmark.py` directly.

---

## Required Output Format

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

## Evaluation Dimensions

| Dimension | Description |
|-----------|-------------|
| Accuracy | Facts correct, no hallucinations |
| Completeness | All sub-tasks addressed |
| Actionability | Concrete next steps |
| Clarity | Well-structured |
| Relevance | On topic |
| Efficiency | Concise |

---

## Methodology (G-Eval)

Chain-of-Thought evaluation steps:
1. Check factual accuracy
2. Verify task completion
3. Assess actionability
4. Check for hallucinations
5. Evaluate conciseness
→ Score 0-5

---

## CLI

```bash
python -m agents.benchmark --tasks github-issue-triage --frameworks autogen crewai openhands
```

---

## Key Files

| File | Line | Class/Function |
|------|------|----------------|
| `agents/benchmark.py` | 286 | `QualityEvaluator` |
| `agents/benchmark.py` | 459 | `ComparativeEvaluator` |
| `agents/benchmark.py` | 694 | `Benchmark` |
