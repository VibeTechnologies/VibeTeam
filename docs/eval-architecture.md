# VibeTeam E2E Evaluation Architecture

## High-Level Test Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        E2E EVALUATION FLOW                                   │
└─────────────────────────────────────────────────────────────────────────────┘

    ┌──────────────────┐
    │  eval_slack_e2e  │  (Local Python Script)
    │      .py         │
    └────────┬─────────┘
             │
    ┌────────▼─────────┐
    │ 1. Post Message  │  "@SupportEngineer there is a request..."
    │    to Slack      │
    └────────┬─────────┘
             │
             │  Slack API (slack_sdk)
             ▼
    ┌─────────────────────────────────────────────────────────────────────┐
    │                         SLACK WORKSPACE                              │
    │  ┌─────────────────────────────────────────────────────────────┐    │
    │  │  #all-vibetechnologies (C0AATPSADB8)                         │    │
    │  │                                                              │    │
    │  │  [User] @SupportEngineer there is a request from a user...  │    │
    │  │  ├── [SupportEngineer] I'll investigate the 400 errors...   │    │
    │  │  ├── [SupportEngineer] Found issue in Sentry: ...           │    │
    │  │  └── [SupportEngineer] @ReleaseEngineer please rollback...  │    │
    │  │      └── [ReleaseEngineer] Rolling back deployment...       │    │
    │  └─────────────────────────────────────────────────────────────┘    │
    └─────────────────────────────────────────────────────────────────────┘
             │
             │  2. Trigger Gateway (explicit POST request)
             │     POST /slack/trigger (Bearer token: SLACK_TRIGGER_SECRET)
             ▼
    ┌─────────────────────────────────────────────────────────────────────┐
    │                      KUBERNETES CLUSTER                              │
    │                        (namespace: vibeteam)                         │
    │                                                                      │
    │  ┌─────────────────────────────────────────────────────────────┐    │
    │  │                   vibeteam-gateway                           │    │
    │  │  ┌─────────────┐  ┌─────────────┐  ┌───────────────────┐    │    │
    │  │  │ /slack/     │  │ Role        │  │ Framework         │    │    │
    │  │  │  trigger    │──│ Parser      │──│ Router            │    │    │
    │  │  │             │  │ @Support... │  │ DEFAULT_FRAMEWORK │    │    │
    │  │  └─────────────┘  └─────────────┘  └─────────┬─────────┘    │    │
    │  └──────────────────────────────────────────────┼───────────────┘    │
    │                                                  │                    │
    │         ┌────────────────────────────────────────┼──────────────┐    │
    │         │                                        │              │    │
    │         ▼                                        ▼              ▼    │
    │  ┌─────────────┐                          ┌─────────────┐ ┌────────┐│
    │  │ crewai-svc  │                          │openhands-svc│ │autogen-││
    │  │  :8080/run  │                          │  :8080/run  │ │  -svc  ││
    │  └──────┬──────┘                          └──────┬──────┘ └────────┘│
    │         │                                        │                   │
    │         │                                        │                   │
    │         ▼                                        ▼                   │
    │  ┌─────────────────────────────────────────────────────────────┐    │
    │  │                    AGENT FRAMEWORKS                          │    │
    │  │                                                              │    │
    │  │  ┌─────────────────────────────────────────────────────┐    │    │
    │  │  │  OpenHands Agent (current focus)                    │    │    │
    │  │  │                                                      │    │    │
    │  │  │  ┌──────────────────┐   ┌────────────────────────┐  │    │    │
    │  │  │  │ support_engineer │   │ Tools:                 │  │    │    │
    │  │  │  │ software_engineer│   │  - slack_tools.py      │  │    │    │
    │  │  │  │ release_engineer │   │  - sentry (k8s access) │  │    │    │
    │  │  │  │ product_manager  │   │  - shell (kubectl)     │  │    │    │
    │  │  │  │ marketing_manager│   │  - handoff.py          │  │    │    │
    │  │  │  └──────────────────┘   └────────────────────────┘  │    │    │
    │  │  │                                                      │    │    │
    │  │  │  POST /run  →  asyncio.to_thread(agent.run())       │    │    │
    │  │  │                (non-blocking for health probes)      │    │    │
    │  │  └─────────────────────────────────────────────────────┘    │    │
    │  └─────────────────────────────────────────────────────────────┘    │
    │                                                                      │
    │  ┌─────────────────────────────────────────────────────────────┐    │
    │  │                    INFRASTRUCTURE                            │    │
    │  │  ┌────────────┐  ┌────────────┐  ┌────────────────────────┐ │    │
    │  │  │ postgres-0 │  │ scheduler  │  │ ServiceAccount:        │ │    │
    │  │  │ (sessions) │  │    -svc    │  │ vibeteam-agent         │ │    │
    │  │  └────────────┘  └────────────┘  │ (readonly + ops in     │ │    │
    │  │                                 │  vibeteam namespace)   │ │    │
    │  │                                   └────────────────────────┘ │    │
    │  └─────────────────────────────────────────────────────────────┘    │
    └─────────────────────────────────────────────────────────────────────┘
             │
             │  3. Agent executes task, uses tools
             │     (Sentry, kubectl, slack_sdk)
             │
             │  4. Agent posts response to Slack thread
             │
             ▼
    ┌────────────────────┐
    │ 5. Poll for Reply  │  (eval script checks thread every 5s)
    │    wait_timeout    │
    └────────┬───────────┘
             │
    ## Components (Short)

    - `scripts/eval_slack_e2e.py` posts to Slack, then calls `POST /slack/trigger`.
    - The gateway parses role mentions and routes to `DEFAULT_FRAMEWORK`.
    - The agent service executes the role task and replies in-thread.
    - DeepEval scores the collected transcript and writes a report.

    ## Handoff Flow

    - Agents mention `@OtherAgent` or `/OtherAgent` in replies.
    - The router subscribes the mentioned agent to the thread.
    - The eval script keeps polling until the thread is idle and includes handoff replies.
    │   "Found deployment  │
    │   issue from 8am.    │
    │   @ReleaseEngineer   │──────┐
    │   please rollback"   │      │
    └──────────────────────┘      │
                                  │  Handoff detected
                                  │  (@ReleaseEngineer)
                                  │
              ┌───────────────────┘
              │
              ▼
    ┌──────────────────────┐
    │   ReleaseEngineer    │
    │   (OpenHands Agent)  │
    │                      │
    │   1. Check PR status │
    │   2. kubectl rollout │
    │      undo            │
    │   3. Verify health   │
    │                      │
    │   Response:          │
    │   "Rolled back to    │
    │   previous version.  │
    │   Health checks OK." │
    └──────────────────────┘
              │
              ▼
    ┌──────────────────────┐
    │  Conversation Done   │
    │  (no more handoffs)  │
    │                      │
    │  Eval script detects │
    │  stability (10s no   │
    │  new messages)       │
    └──────────────────────┘
