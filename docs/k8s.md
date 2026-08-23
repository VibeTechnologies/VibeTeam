# Kubernetes Deploy And Test Guide

> **⚠️ NEEDS VERIFICATION (2026-08-23) — this doc's "authoritative" claim does
> not match live cluster state.** Checked read-only against the `openclaw-aks`
> AKS cluster this doc names:
> - `kubectl get ns` shows no `vibeteam` namespace at all (only `default`,
>   `kube-node-lease`, `kube-public`, `kube-system`, and an orphaned `traefik`
>   ns stuck `Terminating` for 191 days with a still-billing public
>   LoadBalancer, `20.81.65.92`). `default` contains only two unrelated
>   one-off `Completed` pods (`data-mover`, `pc-check3`) — no VibeTeam
>   workload of any kind.
> - The actual `openhands-agents` / `openhands-svc` / `scheduler-svc`
>   Deployments that match this repo's `k8s/base/*.yaml` manifests are
>   instead running on a **different** cluster — the Azure `vibe-k3s` cluster
>   (`4.246.58.241`, namespace `default`, not `vibeteam`) — and have been
>   non-Ready for 193 days (`ContainerStatusUnknown` / `ImagePullBackOff`).
>
> Net: as of this check, VibeTeam is not verifiably running anywhere healthy.
> Do not treat the "Cluster And Namespace Policy" section below as current
> without re-confirming the real intended deploy target first — the AKS
> cluster it names has zero VibeTeam presence, and the cluster that does have
> VibeTeam's workloads has had them broken for over six months.

This document is the authoritative source for where VibeTeam is deployed and how to run deployment validation.

## Cluster And Namespace Policy

- Kubernetes cluster: AKS (`aks-1` kubeconfig)
- Active context in `~/.kube/aks-1`: `openclaw-aks`
- Production namespace: `vibeteam`
- Do not deploy to any separate cluster. Use `aks-1` only.
- Do not use additional namespaces for Slack-connected environments unless you also provision separate Slack app routing.

## Slack Topology (Critical)

Slack Event Subscriptions support a single Request URL per app. A single Slack app cannot deliver events to multiple namespaces at the same time unless you add a routing proxy in front.

Recommended setup:

- Keep the Slack app pointed at the gateway in `vibeteam`.
- Use `/slack/trigger` for evals against the same gateway.
- Store Slack and Azure tokens in `vibeteam/vibeteam-secrets`.

## Preflight (Mandatory)

Run these checks before any `kubectl apply`:

```bash
kubectl config current-context
kubectl config get-contexts
KUBECONFIG=~/.kube/aks-1 kubectl config current-context
KUBECONFIG=~/.kube/aks-1 kubectl get ns vibeteam
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
KUBECONFIG=~/.kube/aks-1 kubectl rollout status deployment/vibeteam-gateway -n vibeteam --timeout=180s
KUBECONFIG=~/.kube/aks-1 kubectl rollout status deployment/openhands-svc -n vibeteam --timeout=180s
KUBECONFIG=~/.kube/aks-1 kubectl rollout status deployment/openclaw-svc -n vibeteam --timeout=180s
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
.venv/bin/python scripts/eval_slack_e2e.py --scenario support_400_errors --channel C0ALG01DLJV --timeout 600
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
.venv/bin/python scripts/eval_slack_e2e.py --scenario openclaw_chrome_cdp_smoke --channel C0ALG01DLJV --timeout 600
```

## Operational Checks

```bash
KUBECONFIG=~/.kube/aks-1 kubectl get pods -n vibeteam
KUBECONFIG=~/.kube/aks-1 kubectl logs deployment/vibeteam-gateway -n vibeteam --tail=200
KUBECONFIG=~/.kube/aks-1 kubectl logs deployment/openhands-svc -n vibeteam --tail=200
KUBECONFIG=~/.kube/aks-1 kubectl logs deployment/openclaw-svc -n vibeteam --tail=200
```

## Notes

- `k8s/overlays/dev/kustomization.yaml` targets `vibeteam`.
- `k8s/overlays/prod/kustomization.yaml` targets `vibeteam`.
- If you see commands elsewhere using other namespaces, treat this document as authoritative and use `vibeteam`.
