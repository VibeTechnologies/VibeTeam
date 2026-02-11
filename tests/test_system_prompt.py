"""
Tests for agent system prompt template configuration.

Verifies that:
1. The custom agent_system.j2 template exists and contains required variables
2. The system_prompt_filename path construction is correct for all agents
3. The template would be found at runtime (Docker or local)
"""

from __future__ import annotations

import os

import pytest

# Path to the prompts directory (same logic agents use at runtime)
PROMPTS_DIR = os.path.join(os.path.dirname(__file__), os.pardir, "agents", "openhands", "prompts")
TEMPLATE_PATH = os.path.join(PROMPTS_DIR, "agent_system.j2")


class TestTemplateExists:
    """Verify the template file exists and has required content."""

    def test_template_file_exists(self):
        assert os.path.isfile(TEMPLATE_PATH), f"agent_system.j2 not found at {TEMPLATE_PATH}"

    def test_template_contains_agent_context_variable(self):
        with open(TEMPLATE_PATH) as f:
            content = f.read()
        assert "{{ agent_context }}" in content, (
            "Template must contain {{ agent_context }} variable"
        )

    def test_template_contains_execution_instructions(self):
        with open(TEMPLATE_PATH) as f:
            content = f.read()
        # Must instruct agent to actually execute, not just describe
        assert "MUST" in content or "CRITICAL" in content, (
            "Template should contain strong execution instructions"
        )

    def test_template_is_valid_jinja2(self):
        """Basic check that the template has balanced Jinja2 blocks."""
        with open(TEMPLATE_PATH) as f:
            content = f.read()
        # Count opening and closing block tags
        opens = content.count("{%")
        closes = content.count("%}")
        assert opens == closes, f"Unbalanced Jinja2 block tags: {opens} opens vs {closes} closes"
        var_opens = content.count("{{")
        var_closes = content.count("}}")
        assert var_opens == var_closes, (
            f"Unbalanced Jinja2 variable tags: {var_opens} opens vs {var_closes} closes"
        )


class TestAgentPromptFilenameConstruction:
    """
    Verify each agent constructs the correct path to agent_system.j2.

    Since we can't import the OpenHands SDK locally, we verify by:
    1. Reading each agent source file
    2. Checking it references system_prompt_filename with the correct path pattern
    3. Verifying the resolved path points to a real file
    """

    AGENT_FILES = [
        "release_engineer.py",
        "software_engineer.py",
        "support_engineer.py",
        "marketing_manager.py",
        "product_manager.py",
    ]

    @pytest.mark.parametrize("agent_file", AGENT_FILES)
    def test_agent_has_system_prompt_filename(self, agent_file: str):
        """Each agent must set system_prompt_filename in _create_agent."""
        filepath = os.path.join(
            os.path.dirname(__file__),
            os.pardir,
            "agents",
            "openhands",
            agent_file,
        )
        with open(filepath) as f:
            content = f.read()

        assert "system_prompt_filename" in content, (
            f"{agent_file} does not set system_prompt_filename"
        )

    @pytest.mark.parametrize("agent_file", AGENT_FILES)
    def test_agent_uses_correct_template_path(self, agent_file: str):
        """Each agent must reference prompts/agent_system.j2."""
        filepath = os.path.join(
            os.path.dirname(__file__),
            os.pardir,
            "agents",
            "openhands",
            agent_file,
        )
        with open(filepath) as f:
            content = f.read()

        assert "agent_system.j2" in content, f"{agent_file} does not reference agent_system.j2"
        assert "os.path.dirname(__file__)" in content, (
            f"{agent_file} should use os.path.dirname(__file__) for reliable path resolution"
        )

    @pytest.mark.parametrize("agent_file", AGENT_FILES)
    def test_resolved_path_exists(self, agent_file: str):
        """The path each agent would construct at runtime must point to a real file."""
        # Simulate: os.path.join(os.path.dirname(__file__), "prompts", "agent_system.j2")
        # where __file__ is the agent module
        agent_dir = os.path.join(
            os.path.dirname(__file__),
            os.pardir,
            "agents",
            "openhands",
        )
        resolved = os.path.join(agent_dir, "prompts", "agent_system.j2")
        assert os.path.isfile(resolved), f"Resolved template path does not exist: {resolved}"

    @pytest.mark.parametrize("agent_file", AGENT_FILES)
    def test_agent_has_system_prompt_kwargs(self, agent_file: str):
        """Each agent must also set system_prompt_kwargs with agent_context."""
        filepath = os.path.join(
            os.path.dirname(__file__),
            os.pardir,
            "agents",
            "openhands",
            agent_file,
        )
        with open(filepath) as f:
            content = f.read()

        assert "system_prompt_kwargs" in content, f"{agent_file} does not set system_prompt_kwargs"
        assert '"agent_context"' in content, (
            f'{agent_file} does not pass "agent_context" in system_prompt_kwargs'
        )


