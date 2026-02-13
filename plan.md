# VibeTeam Production Readiness Assessment

**Date:** 2026-02-13
**Status:** NOT production ready -- 3 high-severity, 3 medium-severity issues

## Current Task: Fix stripe_webhook_failure eval (Issue #105)

### Goal
Fix 3 bugs causing the `stripe_webhook_failure` eval to fail:

1. [x] Duplicate handoff execution — bot messages re-processed by Slack event handler
2. [x] Timeout callback error logging — `{e}` produces empty string, no retry
3. [x] No concurrency controls — unlimited agent executions cause queue starvation
4. [x] Tests pass (509/509)
5. [ ] Deploy fixes to cluster
6. [ ] Re-run stripe_webhook_failure eval and verify pass
7. [ ] Create PR with results

### Changes Made
- `vibeteam/gateway/routes/slack.py:1375-1417`: Skip self-posted bot messages that
  contain role mentions (handoffs already handled by callback handler). Detects
  own messages via `[DisplayName]` prefix pattern in thread replies.
- `agent_service/openhands/server.py:27-45`: Added `MAX_CONCURRENT_JOBS` semaphore
  (default 3, configurable via env var) to prevent resource exhaustion.
- `agent_service/openhands/server.py:435+,488+`: Timeout callback retry with
  exponential backoff (3 attempts), `repr(e)` for full error details.

---

## Detailed Findings

### 1. PostgreSQL UUID Type Mismatch [HIGH]

**Problem:** `agents/shared/db.py:36` defines `id = Column(String(36))` but
`scripts/migrate_db.py:106` creates the table with `id UUID PRIMARY KEY`.
PostgreSQL rejects the INSERT: `column "id" is of type uuid but expression is
of type character varying`.

**Impact:** No agent sessions persist. Every request creates a new session.
Conversation history is lost between messages.

**Fix:** Change ORM model to use `Column(UUID(as_uuid=True))` or change
migration to use `VARCHAR(36)`. Must be consistent.

### 2. Database Schema Drift [HIGH]

**Problem:** Three conflicting schema definitions exist:

| Column | design.md | migrate_db.py | db.py ORM |
|--------|-----------|---------------|-----------|
| `id` | UUID | UUID | String(36) |
| source/context_type | source VARCHAR(50) | -- | context_type String(50) |
| thread_id/context_id | thread_id VARCHAR(255) | -- | context_id String(255) |
| workspace | VARCHAR(500) | -- | -- |

No migration framework (Alembic) exists. `init_db()` and `migrate_db.py`
produce different schemas.

**Fix:** Adopt Alembic, create a single source of truth for schema, add
migration versioning.

### 3. Missing Production K8s Infrastructure [HIGH]

| Component | Status | Impact |
|-----------|--------|--------|
| HPA (autoscaling) | Missing | Cannot handle load spikes |
| PDB (disruption budgets) | Missing | Node maintenance = full downtime |
| Network policies | Missing | Any pod can access postgres directly |
| Ingress/TLS | Not in repo | Managed externally (risk: undocumented) |
| Circuit breaker | Missing | Cascading failures possible |
| Rate limiting | Partial (trigger only) | DoS risk on /slack/events, /webhook |
| Resource limits | Present | Properly configured |
| Monitoring/metrics | Sentry+Langfuse only | No Prometheus, no dashboards, no alerting |

### 4. Eval Script Timing Bug [MEDIUM]

**Problem:** `scripts/eval_slack_e2e.py:766` uses `stable_time_no_handoff = 15`
seconds. The polling loop (lines 772-823) only counts messages, not content
changes. When the gateway updates "Thinking..." via `chat.update`, message count
stays the same, so the eval thinks the conversation is "stable" while the agent
is still processing.

**Evidence:** Agent finished at 02:30:04 (86s after trigger), eval exited at
02:29:11 (21s after trigger).

**Fix options:**
1. Compare message text content, not just count
2. Track message edit timestamps (`edited.ts` in Slack API)
3. Increase `stable_time_no_handoff` to 120s
4. Use progress callback polling to know when agent is done

### 5. Gmail Processor Pods Failing [MEDIUM]

**Problem:** Both gmail-processor pods stuck in `Init:0/1` because K8s secret
`gmail-oauth-secret` doesn't exist. The template at
`k8s/base/gmail-secrets.yaml` has placeholder values only.

**Impact:** Email processing (SupportEngineer email triage) is completely
non-functional.

**Fix:** Document OAuth credential setup in requirements.md. Create and apply
the actual secret.

### 6. AGENTS.md Model Reference Stale [MEDIUM]

**Problem:** Root `AGENTS.md` references `gpt-4.1-mini` but all code and docs
use `gpt-5.2`. Minor but could mislead developers.

**Fix:** Update AGENTS.md to reference `gpt-5.2`.

### 7. Discord Integration Incomplete [LOW]

**Problem:** Discord runs via polling scripts only
(`scripts/run_discord_bot.py`). No gateway webhook route, no K8s deployment.
The connector code exists (`vibeteam/connectors/discord.py`, 661 lines) but is
unused by the gateway.

**Impact:** Discord is not a production-ready integration channel.

---

## What's Working Well

1. **Agent quality:** The SupportEngineer produced a thorough, evidence-based
   investigation with Sentry queries, kubectl diagnostics, and actionable
   recommendations.
2. **Async agent pipeline:** Gateway -> OpenHands agent service -> callback flow
   works correctly. The callback was delivered and Slack messages were updated.
3. **Role routing:** `@RoleName` parsing, thread subscriptions, and handoff
   detection are solid.
4. **Resource management:** K8s resource limits/requests are properly configured.
5. **RBAC:** Proper read-only cluster access + scoped write access for agents.
6. **Evaluation framework:** DeepEval G-Eval with multiple scenarios and metrics
   is well-designed (just needs the timing fix).

## Production Readiness Checklist

- [x] Fix PostgreSQL UUID type mismatch
- [x] Unify database schema (adopt Alembic)
- [x] Add HPA for gateway and agent services
- [x] Add PodDisruptionBudgets
- [x] Add NetworkPolicies (especially for postgres)
- [ ] Add comprehensive rate limiting (all endpoints)
- [x] Fix eval script to detect message content changes
- [x] Set up Gmail OAuth credentials
- [ ] Add Prometheus metrics + alerting
- [ ] Document ingress/TLS setup
- [x] Update AGENTS.md model reference
