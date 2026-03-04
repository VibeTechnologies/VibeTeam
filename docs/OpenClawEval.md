# OpenClaw Slack E2E Eval (support_400_errors)

## One-time setup
```bash
export $( < .env )
unset AZURE_OPENAI_ENDPOINT AZURE_OPENAI_API_KEY
export SLACK_BOT_TOKEN="$(KUBECONFIG=~/.kube/aks-1 kubectl get secret vibeteam-secrets -n vibeteam -o jsonpath='{.data.SLACK_BOT_TOKEN}' | base64 -d)"
export SLACK_TRIGGER_SECRET="$(KUBECONFIG=~/.kube/aks-1 kubectl get secret vibeteam-secrets -n vibeteam -o jsonpath='{.data.SLACK_TRIGGER_SECRET}' | base64 -d)"
export AZURE_API_KEY="$(KUBECONFIG=~/.kube/aks-1 kubectl get secret vibeteam-secrets -n vibeteam -o jsonpath='{.data.AZURE_API_KEY}' | base64 -d)"
export AZURE_API_BASE="$(KUBECONFIG=~/.kube/aks-1 kubectl get secret vibeteam-secrets -n vibeteam -o jsonpath='{.data.AZURE_API_BASE}' | base64 -d)"
export AZURE_API_VERSION="$(KUBECONFIG=~/.kube/aks-1 kubectl get secret vibeteam-secrets -n vibeteam -o jsonpath='{.data.AZURE_API_VERSION}' | base64 -d)"
export AZURE_EVAL_API_VERSION="$AZURE_API_VERSION"
export SLACK_DEFAULT_CHANNEL="C0AATPSADB8"
```

## Port-forward gateway
```bash
KUBECONFIG=~/.kube/aks-1 kubectl port-forward -n vibeteam svc/vibeteam-gateway 18080:8080
```

## Run eval (OpenClaw)
```bash
PYTHONUNBUFFERED=1 GATEWAY_URL=http://127.0.0.1:18080 \
  uv run python scripts/eval_slack_e2e.py \
  --scenario support_400_errors \
  --channel C0AATPSADB8 \
  --framework openclaw \
  --timeout 1200
```

## Latest report (PASS)
- `results/eval_reports/eval_support_400_errors_20260228_091228.md`
