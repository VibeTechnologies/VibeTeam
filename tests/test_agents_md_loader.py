from __future__ import annotations

from pathlib import Path

from agent_service.shared import agents_md_loader


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_load_shared_skill_instructions_strips_front_matter(tmp_path: Path, monkeypatch) -> None:
    agents_root = tmp_path / "agents"
    _write(
        agents_root / "shared" / "skills" / "knowledgebase-search" / "SKILL.md",
        "---\nname: knowledgebase-search\n---\n\n# Body\nUse docs tools",
    )
    monkeypatch.setenv("AGENTS_DIR", str(agents_root))
    monkeypatch.delenv("AGENTS_CONFIG_PATH", raising=False)

    skill = agents_md_loader.load_shared_skill_instructions("knowledgebase-search")

    assert "name: knowledgebase-search" not in skill
    assert "# Body" in skill
    assert "Use docs tools" in skill


def test_load_knowledgebase_skill_instructions_combines_shared_and_role(
    tmp_path: Path, monkeypatch
) -> None:
    agents_root = tmp_path / "agents"
    _write(
        agents_root / "shared" / "skills" / "knowledgebase-search" / "SKILL.md",
        "# Shared KB\nshared instructions",
    )
    _write(
        agents_root / "SupportEngineer" / "skills" / "knowledgebase-search" / "SKILL.md",
        "# Role KB\nrole instructions",
    )
    monkeypatch.setenv("AGENTS_DIR", str(agents_root))
    monkeypatch.delenv("AGENTS_CONFIG_PATH", raising=False)

    skill = agents_md_loader.load_knowledgebase_skill_instructions("support_engineer")

    assert "## Shared Skill: knowledgebase-search" in skill
    assert "shared instructions" in skill
    assert "## Role Skill: support_engineer/knowledgebase-search" in skill
    assert "role instructions" in skill


def test_compose_agent_context_includes_required_knowledgebase_skill(
    tmp_path: Path, monkeypatch
) -> None:
    agents_root = tmp_path / "agents"
    _write(agents_root / "shared" / "AGENTS.md", "Shared agent instruction")
    _write(agents_root / "SupportEngineer" / "AGENTS.md", "Role instruction")
    _write(
        agents_root / "shared" / "skills" / "knowledgebase-search" / "SKILL.md",
        "# Shared KB\nuse search_docs",
    )

    monkeypatch.setenv("AGENTS_DIR", str(agents_root))
    monkeypatch.delenv("AGENTS_CONFIG_PATH", raising=False)

    context = agents_md_loader.compose_agent_context("support_engineer")

    assert "# SHARED AGENT INSTRUCTIONS" in context
    assert "# AGENT-SPECIFIC INSTRUCTIONS" in context
    assert "# REQUIRED SKILL: KNOWLEDGEBASE SEARCH" in context
    assert "use search_docs" in context
