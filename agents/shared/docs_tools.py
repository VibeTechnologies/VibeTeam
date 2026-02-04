from __future__ import annotations

"""
Shared Documentation Search tool functions for all agent frameworks.

This module provides product documentation search capabilities using a hybrid approach:
1. BM25 keyword search (via rank-bm25) - fast and effective for exact term matching
2. Fallback to glob + grep if rank-bm25 is not available
3. Optional semantic search upgrade path via sentence-transformers + FAISS

The tools search local markdown files in the repository and return relevant snippets
with context, enabling agents to answer questions about product documentation.

Usage:
    # AutoGen - use directly as FunctionTool
    from agents.shared.docs_tools import search_docs, get_docs_context

    # CrewAI - wrap in BaseTool
    from agents.shared.docs_tools import search_docs_sync
    class DocsSearchTool(BaseTool):
        def _run(self, query): return search_docs_sync(query)

    # OpenHands - use for context injection
    from agents.shared.docs_tools import get_docs_context
    context = get_docs_context("authentication setup")
"""

import os
import re
from dataclasses import dataclass
from glob import glob
from pathlib import Path
from typing import Any

# Check for rank-bm25 availability
try:
    from rank_bm25 import BM25Okapi

    BM25_AVAILABLE = True
except ImportError:
    BM25_AVAILABLE = False
    BM25Okapi = None


@dataclass
class DocSearchResult:
    """A single documentation search result."""

    filepath: str
    title: str
    snippet: str
    score: float
    line_number: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "filepath": self.filepath,
            "title": self.title,
            "snippet": self.snippet,
            "score": self.score,
            "line_number": self.line_number,
        }


# Default documentation directories to search
DEFAULT_DOCS_DIRS = [
    "docs",
    "readiness",
    ".",  # Root level (README.md, AGENTS.md)
]

# Files to exclude from search
EXCLUDED_PATTERNS = [
    "*/.venv/*",
    "*/.pytest_cache/*",
    "*/.git/*",
    "*/node_modules/*",
    "*/__pycache__/*",
]

# Stopwords for preprocessing
STOPWORDS = {
    "the",
    "is",
    "a",
    "an",
    "and",
    "or",
    "to",
    "of",
    "in",
    "for",
    "on",
    "with",
    "as",
    "by",
    "at",
    "from",
    "it",
    "this",
    "that",
    "be",
    "are",
    "was",
    "were",
    "been",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "could",
    "should",
    "may",
    "might",
    "can",
}


def _get_docs_root() -> str:
    """Get the root directory for documentation search."""
    # Try to find the project root
    current = Path(__file__).resolve()

    # Walk up to find the project root (contains .git or pyproject.toml)
    for parent in current.parents:
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return str(parent)

    # Fallback to current working directory
    return os.getcwd()


def _find_markdown_files(root_dir: str | None = None) -> list[str]:
    """Find all markdown files in the documentation directories."""
    if root_dir is None:
        root_dir = _get_docs_root()

    all_files = []

    for docs_dir in DEFAULT_DOCS_DIRS:
        search_path = os.path.join(root_dir, docs_dir)
        if os.path.isdir(search_path):
            # Search for .md files
            pattern = os.path.join(search_path, "**", "*.md")
            files = glob(pattern, recursive=True)

            # Filter out excluded patterns
            for f in files:
                excluded = False
                for exclude in EXCLUDED_PATTERNS:
                    if glob(exclude) and f in glob(exclude):
                        excluded = True
                        break
                    # Simple check for common exclusions
                    if any(ex.strip("*/") in f for ex in EXCLUDED_PATTERNS):
                        excluded = True
                        break

                if not excluded:
                    all_files.append(f)

    # Normalize paths and deduplicate
    normalized = [os.path.normpath(f) for f in all_files]
    return list(set(normalized))


