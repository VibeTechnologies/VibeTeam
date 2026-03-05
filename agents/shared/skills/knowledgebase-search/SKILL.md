---
name: knowledgebase-search
description: Shared workflow for knowledgebase retrieval using docs_tools and injected OpenClaw context.
---

# Shared Knowledgebase Search Skill

## When To Use
- You are not fully certain and need internal facts before responding.
- The task references runbooks/policies/procedures that may exist in team docs.
- Files were recently added to `agents/shared/knowledgebase`.

## Required Retrieval Path (OpenHands / Terminal-capable agents)
1. Rebuild index after KB updates.
2. Search with `search_docs` (BM25 + fallback keyword scoring).
3. Read source file with `get_doc_content`.
4. Cite file path + evidence snippet in your response.

```bash
uv run python - <<'PY'
from agent_service.shared.docs_tools import rebuild_index, search_docs
print(rebuild_index())
print(search_docs("<query>", max_results=5))
PY
```

```bash
uv run python - <<'PY'
from agent_service.shared.docs_tools import get_doc_content
print(get_doc_content("agents/shared/knowledgebase/<domain>/<file>.md"))
PY
```

## OpenClaw Runtime Behavior
- OpenClaw agents do not call `docs_tools` directly as an MCP function.
- `openclaw-svc` injects this skill plus retrieved KB context into the task before execution.
- If injected KB context is missing or insufficient, explicitly state that and request a KB update instead of guessing.

## Guardrails
- Use indexed retrieval (`search_docs`) as the canonical knowledge lookup path.
- Do not answer from memory when a KB lookup can verify the claim.
