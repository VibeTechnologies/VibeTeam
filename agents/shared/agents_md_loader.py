"""Load and compose AGENTS.md instructions for agents.

Implements hierarchical loading:
1. Load agents/shared/AGENTS.md (shared instructions for all agents)
2. Load agents/<agent_name>/AGENTS.md (agent-specific instructions)
3. Combine shared + specific instructions
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


def get_agents_root() -> Path:
    """Get the root agents directory.

    Handles both local dev and K8s deployment with git-sync.
    In K8s with git-sync, code lives under /code/current (a symlink).
    """
    code_current = Path("/code/current")
    if code_current.exists():
        return code_current / "agents"

    # Local dev fallback: find agents directory relative to this file
    current_file = Path(__file__).resolve()
    return current_file.parent.parent


def load_shared_instructions() -> str:
    """Load shared instructions from agents/shared/AGENTS.md.

    Returns:
        Shared instructions markdown content, or empty string if not found.
    """
    agents_root = get_agents_root()
    shared_path = agents_root / "shared" / "AGENTS.md"

    if not shared_path.exists():
        logger.warning(f"Shared AGENTS.md not found at {shared_path}")
        return ""

    try:
        content = shared_path.read_text(encoding="utf-8")
        return content
    except Exception as e:
        logger.error(f"Error reading {shared_path}: {e}")
        return ""


def load_agent_instructions(agent_name: str) -> str:
    """Load agent-specific instructions from agents/<agent_name>/AGENTS.md.

    Args:
        agent_name: The agent name (e.g., 'support_engineer', 'release_engineer')

    Returns:
        Agent-specific instructions markdown content, or empty string if not found.
    """
    agents_root = get_agents_root()

    agent_path = _resolve_prompt_path(agent_name, agents_root)

    if not agent_path.exists():
        logger.warning(f"Agent AGENTS.md not found at {agent_path}")
        return ""

    try:
        content = agent_path.read_text(encoding="utf-8")
        return content
    except Exception as e:
        logger.error(f"Error reading {agent_path}: {e}")
        return ""


def _resolve_prompt_path(agent_name: str, agents_root: Path) -> Path:
    """Resolve AGENTS.md path using agents.yaml when available."""
    config_path = Path(os.environ.get("AGENTS_CONFIG_PATH", "agents.yaml"))
    if not config_path.is_absolute():
        config_path = agents_root.parent / config_path

    if config_path.exists():
        try:
            data = yaml.safe_load(config_path.read_text()) or {}
            agents = data.get("agents", {}) if isinstance(data, dict) else {}
            if isinstance(agents, dict):
                cfg = agents.get(agent_name, {})
                if isinstance(cfg, dict):
                    agent_dir = cfg.get("agent_dir")
                    if agent_dir:
                        agent_root = Path(str(agent_dir))
                        if not agent_root.is_absolute():
                            agent_root = agents_root.parent / agent_root
                        return agent_root / "AGENTS.md"
                    prompt_path = cfg.get("prompt_path")
                    if prompt_path:
                        prompt = Path(str(prompt_path))
                        if not prompt.is_absolute():
                            prompt = agents_root.parent / prompt
                        return prompt
        except Exception as e:
            logger.warning("Failed to load agents.yaml from %s: %s", config_path, e)

    # Convert snake_case to PascalCase
    # e.g., 'support_engineer' -> 'SupportEngineer'
    agent_dir = "".join(word.capitalize() for word in agent_name.split("_"))
    return agents_root / agent_dir / "AGENTS.md"


def compose_agent_context(agent_name: str, fallback_context: str | None = None) -> str:
    """Load and compose hierarchical instructions for an agent.

    1. Loads shared instructions (agents/shared/AGENTS.md)
    2. Loads agent-specific instructions (agents/<agent_name>/AGENTS.md)
    3. Combines them with the agent-specific instructions taking precedence
    4. Falls back to hardcoded context if AGENTS.md files don't exist

    Args:
        agent_name: The agent name (e.g., 'support_engineer')
        fallback_context: Optional fallback context string if files not found

    Returns:
        Complete agent context/instructions
    """
    shared = load_shared_instructions()
    specific = load_agent_instructions(agent_name)

    if shared or specific:
        # Compose: shared + specific
        # Both are markdown, so concat with clear separation
        parts = []

        if shared:
            parts.append("# SHARED AGENT INSTRUCTIONS\n")
            parts.append(shared)

        if specific:
            parts.append("\n\n# AGENT-SPECIFIC INSTRUCTIONS\n")
            parts.append(specific)

        context = "\n".join(parts)
        logger.info(f"Loaded context for {agent_name} from AGENTS.md files ({len(context)} chars)")
        return context

    if fallback_context:
        logger.info(f"Using fallback hardcoded context for {agent_name}")
        return fallback_context

    logger.warning(f"No context found for {agent_name}")
    return ""