def _preprocess_text(text: str) -> list[str]:
    """Preprocess text for BM25 indexing."""
    # Convert to lowercase
    text = text.lower()

    # Extract words
    tokens = re.findall(r"\w+", text)

    # Remove stopwords and short tokens
    tokens = [t for t in tokens if t not in STOPWORDS and len(t) > 2]

    return tokens


def _extract_title(content: str, filepath: str) -> str:
    """Extract title from markdown content or filename."""
    # Try to find first H1 header
    h1_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if h1_match:
        return h1_match.group(1).strip()

    # Fallback to filename
    return Path(filepath).stem.replace("-", " ").replace("_", " ").title()


def _extract_snippet(content: str, query: str, context_lines: int = 3) -> tuple[str, int]:
    """Extract a relevant snippet from the content around the query match."""
    lines = content.split("\n")
    query_lower = query.lower()
    query_tokens = set(_preprocess_text(query))

    best_line = 0
    best_score = 0

    # Find the line with the best match
    for i, line in enumerate(lines):
        line_lower = line.lower()

        # Exact phrase match is best
        if query_lower in line_lower:
            best_line = i
            best_score = 100
            break

        # Token overlap score
        line_tokens = set(_preprocess_text(line))
        overlap = len(query_tokens & line_tokens)
        if overlap > best_score:
            best_score = overlap
            best_line = i

    # Extract context around the best line
    start = max(0, best_line - context_lines)
    end = min(len(lines), best_line + context_lines + 1)
    snippet_lines = lines[start:end]

    # Clean up and join
    snippet = "\n".join(line for line in snippet_lines if line.strip())

    # Truncate if too long
    if len(snippet) > 500:
        snippet = snippet[:500] + "..."

    return snippet, best_line + 1


class DocsIndex:
    """BM25-based documentation index for fast search."""

    def __init__(self, root_dir: str | None = None):
        self.root_dir = root_dir or _get_docs_root()
        self.files: list[str] = []
        self.contents: list[str] = []
        self.titles: list[str] = []
        self.tokenized_docs: list[list[str]] = []
        self.bm25: BM25Okapi | None = None
        self._indexed = False

    def build_index(self) -> None:
        """Build the BM25 index from markdown files."""
        self.files = _find_markdown_files(self.root_dir)
        self.contents = []
        self.titles = []
        self.tokenized_docs = []

        for filepath in self.files:
            try:
                with open(filepath, encoding="utf-8") as f:
                    content = f.read()

                self.contents.append(content)
                self.titles.append(_extract_title(content, filepath))
                self.tokenized_docs.append(_preprocess_text(content))

            except Exception as e:
                print(f"Warning: Could not read {filepath}: {e}")
                continue

        if BM25_AVAILABLE and self.tokenized_docs:
            self.bm25 = BM25Okapi(self.tokenized_docs)

        self._indexed = True

    def search(self, query: str, max_results: int = 5) -> list[DocSearchResult]:
        """Search the documentation index."""
        if not self._indexed:
            self.build_index()

        if not self.files:
            return []

        results = []
        query_tokens = _preprocess_text(query)

        if BM25_AVAILABLE and self.bm25 is not None:
            # Use BM25 scoring
            scores = self.bm25.get_scores(query_tokens)

            # Get top results
            scored_indices = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[
                :max_results
            ]

            for idx, score in scored_indices:
                if score > 0:  # Only include if there's some relevance
                    snippet, line_num = _extract_snippet(self.contents[idx], query)
                    results.append(
                        DocSearchResult(
                            filepath=self.files[idx],
                            title=self.titles[idx],
                            snippet=snippet,
                            score=float(score),
                            line_number=line_num,
                        )
                    )
        else:
            # Fallback to simple keyword search
            results = self._simple_search(query, max_results)

        return results

    def _simple_search(self, query: str, max_results: int = 5) -> list[DocSearchResult]:
        """Simple keyword-based search fallback."""
        results = []
        query_lower = query.lower()
        query_tokens = set(_preprocess_text(query))

        for filepath, content, title in zip(self.files, self.contents, self.titles, strict=False):
            content_lower = content.lower()

            # Calculate simple score
            score = 0.0

            # Exact phrase match
            if query_lower in content_lower:
                score += 10.0

            # Token overlap
            content_tokens = set(_preprocess_text(content))
            overlap = len(query_tokens & content_tokens)
            score += overlap

            if score > 0:
                snippet, line_num = _extract_snippet(content, query)
                results.append(
                    DocSearchResult(
                        filepath=filepath,
                        title=title,
                        snippet=snippet,
                        score=score,
                        line_number=line_num,
                    )
                )

        # Sort by score and limit
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:max_results]