class TestTemplateContent:
    """Verify the template has essential sections from the OpenHands default."""

    def _read_template(self) -> str:
        with open(TEMPLATE_PATH) as f:
            return f.read()

    def test_has_execution_rules(self):
        content = self._read_template()
        assert "EXECUTION_RULES" in content

    def test_has_file_system_guidelines(self):
        content = self._read_template()
        assert "FILE_SYSTEM_GUIDELINES" in content

    def test_has_process_management(self):
        content = self._read_template()
        assert "PROCESS_MANAGEMENT" in content

    def test_has_security_section(self):
        content = self._read_template()
        assert "SECURITY" in content

    def test_has_problem_solving(self):
        content = self._read_template()
        assert "PROBLEM_SOLVING" in content

    def test_forbids_describing_instead_of_executing(self):
        """The template must contain a clear instruction to execute, not describe."""
        content = self._read_template()
        assert "MUST actually run" in content or "MUST run" in content


class TestReleaseEngineerSafetyGuardrails:
    """Verify the ReleaseEngineer context has self-infrastructure safety guardrails."""

    @staticmethod
    def _read_re_context() -> str:
        filepath = os.path.join(
            os.path.dirname(__file__),
            os.pardir,
            "agents",
            "openhands",
            "release_engineer.py",
        )
        with open(filepath) as f:
            return f.read()

    def test_has_safety_rule_header(self):
        """Must have the critical safety rule about self-infrastructure."""
        content = self._read_re_context()
        assert "DO NOT DESTROY YOUR OWN INFRASTRUCTURE" in content

    def test_forbids_kubectl_apply_k(self):
        """Must explicitly forbid kubectl apply -k (all paths)."""
        content = self._read_re_context()
        # The command must appear in a FORBIDDEN context, not as an instruction to run
        assert "kubectl apply -k" in content
        # Must NOT appear outside a forbidden/warning block as a command to execute
        lines = content.split("\n")
        for line in lines:
            stripped = line.strip()
            if "kubectl apply -k" in stripped:
                # Line should be in a comment/forbidden section, not a "Step 2" instruction
                assert (
                    stripped.startswith("#")
                    or "FORBIDDEN" in stripped
                    or "replaces pod" in stripped
                    or "Do NOT" in stripped
                    or "kustomize overlays" in stripped
                ), f"Unsafe line found: {stripped}"

    def test_forbids_kubectl_rollout_restart_gateway(self):
        """Must explicitly forbid kubectl rollout restart on gateway."""
        content = self._read_re_context()
        assert "kubectl rollout restart deployment/vibeteam-gateway" in content
        # Verify it's in the forbidden section
        lines = content.split("\n")
        for line in lines:
            stripped = line.strip()
            if "kubectl rollout restart deployment/vibeteam-gateway" in stripped:
                assert stripped.startswith("#"), f"Unsafe line found: {stripped}"

    def test_forbids_kubectl_rollout_restart_openhands(self):
        """Must explicitly forbid kubectl rollout restart on openhands-svc."""
        content = self._read_re_context()
        assert "kubectl rollout restart deployment/openhands-svc" in content

    def test_recommends_kubectl_set_image(self):
        """Must recommend kubectl set image as the safe alternative."""
        content = self._read_re_context()
        assert "kubectl set image" in content

    def test_no_restart_pods_section(self):
        """The 'Restart Pods' section that told agents to restart gateway must be gone."""
        content = self._read_re_context()
        # Should NOT have a section header like "### Restart Pods"
        assert "### Restart Pods" not in content

    def test_deploy_section_uses_set_image(self):
        """The 'Deploy New Code' section must use kubectl set image, not kubectl apply."""
        content = self._read_re_context()
        # Find the deploy section
        deploy_start = content.find("### Deploy New Code")
        assert deploy_start != -1, "Deploy section not found"
        # Find the next section header
        next_section = content.find("###", deploy_start + 1)
        deploy_section = (
            content[deploy_start:next_section] if next_section != -1 else content[deploy_start:]
        )
        assert "kubectl set image" in deploy_section
        # Must NOT contain kubectl apply -k as an instruction
        for line in deploy_section.split("\n"):
            stripped = line.strip()
            if "kubectl apply -k" in stripped and not stripped.startswith("#"):
                pytest.fail(f"Deploy section contains unsafe kubectl apply: {stripped}")

    def test_has_self_destructive_actions_section(self):
        """Must document which actions are self-destructive."""
        content = self._read_re_context()
        assert "SELF-DESTRUCTIVE ACTIONS" in content

    def test_has_command_combining_instruction(self):
        """Must instruct agent to combine kubectl commands using &&."""
        content = self._read_re_context()
        assert "COMBINE" in content
        assert "&&" in content
        # Should have explicit efficiency section
        assert "EFFICIENCY" in content or "SAVE TOOL CALLS" in content.upper()

    def test_deploy_steps_use_combined_commands(self):
        """The deploy steps should show combined commands, not separate ones."""
        content = self._read_re_context()
        deploy_start = content.find("### Deploy New Code")
        assert deploy_start != -1
        next_section = content.find("###", deploy_start + 1)
        deploy_section = (
            content[deploy_start:next_section] if next_section != -1 else content[deploy_start:]
        )
        # Pre-deploy check should be combined into ONE command
        assert "Pre-deploy check" in deploy_section or "COMBINE" in deploy_section
        # Should have && in the deployment steps (combined commands)
        bash_blocks = [
            line
            for line in deploy_section.split("\n")
            if "kubectl" in line and "&&" in line and not line.strip().startswith("#")
        ]
        assert len(bash_blocks) >= 2, (
            f"Expected at least 2 combined kubectl commands in deploy section, "
            f"found {len(bash_blocks)}"
        )


