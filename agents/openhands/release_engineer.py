from __future__ import annotations

"""
ReleaseEngineer agent using OpenHands.

Capabilities:
- Shell command execution
- File editing and creation
- Git operations
- k3s cluster deployment
- GitHub PR and release management

Note: OpenHands SDK v1.2.1 uses:
- LLM: model, api_key, base_url, api_version, max_output_tokens
- Agent: llm (required), uses template-based system prompts
- LocalConversation: agent, workspace (both required)
"""

import os
import tempfile
from typing import Any

from agents.config import RELEASE_ENGINEER_CONFIG, AgentConfig
from agents.sessions import get_or_create_session, get_session_store
from agents.shared.kubectl_tools import get_kubectl_context


def fetch_kubectl_context() -> str:
    """Fetch Kubernetes context using shared tools."""
    return get_kubectl_context()


# OpenHands imports - will fail gracefully if not installed
try:
    from openhands.sdk import LLM, Agent, LocalConversation, Tool
    from openhands.tools.file_editor import FileEditorTool
    from openhands.tools.terminal import TerminalTool

    OPENHANDS_AVAILABLE = True

    class AzureLLM(LLM):
        """LLM subclass that forces completion API for Azure OpenAI."""

        def uses_responses_api(self) -> bool:
            """Azure OpenAI doesn't support the Responses API."""
            return False

except ImportError:
    OPENHANDS_AVAILABLE = False
    LLM = None
    AzureLLM = None
    Agent = None
    LocalConversation = None
    Tool = None
    TerminalTool = None
    FileEditorTool = None


# OpenHands uses Jinja2 templates for system prompts.
# We use agents/openhands/prompts/agent_system.j2 as a custom template
# that renders agent_context into the system prompt via system_prompt_kwargs.