# Global index instance (lazy initialization)
_docs_index: DocsIndex | None = None


def _get_index() -> DocsIndex:
    """Get or create the global docs index."""
    global _docs_index
    if _docs_index is None:
        _docs_index = DocsIndex()
    return _docs_index


def search_docs(query: str, max_results: int = 5) -> str:
    """Search product documentation for relevant information.

    Args:
        query: The search query (e.g., "authentication setup", "API configuration")
        max_results: Maximum number of results to return (default: 5)

    Returns:
        Formatted search results with titles, snippets, and file paths
    """
    index = _get_index()
    results = index.search(query, max_results)

    if not results:
        return f"No documentation found matching: {query}"

    output = f"=== Documentation Search: {query} ===\n\n"
    output += f"Found {len(results)} relevant documents:\n\n"

    for i, result in enumerate(results, 1):
        # Make filepath relative for readability
        rel_path = result.filepath
        try:
            rel_path = os.path.relpath(result.filepath, _get_docs_root())
        except ValueError:
            pass

        output += f"**{i}. {result.title}**\n"
        output += f"   File: {rel_path} (line {result.line_number})\n"
        output += f"   Score: {result.score:.2f}\n"
        output += "   ---\n"
        # Indent snippet
        indented_snippet = "\n".join(f"   {line}" for line in result.snippet.split("\n"))
        output += f"{indented_snippet}\n\n"

    return output


def search_docs_sync(query: str, max_results: int = 5) -> str:
    """Synchronous version of search_docs (same implementation)."""
    return search_docs(query, max_results)


def list_docs() -> str:
    """List all available documentation files.

    Returns:
        Formatted list of documentation files with titles
    """
    index = _get_index()
    if not index._indexed:
        index.build_index()

    if not index.files:
        return "No documentation files found."

    output = "=== Available Documentation ===\n\n"

    for filepath, title in zip(index.files, index.titles, strict=False):
        rel_path = filepath
        try:
            rel_path = os.path.relpath(filepath, _get_docs_root())
        except ValueError:
            pass

        output += f"- **{title}**: {rel_path}\n"

    return output


def get_doc_content(filepath: str) -> str:
    """Get the full content of a documentation file.

    Args:
        filepath: Path to the documentation file (relative or absolute)

    Returns:
        Full content of the file or error message
    """
    root = _get_docs_root()

    # Try as relative path first
    full_path = os.path.join(root, filepath)
    if not os.path.exists(full_path):
        # Try as absolute
        full_path = filepath

    if not os.path.exists(full_path):
        return f"Documentation file not found: {filepath}"

    try:
        with open(full_path, encoding="utf-8") as f:
            content = f.read()

        title = _extract_title(content, full_path)
        return f"=== {title} ===\n\n{content}"

    except Exception as e:
        return f"Error reading {filepath}: {e}"


def get_docs_context(query: str, max_results: int = 3) -> str:
    """Get documentation context for injection into agent prompts.

    This is designed for OpenHands-style context injection, providing
    relevant documentation snippets based on the query.

    Args:
        query: The query to find relevant documentation for
        max_results: Maximum number of documents to include

    Returns:
        Formatted context string for agent prompts
    """
    results = search_docs(query, max_results)

    return f"## Product Documentation Context\n\n{results}"


