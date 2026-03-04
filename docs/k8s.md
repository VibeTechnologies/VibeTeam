# Kubernetes Deploy And Test Guide

This document is the authoritative source for where VibeTeam is deployed and how to run deployment validation.

## Cluster And Namespace Policy

- Kubernetes cluster: AKS (`aks-1` kubeconfig)
- Active context in `~/.kube/aks-1`: `openclaw-aks`
- Production namespace: `vibeteam`
- Secondary namespace for isolated OpenClaw eval/testing: `vibeteam-openclaw-1`
- Do not deploy to any separate cluster. Use `aks-1` only.

## Slack Topology (Critical)

Slack Event Subscriptions support a single Request URL per app. A single Slack app cannot deliver events to both `vibeteam` and `vibeteam-openclaw-1` at the same time unless you add a routing proxy in front.

Recommended setup:

- Keep the primary Slack app pointed at the production gateway in `vibeteam`.
- If you need live Slack events in `vibeteam-openclaw-1`, use a separate Slack app or a request router.
- Store each app's token/signing secret in the matching namespace secret.

If you keep one Slack app:

- Point it to production (`vibeteam`) only.
- Use `/slack/trigger` for isolated evals by targeting the `vibeteam-openclaw-1` gateway directly.
- Do not expect both namespaces to receive live Slack events simultaneously.

## Preflight (Mandatory)

Run these checks before any `kubectl apply`:

```bash
kubectl config current-context
kubectl config get-contexts
KUBECONFIG=~/.kube/aks-1 kubectl config current-context
KUBECONFIG=~/.kube/aks-1 kubectl get ns vibeteam
KUBECONFIG=~/.kube/aks-1 kubectl get ns vibeteam-openclaw-1
```

Use the AKS kubeconfig explicitly to avoid targeting the wrong cluster:

```bash
export KUBECONFIG=~/.kube/aks-1
kubectl config use-context openclaw-aks
```

## Deploy

### Dev Deploy

```bash
KUBECONFIG=~/.kube/aks-1 kubectl apply -k k8s/overlays/dev
KUBECONFIG=~/.kube/aks-1 kubectl rollout status deployment/vibeteam-gateway -n vibeteam-openclaw-1 --timeout=180s
KUBECONFIG=~/.kube/aks-1 kubectl rollout status deployment/openhands-svc -n vibeteam-openclaw-1 --timeout=180s
KUBECONFIG=~/.kube/aks-1 kubectl rollout status deployment/openclaw-svc -n vibeteam-openclaw-1 --timeout=180s
```

### Prod Deploy

```bash
KUBECONFIG=~/.kube/aks-1 kubectl apply -k k8s/overlays/prod
KUBECONFIG=~/.kube/aks-1 kubectl rollout status deployment/vibeteam-gateway -n vibeteam --timeout=180s
KUBECONFIG=~/.kube/aks-1 kubectl rollout status deployment/openhands-svc -n vibeteam --timeout=180s
KUBECONFIG=~/.kube/aks-1 kubectl rollout status deployment/openclaw-svc -n vibeteam --timeout=180s
```

## Testing Workflow

Run tests in this order.

1. Unit/integration tests locally.
2. Slack eval against the active Slack app target (normally `vibeteam`).
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
KUBECONFIG=~/.kube/aks-1 kubectl rollout pause deployment/vibeteam-gateway -n vibeteam
KUBECONFIG=~/.kube/aks-1 kubectl rollout pause deployment/openhands-svc -n vibeteam
```

Run eval:

```bash
export $( < ~/.env.d/codex.env )
export $( < .env )
.venv/bin/python scripts/eval_slack_e2e.py --scenario support_400_errors --channel C0AATPSADB8 --timeout 600
```

Resume rollouts after eval:

```bash
KUBECONFIG=~/.kube/aks-1 kubectl rollout resume deployment/vibeteam-gateway -n vibeteam
KUBECONFIG=~/.kube/aks-1 kubectl rollout resume deployment/openhands-svc -n vibeteam
```

### 3) OpenClaw CDP Smoke Eval (Dev)

```bash
export $( < ~/.env.d/codex.env )
export $( < .env )
.venv/bin/python scripts/eval_slack_e2e.py --scenario openclaw_chrome_cdp_smoke --channel C0AATPSADB8 --timeout 600
```

## Operational Checks

```bash
KUBECONFIG=~/.kube/aks-1 kubectl get pods -n vibeteam
KUBECONFIG=~/.kube/aks-1 kubectl logs deployment/vibeteam-gateway -n vibeteam --tail=200
KUBECONFIG=~/.kube/aks-1 kubectl logs deployment/openhands-svc -n vibeteam --tail=200
KUBECONFIG=~/.kube/aks-1 kubectl logs deployment/openclaw-svc -n vibeteam --tail=200
```

## Notes

- `k8s/overlays/dev/kustomization.yaml` targets `vibeteam-openclaw-1`.
- `k8s/overlays/prod/kustomization.yaml` targets `vibeteam`.
- If you see commands elsewhere using `-n vibeteam`, treat this document as authoritative and use the namespace that matches your target environment.
