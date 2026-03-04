# Kubernetes Deploy And Test Guide

This document is the authoritative source for where VibeTeam is deployed and how to run deployment validation.

## Cluster And Namespace Policy

- Kubernetes context/cluster: `aks-1`
- Dev namespace: `vibeteam-dev`
- Prod namespace: `vibeteam-prod`
- Do not deploy to any separate production cluster. Use `aks-1` only.

## Preflight (Mandatory)

Run these checks before any `kubectl apply`:

```bash
kubectl config current-context
kubectl config get-contexts
kubectl --context aks-1 get ns vibeteam-dev
kubectl --context aks-1 get ns vibeteam-prod
```

If your active context is not `aks-1`, switch explicitly:

```bash
kubectl config use-context aks-1
```

## Deploy

### Dev Deploy

```bash
kubectl --context aks-1 apply -k k8s/overlays/dev
kubectl --context aks-1 rollout status deployment/vibeteam-gateway -n vibeteam-dev --timeout=180s
kubectl --context aks-1 rollout status deployment/openhands-svc -n vibeteam-dev --timeout=180s
kubectl --context aks-1 rollout status deployment/openclaw-svc -n vibeteam-dev --timeout=180s
```

### Prod Deploy

```bash
kubectl --context aks-1 apply -k k8s/overlays/prod
kubectl --context aks-1 rollout status deployment/vibeteam-gateway -n vibeteam-prod --timeout=180s
kubectl --context aks-1 rollout status deployment/openhands-svc -n vibeteam-prod --timeout=180s
kubectl --context aks-1 rollout status deployment/openclaw-svc -n vibeteam-prod --timeout=180s
```

## Testing Workflow

Run tests in this order.

1. Unit/integration tests locally.
2. Slack eval against dev namespace deployments.
3. Optional GitHub webhook evals for handoff flows.

### 1) Unit And Integration Tests

```bash
export $( < ~/.env.d/codex.env )
export $( < .env )
.venv/bin/python -m pytest tests/ -v -p no:rerunfailures --run-integration
```

### 2) Slack Evals (Dev)

Pause rollouts to avoid git-sync restarts mid-eval:

```bash
kubectl --context aks-1 rollout pause deployment/vibeteam-gateway -n vibeteam-dev
kubectl --context aks-1 rollout pause deployment/openhands-svc -n vibeteam-dev
```

Run eval:

```bash
export $( < ~/.env.d/codex.env )
export $( < .env )
.venv/bin/python scripts/eval_slack_e2e.py --scenario support_400_errors --channel C0AATPSADB8 --timeout 600
```

Resume rollouts after eval:

```bash
kubectl --context aks-1 rollout resume deployment/vibeteam-gateway -n vibeteam-dev
kubectl --context aks-1 rollout resume deployment/openhands-svc -n vibeteam-dev
```

### 3) OpenClaw CDP Smoke Eval (Dev)

```bash
export $( < ~/.env.d/codex.env )
export $( < .env )
.venv/bin/python scripts/eval_slack_e2e.py --scenario openclaw_chrome_cdp_smoke --channel C0AATPSADB8 --timeout 600
```

## Operational Checks

```bash
kubectl --context aks-1 get pods -n vibeteam-dev
kubectl --context aks-1 logs deployment/vibeteam-gateway -n vibeteam-dev --tail=200
kubectl --context aks-1 logs deployment/openhands-svc -n vibeteam-dev --tail=200
kubectl --context aks-1 logs deployment/openclaw-svc -n vibeteam-dev --tail=200
```

## Notes

- `k8s/overlays/dev/kustomization.yaml` targets `vibeteam-dev`.
- `k8s/overlays/prod/kustomization.yaml` targets `vibeteam-prod`.
- If you see commands elsewhere using `-n vibeteam`, treat this document as authoritative and use the namespace that matches your target environment.
