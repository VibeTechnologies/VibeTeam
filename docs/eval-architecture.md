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
             │     POST /slack/trigger
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
    │  │  :8001/run  │                          │  :8001/run  │ │  -svc  ││
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
    │  │  └────────────┘  └────────────┘  │ (read-only k8s access) │ │    │
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
    ┌────────▼───────────┐
    │ 6. Collect Thread  │  Get all messages in thread
    │    Conversation    │  Detect handoffs (@ReleaseEngineer)
    └────────┬───────────┘
             │
    ┌────────▼───────────────────────────────────────────────────────────┐
    │  7. DEEPEVAL G-EVAL EVALUATION                                      │
    │                                                                      │
    │  ┌──────────────────────────────────────────────────────────────┐  │
    │  │  Azure OpenAI (gpt-5-2)                                       │  │
    │  │                                                               │  │
    │  │  Metrics Evaluated:                                           │  │
    │  │  ┌─────────────────────────────────────────────────────────┐ │  │
    │  │  │ InvestigationQuality                                    │ │  │
    │  │  │ - Did agent ACTUALLY use tools successfully?            │ │  │
    │  │  │ - Did agent query Sentry, kubectl, find evidence?       │ │  │
    │  │  │ - Score 0.0-1.0 (threshold: 0.60)                       │ │  │
    │  │  └─────────────────────────────────────────────────────────┘ │  │
    │  │  ┌─────────────────────────────────────────────────────────┐ │  │
    │  │  │ TaskCompletion                                          │ │  │
    │  │  │ - Was the customer's issue RESOLVED?                    │ │  │
    │  │  │ - Not just "please help" - actual progress              │ │  │
    │  │  │ - Score 0.0-1.0 (threshold: 0.60)                       │ │  │
    │  │  └─────────────────────────────────────────────────────────┘ │  │
    │  └──────────────────────────────────────────────────────────────┘  │
    └────────┬───────────────────────────────────────────────────────────┘
             │
    ┌────────▼───────────┐
    │ 8. Generate Report │  results/eval_reports/eval_support_400_*.md
    └────────┬───────────┘
             │
             ▼
    ┌─────────────────────────────────────────────────────────────────────┐
    │                        EVALUATION REPORT                             │
    │                                                                      │
    │  Status: ✅ PASSED / ❌ FAILED                                       │
    │  Scenario: Support Engineer - API 400 Errors Investigation          │
    │                                                                      │
    │  | Metric               | Score | Threshold | Status  |             │
    │  |---------------------|-------|-----------|---------|             │
    │  | InvestigationQuality | 0.75  | 0.60      | ✅ Pass |             │
    │  | TaskCompletion       | 0.68  | 0.60      | ✅ Pass |             │
    │                                                                      │
    │  Full Conversation History:                                          │
    │  1. [User] @SupportEngineer there is a request...                   │
    │  2. [SupportEngineer] I'll investigate...                           │
    │  3. [SupportEngineer] Found in Sentry: 500 errors...                │
    │  4. ...                                                              │
    └─────────────────────────────────────────────────────────────────────┘
