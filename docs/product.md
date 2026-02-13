# Product Context

## What VibeTeam Is

VibeTeam is an agentic team platform that deploys specialized AI agents for customer support, software engineering, release engineering, marketing, and product management. Agents respond to Slack messages, investigate infrastructure issues, hand off tasks to each other, and take autonomous action across tools (Sentry, kubectl, GitHub, Gmail).

## Competitors

### Tensol (YC W26)

- **Website**: https://tensol.ai
- **Founded by**: Oliviero Pinotti, Pratik Satija
- **Powered by**: OpenClaw
- **What they do**: Deploys autonomous AI employees in secure, isolated environments with one-click integrations, audit logs, and persistent organizational memory. Setup takes 5 minutes.
- **Key differentiator**: Focused on enterprise deployment of OpenClaw — secure isolation, audit trails, persistent memory across sessions.
- **Use cases**: Support agents (resolve tickets, fix bugs), SDRs (lead follow-up, CRM updates), operations agents (invoice chasing, report creation).
- **Pitch**: Most AI agents require prompting, lose context between sessions, and can't work across tools. Tensol solves deployment/security/memory on top of OpenClaw.
- **How they compare to VibeTeam**: Similar multi-role agent vision. Tensol is a managed platform (deploy any role in minutes); VibeTeam is self-hosted on Kubernetes with deeper integration into our own infrastructure (kubectl RBAC, Sentry, Slack routing, agent handoffs).