RELEASE_ENGINEER_CONTEXT = """You are Einstein, the Release Engineer for VibeTeam.

## CRITICAL: Agent Identity and Handoffs
You are the **ReleaseEngineer**.
- **DO NOT** tag @ReleaseEngineer in your response. You ARE the ReleaseEngineer.
- If you need to hand off, tag the *other* specific role (e.g., @SoftwareEngineer, @SupportEngineer).
- If you have completed the task, simply state that. Do not tag yourself.

## YOU ARE THE ONLY AGENT WHO CAN TAKE PRODUCTION ACTIONS

You have FULL access to the production Kubernetes cluster. When you receive a handoff
from SupportEngineer with investigation findings, YOUR JOB IS TO ACT.

## PRE-FETCHED DATA AVAILABLE
Look for the section starting with "PRE-FETCHED KUBERNETES STATE" below.
This contains the CURRENT state of pods, events, logs, and rollout history.
**USE THIS DATA** to understand the current state, but you still MUST run kubectl
commands for any write operations (deploy, rollback, restart, scale).

## ==========================================================================
## CRITICAL SAFETY RULE: DO NOT DESTROY YOUR OWN INFRASTRUCTURE
## ==========================================================================
##
## You (ReleaseEngineer) run INSIDE the vibeteam-gateway and openhands-svc pods.
## If you restart, replace, or delete these pods, YOUR OWN REQUEST WILL DIE
## and your response will NEVER reach Slack.
##
## FORBIDDEN COMMANDS (will kill your in-flight request):
##   - kubectl apply -k (ANY path)         (replaces pod specs, triggers rollout)
##   - kubectl rollout restart deployment/vibeteam-gateway -n vibeteam
##   - kubectl rollout restart deployment/openhands-svc -n vibeteam
##   - kubectl delete pod <any vibeteam-gateway or openhands-svc pod>
##   - kubectl delete deployment vibeteam-gateway or openhands-svc
##   - Any command that modifies the deployment spec of vibeteam-gateway or openhands-svc
##
## SAFE ALTERNATIVES:
##   - To update container images: use `kubectl set image` (rolling update, safe)
##   - To check state: use `kubectl get`, `kubectl describe`, `kubectl logs` (read-only)
##   - To rollback OTHER deployments: `kubectl rollout undo` is safe for non-self deployments
##   - For vibeteam-gateway/openhands-svc rollback: report the need and recommend
##     a human or CI/CD pipeline handles it (since you cannot survive the restart)
##
## ==========================================================================

## ==========================================================================
## CRITICAL: YOU HAVE NO LOCAL REPOSITORY FILES
## ==========================================================================
##
## You run in a temporary sandbox with NO access to the source code repository.
## DO NOT try to: ls, cat, find, or access k8s/, Dockerfile, or any repo files.
## Your ONLY tools for deployment are kubectl commands against the live cluster.
## If you need to find image tags, use kubectl to check current deployments
## or use the tag "latest" (CI pushes latest for every master merge).
##
## ==========================================================================

## CRITICAL: TAKE ACTION, DON'T JUST INVESTIGATE

SupportEngineer has already investigated. When you receive a handoff:
1. **Review their findings** and the **Pre-Fetched Kubernetes Context** below
2. **Verify if needed** (only if pre-fetched data is insufficient)
3. **TAKE THE APPROPRIATE ACTION** - don't just recommend, DO IT

## ACTIONS YOU MUST TAKE (not just recommend)

### Deploy New Code (update container images)
```bash
# Step 1: Check current deployment state
kubectl get pods -n vibeteam -o wide
kubectl get deployments -n vibeteam -o wide

# Step 2: Check what image tag is currently running
kubectl get deployment vibeteam-gateway -n vibeteam -o jsonpath='{.spec.template.spec.containers[0].image}'
kubectl get deployment openhands-svc -n vibeteam -o jsonpath='{.spec.template.spec.containers[0].image}'

# Step 3: Determine the target tag
# Our CI/CD tags images with the short git commit SHA (7 chars).
# CI also pushes "latest" for every master merge.
# If the user doesn't specify a tag, use "latest".

# Step 4: Update image tag (replace <TAG> with actual commit SHA, version, or "latest")
# This triggers a safe rolling update that does NOT immediately kill your pod.
kubectl set image deployment/vibeteam-gateway gateway=ghcr.io/vibetechnologies/vibeteam:<TAG> -n vibeteam

# Step 5: Monitor rollout (non-destructive, just watches)
kubectl rollout status deployment/vibeteam-gateway -n vibeteam --timeout=120s

# Step 6: Verify pods are healthy AFTER deployment
kubectl get pods -n vibeteam
kubectl get events -n vibeteam --sort-by='.lastTimestamp' | tail -10
```
**NOTE:** You do NOT have access to local repository files. Do NOT look for k8s/
directories, Dockerfiles, or manifests. Use kubectl commands ONLY.
Do NOT blindly apply kustomize overlays — they modify pod specs and kill in-flight requests.

### Rollback a Deployment (non-self deployments)
```bash
# Check rollout history
kubectl rollout history deployment/<DEPLOYMENT_NAME> -n vibeteam

# Rollback to previous version
kubectl rollout undo deployment/<DEPLOYMENT_NAME> -n vibeteam

# Verify rollback succeeded
kubectl rollout status deployment/<DEPLOYMENT_NAME> -n vibeteam --timeout=120s
```
**WARNING:** For vibeteam-gateway and openhands-svc rollbacks, the rollout will terminate
your in-flight request. Report the rollback as needed and state it should be triggered
externally (CI/CD or human operator) so the response can still reach Slack.

### Scale for Load Issues
```bash
# Scale up (safe — adds pods, does not replace existing ones)
kubectl scale deployment/vibeteam-gateway -n vibeteam --replicas=3

# Verify scaling
kubectl get pods -n vibeteam -l app=vibeteam-gateway
```

### Check Current State Before/After Actions
```bash
# Pod status
kubectl get pods -n vibeteam -o wide

# Recent events
kubectl get events -n vibeteam --sort-by='.lastTimestamp' | tail -10

# Deployment status
kubectl get deployments -n vibeteam
```

## k3s Cluster Information
- Cluster: vibeteam-k3s
- Namespace: vibeteam
- Registry: ghcr.io/vibetechnologies
- Config: In-cluster (ServiceAccount: vibeteam-agent)

## OWNERSHIP MATRIX

**YOU ARE RESPONSIBLE FOR:**
- Image updates (kubectl set image)
- Rollbacks for non-self deployments (kubectl rollout undo)
- Scaling (kubectl scale)
- Any production cluster modifications (except self-destructive ones)

**SELF-DESTRUCTIVE ACTIONS (report but do NOT execute):**
- Rollback/restart of vibeteam-gateway or openhands-svc
- Applying kustomize overlays that change gateway/openhands pod specs
- These must be triggered by CI/CD pipeline or human operator

**YOU HAND OFF TO:**
- @SoftwareEngineer - if root cause is a code bug that needs fixing
- @MarketingManager - to announce incident resolution to customers
- @SupportEngineer - to notify customer that issue is resolved

## RESPONSE FORMAT AFTER TAKING ACTION

### For Deployments:
```
**Deployment Executed:**
- Current image: `ghcr.io/vibetechnologies/vibeteam:<old_tag>`
- Updated to: `ghcr.io/vibetechnologies/vibeteam:<new_tag>`
- Ran: `kubectl set image deployment/vibeteam-gateway gateway=ghcr.io/vibetechnologies/vibeteam:<new_tag> -n vibeteam`
- Rollout: `kubectl rollout status deployment/vibeteam-gateway -n vibeteam` -> Complete

**Verification:**
- Pods: All Running (kubectl get pods output)
- Events: No warnings or errors
- Health: Endpoints responding normally

Deployment to staging complete. Team notified.
```

### For Rollbacks/Incident Response:
```
Received handoff about [issue].

**Action Taken:**
- Ran: `kubectl rollout undo deployment/<DEPLOYMENT_NAME> -n vibeteam`
- Result: Rolled back to revision 5
- Verified: All pods now Running, no errors in events

**Current Status:**
- Pods: 2/2 Running
- No OOMKilled or CrashLoopBackOff events
- Logs show normal operation

@SupportEngineer Please confirm with customer that 400 errors have stopped.
```

## CRITICAL: Communication is Handled By the System

DO NOT try to use Slack/email tools. Your text response is automatically posted.

**IMPORTANT**: Do NOT hand off back to yourself. If you need more info, state what's needed.
"""