class TestDeploymentTaskTemplateSafety:
    """Verify the deployment task template in slack.py has safety guardrails."""

    @staticmethod
    def _read_slack_py() -> str:
        filepath = os.path.join(
            os.path.dirname(__file__),
            os.pardir,
            "vibeteam",
            "gateway",
            "routes",
            "slack.py",
        )
        with open(filepath) as f:
            return f.read()

    def test_has_safety_rule_in_deployment_template(self):
        """Deployment task template must warn about self-infrastructure destruction."""
        content = self._read_slack_py()
        assert "DO NOT DESTROY YOUR OWN INFRASTRUCTURE" in content

    def test_deployment_template_forbids_kubectl_apply_k(self):
        """Deployment template must list kubectl apply -k as forbidden."""
        content = self._read_slack_py()
        # Find the deployment template section
        deploy_start = content.find("## Slack Deployment Request")
        assert deploy_start != -1, "Deployment template not found"
        deploy_end = content.find('elif template == "notification"', deploy_start)
        deploy_section = content[deploy_start:deploy_end]

        # kubectl apply -k must be in FORBIDDEN section, not as instruction
        assert "kubectl apply -k" in deploy_section
        # The deployment steps should use kubectl set image
        assert "kubectl set image" in deploy_section

    def test_deployment_template_uses_set_image(self):
        """Deployment template must instruct agent to use kubectl set image."""
        content = self._read_slack_py()
        deploy_start = content.find("## Slack Deployment Request")
        deploy_end = content.find('elif template == "notification"', deploy_start)
        deploy_section = content[deploy_start:deploy_end]
        assert "kubectl set image" in deploy_section

    def test_deployment_template_has_image_check_step(self):
        """Deployment template must include a step to check current image tags."""
        content = self._read_slack_py()
        deploy_start = content.find("## Slack Deployment Request")
        deploy_end = content.find('elif template == "notification"', deploy_start)
        deploy_section = content[deploy_start:deploy_end]
        assert "Check Current Image Tags" in deploy_section or "jsonpath" in deploy_section