```

## Test Scenarios

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          AVAILABLE SCENARIOS                                 │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  1. support_400_errors (Primary Test)                                        │
│  ────────────────────────────────────                                        │
│  Message: "@SupportEngineer there is a request from a user who sees the     │
│            issue with Vibe API Gateway returning 400 errors..."             │
│                                                                              │
│  Expected Agent: SupportEngineer                                             │
│  Expected Tools: Sentry queries, kubectl, Slack messages                     │
│  Expected Outcome: Identify root cause, initiate fix/rollback                │
│                                                                              │
│  Evaluation Criteria:                                                        │
│  - InvestigationQuality: Did tools WORK? Evidence found?                     │
│  - TaskCompletion: Was issue RESOLVED or meaningfully addressed?             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  2. github_issue                                                             │
│  ────────────────                                                            │
│  Message: "@SoftwareEngineer we have a new GitHub issue #42 reporting       │
│            that the browser extension crashes when clicking record..."       │
│                                                                              │
│  Expected Agent: SoftwareEngineer                                            │
│  Expected Tools: GitHub API, code analysis                                   │
│  Expected Outcome: Analyze issue, identify cause, propose fix                │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  3. release_deploy                                                           │
│  ─────────────────                                                           │
│  Message: "@ReleaseEngineer we need to deploy the latest changes to         │
│            staging. The PR #123 has been merged..."                          │
│                                                                              │
│  Expected Agent: ReleaseEngineer                                             │
│  Expected Tools: kubectl, GitHub API, deployment pipelines                   │
│  Expected Outcome: Execute deployment, verify health, notify team            │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Component Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        COMPONENT RELATIONSHIPS                               │
└─────────────────────────────────────────────────────────────────────────────┘

                          scripts/
                    ┌─────────────────┐
                    │ eval_slack_e2e  │
                    │      .py        │
                    └────────┬────────┘
                             │ uses
                             ▼
               vibeteam/connectors/
                    ┌─────────────────┐
                    │ slack.py        │ SlackConnector
                    │                 │ - post_message()
                    │                 │ - get_thread_replies()
                    └─────────────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
         ▼                   ▼                   ▼
    ┌─────────┐        ┌─────────┐        ┌─────────┐
    │ Slack   │        │ Gateway │        │ DeepEval│
    │   API   │        │   API   │        │ G-Eval  │
    └─────────┘        └─────────┘        └─────────┘


                       vibeteam/gateway/
    ┌───────────────────────────────────────────────────────────────────────┐
    │                                                                        │
    │  routes/slack.py                routes/api.py                          │
    │  ┌─────────────────────┐       ┌─────────────────────┐                │
    │  │ /slack/events       │       │ /run                │                │
    │  │ /slack/trigger      │       │ /health             │                │
    │  │ /slack/interactive  │       │ /metrics            │                │
    │  └──────────┬──────────┘       └─────────────────────┘                │
    │             │                                                          │
    │             │ parse_role_mentions()                                    │
    │             │ route_to_framework()                                     │
    │             ▼                                                          │
    │  ┌─────────────────────────────────────────────────────────────────┐  │
    │  │  Framework Router                                                │  │
    │  │  DEFAULT_FRAMEWORK env var → openhands | crewai | autogen       │  │
    │  │                                                                  │  │
    │  │  HTTP POST to framework service:                                 │  │
    │  │  - openhands-svc:8001/run                                       │  │
    │  │  - crewai-svc:8001/run                                          │  │
    │  │  - autogen-svc:8001/run                                         │  │
    │  └─────────────────────────────────────────────────────────────────┘  │
    └───────────────────────────────────────────────────────────────────────┘


                         agents/openhands/
    ┌───────────────────────────────────────────────────────────────────────┐
    │                                                                        │
    │  server.py                                                             │
    │  ┌─────────────────────────────────────────────────────────────────┐  │
    │  │ POST /run                                                        │  │
    │  │   request: { task, role, channel, thread_ts }                   │  │
    │  │                                                                  │  │
    │  │   agent = get_agent(role)  # support_engineer.py, etc.          │  │
    │  │                                                                  │  │
    │  │   # KEY FIX: Non-blocking execution                              │  │
    │  │   result = await asyncio.to_thread(                              │  │
    │  │       agent.run,                                                 │  │
    │  │       task=request.task,                                        │  │
    │  │       ...                                                        │  │
    │  │   )                                                              │  │
    │  │                                                                  │  │
    │  │   return { response, status }                                   │  │
    │  └─────────────────────────────────────────────────────────────────┘  │
    │                                                                        │
    │  Agent Files:                                                          │
    │  ┌───────────────┐ ┌───────────────┐ ┌───────────────┐               │
    │  │ support_      │ │ software_     │ │ release_      │               │
    │  │ engineer.py   │ │ engineer.py   │ │ engineer.py   │               │
    │  └───────────────┘ └───────────────┘ └───────────────┘               │
    │  ┌───────────────┐ ┌───────────────┐                                  │
    │  │ product_      │ │ marketing_    │                                  │
    │  │ manager.py    │ │ manager.py    │                                  │
    │  └───────────────┘ └───────────────┘                                  │
    │                                                                        │
    └───────────────────────────────────────────────────────────────────────┘


                          agents/shared/
    ┌───────────────────────────────────────────────────────────────────────┐
    │  Shared Tools (used by all frameworks)                                 │
    │                                                                        │
    │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
    │  │ slack_tools │  │ handoff.py  │  │ browser_    │  │ gmail_tools │  │
    │  │    .py      │  │             │  │  tools.py   │  │    .py      │  │
    │  │             │  │ @RoleName   │  │             │  │             │  │
    │  │ post_msg()  │  │ handoffs    │  │ browse()    │  │ send_email()│  │
    │  │ reply()     │  │             │  │             │  │             │  │
    │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘  │
    │                                                                        │
    │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                    │
    │  │ scheduler_  │  │ docs_tools  │  │ langfuse_   │                    │
    │  │  tools.py   │  │    .py      │  │  tools.py   │                    │
    │  └─────────────┘  └─────────────┘  └─────────────┘                    │
    └───────────────────────────────────────────────────────────────────────┘
```

## Handoff Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           AGENT HANDOFF FLOW                                 │
└─────────────────────────────────────────────────────────────────────────────┘

User: "@SupportEngineer investigate 400 errors"
              │
              ▼
    ┌──────────────────────┐
    │   SupportEngineer    │
    │   (OpenHands Agent)  │
    │                      │
    │   1. Query Sentry    │
    │   2. Check kubectl   │
    │   3. Identify issue  │
    │                      │
    │   Response:          │
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
│  Fix: kubectl set env deployment/vibeteam-gateway DEFAULT_FRAMEWORK=openhands│
│  TODO: Persist in kustomize overlay                                          │
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

**Threshold: 0.60** (must achieve to pass)
