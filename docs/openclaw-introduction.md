# OpenClaw Introduction

This repository runs a hybrid agent stack. OpenHands agents handle most roles, while OpenClaw powers ProductManager (and optionally others) through a dedicated gateway.

## Why OpenClaw

OpenClaw provides durable multi-session agent execution and a browser-capable runtime. In VibeTeam we use it to:

- Route specific roles (e.g., ProductManager) to OpenClaw via `openclaw-svc`.
- Run browser-driven tasks using CDP (Chrome DevTools skill).
- Keep model routing inside the cluster via LiteLLM.

## High-Level Flow

1. Slack/Gateway routes an OpenClaw role (via `agents.yaml`) to `openclaw-svc`.
2. `openclaw-svc` connects to OpenClaw Gateway over WebSocket.
3. OpenClaw Gateway loads `openclaw.json` from `openclaw-config` and agent prompts from `openclaw-agent-prompts`.
4. OpenClaw uses the in-namespace LiteLLM service for Azure OpenAI access.
5. Browser tasks are executed through CDP using the in-cluster `browserless` service.

## Configuration Sources

- **Routing**: `agents.yaml` (framework, Slack handle, prompt path, OpenClaw agent ID)
- **OpenClaw config**: `k8s/base/openclaw-config.yaml`
- **OpenClaw prompts**: `k8s/base/openclaw-prompts/`
- **Gateway**: `k8s/base/openclaw-gateway.yaml`

## Browser / Chrome DevTools Skill

OpenClaw does not use MCP. It uses its built-in browser/CDP tooling. In OpenClaw prompts, we treat that as the **Chrome DevTools skill** and explicitly confirm its usage in responses.

The CDP endpoint is wired to browserless in-cluster:

```
cdpUrl: http://browserless:3000
attachOnly: true
```

## Required Secrets

- `vibeteam-secrets`: Azure OpenAI + LiteLLM keys
- `openclaw-secret`: `OPENCLAW_GATEWAY_TOKEN`

## Quick Deploy (Dev)

```bash
kubectl apply -k k8s/overlays/dev
```

## E2E Eval (OpenClaw)

See `docs/OpenClawEval.md` for the exact commands to run the Slack E2E test against a dev tenant.