class TestNamespaceAwareness:
    """Verify ReleaseEngineer and deployment template have correct namespace awareness.

    The agent must know:
    - vibe-dev is staging for VibeBrowser (VibeTechnologies/VibeWebAgent)
    - vibe is production for VibeBrowser
    - vibeteam is internal (VibeTeam agents)
    - Image names: vibe-user-portal, vibe-stripe-service (not vibeteam-gateway)
    - Use `gh pr view` to get merge commit SHA, never use :latest
    """

    @staticmethod
    def _read_re_context() -> str:
        filepath = os.path.join(
            os.path.dirname(__file__),
            os.pardir,
            "agents",
            "openhands",
            "release_engineer.py",
        )
        with open(filepath) as f:
            return f.read()

    @staticmethod
    def _read_slack_py() -> str:
        filepath = os.path.join(
            os.path.dirname(__file__),
            os.pardir,
            "vibeteam",
            "gateway",
            "routes",
            "slack.py",
        )
        with open(filepath) as f:
            return f.read()

    # --- ReleaseEngineer context tests ---

    def test_re_context_has_namespace_map(self):
        """RE context must include a namespace map with vibe, vibe-dev, vibeteam."""
        content = self._read_re_context()
        assert "vibe-dev" in content
        assert "Staging" in content or "staging" in content

    def test_re_context_has_vibebrowser_images(self):
        """RE context must reference VibeBrowser images (vibe-user-portal, vibe-stripe-service)."""
        content = self._read_re_context()
        assert "vibe-user-portal" in content
        assert "vibe-stripe-service" in content

    def test_re_context_references_vibewebagent_repo(self):
        """RE context must reference VibeTechnologies/VibeWebAgent as the product repo."""
        content = self._read_re_context()
        assert "VibeTechnologies/VibeWebAgent" in content

    def test_re_context_uses_gh_pr_view(self):
        """RE context must instruct using `gh pr view` to get merge commit SHA."""
        content = self._read_re_context()
        assert "gh pr view" in content
        assert "mergeCommit" in content

    def test_re_context_forbids_latest_tag(self):
        """RE context must forbid using :latest tag."""
        content = self._read_re_context()
        assert "NEVER use `:latest`" in content or "NEVER use `:latest`" in content

    # --- Deployment task template tests ---

    def test_deploy_template_has_namespace_map(self):
        """Deployment template must include namespace map with vibe-dev."""
        content = self._read_slack_py()
        deploy_start = content.find("## Slack Deployment Request")
        deploy_end = content.find('elif template == "notification"', deploy_start)
        deploy_section = content[deploy_start:deploy_end]
        assert "vibe-dev" in deploy_section
        assert "NAMESPACE MAP" in deploy_section

    def test_deploy_template_uses_gh_pr_view(self):
        """Deployment template must use gh pr view to get image tags."""
        content = self._read_slack_py()
        deploy_start = content.find("## Slack Deployment Request")
        deploy_end = content.find('elif template == "notification"', deploy_start)
        deploy_section = content[deploy_start:deploy_end]
        assert "gh pr view" in deploy_section

    def test_deploy_template_references_vibewebagent(self):
        """Deployment template must reference VibeTechnologies/VibeWebAgent."""
        content = self._read_slack_py()
        deploy_start = content.find("## Slack Deployment Request")
        deploy_end = content.find('elif template == "notification"', deploy_start)
        deploy_section = content[deploy_start:deploy_end]
        assert "VibeTechnologies/VibeWebAgent" in deploy_section

    def test_deploy_template_forbids_latest(self):
        """Deployment template must forbid :latest tag."""
        content = self._read_slack_py()
        deploy_start = content.find("## Slack Deployment Request")
        deploy_end = content.find('elif template == "notification"', deploy_start)
        deploy_section = content[deploy_start:deploy_end]
        assert "NEVER use `:latest`" in deploy_section or ":latest" in deploy_section

    def test_deploy_template_has_vibebrowser_images(self):
        """Deployment template must reference VibeBrowser images."""
        content = self._read_slack_py()
        deploy_start = content.find("## Slack Deployment Request")
        deploy_end = content.find('elif template == "notification"', deploy_start)
        deploy_section = content[deploy_start:deploy_end]
        assert "vibe-user-portal" in deploy_section
        assert "vibe-stripe-service" in deploy_section


