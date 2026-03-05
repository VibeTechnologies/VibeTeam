---
name: knowledgebase-search
description: Search shared knowledgebase content using docs_tools (BM25 + fallback keyword scoring) before answering from memory.
---

# Knowledgebase Search

## When To Use
- You are unsure about an internal procedure, policy, runbook, or prior implementation detail.
- A user asks for facts that should come from team documentation.
- A recent task uploaded/edited files under `agents/shared/knowledgebase`.

## Required Toolchain
- Primary retrieval: `agent_service.shared.docs_tools.search_docs()`
- Full-file read: `agent_service.shared.docs_tools.get_doc_content()`
- Re-index after KB writes: `agent_service.shared.docs_tools.rebuild_index()`
- Use indexed retrieval via `search_docs` (BM25 + built-in keyword fallback) for all knowledgebase lookups.

## Workflow
1. **Rebuild index if KB changed recently**
```bash
uv run python - <<'PY'
from agent_service.shared.docs_tools import rebuild_index
print(rebuild_index())
PY
```

2. **Search the KB/docs index**
```bash
uv run python - <<'PY'
from agent_service.shared.docs_tools import search_docs
print(search_docs("<question or keywords>", max_results=5))
PY
```

3. **Open the most relevant file(s)**
```bash
uv run python - <<'PY'
from agent_service.shared.docs_tools import get_doc_content
print(get_doc_content("agents/shared/knowledgebase/<domain>/<file>.md"))
PY
```

4. **Answer with evidence**
- Include file path and the specific snippet/line context from search output.
- If nothing relevant is found, state that clearly and request/perform KB ingestion rather than guessing.

