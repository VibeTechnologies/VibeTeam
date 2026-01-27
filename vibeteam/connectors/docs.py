"""
Docs Connector - Knowledge base connector for documentation files.

Provides access to markdown documentation files across multiple repositories.
Used by agents to retrieve context about infrastructure, services, and codebase.

Documentation repos should be cloned/pulled at container startup via the
`vibeteam docs sync` CLI command, not on every query.
"""

import fnmatch
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Default directory for cloned repos
DOCS_CACHE_DIR = os.environ.get("VIBETEAM_DOCS_CACHE", "/tmp/vibeteam-docs")


@dataclass
class DocsSource:
    """A documentation source configuration."""

    path: str  # Local path or git repo URL
    patterns: list[str] = field(default_factory=lambda: ["*.md"])
    name: str | None = None  # Optional name for this source
    branch: str = "master"  # Git branch (only used for git repos)
    subdirectory: str | None = None  # Subdirectory within repo to index

    def __post_init__(self):
        # Expand ~ and environment variables for local paths
        if not self.is_git_repo:
            self.path = os.path.expanduser(os.path.expandvars(self.path))
        if not self.name:
            if self.is_git_repo:
                # Extract repo name from URL
                self.name = self.path.rstrip("/").split("/")[-1].replace(".git", "")
            else:
                self.name = Path(self.path).name

    @property
    def is_git_repo(self) -> bool:
        """Check if this source is a git repository URL."""
        return self.path.startswith(("git@", "https://github.com", "git://"))

    def get_local_path(self) -> str:
        """Get the local path for this source (resolves git repos to cache dir)."""
        if self.is_git_repo:
            # name is always set in __post_init__ for git repos
            name = self.name or "unknown"
            base_path = Path(DOCS_CACHE_DIR) / name
            if self.subdirectory:
                return str(base_path / self.subdirectory)
            return str(base_path)
        return self.path


@dataclass
class DocFile:
    """A documentation file."""

    path: str
    name: str
    source: str
    relative_path: str
    size: int


@dataclass
class DocSearchResult:
    """A search result from documentation."""

    file: DocFile
    matches: list[str]  # Matching lines with context
    score: float  # Relevance score (higher = more relevant)