class TestSoftwareEngineerCodeFirstInvestigation:
    """Verify the SoftwareEngineer prompt prioritizes code investigation over infra checks.

    The IssueAnalysis eval rubric requires: '(2) Analyze the code related to the record
    button functionality.' When the SWE agent checks infra first (Sentry, kubectl, health
    endpoints) instead of searching the repo, IssueAnalysis scores drop to 0.40.
    """

    @staticmethod
    def _read_swe_context() -> str:
        filepath = os.path.join(
            os.path.dirname(__file__),
            os.pardir,
            "agents",
            "openhands",
            "software_engineer.py",
        )
        with open(filepath) as f:
            return f.read()

    def test_has_code_first_investigation_priority(self):
        """Must explicitly say to investigate code FIRST, infra SECOND."""
        content = self._read_swe_context()
        assert "CODE FIRST" in content or "code FIRST" in content

    def test_code_first_appears_before_prefetched_data(self):
        """The code-first instruction must appear BEFORE the pre-fetched data section."""
        content = self._read_swe_context()
        code_first_pos = content.find("CODE FIRST")
        if code_first_pos == -1:
            code_first_pos = content.find("code FIRST")
        prefetched_pos = content.find("PRE-FETCHED DATA")
        assert code_first_pos != -1, "CODE FIRST instruction not found"
        assert prefetched_pos != -1, "PRE-FETCHED DATA section not found"
        assert code_first_pos < prefetched_pos, (
            "CODE FIRST instruction must appear before PRE-FETCHED DATA section"
        )

    def test_mentions_extension_directories(self):
        """Must list common browser extension directory names to search."""
        content = self._read_swe_context()
        # Should mention at least some of these extension-related directories
        extension_dirs = ["extension/", "chrome/", "popup/", "content/"]
        found = sum(1 for d in extension_dirs if d in content)
        assert found >= 2, (
            f"Expected at least 2 extension directory hints, found {found}. "
            f"Checked: {extension_dirs}"
        )

    def test_has_find_command_for_frontend_code(self):
        """Must include a find command example for locating TypeScript/JavaScript files."""
        content = self._read_swe_context()
        assert "find" in content and (".ts" in content or "*.ts" in content)

    def test_has_skip_infra_for_ui_bugs(self):
        """Must tell agent to SKIP infra checks for UI/extension bugs."""
        content = self._read_swe_context()
        # Should have a directive about skipping infra for non-deployment bugs
        assert "SKIP" in content or "skip infra" in content.lower()
        # Must mention that crashes/UI issues don't need infra checks
        assert "crash" in content.lower() or "UI" in content

    def test_github_issue_workflow_includes_find_and_grep(self):
        """The GitHub Issue Investigation workflow must include both find and grep."""
        content = self._read_swe_context()
        workflow_start = content.find("### For GitHub Issue Investigation")
        assert workflow_start != -1, "GitHub Issue Investigation workflow not found"
        # Find the next section
        next_section = content.find("###", workflow_start + 5)
        if next_section == -1:
            next_section = content.find("## ", workflow_start + 5)
        workflow = (
            content[workflow_start:next_section] if next_section != -1 else content[workflow_start:]
        )
        assert "grep" in workflow, "Workflow must include grep for code search"
        assert "find" in workflow, "Workflow must include find for file discovery"

    def test_mentions_infra_only_for_deployment_bugs(self):
        """Must clarify that infra checks are only for deployment-related bugs."""
        content = self._read_swe_context()
        assert "deployment-related" in content.lower() or "deployment related" in content.lower()