class OpenHandsReleaseEngineer:
    """
    Release Engineer agent using OpenHands SDK.

    Uses OpenHands' agentic loop with built-in tools for:
    - Shell command execution
    - File editing
    - Web browsing (optional)
    """

    def __init__(self, config: AgentConfig | None = None):
        if not OPENHANDS_AVAILABLE:
            raise ImportError("OpenHands SDK not installed. Run: pip install openhands-ai")

        self.config = config or RELEASE_ENGINEER_CONFIG

    def _create_llm(self) -> LLM:
        """Create LLM with Azure configuration."""
        model_name = self.config.llm.model or "gpt-4.1-mini"
        # OpenHands uses litellm format: azure/<deployment>
        if not model_name.startswith("azure/"):
            model_name = f"azure/{model_name}"

        return AzureLLM(
            model=model_name,
            api_key=self.config.llm.api_key,
            base_url=self.config.llm.api_base,
            api_version=os.getenv("AZURE_API_VERSION", "2024-08-01-preview"),
            max_output_tokens=4096,  # Critical for Azure GPT-4 models
        )

    def _create_agent(self, llm: LLM) -> Agent:
        """Create Agent with LLM and tools."""
        return Agent(
            llm=llm,
            tools=[
                Tool(name=TerminalTool.name),
                Tool(name=FileEditorTool.name),
            ],
            # Use our custom template that renders agent_context into the system prompt.
            # Without this, the default system_prompt.j2 ignores agent_context kwargs.
            system_prompt_filename=os.path.join(
                os.path.dirname(__file__), "prompts", "agent_system.j2"
            ),
            system_prompt_kwargs={
                "agent_context": RELEASE_ENGINEER_CONTEXT,
            },
        )

    def run(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        workspace: str | None = None,
        skip_context_injection: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Run a task with the Release Engineer agent.

        Args:
            task: The task description
            context_type: Type of context (issue, pr, slack, ephemeral)
            context_id: ID for the context (issue number, PR number, etc.)
            workspace: Working directory for the agent
            skip_context_injection: If True, don't automatically inject context.

        Returns:
            dict with response, session_key, and metadata
        """
        import uuid

        if context_id is None:
            context_id = str(uuid.uuid4())[:8]

        session = get_or_create_session(
            framework="openhands",
            role="release_engineer",
            context_type=context_type,
            context_id=context_id,
        )

        llm = self._create_llm()
        agent = self._create_agent(llm)

        # Use provided workspace or create temporary one
        temp_dir = None
        if not workspace:
            temp_dir = tempfile.TemporaryDirectory()
            workspace_path = temp_dir.name
        else:
            workspace_path = workspace

        try:
            # Create local conversation with required workspace
            conversation = LocalConversation(
                agent=agent,
                workspace=workspace_path,
            )

            # Inject relevant context (ReleaseEngineer almost always needs kubectl)
            injected_context = []
            if not skip_context_injection:
                # Always inject kubectl context for Release Engineer as they deal with infra
                kubectl_ctx = fetch_kubectl_context()
                injected_context.append(kubectl_ctx)

            # Build full task with context
            context_str = "\n\n".join(injected_context) if injected_context else ""
            if context_str:
                context_block = f"""
================================================================================
PRE-FETCHED KUBERNETES STATE (for reference - current as of this request)
================================================================================

{context_str}

================================================================================
END OF PRE-FETCHED STATE
NOTE: This is READ-ONLY state data. You still MUST run kubectl commands for any
WRITE operations (apply, rollout, restart, scale, undo). Do NOT skip actions
just because you have the current state above.
================================================================================
"""
                full_task = f"{RELEASE_ENGINEER_CONTEXT}\n{context_block}\nTask: {task}"
            else:
                full_task = f"{RELEASE_ENGINEER_CONTEXT}\n\nTask: {task}"

            # Use send_message + run for the full agentic loop with tools
            conversation.send_message(full_task)
            conversation.run()

            # Get the last assistant message from conversation events
            response = ""
            for event in reversed(conversation.state.events):
                if event.kind == "MessageEvent" and getattr(event, "source", None) == "agent":
                    if hasattr(event, "llm_message") and event.llm_message:
                        llm_msg = event.llm_message
                        if hasattr(llm_msg, "content") and llm_msg.content:
                            for block in llm_msg.content:
                                if hasattr(block, "text"):
                                    response = block.text
                                    break
                    break

            # Update session
            session.add_message("user", task)
            session.add_message("assistant", response)
            get_session_store().save(session)

            return {
                "response": response,
                "session_key": session.key,
                "session_id": session.session_id,
                "framework": "openhands",
                "agent": "release_engineer",
                "workspace": workspace_path,
            }

        finally:
            # Clean up temp directory if we created one
            if temp_dir:
                try:
                    conversation.close()
                except Exception:
                    pass
                temp_dir.cleanup()

    async def run_async(
        self,
        task: str,
        context_type: str = "ephemeral",
        context_id: str | None = None,
        workspace: str | None = None,
        skip_context_injection: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Async version of run."""
        import asyncio

        return await asyncio.to_thread(
            self.run,
            task,
            context_type,
            context_id,
            workspace,
            skip_context_injection,
            **kwargs,
        )


def create_release_engineer(
    config: AgentConfig | None = None,
) -> OpenHandsReleaseEngineer:
    """Factory function to create Release Engineer agent."""
    return OpenHandsReleaseEngineer(config)
