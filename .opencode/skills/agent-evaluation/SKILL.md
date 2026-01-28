---
name: agent-evaluation
description: Evaluate VibeTeam agent responses with LLM-as-judge scoring and detailed feedback for AutoGen, CrewAI, and OpenHands frameworks
license: MIT
compatibility: opencode
metadata:
  audience: developers
  workflow: evaluation
---

# Agent Evaluation Skill

Evaluate and compare VibeTeam agent responses using LLM-as-judge. This skill provides detailed scoring and feedback to help improve agent quality.

## Quick Start

Run a comparative evaluation of all three frameworks:

```bash
cd ~/workspace/vibebrowser/VibeTeam
set -a && source .env && set +a
python -c "
import asyncio
from agents.benchmark import ComparativeEvaluator

async def evaluate():
    evaluator = ComparativeEvaluator()
    result = await evaluator.evaluate(
        task='List the 3 most recent open GitHub issues',
        responses={
            'autogen': '''YOUR_AUTOGEN_RESPONSE_HERE''',
            'crewai': '''YOUR_CREWAI_RESPONSE_HERE''',
            'openhands': '''YOUR_OPENHANDS_RESPONSE_HERE''',
        }
    )
    print(result)

asyncio.run(evaluate())
"
```

---

## Evaluation Modes

### Mode 1: Comparative Evaluation (Recommended)

Compare all three frameworks on the same task. Returns 0-5 scores with feedback.

```python
from agents.benchmark import ComparativeEvaluator

evaluator = ComparativeEvaluator()
result = await evaluator.evaluate(
    task="Your task description",
    responses={
        "autogen": "AutoGen's response...",
        "crewai": "CrewAI's response...",
        "openhands": "OpenHands' response...",
    }
)

# Output format:
# AUTOGEN: 4/5
#   Feedback: Good response with accurate data...
# CREWAI: 3/5
#   Feedback: Partially complete, missing details...
# OPENHANDS: 5/5
#   Feedback: Excellent response with actionable insights...
# WINNER: OPENHANDS
# Reasoning: Best combination of accuracy and completeness
```

### Mode 2: Individual Quality Evaluation

Evaluate a single response on 6 quality dimensions (0.0-1.0 scale).

```python
from agents.benchmark import QualityEvaluator, BenchmarkTask

evaluator = QualityEvaluator()
task = BenchmarkTask(
    task_id="test",
    prompt="List recent GitHub issues",
    expected_behavior="Should list issues with titles, numbers, and status"
)

scores = await evaluator.evaluate(task, "Agent's response here...")

print(f"Accuracy: {scores.accuracy}")
print(f"Completeness: {scores.completeness}")
print(f"Actionability: {scores.actionability}")
print(f"Clarity: {scores.clarity}")
print(f"Relevance: {scores.relevance}")
print(f"Efficiency: {scores.efficiency}")
print(f"Overall: {scores.overall}")
print(f"Reasoning: {scores.judge_reasoning}")
```

---

## Full Evaluation Workflow

### Step 1: Run All Three Agents

Run agents individually and capture their responses:

```bash
cd ~/workspace/vibebrowser/VibeTeam
set -a && source .env && set +a

# Define your task
TASK="List the 3 most recent open GitHub issues in VibeTechnologies/VibeWebAgent"
```

**AutoGen:**
```python
from agents.autogen.software_engineer import AutoGenSoftwareEngineer
agent = AutoGenSoftwareEngineer()
result = await agent.run_async(task=TASK)
autogen_response = result['response']
```

**CrewAI:**
```python
from agents.crewai.software_engineer import CrewAISoftwareEngineer
agent = CrewAISoftwareEngineer()
result = await agent.run_async(task=TASK)
crewai_response = result['response']
```

**OpenHands:**
```python
from agents.openhands.software_engineer import OpenHandsSoftwareEngineer
agent = OpenHandsSoftwareEngineer()
result = await agent.run_async(task=TASK)
openhands_response = result['response']
```

### Step 2: Run Comparative Evaluation

```python
from agents.benchmark import ComparativeEvaluator

evaluator = ComparativeEvaluator()
result = await evaluator.evaluate(
    task=TASK,
    responses={
        'autogen': autogen_response,
        'crewai': crewai_response,
        'openhands': openhands_response,
    }
)
print(result)
```

### Step 3: Interpret Results

The evaluation returns:

| Field | Description |
|-------|-------------|
| `scores[framework].score` | 0-5 rating for each framework |
| `scores[framework].feedback` | Specific feedback for improvement |
| `winner` | Best performing framework |
| `reasoning` | Why the winner was chosen |
| `evaluation_time_ms` | How long evaluation took |

---

## Scoring Scale

### Comparative Evaluation (0-5)

