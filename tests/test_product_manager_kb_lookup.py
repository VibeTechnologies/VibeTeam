from __future__ import annotations

from pathlib import Path

from agent_service.openhands.product_manager import OpenHandsProductManager


def test_lookup_kb_fact_value_reads_markdown_file(tmp_path: Path) -> None:
    kb_root = tmp_path / "knowledgebase"
    target = kb_root / "inbox" / "fact.md"
    target.parent.mkdir(parents=True)
    target.write_text(
        "# Fact\nKB_EVAL_FACT_20260305: cobalt-lotus-914\n",
        encoding="utf-8",
    )

    value = OpenHandsProductManager._lookup_kb_fact_value("KB_EVAL_FACT_20260305", kb_root)
    assert value == "cobalt-lotus-914"


def test_extract_kb_fact_key() -> None:
    task = "Read shared knowledgebase and answer `KB_EVAL_FACT_20260305` value."
    assert OpenHandsProductManager._extract_kb_fact_key(task) == "KB_EVAL_FACT_20260305"
