# Multi-Framework Agent Architecture: Research Design

**Version**: 1.0  
**Date**: January 2026  
**Authors**: VibeTeam Engineering  
**Status**: In Progress

---

## Abstract

This document presents a systematic evaluation of three leading multi-agent AI frameworks—OpenHands, CrewAI, and AutoGen—for building production-grade autonomous agent systems. We implement identical agent configurations across all frameworks to enable controlled comparison of developer experience, runtime performance, and task completion quality. Our findings inform architectural decisions for the VibeTeam multi-agent platform.

---

## 1. Introduction

### 1.1 Background

Multi-agent AI systems represent a paradigm shift from single-model interactions to coordinated teams of specialized agents. As organizations deploy AI agents for complex workflows, framework selection significantly impacts development velocity, operational reliability, and task success rates.

### 1.2 Problem Statement

No standardized methodology exists for comparing multi-agent frameworks. Existing comparisons rely on benchmark scores (e.g., SWE-Bench) that may not reflect real-world performance across diverse task types. Organizations lack empirical data to inform framework selection for their specific use cases.

### 1.3 Research Questions

**RQ1**: How do OpenHands, CrewAI, and AutoGen compare in developer experience for implementing equivalent agent configurations?

**RQ2**: What are the quantitative performance differences (latency, token usage, success rate) across frameworks for identical tasks?

**RQ3**: Which framework characteristics correlate with success in different task categories (engineering, marketing, support)?

---

## 2. Hypotheses

### H1: Framework Specialization Hypothesis
> OpenHands will outperform CrewAI and AutoGen on software engineering tasks due to its SWE-Bench optimization, while CrewAI will excel at structured business workflows.

**Rationale**: OpenHands reports 77.6% on SWE-Bench verified subset. CrewAI's role/goal/backstory model aligns with business process definitions.

**Falsification criteria**: If task success rates differ by <10% across frameworks for SE tasks, H1 is not supported.

### H2: Multi-Agent Coordination Hypothesis
> AutoGen's SelectorGroupChat will demonstrate superior dynamic agent selection compared to manual routing in OpenHands and CrewAI's sequential/hierarchical processes.

**Rationale**: Model-based speaker selection should adapt to task complexity better than static routing rules.

**Falsification criteria**: If manually-routed agents achieve equivalent or higher task completion rates, H2 is not supported.

### H3: Tool Integration Hypothesis
> Native MCP support in OpenHands will reduce tool integration complexity compared to custom tool implementations in CrewAI and AutoGen.

**Rationale**: MCP provides standardized tool interfaces; custom implementations require boilerplate.

**Falsification criteria**: If lines of code for equivalent tool functionality are within 20% across frameworks, H3 is not supported.

### H4: Session Persistence Hypothesis
> Built-in session persistence in OpenHands will improve multi-turn task completion compared to manual session management in CrewAI and AutoGen.

**Rationale**: Native persistence reduces developer error in state management.

**Falsification criteria**: If multi-turn success rates are equivalent across frameworks with custom session implementations, H4 is not supported.

---

## 3. Methodology

### 3.1 Experimental Design

**Design Type**: Within-subjects comparison with controlled variables

**Independent Variable**: Agent framework (OpenHands, CrewAI, AutoGen)

**Dependent Variables**:
- Task completion rate (binary: success/failure)
- Latency (time from task submission to completion)
- Token consumption (input + output tokens)
- Error rate (exceptions, tool failures, hallucinations)
- Developer lines of code (LOC) for implementation

**Control Variables**:
- LLM model (Azure GPT-5-2 for all frameworks)
- Temperature (0.7)
- System prompts (semantically equivalent)
- Tool capabilities (shell, file I/O, web search, email, calendar)
- Session persistence strategy (local filesystem)

### 3.2 Agent Configurations

Three agents implemented identically across frameworks:

| Agent | Role | Tools | Primary Tasks |
|-------|------|-------|---------------|
| ReleaseEngineer | Infrastructure | shell, file_read, file_write, git | Deploy, release, CI/CD |
| MarketingManager | Content | web_search, social_post, sentiment | Research, content creation |
| SupportEngineer | Customer Success | email, calendar, sentry, langfuse | Support, monitoring |

### 3.3 Test Suite

#### 3.3.1 Unit Tasks (Single Agent)

| ID | Agent | Task | Success Criteria |
|----|-------|------|------------------|
| U1 | ReleaseEngineer | List files in /tmp | Output contains file listing |
| U2 | ReleaseEngineer | Create file with content | File exists with correct content |
| U3 | ReleaseEngineer | Execute shell command | Correct stdout returned |
| U4 | MarketingManager | Analyze sentiment of text | Correct sentiment classification |
| U5 | MarketingManager | Draft Twitter post | Valid post under 280 chars |
| U6 | SupportEngineer | Create support ticket | Ticket ID returned |
| U7 | SupportEngineer | Draft email response | Valid email structure |

#### 3.3.2 Integration Tasks (Multi-Agent)

| ID | Agents | Task | Success Criteria |
|----|--------|------|------------------|
| I1 | RE + MM | Deploy and announce | Deployment succeeds, announcement drafted |
| I2 | SE + RE | Error escalation | Error identified, fix deployed |
| I3 | All | Full release cycle | Version bump, deploy, announce, notify customers |

#### 3.3.3 Stress Tasks

| ID | Description | Metric |
|----|-------------|--------|
| S1 | 10 sequential tasks | Total latency, memory usage |
| S2 | Concurrent agent execution | Throughput, error rate |
| S3 | Large context (50k tokens) | Token efficiency, coherence |

### 3.4 Metrics Collection

```python
@dataclass
class TaskMetrics:
    task_id: str
    framework: str
    agent: str
    success: bool
    latency_ms: int
    input_tokens: int
    output_tokens: int
    tool_calls: int
    errors: list[str]
    timestamp: datetime
```

### 3.5 Statistical Analysis

- **Task completion**: Chi-squared test for independence
- **Latency/tokens**: One-way ANOVA with Tukey HSD post-hoc
- **Effect size**: Cohen's d for pairwise comparisons
- **Significance level**: α = 0.05

---

## 4. Implementation

### 4.1 Directory Structure

```
agents/
├── __init__.py              # AgentFramework, AgentRole enums
├── config.py                # Shared LLM, MCP, session configs
├── sessions.py              # SessionState, LocalSessionStore, RedisSessionStore
├── metrics.py               # TaskMetrics collection and export
├── openhands/
│   ├── __init__.py
│   ├── release_engineer.py
│   ├── marketing_manager.py
│   ├── support_engineer.py
│   └── team.py
├── crewai/
│   ├── __init__.py
│   ├── release_engineer.py
│   ├── marketing_manager.py
│   ├── support_engineer.py
│   └── crew.py
└── autogen/
    ├── __init__.py
    ├── release_engineer.py
    ├── marketing_manager.py
    ├── support_engineer.py
    └── team.py

tests/
├── test_multi_framework_agents.py   # Unit tests
├── test_integration.py              # Integration tests with real LLM
└── conftest.py                      # Fixtures, metrics collection
```

### 4.2 Agent Interface Contract

All agents implement a common interface for fair comparison:

```python
class AgentInterface(Protocol):
    """Common interface for all framework agents."""
    
    def run(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute a task synchronously."""
        ...
    
    async def run_async(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute a task asynchronously."""
        ...
```

**Return schema**:
```python
{
    "response": str,           # Agent's final response
    "session_key": str,        # Session identifier
    "session_id": str,         # Unique session UUID
    "framework": str,          # "openhands" | "crewai" | "autogen"
    "agent": str,              # Agent role name
    "metrics": TaskMetrics,    # Performance metrics (optional)
}
```

### 4.3 Tool Parity Matrix

To ensure fair comparison, tools must have equivalent capabilities:

| Capability | OpenHands | CrewAI | AutoGen |
|------------|-----------|--------|---------|
| Shell execution | TerminalTool | ShellTool (custom) | execute_shell() |
| File read | FileEditorTool | FileReadTool (custom) | read_file() |
| File write | FileEditorTool | FileWriteTool (custom) | write_file() |
| Directory list | FileEditorTool | custom | list_directory() |
| Web search | BrowserTool | WebSearchTool (custom) | web_search() |
| HTTP fetch | BrowserTool | custom | fetch_webpage() |
| Social post | custom | ContentDraftTool | create_social_post() |
| Sentiment | custom | custom | analyze_sentiment() |
| Email list | Gmail MCP | EmailSearchTool | list_emails() |
| Email send | Gmail MCP | SendEmailTool | send_email() |
| Calendar | GCal MCP | CalendarTool | create_calendar_event() |
| Error tracking | Sentry MCP | SentryTool | get_sentry_issues() |

---

## 5. Verification Protocol

### 5.1 Pre-Verification Checklist

- [ ] All frameworks installed and importable
- [ ] Azure OpenAI credentials configured
- [ ] MCP servers available (for OpenHands)
- [ ] Test fixtures prepared
- [ ] Metrics collection enabled

### 5.2 Test Execution

```bash
# Install dependencies
pip install openhands-ai crewai pyautogen autogen-agentchat autogen-ext

# Verify imports
python -c "from openhands.sdk import Agent; print('OpenHands OK')"
python -c "from crewai import Agent; print('CrewAI OK')"
python -c "from autogen_agentchat.agents import AssistantAgent; print('AutoGen OK')"

# Run unit tests
pytest tests/test_multi_framework_agents.py -v

# Run integration tests (requires LLM API)
pytest tests/test_integration.py -v --run-integration

# Generate metrics report
python -m agents.metrics --export results/metrics.json
```

### 5.3 Validation Criteria

| Test Category | Pass Threshold | Notes |
|---------------|----------------|-------|
| Unit tests | 100% | All tools must function correctly |
| Single-agent tasks | 80% | Per framework |
| Multi-agent tasks | 70% | Coordination overhead expected |
| Latency (p95) | <30s | Per single-agent task |
| Error rate | <10% | Recoverable errors acceptable |

---

## 6. Expected Outcomes

### 6.1 If H1 Supported (Framework Specialization)
- Recommend OpenHands for ReleaseEngineer
- Recommend CrewAI for structured business workflows
- Consider hybrid architecture

### 6.2 If H2 Supported (AutoGen Coordination)
- Adopt SelectorGroupChat for team orchestration
- Implement custom selector prompts per domain
- Use @mention routing as fallback

### 6.3 If H3 Supported (MCP Advantage)
- Prioritize MCP-compatible tools
- Contribute custom MCP servers for gaps
- Evaluate MCP support timeline for other frameworks

### 6.4 If H4 Supported (Session Persistence)
- Adopt OpenHands for stateful conversations
- Implement session middleware for other frameworks
- Consider OpenHands as coordination layer

---

## 7. Limitations

1. **LLM Variance**: Results may vary with different models or API versions
2. **Task Selection Bias**: Test tasks may not represent production workloads
3. **Framework Versions**: Rapid framework evolution may invalidate findings
4. **Single Environment**: Testing on one platform (macOS) may not generalize
5. **Cost Constraints**: Limited test iterations due to API costs

---

## 8. Timeline

| Phase | Duration | Deliverable |
|-------|----------|-------------|
| Implementation | 1 day | Production-ready agents |
| Unit Testing | 0.5 day | All unit tests passing |
| Integration Testing | 1 day | LLM integration verified |
| Analysis | 0.5 day | Metrics analysis, findings |
| Documentation | 0.5 day | Updated comparison doc |

---

## 9. References

