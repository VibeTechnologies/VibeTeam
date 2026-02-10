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
