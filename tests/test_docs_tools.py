from __future__ import annotations

from pathlib import Path

from agent_service.shared.docs_tools import DocsIndex, _find_markdown_files


def test_find_markdown_files_includes_shared_knowledgebase(tmp_path: Path) -> None:
    # Included scopes
    (tmp_path / "README.md").write_text("# Root README\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (tmp_path / "readiness").mkdir()
    (tmp_path / "readiness" / "checklist.md").write_text("# Checklist\n", encoding="utf-8")
    kb_file = tmp_path / "agents" / "shared" / "knowledgebase" / "runbooks" / "incident.md"
    kb_file.parent.mkdir(parents=True)
    kb_file.write_text("# Incident\nHow to rotate kubeconfig\n", encoding="utf-8")

    # Excluded scope
    ignored_file = tmp_path / ".venv" / "notes.md"
    ignored_file.parent.mkdir()
    ignored_file.write_text("# Ignore me\n", encoding="utf-8")

    found = set(_find_markdown_files(str(tmp_path)))

    assert str((tmp_path / "README.md").resolve()) in found
    assert str((tmp_path / "docs" / "guide.md").resolve()) in found
    assert str((tmp_path / "readiness" / "checklist.md").resolve()) in found
    assert str(kb_file.resolve()) in found
    assert str(ignored_file.resolve()) not in found


def test_docs_index_searches_knowledgebase_content(tmp_path: Path) -> None:
    kb_file = tmp_path / "agents" / "shared" / "knowledgebase" / "ops" / "billing.md"
    kb_file.parent.mkdir(parents=True)
    unique_text = "Moonshot billing remediation runbook"
    kb_file.write_text(
        f"# Billing Recovery\n\nUse this procedure for {unique_text}.\n",
        encoding="utf-8",
    )

    index = DocsIndex(root_dir=str(tmp_path))
    index.build_index()
    results = index.search("moonshot billing remediation", max_results=5)

    assert results
    assert any(result.filepath.endswith("billing.md") for result in results)
    assert any("Moonshot billing remediation runbook" in result.snippet for result in results)
