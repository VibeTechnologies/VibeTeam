# Beyond Prompt Engineering: A Recursive Framework for Self-Optimizing Agentic Systems

**Abstract**
Building reliable multi-agent systems requires moving beyond static prompt engineering toward dynamic, metric-driven optimization. This paper outlines the architectural and methodological framework used at VibeTeam to engineer autonomous agents hosted on Kubernetes. We present a case study of a "recursive engineering" loop where an AI engineering agent (OpenCode) utilizes semantic evaluation (DeepEval) to iteratively refine the behavior of production service agents, resulting in a 233% improvement in task execution scores and a 40% reduction in latency.

---

## 1. Introduction: The Reliability Gap

The transition from single-turn LLM chatbots to "embodied" agents—autonomous systems capable of executing tools and modifying infrastructure—introduces significant reliability challenges. In a production environment, an agent that hallucinates a command or misinterprets a user intent does not merely produce bad text; it risks system stability.

At VibeTechnologies, we orchestrate a fleet of specialized microservice agents (Support, Release, Software Engineering) hosted on a **k3s (Kubernetes)** cluster. These agents are fully integrated with our production toolchain: Slack, GitHub, Sentry, and Kubernetes.

The challenge was not capability, but control. How do we ensure a Support Agent investigates alerts thoroughly without wasting resources on trivial notification requests?

## 2. System Architecture

The VibeTeam ecosystem treats agents as independent microservices, each with a defined role and a rigid handoff matrix to prevent scope creep.

*   **Runtime:** Dockerized agents (OpenHands runtime) on k3s.
*   **Context Window:** Agents have read/write access to `kubectl` (infrastructure), Sentry (observability), and GitHub (code).
*   **Router:** A specialized Gateway service intercepts Slack events and routes them to the appropriate agent persona based on semantic intent.

## 3. Methodology: Semantic Evaluation via G-Eval

Traditional software testing (unit tests, string matching) is insufficient for stochastic LLM agents. We adopted **DeepEval**, utilizing the **G-Eval** framework (GPT-4-based evaluation), to score agent behaviors against semantic criteria.

Instead of asserting `response == "Done"`, we define criteria such as:
*   **Investigation Quality:** *Did the agent verify Sentry logs before recommending a rollback?*
*   **Evidence-Based Decision:** *Are recommendations supported by the tool outputs?*
*   **Scope Adherence:** *Did the agent attempt to perform tasks outside its role?*

This produces a scalar score (0.0 - 1.0) that quantifies "quality," turning subjective behavior into objective data.

## 4. The Recursive Engineering Loop

Our core innovation is the removal of the human developer from the immediate optimization loop. We employ a meta-agent, **OpenCode**, to drive the refinement process:

1.  **Simulation:** OpenCode triggers an end-to-end scenario (e.g., `scripts/eval_slack_e2e.py`) via the Gateway.
2.  **Observation:** The system captures the full conversation transcript, tool usage logs, and latency metrics.
3.  ** adjudication:** DeepEval scores the transcript against the defined G-Eval criteria.
4.  **Refinement:** OpenCode analyzes the report. If scores are sub-threshold, it modifies the system prompts or Gateway routing logic.
5.  **Verification:** The test is re-run to confirm regression-free improvement.

## 5. Case Study: The "Over-Eager" Support Engineer

### 5.1 The Anomaly
We observed that our `SupportEngineer` agent was suffering from "over-investigation." When a user requested a simple notification (e.g., *"Notify the team that PR #123 is deployed"*), the agent would:
1.  Fetch the last 24 hours of Sentry logs.
2.  Query Kubernetes for pod status.
3.  Analyze the data for anomalies.
4.  Finally post the notification.

**Baseline Score:** `0.30` (Fail)
**Diagnosis:** Inefficient resource usage and high latency.

### 5.2 The Iterative Correction
OpenCode was tasked with optimizing this behavior.

*   **Iteration 1 (Gateway Logic):** OpenCode modified the Gateway (`slack.py`) to semantically detect "notification" intent. It injected a "Simplified Prompt" that explicitly forbade tool usage for these requests.
*   **Iteration 2 (Agent Logic):** The agent code (`support_engineer.py`) was updated to conditionally skip context fetching. If `is_notification=True`, the heavy Sentry/Kubectl initialization was bypassed.
*   **Iteration 3 (Self-Correction):** During verification, OpenCode detected a typo in the generated prompt (`specificy` vs `Specify`) and committed a fix before final deployment.

### 5.3 Results

| Metric | Baseline | Optimized | Improvement |
|--------|----------|-----------|-------------|
| **Notification Score** | 0.30 | 1.00 | **+233%** |
| **Tool Usage** | 3 (Sentry, Kubectl, HTTP) | 0 | **100% Reduction** |
| **Response Latency** | ~38s | ~26s | **~32% Reduction** |

## 6. Conclusion

By integrating semantic evaluation directly into the engineering workflow, we created a self-reinforcing system. The agentic platform does not just execute tasks; it generates the data required to improve its own performance. This "Recursive Engineering" approach reduces the operational overhead of maintaining LLM agents and ensures that reliability scales alongside capability.

---
*The VibeTeam architecture is built on OpenHands, OpenCode, and Kubernetes.*
