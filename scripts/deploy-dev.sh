#!/bin/bash
# Build and deploy dev images that pull fresh code from GitHub on restart
# Usage: ./scripts/deploy-dev.sh [framework]
#   framework: crewai, autogen, or all (default: all)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
REGISTRY="ghcr.io/vibetechnologies"

FRAMEWORK="${1:-all}"

build_and_push() {
    local name=$1
    local dockerfile=$2
    local context=$3
    
    echo "=== Building $name dev image ==="
    docker build -f "$dockerfile" -t "$REGISTRY/vibeteam-$name:dev" "$context"
    
    echo "=== Pushing $name dev image ==="
    docker push "$REGISTRY/vibeteam-$name:dev"
}

deploy_dev() {
    echo "=== Deploying dev overlay ==="
    kubectl apply -k "$PROJECT_DIR/k8s/overlays/dev"
    
    echo "=== Restarting deployments to pull fresh code ==="
    kubectl rollout restart deployment/crewai-agents deployment/autogen-agents -n vibeteam
    
    echo "=== Waiting for rollout ==="
    kubectl rollout status deployment/crewai-agents -n vibeteam --timeout=120s
}

case "$FRAMEWORK" in
    crewai)
        build_and_push "crewai" "$PROJECT_DIR/agents/crewai/Dockerfile.dev" "$PROJECT_DIR"
        ;;
    autogen)
        build_and_push "autogen" "$PROJECT_DIR/agents/autogen/Dockerfile.dev" "$PROJECT_DIR"
        ;;
    all)
        build_and_push "crewai" "$PROJECT_DIR/agents/crewai/Dockerfile.dev" "$PROJECT_DIR"
        build_and_push "autogen" "$PROJECT_DIR/agents/autogen/Dockerfile.dev" "$PROJECT_DIR"
        ;;
    deploy)
        deploy_dev
        ;;
    *)
        echo "Usage: $0 [crewai|autogen|all|deploy]"
        exit 1
        ;;
esac

echo ""
echo "=== Dev image built ==="
echo "To deploy: $0 deploy"
echo "To refresh code: kubectl rollout restart deployment/crewai-agents -n vibeteam"
