---
name: k3s-ops
description: Deploy VibeTeam services to k3s, scale worker nodes, and manage node naming (vibe-backend-vm, vibe-worker-0N, k3s-vmss-<suffix>).
---

# K3s Ops (Vibe)

## Deploy (VibeTeam)

```bash
kubectl apply -k k8s/overlays/dev
# or
kubectl apply -k k8s/overlays/prod
```

Validate rollouts:
```bash
kubectl rollout status deployment/openhands-svc -n vibeteam --timeout=180s
kubectl get pods -n vibeteam
```

## Scale Workers (Standalone VM)

Edit `services/k3s/terraform/variables.tf`:
- `worker_count`

Then apply:
```bash
cd services/k3s/terraform
terraform init
terraform plan
terraform apply
```

## Scale Workers (VMSS + Autoscaler)

Enable VMSS:
```bash
cd services/k3s/terraform
terraform apply -var 'enable_vmss=true'
```

Deploy autoscaler:
```bash
cd services/k3s/manifests
./setup-autoscaler.sh
```

Set bounds in `services/k3s/terraform/variables.tf`:
- `vmss_min_count`
- `vmss_max_count`

## Node Naming (Correct Sources)

- Control-plane: `vibe-backend-vm`
- Standalone workers: `vibe-worker-0N` from `node_name` in `cloud-init-worker.yaml` and VM name in `services/k3s/terraform/main.tf`.
- VMSS workers: `k3s-vmss-<suffix>` from `NODE_NAME` in `cloud-init-vmss.yaml`.

Renaming is **not in-place**. To rename:
1. `kubectl drain <old-node> --ignore-daemonsets --delete-emptydir-data`
2. `kubectl delete node <old-node>`
3. Update naming source (Terraform `node_name` / `cloud-init-vmss.yaml`).
4. Recreate VM/VMSS instance (Terraform apply / VMSS roll).

If you need strict names like `k3s-node-1..N`, use standalone workers (static `node_name`). VMSS names are derived and should stay pattern-based.
