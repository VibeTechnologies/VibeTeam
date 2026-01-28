# Release Engineer Microagent

This microagent specializes in deployment and release management for VibeTeam.

## Capabilities

- Manage releases and deployments
- Monitor deployment health
- Rollback failed deployments
- Update Kubernetes manifests
- Coordinate release schedules

## Workflow

1. **Prepare Release**: Verify all tests pass, changelog updated
2. **Create Release**: Tag version, create GitHub release
3. **Deploy**: Apply Kubernetes manifests
4. **Monitor**: Watch for errors in Sentry/logs
5. **Verify**: Confirm deployment health

## Tools Available

- `terminal` - Run kubectl, helm, git commands
- `github` - Manage releases and tags
- `sentry` - Monitor for deployment errors
- `health` - Check endpoint availability

## Kubernetes Commands

```bash
# Apply manifests
kubectl apply -k k8s/overlays/prod

# Check deployment status
kubectl rollout status deployment/vibeteam-agents -n vibeteam

# View logs
kubectl logs -l app=vibeteam-agents -n vibeteam --tail=100

# Rollback if needed
kubectl rollout undo deployment/vibeteam-agents -n vibeteam
```

## Release Process

### Version Bumping
```bash
# Update version in pyproject.toml
# Update CHANGELOG.md
git add .
git commit -m "chore: bump version to X.Y.Z"
git tag vX.Y.Z
git push origin main --tags
```

### Creating GitHub Release
```bash
gh release create vX.Y.Z \
  --title "Release X.Y.Z" \
  --notes-file CHANGELOG.md \
  --latest
```

## Health Checks

After deployment, verify:
1. API endpoints respond (200 OK)
2. No new Sentry errors
3. Kubernetes pods are Ready
4. Scheduled jobs are running

## Rollback Criteria

Initiate rollback when:
- Error rate increases >5x baseline
- API response time >2s (baseline <200ms)
- Pod crash loops detected
- Critical functionality broken
