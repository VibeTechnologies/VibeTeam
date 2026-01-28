---
name: researcher-evaluation
description: Technical playbook for GenAI agent evaluation using world-class frameworks (DeepEval, Ragas, G-Eval)
license: MIT
compatibility: opencode
metadata:
  audience: developers
  workflow: evaluation
---

# Researcher Evaluation Skill

Technical playbook for evaluating GenAI agents using industry-standard methodologies.

## Evaluation Report Format

Every evaluation produces this standardized output:

```
BENCHMARK: <test_id>
INPUT:     <original prompt>
OUTPUT:    <agent response (truncated)>
SCORE:     <0-5>/5
FEEDBACK:  <judge feedback>
IMPROVE:   <specific recommendations>
```

---

## 1. LLM-as-Judge Methodology

### G-Eval Pattern (DeepEval)

Uses Chain-of-Thought (CoT) scoring with probability-weighted outputs:

```python
JUDGE_PROMPT = """Evaluate the agent response on a 0-5 scale.

TASK: {input_prompt}
RESPONSE: {output}

Evaluation steps:
1. Check factual accuracy against known data
2. Verify task completion (all sub-tasks addressed)
3. Assess actionability (concrete next steps provided)
4. Check for hallucinations or unsupported claims
5. Evaluate conciseness (no unnecessary verbosity)

Score:
- 0: Failed/error/refusal
- 1: Mostly wrong
- 2: Partial, missing key elements
- 3: Acceptable, main points covered
- 4: Good, comprehensive
- 5: Excellent, exceeds expectations

Return JSON:
{{"score": 0, "feedback": "...", "recommendations": ["..."]}}
"""
```

### Pairwise Comparison (Arena-style)

For A/B testing two agent versions:

```python
PAIRWISE_PROMPT = """Compare two agent responses to the same task.

TASK: {input_prompt}
RESPONSE_A: {output_a}
RESPONSE_B: {output_b}

Which response is better? Consider:
- Accuracy, completeness, usefulness, clarity

Return: {{"winner": "A"|"B"|"tie", "reasoning": "..."}}
"""
```

---

## 2. Evaluation Dimensions

| Dimension | Weight | Criteria |
|-----------|--------|----------|
| **Accuracy** | 25% | Facts correct, no hallucinations |
| **Completeness** | 20% | All sub-tasks addressed |
| **Actionability** | 20% | Concrete next steps provided |
| **Tool Usage** | 15% | Correct tools called with valid args |
| **Clarity** | 10% | Well-structured, easy to parse |
| **Efficiency** | 10% | Concise, no redundancy |

---

## 3. Quick Evaluation Script

Run single agent evaluation:

```python
import asyncio
import json
import httpx
import os

JUDGE_PROMPT = """Evaluate the agent response.

TASK: {task}
RESPONSE: {response}

Return JSON with:
- score (0-5): Overall quality
- feedback: What the agent did well/poorly
- recommendations: List of specific improvements

{{"score": 0, "feedback": "...", "recommendations": ["..."]}}
"""

async def evaluate(task: str, response: str) -> dict:
    prompt = JUDGE_PROMPT.format(task=task[:500], response=response[:2000])
    
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            f"{os.environ['AZURE_OPENAI_ENDPOINT']}/openai/deployments/{os.environ.get('AZURE_OPENAI_DEPLOYMENT', 'gpt-5-2')}/chat/completions",
            headers={"api-key": os.environ['AZURE_OPENAI_API_KEY']},
            params={"api-version": os.environ.get('AZURE_API_VERSION', '2024-08-01-preview')},
            json={"messages": [{"role": "user", "content": prompt}], "temperature": 0.1, "max_completion_tokens": 500},
        )
        content = r.json()["choices"][0]["message"]["content"]
        return json.loads(content[content.find("{"):content.rfind("}")+1])

# Usage
result = asyncio.run(evaluate("List GitHub issues", "Here are 3 issues..."))
print(f"SCORE: {result['score']}/5")
print(f"FEEDBACK: {result['feedback']}")
print(f"IMPROVE: {result['recommendations']}")
```

---

## 4. Full Benchmark Test