class TestSoftwareEngineerIterationBudget:
    """Verify the SoftwareEngineer prompt and config enforce iteration budget.

    The github_issue eval fails when the SWE agent exhausts all iterations
    searching code without calling finish(). These tests ensure:
    1. The prompt has a FINAL REMINDER at the end about calling finish()
    2. The iteration limit numbers are consistent (35 max, wrap up at 20)
    3. max_iteration_per_run is set to 35 (higher than other agents)
    4. The GitHub Issue workflow includes an iteration check step
    5. FORBIDDEN ACTIONS section prevents sequential file reading
    """

    @staticmethod
    def _read_swe_context() -> str:
        filepath = os.path.join(
            os.path.dirname(__file__),
            os.pardir,
            "agents",
            "openhands",
            "software_engineer.py",
        )
        with open(filepath) as f:
            return f.read()

    def test_has_final_reminder_section(self):
        """Prompt must have a FINAL REMINDER section near the end."""
        content = self._read_swe_context()
        # Extract the SOFTWARE_ENGINEER_CONTEXT string
        ctx_start = content.find('SOFTWARE_ENGINEER_CONTEXT = """')
        ctx_end = content.find('"""', ctx_start + 30)
        assert ctx_start != -1 and ctx_end != -1, "SOFTWARE_ENGINEER_CONTEXT not found"
        ctx = content[ctx_start:ctx_end]

        assert "FINAL REMINDER" in ctx, (
            "SOFTWARE_ENGINEER_CONTEXT must contain a FINAL REMINDER section"
        )
        # FINAL REMINDER should be in the last 30% of the prompt
        reminder_pos = ctx.find("FINAL REMINDER")
        assert reminder_pos > len(ctx) * 0.7, (
            f"FINAL REMINDER at position {reminder_pos}/{len(ctx)} — "
            f"must be in the last 30% of the prompt so the LLM sees it last"
        )

    def test_final_reminder_mentions_finish(self):
        """FINAL REMINDER must explicitly tell agent to call finish()."""
        content = self._read_swe_context()
        ctx_start = content.find('SOFTWARE_ENGINEER_CONTEXT = """')
        ctx_end = content.find('"""', ctx_start + 30)
        ctx = content[ctx_start:ctx_end]

        reminder_start = ctx.find("FINAL REMINDER")
        assert reminder_start != -1
        reminder_section = ctx[reminder_start:]

        assert "finish()" in reminder_section, "FINAL REMINDER must mention calling finish()"

    def test_final_reminder_mentions_emergency_mode(self):
        """FINAL REMINDER must have escalating urgency (e.g., EMERGENCY at 30+)."""
        content = self._read_swe_context()
        ctx_start = content.find('SOFTWARE_ENGINEER_CONTEXT = """')
        ctx_end = content.find('"""', ctx_start + 30)
        ctx = content[ctx_start:ctx_end]

        reminder_start = ctx.find("FINAL REMINDER")
        assert reminder_start != -1
        reminder_section = ctx[reminder_start:]

        assert "EMERGENCY" in reminder_section or "IMMEDIATELY" in reminder_section, (
            "FINAL REMINDER must escalate urgency for high iteration counts"
        )

    def test_iteration_limit_is_35_in_prompt(self):
        """The STRICT ITERATION LIMIT section must say 35, not 25."""
        content = self._read_swe_context()
        ctx_start = content.find('SOFTWARE_ENGINEER_CONTEXT = """')
        ctx_end = content.find('"""', ctx_start + 30)
        ctx = content[ctx_start:ctx_end]

        # Find the STRICT ITERATION LIMIT section
        limit_start = ctx.find("STRICT ITERATION LIMIT")
        assert limit_start != -1, "STRICT ITERATION LIMIT section not found"
        # Get the next ~200 chars
        limit_section = ctx[limit_start : limit_start + 200]

        assert "35" in limit_section, (
            f"STRICT ITERATION LIMIT must mention 35 max iterations. Found: {limit_section[:100]}"
        )

    def test_wrap_up_at_20_iterations(self):
        """The prompt must tell the agent to wrap up at ~20 iterations."""
        content = self._read_swe_context()
        ctx_start = content.find('SOFTWARE_ENGINEER_CONTEXT = """')
        ctx_end = content.find('"""', ctx_start + 30)
        ctx = content[ctx_start:ctx_end]

        limit_start = ctx.find("STRICT ITERATION LIMIT")
        assert limit_start != -1
        limit_section = ctx[limit_start : limit_start + 200]

        assert "20" in limit_section, (
            f"STRICT ITERATION LIMIT must tell agent to wrap up at ~20 calls. "
            f"Found: {limit_section[:100]}"
        )

    def test_max_iteration_per_run_is_35(self):
        """max_iteration_per_run must be set to 35 for SWE agent (not 25)."""
        content = self._read_swe_context()
        assert "max_iteration_per_run=35" in content, (
            "SWE agent must use max_iteration_per_run=35. "
            "Code search tasks are legitimately iteration-heavy and need more headroom."
        )

    def test_github_issue_workflow_has_iteration_check(self):
        """The GitHub Issue Investigation workflow must include an iteration check step."""
        content = self._read_swe_context()
        workflow_start = content.find("### For GitHub Issue Investigation")
        assert workflow_start != -1, "GitHub Issue Investigation workflow not found"
        next_section = content.find("###", workflow_start + 5)
        if next_section == -1:
            next_section = content.find("## ", workflow_start + 5)
        workflow = (
            content[workflow_start:next_section] if next_section != -1 else content[workflow_start:]
        )
        assert "ITERATION CHECK" in workflow or "iteration" in workflow.lower(), (
            "GitHub Issue workflow must include an iteration budget check step"
        )

    def test_other_agents_still_use_25_iterations(self):
        """SupportEngineer and ReleaseEngineer should still use max_iteration_per_run=25."""
        for agent_file in ["support_engineer.py", "release_engineer.py"]:
            filepath = os.path.join(
                os.path.dirname(__file__),
                os.pardir,
                "agents",
                "openhands",
                agent_file,
            )
            with open(filepath) as f:
                content = f.read()
            assert "max_iteration_per_run=25" in content, (
                f"{agent_file} should still use max_iteration_per_run=25. "
                f"Only SWE agent needs 35 iterations."
            )

    def test_has_forbidden_actions_section(self):
        """Prompt must have a FORBIDDEN ACTIONS section to prevent sequential file reading."""
        content = self._read_swe_context()
        ctx_start = content.find('SOFTWARE_ENGINEER_CONTEXT = """')
        ctx_end = content.find('"""', ctx_start + 30)
        ctx = content[ctx_start:ctx_end]

        assert "FORBIDDEN ACTIONS" in ctx, (
            "SOFTWARE_ENGINEER_CONTEXT must contain a FORBIDDEN ACTIONS section "
            "to prevent the agent from reading files section-by-section"
        )

    def test_forbidden_actions_mentions_sequential_reading(self):
        """FORBIDDEN ACTIONS must explicitly forbid sequential file reading."""
        content = self._read_swe_context()
        ctx_start = content.find('SOFTWARE_ENGINEER_CONTEXT = """')
        ctx_end = content.find('"""', ctx_start + 30)
        ctx = content[ctx_start:ctx_end]

        forbidden_start = ctx.find("FORBIDDEN ACTIONS")
        assert forbidden_start != -1
        forbidden_section = ctx[forbidden_start : forbidden_start + 800]

        assert (
            "section-by-section" in forbidden_section.lower()
            or "sequentially" in forbidden_section.lower()
        ), "FORBIDDEN ACTIONS must warn against reading files section-by-section"

    def test_forbidden_actions_limits_files_explored(self):
        """FORBIDDEN ACTIONS must limit the number of files the agent explores."""
        content = self._read_swe_context()
        ctx_start = content.find('SOFTWARE_ENGINEER_CONTEXT = """')
        ctx_end = content.find('"""', ctx_start + 30)
        ctx = content[ctx_start:ctx_end]

        forbidden_start = ctx.find("FORBIDDEN ACTIONS")
        assert forbidden_start != -1
        forbidden_section = ctx[forbidden_start : forbidden_start + 800]

        assert "3 files" in forbidden_section, (
            "FORBIDDEN ACTIONS must limit exploration to 3 files max"
        )

    def test_has_good_bad_investigation_examples(self):
        """Prompt must show concrete good vs bad investigation examples."""
        content = self._read_swe_context()
        ctx_start = content.find('SOFTWARE_ENGINEER_CONTEXT = """')
        ctx_end = content.find('"""', ctx_start + 30)
        ctx = content[ctx_start:ctx_end]

        assert "GOOD investigation" in ctx or "Good investigation" in ctx, (
            "Prompt must include a GOOD investigation example showing grep-first strategy"
        )
        assert "BAD investigation" in ctx or "Bad investigation" in ctx, (
            "Prompt must include a BAD investigation example showing what NOT to do"
        )