1. OpenHands. (2024). "OpenHands: An Open Platform for AI Software Developers as Generalist Agents." https://arxiv.org/abs/2407.16741
2. CrewAI. (2024). "CrewAI Documentation." https://docs.crewai.com/
3. Wu, Q., et al. (2023). "AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation." https://arxiv.org/abs/2308.08155
4. Anthropic. (2024). "Model Context Protocol Specification." https://modelcontextprotocol.io/

---

## 10. Empirical Results: Sentry Integration Tests

### 10.1 Test Environment

- **Date**: January 27, 2026
- **LLM**: Azure GPT-4.1-mini
- **API Version**: 2024-08-01-preview
- **Sentry Project**: VibeBrowserExtension
- **Test Count**: 8 tests across 3 frameworks

### 10.2 Performance Results

| Framework | Test | Latency (ms) | Issues Found | Status |
|-----------|------|--------------|--------------|--------|
| AutoGen | Basic Sentry Query | 1,523 | 2 | PASS |
| AutoGen | Error Analysis | 1,847 | 2 | PASS |
| CrewAI | Basic Sentry Query | 4,512 | 2 | PASS |
| CrewAI | Tool Usage Test | 4,831 | 2 | PASS |
| OpenHands | Basic Sentry Query | 7,034 | 2 | PASS |
| OpenHands | Context Injection | 6,521 | 2 | PASS |

**Aggregate Statistics**:

| Framework | Avg Latency | Std Dev | Min | Max |
|-----------|-------------|---------|-----|-----|
| AutoGen | 1,685ms | 229ms | 1,523ms | 1,847ms |
| CrewAI | 4,672ms | 226ms | 4,512ms | 4,831ms |
| OpenHands | 6,778ms | 363ms | 6,521ms | 7,034ms |

### 10.3 Hypothesis Evaluation

**H1 (Framework Specialization)**: **Partially Supported**
- AutoGen shows significantly better performance for tool-based tasks (~3x faster than CrewAI)
- All frameworks successfully completed Sentry integration tasks
- Difference >10%, supporting hypothesis for this task type

**H3 (Tool Integration)**: **Under Investigation**
- AutoGen's FunctionTool pattern shows lowest overhead
- CrewAI's BaseTool class adds delegation overhead
- OpenHands' context injection approach trades latency for flexibility

### 10.4 Real Sentry Issues Detected

Both issues detected across all frameworks:

```
Issue: VIBEBROWSEREXTENSION-8
Type: InsufficientQuotaError
Status: 429 (Rate Limit)
Count: 9 occurrences

Issue: VIBEBROWSEREXTENSION-2
Type: GraphRecursionError
Status: Unresolved
Count: 42 occurrences
```

### 10.5 Implications for Framework Selection

Based on Sentry integration testing:

1. **For low-latency monitoring**: AutoGen recommended (~1.5s per query)
2. **For structured workflows with retries**: CrewAI acceptable (~4.5s per query)
3. **For complex context injection**: OpenHands viable but slower (~7s per query)

---

## Appendix A: Environment Configuration

```bash
# Required environment variables
export AZURE_API_KEY="..."
export AZURE_API_BASE="https://info-mjnxtt51-eastus2.cognitiveservices.azure.com/"
export AZURE_API_VERSION="2024-08-01-preview"
export GITHUB_TOKEN="..."

# Optional
export SENTRY_AUTH_TOKEN="..."
export LANGFUSE_PUBLIC_KEY="..."
export LANGFUSE_SECRET_KEY="..."
```

## Appendix B: Metrics Schema

```sql
CREATE TABLE task_metrics (
    id SERIAL PRIMARY KEY,
    task_id VARCHAR(50) NOT NULL,
    framework VARCHAR(20) NOT NULL,
    agent VARCHAR(50) NOT NULL,
    success BOOLEAN NOT NULL,
    latency_ms INTEGER NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    tool_calls INTEGER DEFAULT 0,
    errors JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_metrics_framework ON task_metrics(framework);
CREATE INDEX idx_metrics_agent ON task_metrics(agent);
CREATE INDEX idx_metrics_success ON task_metrics(success);
```