class DocsConnector:
    """
    Connector for accessing documentation files.

    Provides search and retrieval capabilities across multiple documentation
    sources (repositories, directories).

    Configuration via environment variable or constructor:
        VIBETEAM_DOCS_PATHS: Comma-separated list of paths
        Example: "/path/to/vibe/docs,/path/to/vibeteam/docs"
    """

    DEFAULT_SOURCES = [
        # Git repositories - will be cloned/pulled automatically
        DocsSource(
            path="https://github.com/VibeTechnologies/VibeWebAgent.git",
            patterns=["**/*.md"],
            name="vibe",
            subdirectory="docs",
        ),
        DocsSource(
            path="https://github.com/VibeTechnologies/VibeTeam.git",
            patterns=["**/*.md"],
            name="vibeteam",
        ),
    ]

    def __init__(self, sources: list[DocsSource] | None = None, auto_sync: bool = False):
        """
        Initialize the docs connector.

        Args:
            sources: List of DocsSource configurations. If None, uses
                     VIBETEAM_DOCS_REPOS env var or DEFAULT_SOURCES.
            auto_sync: If False (default), assumes repos are already cloned
                       via `vibeteam docs sync` at container startup.
                       If True, clone/pull git repos on init (slow).
        """
        if sources:
            self.sources = sources
        else:
            self.sources = self._load_sources_from_env()

        # Sync git repos if enabled
        if auto_sync:
            self._sync_repos()

        # Build index of available files
        self._file_index: list[DocFile] = []
        self._rebuild_index()

    def _load_sources_from_env(self) -> list[DocsSource]:
        """Load documentation sources from environment variable."""
        # Support both repo URLs and local paths
        repos_env = os.environ.get("VIBETEAM_DOCS_REPOS", "")
        paths_env = os.environ.get("VIBETEAM_DOCS_PATHS", "")

        sources = []

        # Git repos (comma-separated URLs)
        if repos_env:
            for repo in repos_env.split(","):
                repo = repo.strip()
                if repo:
                    sources.append(DocsSource(path=repo))

        # Local paths (comma-separated)
        if paths_env:
            for path in paths_env.split(","):
                path = path.strip()
                if path:
                    sources.append(DocsSource(path=path))

        if sources:
            return sources

        return self.DEFAULT_SOURCES

    def _sync_repos(self) -> None:
        """Clone or pull git repositories."""
        cache_dir = Path(DOCS_CACHE_DIR)
        cache_dir.mkdir(parents=True, exist_ok=True)

        for source in self.sources:
            if not source.is_git_repo:
                continue

            # name is always set in __post_init__ for git repos
            source_name = source.name or "unknown"
            repo_dir = cache_dir / source_name

            try:
                if repo_dir.exists():
                    # Pull latest changes
                    logger.info(f"Pulling {source.name}...")
                    result = subprocess.run(
                        ["git", "pull", "--ff-only"],
                        cwd=repo_dir,
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )
                    if result.returncode != 0:
                        logger.warning(f"Git pull failed for {source.name}: {result.stderr}")
                else:
                    # Clone repository
                    logger.info(f"Cloning {source.name} from {source.path}...")
                    result = subprocess.run(
                        [
                            "git",
                            "clone",
                            "--depth",
                            "1",
                            "--branch",
                            source.branch,
                            source.path,
                            str(repo_dir),
                        ],
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
                    if result.returncode != 0:
                        logger.error(f"Git clone failed for {source.name}: {result.stderr}")
                        continue

                # Update source path to local clone
                if source.subdirectory:
                    source.path = str(repo_dir / source.subdirectory)
                else:
                    source.path = str(repo_dir)

                logger.info(f"Synced {source.name} to {source.path}")

            except subprocess.TimeoutExpired:
                logger.error(f"Git operation timed out for {source.name}")
            except Exception as e:
                logger.error(f"Failed to sync {source.name}: {e}")

    def _rebuild_index(self) -> None:
        """Rebuild the file index from all sources."""
        self._file_index = []

        for source in self.sources:
            source_path = Path(source.path)
            if not source_path.exists():
                logger.warning(f"Docs source not found: {source.path}")
                continue

            for pattern in source.patterns:
                # Handle recursive patterns
                if "**" in pattern:
                    files = source_path.glob(pattern)
                else:
                    files = source_path.glob(f"**/{pattern}")

                for file_path in files:
                    if file_path.is_file():
                        try:
                            stat = file_path.stat()
                            self._file_index.append(
                                DocFile(
                                    path=str(file_path),
                                    name=file_path.name,
                                    source=source.name or source.path,
                                    relative_path=str(file_path.relative_to(source_path)),
                                    size=stat.st_size,
                                )
                            )
                        except OSError as e:
                            logger.warning(f"Could not index {file_path}: {e}")

        logger.info(f"Indexed {len(self._file_index)} documentation files")

    def list_files(self, pattern: str | None = None) -> list[DocFile]:
        """
        List available documentation files.

        Args:
            pattern: Optional glob pattern to filter files (e.g., "*deploy*")

        Returns:
            List of DocFile objects
        """
        if not pattern:
            return self._file_index

        return [
            f
            for f in self._file_index
            if fnmatch.fnmatch(f.name.lower(), pattern.lower())
            or fnmatch.fnmatch(f.relative_path.lower(), pattern.lower())
        ]

    def get_file(self, path: str, max_size: int = 100_000) -> str | None:
        """
        Get the contents of a documentation file.

        Args:
            path: Full path or relative path to the file
            max_size: Maximum file size to read (bytes)

        Returns:
            File contents as string, or None if not found
        """
        # Try exact path first
        target = Path(path)
        if target.exists() and target.is_file():
            return self._read_file(target, max_size)

        # Search in index
        for doc_file in self._file_index:
            if doc_file.path == path or doc_file.relative_path == path or doc_file.name == path:
                return self._read_file(Path(doc_file.path), max_size)

        return None

    def _read_file(self, path: Path, max_size: int) -> str | None:
        """Read a file with size limit."""
        try:
            stat = path.stat()
            if stat.st_size > max_size:
                logger.warning(f"File too large: {path} ({stat.st_size} bytes)")
                with open(path, encoding="utf-8") as f:
                    content = f.read(max_size)
                    return content + f"\n\n[... truncated at {max_size} bytes ...]"

            with open(path, encoding="utf-8") as f:
                return f.read()
        except OSError as e:
            logger.error(f"Could not read {path}: {e}")
            return None

    def search(
        self,
        query: str,
        limit: int = 10,
        context_lines: int = 2,
    ) -> list[DocSearchResult]:
        """
        Search documentation files for a query.

        Uses keyword matching with scoring based on:
        - Number of matches
        - Match location (title matches score higher)
        - Proximity of query terms

        Args:
            query: Search query (keywords or phrase)
            limit: Maximum number of results
            context_lines: Number of context lines around matches

        Returns:
            List of DocSearchResult objects, sorted by relevance
        """
        results: list[DocSearchResult] = []
        query_terms = query.lower().split()

        for doc_file in self._file_index:
            content = self.get_file(doc_file.path)
            if not content:
                continue

            matches, score = self._search_content(
                content, query_terms, context_lines, doc_file.name
            )

            if matches:
                results.append(
                    DocSearchResult(
                        file=doc_file,
                        matches=matches,
                        score=score,
                    )
                )

        # Sort by score descending
        results.sort(key=lambda r: r.score, reverse=True)

        return results[:limit]

    def _search_content(
        self,
        content: str,
        query_terms: list[str],
        context_lines: int,
        filename: str,
    ) -> tuple[list[str], float]:
        """
        Search content for query terms and calculate relevance score.

        Returns:
            Tuple of (matching lines with context, score)
        """
        lines = content.split("\n")
        matches: list[str] = []
        score = 0.0
        matched_line_indices: set[int] = set()

        # Check filename match (high score)
        filename_lower = filename.lower()
        for term in query_terms:
            if term in filename_lower:
                score += 10.0

        # Search content
        for i, line in enumerate(lines):
            line_lower = line.lower()
            term_matches = sum(1 for term in query_terms if term in line_lower)

            if term_matches > 0:
                # Calculate line score
                line_score = term_matches

                # Boost for header lines
                if line.startswith("#"):
                    line_score *= 3.0

                # Boost for lines with all query terms
                if term_matches == len(query_terms):
                    line_score *= 2.0

                score += line_score

                # Add context if not already included
                if i not in matched_line_indices:
                    start = max(0, i - context_lines)
                    end = min(len(lines), i + context_lines + 1)

                    context = lines[start:end]
                    match_text = "\n".join(context)
                    matches.append(match_text)

                    # Mark these lines as matched
                    for j in range(start, end):
                        matched_line_indices.add(j)

        return matches, score

    def search_by_topic(
        self,
        topic: str,
        limit: int = 5,
    ) -> list[DocSearchResult]:
        """
        Search for documentation by topic/category.

        Higher-level search that looks for relevant documentation
        based on topic keywords and file naming conventions.

        Args:
            topic: Topic to search for (e.g., "kubernetes", "deployment", "oauth")
            limit: Maximum number of results

        Returns:
            List of DocSearchResult objects
        """
        # Expand topic into related keywords
        topic_keywords = self._expand_topic(topic)

        # Search with expanded keywords
        return self.search(" ".join(topic_keywords), limit=limit)

    def _expand_topic(self, topic: str) -> list[str]:
        """Expand a topic into related keywords."""
        topic_lower = topic.lower()

        # Topic expansions
        expansions: dict[str, list[str]] = {
            "k8s": ["kubernetes", "k8s", "cluster", "pod", "deployment"],
            "kubernetes": ["kubernetes", "k8s", "cluster", "pod", "deployment"],
            "cluster": ["kubernetes", "k8s", "cluster", "node", "pod"],
            "deploy": ["deployment", "deploy", "release", "rollout"],
            "auth": ["authentication", "oauth", "login", "token", "credentials"],
            "oauth": ["oauth", "authentication", "google", "token"],
            "subscription": ["subscription", "tier", "billing", "stripe", "payment"],
            "error": ["error", "exception", "sentry", "debug", "troubleshoot"],
            "api": ["api", "endpoint", "rest", "http", "request"],
            "test": ["test", "testing", "ci", "qa", "automation"],
        }

        # Check if topic matches any expansion
        for key, words in expansions.items():
            if key in topic_lower:
                return words

        # Default: return topic as-is
        return [topic]

    def get_summary(self) -> dict:
        """
        Get a summary of available documentation.

        Returns:
            Dict with source counts and total files
        """
        source_counts: dict[str, int] = {}
        for doc_file in self._file_index:
            source_counts[doc_file.source] = source_counts.get(doc_file.source, 0) + 1

        return {
            "total_files": len(self._file_index),
            "sources": source_counts,
            "source_paths": [s.path for s in self.sources],
        }

    def health_check(self) -> bool:
        """Check if at least one documentation source is accessible."""
        for source in self.sources:
            if Path(source.path).exists():
                return True
        return False
