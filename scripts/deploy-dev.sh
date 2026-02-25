#!/bin/bash
# Build and deploy dev images that pull fresh code from GitHub on restart
# Usage: ./scripts/deploy-dev.sh [target]
#   target: openhands, autogen, crewai, gateway, all (default: all), or deploy

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
REGISTRY="ghcr.io/vibetechnologies"

TARGET="${1:-all}"

build_and_push() {
    local name=$1
    local dockerfile=$2
    local context=$3
    
    echo "=== Building $name dev image ==="
    docker build -f "$dockerfile" -t "$REGISTRY/vibeteam-$name:dev" "$context"
    
    echo "=== Pushing $name dev image ==="
    docker push "$REGISTRY/vibeteam-$name:dev"
}

build_gateway() {
    echo "=== Building gateway dev image ==="
    docker build -f "$PROJECT_DIR/Dockerfile" -t "$REGISTRY/vibeteam:dev" "$PROJECT_DIR"

    echo "=== Pushing gateway dev image ==="
    docker push "$REGISTRY/vibeteam:dev"
}

restart_if_exists() {
    local name=$1
    if kubectl get deployment "$name" -n vibeteam >/dev/null 2>&1; then
        kubectl rollout restart "deployment/$name" -n vibeteam
        kubectl rollout status "deployment/$name" -n vibeteam --timeout=120s
    fi
}

deploy_dev() {
    echo "=== Deploying dev overlay ==="
    kubectl apply -k "$PROJECT_DIR/k8s/overlays/dev"
    
    echo "=== Restarting deployments to pull fresh code ==="
    restart_if_exists "vibeteam-gateway"
    restart_if_exists "openhands-svc"
    restart_if_exists "openhands-agents"
    restart_if_exists "autogen-svc"
    restart_if_exists "crewai-svc"
}

case "$TARGET" in
    openhands)
        build_and_push "openhands" "$PROJECT_DIR/agent_service/openhands/Dockerfile" "$PROJECT_DIR"
        ;;
    autogen)
        build_and_push "autogen" "$PROJECT_DIR/agent_service/autogen/Dockerfile" "$PROJECT_DIR"
        ;;
    crewai)
        build_and_push "crewai" "$PROJECT_DIR/agent_service/crewai/Dockerfile" "$PROJECT_DIR"
        ;;
    gateway)
        build_gateway
        ;;
    all)
        build_and_push "openhands" "$PROJECT_DIR/agent_service/openhands/Dockerfile" "$PROJECT_DIR"
        build_and_push "autogen" "$PROJECT_DIR/agent_service/autogen/Dockerfile" "$PROJECT_DIR"
        build_and_push "crewai" "$PROJECT_DIR/agent_service/crewai/Dockerfile" "$PROJECT_DIR"
        ;;
    deploy)
        deploy_dev
        ;;
    *)
        echo "Usage: $0 [openhands|autogen|crewai|gateway|all|deploy]"
        exit 1
        ;;
esac

echo ""
echo "=== Dev image(s) built ==="
echo "To deploy: $0 deploy"
echo "To refresh code: kubectl rollout restart deployment/openhands-svc -n vibeteam"
