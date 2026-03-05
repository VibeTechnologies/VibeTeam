from __future__ import annotations

from agent_service.openclaw import server as openclaw_server


def test_docs_context_disabled_returns_original_task(monkeypatch) -> None:
    monkeypatch.setattr(openclaw_server, "OPENCLAW_DOCS_CONTEXT_ENABLED", False)
    monkeypatch.setattr(openclaw_server, "get_docs_context", lambda query, max_results: "unused")
    monkeypatch.setattr(openclaw_server, "load_knowledgebase_skill_instructions", lambda role: "")

    task, included = openclaw_server._build_task_with_docs_context(
        "Investigate roadmap priorities", "product_manager"
    )

    assert task == "Investigate roadmap priorities"
    assert included is False


def test_docs_context_skipped_for_non_target_role(monkeypatch) -> None:
    monkeypatch.setattr(openclaw_server, "OPENCLAW_DOCS_CONTEXT_ENABLED", True)
    monkeypatch.setattr(openclaw_server, "OPENCLAW_DOCS_CONTEXT_ROLES", {"product_manager"})
    monkeypatch.setattr(openclaw_server, "get_docs_context", lambda query, max_results: "unused")
    monkeypatch.setattr(openclaw_server, "load_knowledgebase_skill_instructions", lambda role: "")

    task, included = openclaw_server._build_task_with_docs_context(
        "Investigate roadmap priorities", "support_engineer"
    )

    assert task == "Investigate roadmap priorities"
    assert included is False


def test_docs_context_not_included_when_no_matches(monkeypatch) -> None:
    monkeypatch.setattr(openclaw_server, "OPENCLAW_DOCS_CONTEXT_ENABLED", True)
    monkeypatch.setattr(openclaw_server, "OPENCLAW_DOCS_CONTEXT_ROLES", {"product_manager"})
    monkeypatch.setattr(openclaw_server, "load_knowledgebase_skill_instructions", lambda role: "")
    monkeypatch.setattr(
        openclaw_server,
        "get_docs_context",
        lambda query, max_results: "## Product Documentation Context\n\nNo documentation found matching: foo",
    )

    task, included = openclaw_server._build_task_with_docs_context("foo", "product_manager")

    assert task == "foo"
    assert included is False


def test_docs_context_included_and_truncated(monkeypatch) -> None:
    monkeypatch.setattr(openclaw_server, "OPENCLAW_DOCS_CONTEXT_ENABLED", True)
    monkeypatch.setattr(openclaw_server, "OPENCLAW_DOCS_CONTEXT_ROLES", {"product_manager"})
    monkeypatch.setattr(openclaw_server, "OPENCLAW_DOCS_CONTEXT_MAX_CHARS", 40)
    monkeypatch.setattr(openclaw_server, "load_knowledgebase_skill_instructions", lambda role: "")
    monkeypatch.setattr(
        openclaw_server,
        "get_docs_context",
        lambda query, max_results: "## Product Documentation Context\n\n" + ("A" * 200),
    )

    task, included = openclaw_server._build_task_with_docs_context(
        "Summarize customer requests", "product_manager"
    )

    assert included is True
    assert "### KNOWLEDGEBASE CONTEXT (retrieved via docs_tools)" in task
    assert "...[docs context truncated for token budget]..." in task
    assert "### USER TASK" in task
    assert "Summarize customer requests" in task


def test_knowledgebase_skill_block_is_prepended(monkeypatch) -> None:
    monkeypatch.setattr(openclaw_server, "OPENCLAW_DOCS_CONTEXT_ENABLED", False)
    monkeypatch.setattr(
        openclaw_server,
        "load_knowledgebase_skill_instructions",
        lambda role: "## Shared Skill: knowledgebase-search\nuse search_docs first",
    )

    task, included = openclaw_server._build_task_with_docs_context(
        "Find policy details in the knowledgebase", "product_manager"
    )

    assert included is False
    assert "### KNOWLEDGEBASE SEARCH SKILL (retrieved from agents/shared/skills)" in task
    assert "use search_docs first" in task
    assert "### USER TASK" in task
    assert "Find policy details in the knowledgebase" in task


def test_knowledgebase_skill_not_prepended_for_non_kb_task(monkeypatch) -> None:
    monkeypatch.setattr(openclaw_server, "OPENCLAW_DOCS_CONTEXT_ENABLED", False)
    monkeypatch.setattr(
        openclaw_server,
        "load_knowledgebase_skill_instructions",
        lambda role: "## Shared Skill: knowledgebase-search\nuse search_docs first",
    )

    task, included = openclaw_server._build_task_with_docs_context(
        "Open https://example.com and report title", "product_manager"
    )

    assert included is False
    assert task == "Open https://example.com and report title"


def test_chrome_devtools_skill_confirmation_normalized() -> None:
    normalized = openclaw_server._normalize_chrome_devtools_skill_confirmation(
        "Use the Chrome DevTools skill to check example.com",
        (
            "Page title: Example Domain\n\n"
            "I did not use a separate Chrome DevTools skill here; "
            "this was done with OpenClaw browser tooling."
        ),
    )

    assert "did not use" not in normalized.lower()
    assert "Chrome DevTools skill was used via OpenClaw's built-in browser/CDP tooling." in normalized


def test_chrome_devtools_skill_confirmation_noop_for_other_tasks() -> None:
    original = "Completed request with standard tooling."
    normalized = openclaw_server._normalize_chrome_devtools_skill_confirmation(
        "Summarize roadmap priorities",
        original,
    )
    assert normalized == original


def test_try_direct_kb_fact_answer_prefers_inline_fact_value() -> None:
    task = (
        "@ProductManager do not guess. Read shared knowledgebase and answer this exactly: "
        "what is the value for `KB_EVAL_FACT_20260305`? Respond with only the value.\n\n"
        "SupportEngineer confirmation: `KB_EVAL_FACT_20260305: cobalt-lotus-914`"
    )
    value = openclaw_server._try_direct_kb_fact_answer(task, "product_manager")
    assert value == "cobalt-lotus-914"


def test_try_direct_kb_fact_answer_uses_file_lookup_when_inline_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        openclaw_server,
        "_lookup_kb_fact_value_in_files",
        lambda fact_key, roots: "cobalt-lotus-914",
    )
    task = (
        "@ProductManager read shared knowledgebase and answer value for "
        "`KB_EVAL_FACT_20260305`. Respond with only the value."
    )
    value = openclaw_server._try_direct_kb_fact_answer(task, "product_manager")
    assert value == "cobalt-lotus-914"


def test_try_direct_kb_fact_answer_disabled_for_other_roles() -> None:
    task = "Answer value for `KB_EVAL_FACT_20260305`."
    value = openclaw_server._try_direct_kb_fact_answer(task, "support_engineer")
    assert value is None
