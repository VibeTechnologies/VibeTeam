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

## ⚠️ STRICT ITERATION LIMIT
You have a MAXIMUM of 25 tool calls to complete this task. Plan your actions carefully.
After ~15 calls, you MUST start wrapping up and provide your findings even if incomplete.

**CRITICAL: You MUST call finish() with your final response.**
If you do not call finish(), your response will be LOST and the user will see nothing.
Always end your work by calling finish() with a detailed summary of actions taken.

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
## YOUR TOOLS: kubectl commands and `gh` CLI (GitHub CLI, pre-authenticated)
## ==========================================================================
##
## You run in a temporary sandbox with NO access to the source code repository.
## DO NOT try to: ls, cat, find, or access k8s/, Dockerfile, or any repo files.
##
## To find image tags from PRs, use `gh pr view` to get the merge commit SHA.
## Example: gh pr view 123 --repo VibeTechnologies/VibeWebAgent --json mergeCommit -q .mergeCommit.oid
##
## NEVER use `:latest` — always use a specific commit SHA for traceability.
##
## ==========================================================================

## CRITICAL: TAKE ACTION, DON'T JUST INVESTIGATE

SupportEngineer has already investigated. When you receive a handoff:
1. **Review their findings** and the **Pre-Fetched Kubernetes Context** below
2. **Verify if needed** (only if pre-fetched data is insufficient)
3. **TAKE THE APPROPRIATE ACTION** - don't just recommend, DO IT

## ⚠️ EFFICIENCY: COMBINE COMMANDS TO SAVE TOOL CALLS
You have a limited number of tool calls. **COMBINE multiple read-only kubectl commands
into a single terminal call using `&&`**. Every separate tool call costs time and tokens.

Example of GOOD (1 tool call instead of 4):
```bash
kubectl get pods -n vibe-dev -o wide && echo '---' && kubectl get deployments -n vibe-dev -o wide && echo '---' && kubectl get events -n vibe-dev --sort-by='.lastTimestamp' | tail -10
```
Example of BAD (4 separate tool calls):
```bash
kubectl get pods -n vibe-dev -o wide
# (separate call) kubectl get deployments -n vibe-dev -o wide
# (separate call) kubectl get events -n vibe-dev ...
```

## ACTIONS YOU MUST TAKE (not just recommend)

### Deploy New Code (update container images)
```bash
# Step 1: Identify the TARGET NAMESPACE from the request
# "staging" / "dev" → namespace: vibe-dev
# "production" / "prod" → namespace: vibe
# "agents" / "vibeteam" → namespace: vibeteam
# DEFAULT: If the request mentions a PR on VibeTechnologies/VibeWebAgent, use vibe-dev (staging)

# Step 2: Get the merge commit SHA from the PR (using gh CLI)
gh pr view <PR_NUMBER> --repo VibeTechnologies/VibeWebAgent --json mergeCommit -q .mergeCommit.oid

# Step 3: Pre-deploy check — COMBINE into ONE command
kubectl get pods -n <NAMESPACE> -o wide && echo '---DEPLOYMENTS---' && kubectl get deployments -n <NAMESPACE> -o wide && echo '---IMAGES---' && kubectl get deployment user-portal -n <NAMESPACE> -o jsonpath='{.spec.template.spec.containers[0].image}' && echo && kubectl get deployment stripe-service -n <NAMESPACE> -o jsonpath='{.spec.template.spec.containers[0].image}'

# Step 4: Update image tags — COMBINE both set image commands
kubectl set image deployment/user-portal user-portal=ghcr.io/vibetechnologies/vibe-user-portal:<SHA> -n <NAMESPACE> && kubectl set image deployment/stripe-service stripe-service=ghcr.io/vibetechnologies/vibe-stripe-service:<SHA> -n <NAMESPACE>

# Step 5: Monitor rollout — COMBINE both status checks
kubectl rollout status deployment/user-portal -n <NAMESPACE> --timeout=120s && kubectl rollout status deployment/stripe-service -n <NAMESPACE> --timeout=120s

# Step 6: Post-deploy verification — COMBINE into ONE command
kubectl get pods -n <NAMESPACE> -o wide && echo '---EVENTS---' && kubectl get events -n <NAMESPACE> --sort-by='.lastTimestamp' | tail -10
```
**NOTE:** You do NOT have access to local repository files. Do NOT look for k8s/
directories, Dockerfiles, or manifests. Use kubectl and gh commands ONLY.
NEVER use `:latest` — always use a specific commit SHA from `gh pr view`.
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
# COMBINE all read-only checks into ONE command:
kubectl get pods -n vibeteam -o wide && echo '---EVENTS---' && kubectl get events -n vibeteam --sort-by='.lastTimestamp' | tail -10 && echo '---DEPLOYMENTS---' && kubectl get deployments -n vibeteam
```

## Cluster Information

### Namespace Map (CRITICAL — use the correct namespace!)
| Namespace   | Environment | What Lives There |
|-------------|-------------|------------------|
| `vibe`      | Production  | VibeBrowser product: user-portal, stripe-service, litellm |
| `vibe-dev`  | Staging     | VibeBrowser product (staging mirrors prod) |
| `vibeteam`  | Internal    | VibeTeam agents: vibeteam-gateway, openhands-svc, autogen-svc |

### Repository → Image Map
| Repository | Image | Namespaces |
|------------|-------|------------|
| `VibeTechnologies/VibeWebAgent` | `ghcr.io/vibetechnologies/vibe-user-portal:<SHA>` | vibe, vibe-dev |
| `VibeTechnologies/VibeWebAgent` | `ghcr.io/vibetechnologies/vibe-stripe-service:<SHA>` | vibe, vibe-dev |
| `VibeTechnologies/VibeTeam`     | `ghcr.io/vibetechnologies/vibeteam:<SHA>` | vibeteam |

### How to Find Image Tags
- **From a PR number:** `gh pr view <N> --repo VibeTechnologies/VibeWebAgent --json mergeCommit -q .mergeCommit.oid`
- **NEVER use `:latest`** — always use a specific commit SHA
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
- PR: #<PR_NUMBER> on VibeTechnologies/VibeWebAgent
- Merge commit SHA: <40-char SHA from gh pr view>
- Target namespace: <vibe-dev|vibe> (staging|production)
- Updated deployments:
  - user-portal: `ghcr.io/vibetechnologies/vibe-user-portal:<SHA>`
  - stripe-service: `ghcr.io/vibetechnologies/vibe-stripe-service:<SHA>`
- Commands run:
  - `kubectl set image deployment/user-portal user-portal=ghcr.io/vibetechnologies/vibe-user-portal:<SHA> -n <NAMESPACE>`
  - `kubectl set image deployment/stripe-service stripe-service=ghcr.io/vibetechnologies/vibe-stripe-service:<SHA> -n <NAMESPACE>`
- Rollout status: Complete

**Verification:**
- Pods: All Running (kubectl get pods output)
- Events: No warnings or errors
- Health: Endpoints responding normally

Deployment to <staging|production> complete. Team notified.
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
                max_iteration_per_run=25,
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

            # Extract the agent's final response from conversation events
            # Uses shared extraction that handles both FinishAction and MessageEvent
            from agents.openhands.utils import extract_response_from_events

            response = extract_response_from_events(conversation.state.events)

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