def rebuild_index() -> str:
    """Rebuild the documentation index.

    Useful after documentation files have been modified.

    Returns:
        Status message with index statistics
    """
    global _docs_index
    _docs_index = DocsIndex()
    _docs_index.build_index()

    return (
        f"Documentation index rebuilt. "
        f"Indexed {len(_docs_index.files)} files. "
        f"BM25 available: {BM25_AVAILABLE}"
    )


# =====================
# Infrastructure Docs (from vibe repo)
# =====================

# Path to infrastructure docs (generated from vibe repo)
INFRA_DOCS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "docs",
    "infra-llms.txt",
)


def search_infra_docs(query: str, max_results: int = 5) -> str:
    """Search infrastructure documentation for k8s, deployment, and service information.

    This searches the aggregated infrastructure docs from the vibe repository,
    which includes:
    - Kubernetes (k3s) cluster documentation
    - Deployment and release processes
    - Service configurations (LiteLLM, Stripe, Langfuse)
    - Azure infrastructure (Terraform, VMs, Key Vault)
    - Monitoring and alerting setup

    Args:
        query: The search query (e.g., "k3s cluster", "deployment process", "litellm config")
        max_results: Maximum number of sections to return (default: 5)

    Returns:
        Formatted search results with relevant infrastructure documentation
    """
    if not os.path.exists(INFRA_DOCS_PATH):
        return (
            f"Infrastructure docs not found at {INFRA_DOCS_PATH}. "
            "Run `python scripts/build_infra_docs.py` to generate them."
        )

    try:
        with open(INFRA_DOCS_PATH, encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return f"Error reading infrastructure docs: {e}"

    # Split into sections (delimited by ## headers)
    sections = re.split(r"(?=^## )", content, flags=re.MULTILINE)

    # Search for matching sections
    query_lower = query.lower()
    query_tokens = set(_preprocess_text(query))

    scored_sections = []
    for section in sections:
        if not section.strip():
            continue

        section_lower = section.lower()
        score = 0.0

        # Exact phrase match
        if query_lower in section_lower:
            score += 10.0

        # Token overlap
        section_tokens = set(_preprocess_text(section[:2000]))  # First 2000 chars
        overlap = len(query_tokens & section_tokens)
        score += overlap * 2.0

        # Boost for keyword matches in header
        header_match = re.match(r"^## (.+)\n", section)
        if header_match:
            header = header_match.group(1).lower()
            if query_lower in header:
                score += 5.0
            header_tokens = set(_preprocess_text(header))
            score += len(query_tokens & header_tokens) * 3.0

        if score > 0:
            scored_sections.append((score, section))

    # Sort by score and take top results
    scored_sections.sort(key=lambda x: x[0], reverse=True)
    top_sections = scored_sections[:max_results]

    if not top_sections:
        return f"No infrastructure documentation found matching: {query}"

    # Format output
    output = f"=== Infrastructure Documentation: {query} ===\n\n"
    output += f"Found {len(top_sections)} relevant sections:\n\n"

    for i, (score, section) in enumerate(top_sections, 1):
        # Extract header
        header_match = re.match(r"^## (.+)\n", section)
        title = header_match.group(1) if header_match else "Untitled"

        # Truncate long sections
        if len(section) > 1500:
            section = section[:1400] + "\n\n[...truncated...]\n"

        output += f"**{i}. {title}** (score: {score:.1f})\n"
        output += "-" * 40 + "\n"
        output += section.strip() + "\n\n"

    return output


def search_infra_docs_sync(query: str, max_results: int = 5) -> str:
    """Synchronous version of search_infra_docs (same implementation)."""
    return search_infra_docs(query, max_results)


def get_infra_context(query: str, max_results: int = 3) -> str:
    """Get infrastructure context for injection into agent prompts.

    This is designed for ReleaseEngineer and other ops-focused agents
    to get relevant infrastructure documentation as context.

    Args:
        query: The query to find relevant documentation for
        max_results: Maximum number of sections to include

    Returns:
        Formatted context string for agent prompts
    """
    results = search_infra_docs(query, max_results)

    return f"## Infrastructure Documentation Context\n\n{results}"
