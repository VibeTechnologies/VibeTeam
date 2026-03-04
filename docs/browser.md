# Browser/CDP Topology

This document describes the browser automation path used by VibeTeam agents.

## Runtime Diagram

```text
                            Internet
                               |
                        Ingress (TLS)
                               |
                        vibeteam-gateway
                               |
           +-------------------+-------------------+
           |                                       |
      openhands-svc                           openclaw-svc
      (agent-service)                         (agent-service)
           |                                       |
           | CHROME_DEVTOOLS_BROWSER_URL           | OPENCLAW_GATEWAY_URL
           v                                       v
      browserless <------------------------- openclaw-gateway
    (browserless/chrome)                           |
           |                                       |
           +--------------- CDP endpoint ----------+
                           browserless:3000

Other core services:
- scheduler-svc
- postgres
- litellm
- gmail-processor
```

## What Is Deployed

- `browserless` is deployed as `browserless/chrome:latest` and exposed as a ClusterIP service on port `3000`.
- `openhands-svc` is configured with `CHROME_DEVTOOLS_BROWSER_URL=http://browserless:3000`.
- OpenClaw gateway config points to the same `cdpUrl` (`http://browserless:3000`).
- Network policy allows ingress to `browserless` only from pods labeled `component=agent-service`.

## Source of Truth

- `k8s/base/browserless.yaml`
- `k8s/base/openhands-svc.yaml`
- `k8s/base/openclaw-config.base.json`
- `k8s/base/openclaw-config.json`
- `k8s/base/openclaw-svc.yaml`
- `k8s/base/openclaw-gateway.yaml`
- `k8s/base/network-policy.yaml`

## Operational Note

CDP wiring can be healthy while specific websites still block browser automation traffic.
In those cases, eval scenarios should either:

1. explicitly allow a blocked-site fallback mode, or
2. use targets less likely to block cloud-hosted browser sessions.
