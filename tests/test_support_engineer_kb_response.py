from __future__ import annotations

from agent_service.openhands.support_engineer import (
    _compact_knowledgebase_ingestion_response,
    _is_knowledgebase_ingestion_task,
)


def test_identifies_knowledgebase_ingestion_task() -> None:
    task = (
        "@SupportEngineer add a new knowledgebase markdown file at "
        "`agents/shared/knowledgebase/inbox/kb_eval_123.md` with this exact line: "
        "`KB_EVAL_FACT_123: cobalt-lotus-914`. Then rebuild the docs index and confirm "
        "the file path and fact key in your response."
    )
    assert _is_knowledgebase_ingestion_task(task) is True


def test_compacts_knowledgebase_ingestion_response() -> None:
    task = (
        "@SupportEngineer add a new knowledgebase markdown file at "
        "`agents/shared/knowledgebase/inbox/kb_eval_123.md` with this exact line: "
        "`KB_EVAL_FACT_123: cobalt-lotus-914`. Then rebuild the docs index and confirm "
        "the file path and fact key in your response."
    )
    noisy = (
        "- Knowledgebase update done.\n"
        "- Sentry findings: none.\n"
        "- kubectl findings: unrelated details.\n"
    )
    compact = _compact_knowledgebase_ingestion_response(task, noisy)

    assert "Knowledgebase update complete:" in compact
    assert "`/app/agents/shared/knowledgebase/inbox/kb_eval_123.md`" in compact
    assert "`KB_EVAL_FACT_123: cobalt-lotus-914`" in compact
    assert "Sentry findings" not in compact