| Score | Meaning |
|-------|---------|
| 0 | Failed completely, error, or refused to answer |
| 1 | Attempted but mostly wrong or unhelpful |
| 2 | Partially correct but missing key elements |
| 3 | Acceptable, addresses the main points adequately |
| 4 | Good, comprehensive and accurate response |
| 5 | Excellent, exceeds expectations with actionable insights |

### Quality Dimensions (0.0-1.0)

| Dimension | What It Measures |
|-----------|-----------------|
| **Accuracy** | Is the information factually correct? |
| **Completeness** | Does it address all parts of the task? |
| **Actionability** | Does it provide concrete next steps? |
| **Clarity** | Is it well-organized and easy to understand? |
| **Relevance** | Does it stay on topic without hallucination? |
| **Efficiency** | Is it concise without unnecessary verbosity? |

---

## One-Liner Evaluation Script

Run this complete evaluation in one command:

```bash
cd ~/workspace/vibebrowser/VibeTeam && set -a && source .env && set +a && python << 'EOF'
import asyncio
from agents.autogen.software_engineer import AutoGenSoftwareEngineer
from agents.crewai.software_engineer import CrewAISoftwareEngineer
from agents.openhands.software_engineer import OpenHandsSoftwareEngineer
from agents.benchmark import ComparativeEvaluator

TASK = "List the 3 most recent open GitHub issues in VibeTechnologies/VibeWebAgent"

async def run_all():
    print("Running AutoGen...")
    autogen = AutoGenSoftwareEngineer()
    autogen_result = await autogen.run_async(task=TASK)
    print(f"  Response length: {len(autogen_result.get('response', ''))}")
    
    print("Running CrewAI...")
    crewai = CrewAISoftwareEngineer()
    crewai_result = await crewai.run_async(task=TASK)
    print(f"  Response length: {len(crewai_result.get('response', ''))}")
    
    print("Running OpenHands...")
    openhands = OpenHandsSoftwareEngineer()
    openhands_result = await openhands.run_async(task=TASK)
    print(f"  Response length: {len(openhands_result.get('response', ''))}")
    
    print("\nEvaluating with LLM-as-judge...")
    evaluator = ComparativeEvaluator()
    eval_result = await evaluator.evaluate(
        task=TASK,
        responses={
            'autogen': autogen_result.get('response', ''),
            'crewai': crewai_result.get('response', ''),
            'openhands': openhands_result.get('response', ''),
        }
    )
    
    print("\n" + "="*60)
    print("EVALUATION RESULTS")
    print("="*60)
    print(eval_result)
    
    return eval_result

asyncio.run(run_all())
EOF
```

---

## Configuration

The evaluator uses these environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `AZURE_OPENAI_API_KEY` | - | Azure OpenAI API key |
| `AZURE_OPENAI_ENDPOINT` | - | Azure OpenAI endpoint |
| `AZURE_API_VERSION` | 2024-08-01-preview | API version |
| `BENCHMARK_JUDGE_MODEL` | gpt-4.1-mini | Model for LLM-as-judge |

To use GPT-5.2 as the judge:
```bash
export BENCHMARK_JUDGE_MODEL=gpt-5-2
```

---

## Predefined Benchmark Tasks

Run standard benchmarks via CLI:

```bash
cd ~/workspace/vibebrowser/VibeTeam
set -a && source .env && set +a

# List available tasks
python -m agents.benchmark --help

# Run specific task
python -m agents.benchmark --tasks github-issue-triage --frameworks autogen crewai openhands

# Run all standard tasks
python -m agents.benchmark --tasks sentry-weekly-summary github-issue-triage release-notes
```

Available tasks:
- `sentry-weekly-summary` - Summarize Sentry issues
- `github-issue-triage` - Triage GitHub issues
- `release-notes` - Generate release notes

---

## Troubleshooting

### "AZURE_API_BASE environment variable not set"
```bash
source .env  # Load environment variables
```

### "Request timed out"
Increase timeout:
```bash
export BENCHMARK_TIMEOUT=300
```

### Low scores for working responses
Check if the `expected_behavior` in BenchmarkTask matches what the agent actually does. The judge compares responses against expected behavior.

---

## Example Output

```
============================================================
LLM-AS-JUDGE EVALUATION RESULTS
============================================================

OPENHANDS: 5/5
  Feedback: Excellent response with real data from GitHub API. Listed issues with numbers, titles, and links. Well formatted.

AUTOGEN: 4/5
  Feedback: Good response with accurate issue data. Slightly less detailed formatting than OpenHands.

CREWAI: 4/5
  Feedback: Accurate data retrieved. Good structure but could include more context.

------------------------------------------------------------
WINNER: OPENHANDS
Reasoning: Best combination of accuracy, formatting, and actionable information with direct links to issues.
------------------------------------------------------------
Judge: gpt-5-2 | Time: 2341ms
```
