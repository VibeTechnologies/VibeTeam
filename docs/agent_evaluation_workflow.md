# VibeTeam Agent Evaluation & Self-Reinforcement Workflow

This document outlines the continuous improvement loop for VibeTeam's multi-agent system. It demonstrates how we use automated evaluation (DeepEval) and an AI engineering agent (OpenCode) to iteratively refine agent behavior.

## 1. System Architecture

The VibeTeam ecosystem consists of specialized AI agents running as microservices on a Kubernetes (k3s) cluster.

*   **Hosting:** k3s cluster (`vibeteam` namespace)
*   **Gateway:** `vibeteam-gateway` routes Slack events to agents via HTTP webhooks.
*   **Agents:** Hosted as Docker containers (e.g., `openhands-svc`), scaling independently.

## 2. Integrations & Context

Agents are "embodied" with direct access to production tools:

*   **Slack:** Native chat interface for users and inter-agent communication.
*   **GitHub:** Reading issues, checking PR status, analyzing code.
*   **Sentry:** Real-time error monitoring and stack trace analysis.
*   **Kubernetes:** Read-only (or write for ReleaseEngineer) access to pod logs, events, and status via `kubectl`.

## 3. Roles & Handoff Matrix

Each agent has a strict persona and distinct responsibilities to prevent hallucinations and overlap.

| Agent | Role | Handoffs To |
|-------|------|-------------|
| **SupportEngineer** | Investigation & Triage (Read-Only) | `@ReleaseEngineer` (infra fixes), `@SoftwareEngineer` (code bugs) |
| **ReleaseEngineer** | Deployment & Rollbacks (Write Access) | `@SoftwareEngineer` (if rollback fails/needs fix) |
| **SoftwareEngineer** | Code Implementation & Review | `@ReleaseEngineer` (to deploy fixes) |

## 4. Evaluation Framework (DeepEval)

We use **DeepEval** with **G-Eval** (GPT-based evaluation) to score agent performance against semantic criteria rather than exact string matching.

*   **Scoring:** 0.0 to 1.0 scale.
*   **Metrics:** Custom metrics like `InvestigationQuality`, `EvidenceBasedDecision`, `HandoffCompletion`.
*   **Judge Model:** Azure OpenAI `gpt-4.1-mini` (or similar).

## 5. The Self-Reinforcement Loop

The "secret sauce" is the feedback loop driven by the engineering agent (OpenCode).

1.  **Execute Eval:** OpenCode runs `scripts/eval_slack_e2e.py` to simulate a user scenario in a real Slack channel.
2.  **Analyze Report:** The script generates a Markdown report with conversation transcripts and G-Eval scores.
3.  **Review & Refine:** OpenCode analyzes low scores to identify root causes (e.g., "over-investigation," "hallucinated handoffs").
4.  **Modify Code:** OpenCode patches the Gateway routing logic or Agent system prompts.
5.  **Verify:** OpenCode reruns the eval to confirm the score improved.

---

## Case Study: Optimizing SupportEngineer Notifications

**Scenario:** A user asks the SupportEngineer to simply "notify the team" about a deployment.
**Goal:** The agent should just send the message, not waste time/tokens investigating infrastructure.

### Phase 1: Baseline (The Problem)
*   **Input:** "@SupportEngineer please notify the team..."
*   **Behavior:** The agent ignored the simple request, fetched Sentry logs, checked Kubernetes pods, found no errors, and reported "Infrastructure healthy" before sending the notification.
*   **Eval Score:** `0.3` (Fail - Over-investigation)

### Phase 2: Gateway Optimization
*   **Action:** We updated `vibeteam/gateway/routes/slack.py` to detect "notify" intent.
*   **Change:** Injected a "Simplified Prompt" for notification tasks, explicitly forbidding tool usage.
*   **Result:** Agent behavior improved, but it still attempted to initialize the heavy context tools (Sentry/Kubectl) before seeing the prompt, wasting latency.

### Phase 3: Agent Code Optimization
*   **Action:** We updated `agents/openhands/support_engineer.py` to check the task type *before* context injection.
*   **Change:**
    ```python
    if is_notification and not is_explicit_investigation:
        skip_infra_context = True  # Skip Sentry/Kubectl fetch
    ```
*   **Result:** Latency dropped significantly.

### Phase 4: Final Polish (Self-Correction)
*   **Observation:** During verification, OpenCode noticed a typo in the new prompt (`specificy` vs `Specify`).
*   **Action:** OpenCode corrected the typo in `slack.py` and redeployed the Gateway.
*   **Final Eval:**
    *   **Scenario:** `support_notify_check`
    *   **Score:** `1.0` (Perfect)
    *   **Latency:** Reduced by ~40%
    *   **Output:** "The deployment of PR #123 to staging is complete and verified." (No infra checks)

### Evidence of Progression

| Iteration | Metric | Score | Outcome |
|-----------|--------|-------|---------|
| Baseline | `NotificationOnly` | 0.30 | ❌ Fail (Checked Sentry) |
| Prompt Fix | `NotificationOnly` | 0.85 | ✅ Pass (Behavior correct, high latency) |
| Context Fix | `NotificationOnly` | 1.00 | ✅ Pass (Fast & Correct) |

This loop demonstrates how the system can "self-heal" and optimize its own cognitive architectures through rigorous, metric-driven evaluation.