```

## Key Issues We Fixed

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          PROBLEMS & FIXES                                    │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  PROBLEM: Health probe timeouts causing pod restarts                         │
│  ─────────────────────────────────────────────────────────────────────────  │
│                                                                              │
│  Before:                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  POST /run arrives                                                   │   │
│  │        │                                                             │   │
│  │        ▼                                                             │   │
│  │  agent.run() BLOCKS event loop (30-60 seconds)                       │   │
│  │        │                                                             │   │
│  │        │  Meanwhile: GET /health times out                           │   │
│  │        │  Kubernetes: Pod not responding!                            │   │
│  │        │  Action: KILL POD AND RESTART                               │   │
│  │        │                                                             │   │
│  │        ▼                                                             │   │
│  │  Gateway gets: "Failed to connect to agent service"                  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  After (commit 8c593bd):                                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  POST /run arrives                                                   │   │
│  │        │                                                             │   │
│  │        ▼                                                             │   │
│  │  asyncio.to_thread(agent.run, ...)                                   │   │
│  │        │                                                             │   │
│  │        │  Event loop stays responsive!                               │   │
│  │        │  GET /health → 200 OK ✓                                     │   │
│  │        │  Kubernetes: Pod healthy ✓                                  │   │
│  │        │                                                             │   │
│  │        ▼                                                             │   │
│  │  agent.run() completes in thread pool                               │   │
│  │        │                                                             │   │
│  │        ▼                                                             │   │
│  │  Return response to gateway → post to Slack                         │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  PROBLEM: Gateway using wrong framework                                      │
│  ─────────────────────────────────────────────────────────────────────────  │
│                                                                              │
│  Fix: DEFAULT_FRAMEWORK set to `openhands` in `k8s/base/vibeteam-gateway.yaml`│
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  PROBLEM: Missing slack_sdk in OpenHands requirements                        │
│  ─────────────────────────────────────────────────────────────────────────  │
│                                                                              │
│  Fix (commit d2c7388): Added slack_sdk>=3.21.0 to requirements.txt          │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Running the Evaluation

```bash
# 1. Setup port-forward (if not running)
kubectl port-forward svc/vibeteam-gateway 8000:8080 -n vibeteam &

# 2. Run evaluation
uv run python scripts/eval_slack_e2e.py \
    --scenario support_400_errors \
    --channel C0AATPSADB8 \
    --timeout 180

# 3. Check results
ls -la results/eval_reports/

# 4. View latest report
cat results/eval_reports/eval_support_400_errors_*.md | head -100
```

## Evaluation Scoring Rubric

| Score Range | Meaning | Example |
|-------------|---------|---------|
| 0.0 - 0.2 | Complete failure | Tools failed, no investigation, circular handoffs |
| 0.2 - 0.4 | Minimal effort | External HTTP checks only, no internal tool access |
| 0.4 - 0.6 | Partial success | Some tools worked, partial findings |
| 0.6 - 0.8 | Good | Root cause identified with evidence |
| 0.8 - 1.0 | Excellent | Full investigation, resolution implemented |

## Metrics and Thresholds

Metrics and thresholds are **scenario-specific** and defined in `scripts/eval_slack_e2e.py` (`SCENARIOS`). Typical thresholds range `0.60`–`0.80`. A scenario passes only if **all** of its metrics meet their thresholds, and the report lists each metric with its threshold.

Common metrics include:
- InvestigationQuality
- EvidenceBasedDecision
- HandoffCompletion
- ResponseEfficiency
- NotificationOnly
- SentryUsage
- GmailUsage
- IssueAnalysis
- DeploymentExecution
- CorrectNamespace
- ChromeDevToolsUsage
- HNFitAndGuidelines
- CommunityFitAndRules
- SoftPromoQuality

If DeepEval is unavailable, reports are written with status `NO EVALUATION (DeepEval not available)` and no metric scores.