```bash
cd ~/workspace/vibebrowser/VibeTeam && set -a && source .env && set +a && python << 'EOF'
import asyncio
import json
import httpx
import os

JUDGE_PROMPT = """Evaluate these agent responses to the same task.

TASK: {task}

AUTOGEN: {autogen}
CREWAI: {crewai}
OPENHANDS: {openhands}

For EACH agent return:
- score (0-5)
- feedback (1 sentence)
- recommendations (list of 2-3 specific improvements)

Return JSON:
{{
  "autogen": {{"score": 0, "feedback": "...", "recommendations": ["..."]}},
  "crewai": {{"score": 0, "feedback": "...", "recommendations": ["..."]}},
  "openhands": {{"score": 0, "feedback": "...", "recommendations": ["..."]}},
  "winner": "framework_name",
  "summary": "One line comparison"
}}
"""

async def run_agent(agent_class, task):
    try:
        agent = agent_class()
        result = await agent.run_async(task=task)
        return result.get("response", "")[:2000]
    except Exception as e:
        return f"ERROR: {e}"

async def evaluate(task, responses):
    prompt = JUDGE_PROMPT.format(
        task=task[:500],
        autogen=responses["autogen"][:1500],
        crewai=responses["crewai"][:1500],
        openhands=responses["openhands"][:1500],
    )
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(
            f"{os.environ['AZURE_OPENAI_ENDPOINT']}/openai/deployments/{os.environ.get('AZURE_OPENAI_DEPLOYMENT', 'gpt-5-2')}/chat/completions",
            headers={"api-key": os.environ['AZURE_OPENAI_API_KEY']},
            params={"api-version": os.environ.get('AZURE_API_VERSION', '2024-08-01-preview')},
            json={"messages": [{"role": "user", "content": prompt}], "temperature": 0.1, "max_completion_tokens": 1000},
        )
        content = r.json()["choices"][0]["message"]["content"]
        return json.loads(content[content.find("{"):content.rfind("}")+1])

async def main():
    from agents.autogen.software_engineer import AutoGenSoftwareEngineer
    from agents.crewai.software_engineer import CrewAISoftwareEngineer
    from agents.openhands.software_engineer import OpenHandsSoftwareEngineer
    
    TASK = "List the 3 most recent open GitHub issues in VibeTechnologies/VibeWebAgent"
    
    print(f"BENCHMARK: github-issues")
    print(f"INPUT: {TASK}")
    print("-" * 60)
    
    # Run agents
    print("Running agents...")
    autogen, crewai, openhands = await asyncio.gather(
        run_agent(AutoGenSoftwareEngineer, TASK),
        run_agent(CrewAISoftwareEngineer, TASK),
        run_agent(OpenHandsSoftwareEngineer, TASK),
    )
    
    responses = {"autogen": autogen, "crewai": crewai, "openhands": openhands}
    
    # Evaluate
    print("Evaluating...")
    result = await evaluate(TASK, responses)
    
    # Print results
    for fw in ["autogen", "crewai", "openhands"]:
        data = result.get(fw, {})
        print(f"\n{'='*60}")
        print(f"FRAMEWORK: {fw.upper()}")
        print(f"OUTPUT: {responses[fw][:200]}...")
        print(f"SCORE: {data.get('score', 0)}/5")
        print(f"FEEDBACK: {data.get('feedback', 'N/A')}")
        print(f"IMPROVE:")
        for rec in data.get('recommendations', []):
            print(f"  - {rec}")
    
    print(f"\n{'='*60}")
    print(f"WINNER: {result.get('winner', 'N/A').upper()}")
    print(f"SUMMARY: {result.get('summary', 'N/A')}")

asyncio.run(main())
EOF
```

---

## 5. Evaluation Best Practices

### From DeepEval Research

1. **Use CoT prompting** - Forces judge to reason before scoring
2. **Token probability weighting** - Average logprobs across score tokens
3. **Structured output** - Force JSON to prevent parsing errors
4. **Few-shot examples** - Include good/bad response examples in prompt

### From Ragas Research

1. **Discrete metrics** for categorical judgments (pass/fail)
2. **Numeric metrics** for continuous scores (0.0-1.0)
3. **Ranking metrics** for pairwise comparison

### From Anthropic Research

1. **Evaluation consistency** - Same format changes can cause 5% variance
2. **Multi-judge consensus** - Use 3 judges, take median
3. **Human calibration** - Validate judge vs human labels periodically

---

## 6. Multi-Judge Consensus

For critical evaluations, use multiple judge models:

```python
async def multi_judge_evaluate(task, response):
    judges = ["gpt-5-2", "gpt-4.1", "gpt-4.1-mini"]
    scores = []
    
    for judge in judges:
        result = await evaluate_with_model(task, response, judge)
        scores.append(result["score"])
    
    return {
        "scores": dict(zip(judges, scores)),
        "consensus": statistics.median(scores),
        "agreement": max(scores) - min(scores) <= 1
    }
```

---

## 7. Tool Usage Evaluation

For agents with tools, add tool-specific metrics:

```python
TOOL_EVAL_PROMPT = """Evaluate tool usage.

TASK: {task}
EXPECTED_TOOLS: {expected}
ACTUAL_TOOLS: {actual}

Return:
- precision: correct_tools / total_called
- recall: correct_tools / total_expected
- sequence_correct: true if tools called in logical order
"""
```

Metrics:
- **Tool Precision**: Correct tools / Total tools called
- **Tool Recall**: Correct tools / Expected tools
- **Sequence Score**: Was tool order logical?

---

## 8. Tracking Over Time

Save results to `.benchmarks/` for trend analysis:

```python
import json
from datetime import datetime
from pathlib import Path

def save_result(benchmark_id, result):
    path = Path(".benchmarks") / f"{benchmark_id}_{datetime.now():%Y%m%d_%H%M%S}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(result, indent=2))
```

Compare scores across releases:
```bash
cat .benchmarks/github-issues_*.json | jq -r '.autogen.score' | sort -n
```

---

## 9. Recommended Frameworks

| Framework | Best For | Install |
|-----------|----------|---------|
| **DeepEval** | Production testing, CI/CD | `pip install deepeval` |
| **Ragas** | RAG evaluation | `pip install ragas` |
| **LangSmith** | Tracing + evaluation | `pip install langsmith` |

DeepEval integration example:
```python
from deepeval import evaluate
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase, LLMTestCaseParams

metric = GEval(
    name="TaskCompletion",
    criteria="Did the agent complete the assigned task?",
    evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
    threshold=0.7
)

test_case = LLMTestCase(input="List issues", actual_output="Here are 3 issues...")
evaluate([test_case], [metric])
```

---

## 10. Quick Reference

### Score Scale
```
0 = Failed/error     3 = Acceptable
1 = Mostly wrong     4 = Good
2 = Partial          5 = Excellent
```

### Evaluation Command
```bash
python -c "from agents.benchmark import ComparativeEvaluator; import asyncio; print(asyncio.run(ComparativeEvaluator().evaluate('task', {'autogen':'...', 'crewai':'...', 'openhands':'...'})))"
```

### Key Files
- `agents/benchmark.py` - Core evaluation classes
- `.benchmarks/` - Historical results
- `.opencode/skills/agent-evaluation/SKILL.md` - User-facing skill
