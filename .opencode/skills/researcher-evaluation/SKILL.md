---
name: researcher-evaluation
description: Technical playbook for GenAI agent evaluation using agents/benchmark.py with world-class methodologies (G-Eval, DeepEval, Ragas)
license: MIT
compatibility: opencode
metadata:
  audience: developers
  workflow: evaluation
---

# Researcher Evaluation Skill

Technical playbook for evaluating GenAI agents. OpenCode uses `agents/benchmark.py` directly and reports results in table format.

---

## Required Output Format

All evaluations MUST produce results in this table format:

### Evaluation Results

| Framework | Input | Output | Score | Feedback | Recommendations |
|-----------|-------|--------|-------|----------|-----------------|
| AutoGen | {task} | {response truncated to 100 chars}... | 4/5 | {judge feedback} | {list of improvements} |
| CrewAI | {task} | {response truncated}... | 3/5 | {judge feedback} | {list of improvements} |
| OpenHands | {task} | {response truncated}... | 5/5 | {judge feedback} | {list of improvements} |

### Summary

| Metric | Value |
|--------|-------|
| Winner | {framework} |
| Reasoning | {why winner was chosen} |
| Judge Model | {model used} |
| Eval Time | {ms} |

---

## How to Run Evaluation

OpenCode uses `agents/benchmark.py` - no new code needed:

```python
# Step 1: Run agents
from agents.autogen.software_engineer import AutoGenSoftwareEngineer
from agents.crewai.software_engineer import CrewAISoftwareEngineer
from agents.openhands.software_engineer import OpenHandsSoftwareEngineer

TASK = "List 3 recent GitHub issues"
responses = {}
for name, cls in [("autogen", AutoGenSoftwareEngineer), ("crewai", CrewAISoftwareEngineer), ("openhands", OpenHandsSoftwareEngineer)]:
    result = await cls().run_async(task=TASK)
    responses[name] = result.get("response", "")

# Step 2: Evaluate using benchmark.py
from agents.benchmark import ComparativeEvaluator
result = await ComparativeEvaluator().evaluate(task=TASK, responses=responses)

# Step 3: Extract for table
for fw in ["autogen", "crewai", "openhands"]:
    score = result.scores[fw].score  # 0-5
    feedback = result.scores[fw].feedback
winner = result.winner
reasoning = result.reasoning
```

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

## Evaluation Dimensions (benchmark.py)

| Dimension | Description |
|-----------|-------------|
| Accuracy | Facts correct, no hallucinations |
| Completeness | All sub-tasks addressed |
| Actionability | Concrete next steps provided |
| Clarity | Well-structured output |
| Relevance | Stays on topic |
| Efficiency | Concise, no redundancy |

---

## CLI Alternative

```bash
cd ~/workspace/vibebrowser/VibeTeam
set -a && source .env && set +a
python -m agents.benchmark --tasks github-issue-triage --frameworks autogen crewai openhands
```

---

## Research: World-Class Evaluation Approaches

### G-Eval Pattern (DeepEval)

Chain-of-Thought scoring with evaluation steps:

```
1. Check factual accuracy
2. Verify task completion
3. Assess actionability
4. Check for hallucinations
5. Evaluate conciseness
→ Return score 0-5
```

### Pairwise Comparison (Arena-style)

Compare two responses, pick winner. Reduces position bias.

### Multi-Judge Consensus

Use 3 judge models, take median score for critical evaluations.

---

## Key Files

| File | Purpose |
|------|---------|
| `agents/benchmark.py` | `ComparativeEvaluator`, `QualityEvaluator` classes |
| `agents/benchmark.py:ComparativeEvaluator.evaluate()` | Main evaluation method |
| `agents/benchmark.py:QualityScores` | Individual dimension scores |
| `.benchmarks/` | Historical results storage |

---

## Example Output

```
## Agent Evaluation: List GitHub Issues

### Input
List the 3 most recent open GitHub issues

### Results

| Framework | Output | Score | Feedback | Recommendations |
|-----------|--------|-------|----------|-----------------|
| AutoGen | Here are 3 issues: #325... | 4/5 | Accurate, good tool usage | Add issue links |
| CrewAI | Found 3 open issues... | 4/5 | Complete list | Add timestamps |
| OpenHands | # Issues\n1. #325... | 5/5 | Excellent formatting | None |

### Summary

| Metric | Value |
|--------|-------|
| Winner | OpenHands |
| Reasoning | Best formatting with actionable links |
| Judge Model | gpt-5-2 |
| Eval Time | 2341ms |
```