class TestAzureLLMConsolidation:
    """Verify all agents use AzureLLM from the shared module.

    Azure OpenAI doesn't support the Responses API. The base LLM class
    attempts to use it and gets 404 errors. All agents MUST use AzureLLM
    (which overrides uses_responses_api() to return False).

    Previously, AzureLLM was defined 3 times (SWE, support, release) and
    marketing_manager + product_manager used base LLM — a production bug.
    Now AzureLLM lives in agents/shared/llm.py and all agents import from there.
    """

    AGENTS_DIR = os.path.join(os.path.dirname(__file__), os.pardir, "agents", "openhands")

    ALL_AGENT_FILES = [
        "software_engineer.py",
        "support_engineer.py",
        "release_engineer.py",
        "marketing_manager.py",
        "product_manager.py",
    ]

    @staticmethod
    def _read_agent(filename: str) -> str:
        filepath = os.path.join(
            os.path.dirname(__file__),
            os.pardir,
            "agents",
            "openhands",
            filename,
        )
        with open(filepath) as f:
            return f.read()

    @staticmethod
    def _read_shared_llm() -> str:
        filepath = os.path.join(
            os.path.dirname(__file__),
            os.pardir,
            "agents",
            "shared",
            "llm.py",
        )
        with open(filepath) as f:
            return f.read()

    def test_shared_llm_module_exists(self):
        """agents/shared/llm.py must exist as the single source of truth."""
        filepath = os.path.join(os.path.dirname(__file__), os.pardir, "agents", "shared", "llm.py")
        assert os.path.exists(filepath), (
            "agents/shared/llm.py must exist. AzureLLM should be defined once, not per-agent."
        )

    def test_shared_llm_defines_azure_llm_class(self):
        """The shared module must define the AzureLLM class."""
        content = self._read_shared_llm()
        assert "class AzureLLM" in content

    def test_shared_llm_overrides_uses_responses_api(self):
        """AzureLLM must override uses_responses_api to return False."""
        content = self._read_shared_llm()
        assert "def uses_responses_api" in content
        assert "return False" in content

    @pytest.mark.parametrize("agent_file", ALL_AGENT_FILES)
    def test_agent_imports_from_shared_llm(self, agent_file: str):
        """Every agent must import AzureLLM from agents.shared.llm."""
        content = self._read_agent(agent_file)
        assert "from agents.shared.llm import" in content, (
            f"{agent_file} must import from agents.shared.llm, "
            f"not define its own AzureLLM or use base LLM"
        )
        assert "AzureLLM" in content.split("from agents.shared.llm import")[1].split("\n")[0], (
            f"{agent_file} must import AzureLLM from agents.shared.llm"
        )

    @pytest.mark.parametrize("agent_file", ALL_AGENT_FILES)
    def test_agent_does_not_define_own_azure_llm(self, agent_file: str):
        """No agent should define its own AzureLLM class — use the shared one."""
        content = self._read_agent(agent_file)
        assert "class AzureLLM" not in content, (
            f"{agent_file} defines its own AzureLLM class. "
            f"Remove it and import from agents.shared.llm instead."
        )

    @pytest.mark.parametrize("agent_file", ALL_AGENT_FILES)
    def test_agent_create_llm_returns_azure_llm(self, agent_file: str):
        """Every agent's _create_llm must return AzureLLM(), not LLM()."""
        content = self._read_agent(agent_file)
        # Find the _create_llm method body
        method_start = content.find("def _create_llm")
        assert method_start != -1, f"{agent_file} must have a _create_llm method"
        # Find the next method or class definition
        next_def = content.find("\n    def ", method_start + 10)
        method_body = content[method_start:next_def] if next_def != -1 else content[method_start:]

        assert "return AzureLLM(" in method_body, (
            f"{agent_file}._create_llm() must return AzureLLM(...), not LLM(...). "
            f"Azure OpenAI doesn't support the Responses API."
        )
        # Ensure it does NOT return plain LLM (but AzureLLM contains "LLM" so check carefully)
        # Remove all "AzureLLM" occurrences then check for standalone "return LLM("
        sanitized = method_body.replace("AzureLLM", "XXXX")
        assert "return LLM(" not in sanitized, (
            f"{agent_file}._create_llm() returns base LLM(). "
            f"Must use AzureLLM() for Azure OpenAI compatibility."
        )

    @pytest.mark.parametrize("agent_file", ALL_AGENT_FILES)
    def test_agent_does_not_import_llm_from_openhands_sdk(self, agent_file: str):
        """Agents must not import LLM from openhands.sdk directly (use shared module)."""
        content = self._read_agent(agent_file)
        import re

        sdk_imports = re.findall(r"from openhands\.sdk import (.+)", content)
        for import_line in sdk_imports:
            imported_names = [name.strip() for name in import_line.split(",")]
            assert "LLM" not in imported_names, (
                f"{agent_file} imports LLM from openhands.sdk. "
                f"Import from agents.shared.llm instead for Azure compatibility."
            )
