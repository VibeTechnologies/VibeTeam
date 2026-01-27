# ADR 001: Use OpenHands as Agent Infrastructure

**Status:** Accepted  
**Date:** 2026-01-26  
**Decision Makers:** VibeTeam Engineering

## Context

VibeTeam is an autonomous AI team for SaaS development. We needed to decide between two agent platforms:

1. **OpenHands** - Python-based agent framework with Docker sandbox
2. **OpenCode** - TypeScript-based agent framework with rich TUI

The decision impacts:
- How we define and trigger agent skills
- How we integrate with external services (Sentry, GitHub, Slack, Gmail)
- Whether code-modifying agents run in sandboxed environments
- Long-term maintainability of the Python codebase

## Decision

**We will continue using OpenHands as our agent infrastructure.**

## Rationale

### 1. Already Deployed
OpenHands Server is already running in our Kubernetes cluster:
- Deployment: `ghcr.io/all-hands-ai/openhands:0.40`
- Namespace: `vibeteam`
- Runtime: Local (no Docker-in-Docker)

### 2. Python-Native Tools
Our existing tools and connectors are Python:
- `vibeteam/tools/sentry.py`
- `vibeteam/tools/github.py`
- `vibeteam/connectors/*.py`

Switching to OpenCode would require rewriting these in TypeScript or creating shell wrappers.

### 3. Skills Already Defined
We have keyword-triggered skills in `.openhands/skills/`:
- `sentry-triage/` - Error classification
- `customer-support/` - Email handling
- `code-fix/` - PR guidelines

### 4. Docker Sandbox Available
OpenHands provides Docker sandboxing for code-modifying agents (SoftwareEngineer), which is important for security when agents clone and modify external repositories.

### 5. Webhook Integration Works
Our webhook server (`vibeteam/webhook/server.py`) already routes events to OpenHands:
- Sentry errors -> Release Engineer
- GitHub issues -> Software Engineer
- Slack mentions -> General agent

## Alternatives Considered

### OpenCode

**Pros:**
- Rich TUI experience
- Session forking and sharing
- Plugin/hook system
- Granular agent permissions

**Cons:**
- TypeScript-based (our codebase is Python)
- No Docker sandboxing
- Would require rewriting all tools
- Not deployed yet

### Custom LiteLLM Framework (Current)

**Pros:**
- Full control
- Python native

**Cons:**
- Maintenance burden
- Missing features (sandboxing, skills, subagents)
- Reinventing the wheel

## Consequences

### Positive
- Leverage existing OpenHands deployment
- No rewrite of Python tools needed
- Access to OpenHands ecosystem (public skills, community)
- Docker sandbox for secure code execution

### Negative
- Dependent on OpenHands project maintenance
- Limited TUI compared to OpenCode
- No session forking capability

### Migration Path
If we ever need to switch to OpenCode:
1. Skills use similar format (SKILL.md with YAML frontmatter)
2. Tools would need TypeScript wrappers
3. Webhook would call OpenCode API instead of OpenHands

## Related

- OpenHands Docs: https://docs.all-hands.dev
- Skills Overview: https://docs.all-hands.dev/modules/usage/prompting/microagents-overview
- K8s Deployment: `k8s/base/openhands/deployment.yaml`
