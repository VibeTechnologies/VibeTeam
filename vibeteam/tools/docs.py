"""
Docs Tool - OpenHands tool wrapper for documentation knowledge base.

Provides agent-callable functions for searching and retrieving documentation.
"""

import json
from dataclasses import asdict
from typing import Any

from vibeteam.agents.base import BaseTool, ToolResult
from vibeteam.connectors.docs import DocsConnector, DocsSource


class DocsTool(BaseTool):
    """
    Tool for searching and retrieving documentation.

    Provides agents with access to a knowledge base of markdown documentation
    from configured repositories and directories. Git repos are automatically
    cloned/pulled.

    Actions:
        - search: Search documentation by keywords or phrase
        - get_file: Retrieve a specific documentation file
        - list_files: List available documentation files
        - get_summary: Get summary of available documentation sources
        - search_topic: Search by high-level topic with keyword expansion
        - sync: Refresh documentation by pulling latest from git repos
    """

    name = "docs"
    description = "Search and retrieve documentation from the knowledge base (auto-syncs git repos)"

    def __init__(self, sources: list[DocsSource] | None = None, auto_sync: bool = True):
        """
        Initialize the docs tool.

        Args:
            sources: Optional list of DocsSource configurations.
                     If None, uses VIBETEAM_DOCS_REPOS env var or defaults.
            auto_sync: If True, clone/pull git repos on initialization.
        """
        self.connector = DocsConnector(sources=sources, auto_sync=auto_sync)

    def get_schema(self) -> dict:
        """Return OpenAI function schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "search",
                                "get_file",
                                "list_files",
                                "get_summary",
                                "search_topic",
                                "sync",
                            ],
                            "description": "The documentation action to perform",
                        },
                        "query": {
                            "type": "string",
                            "description": "Search query (keywords or phrase)",
                        },
                        "topic": {
                            "type": "string",
                            "description": "Topic to search for (e.g., 'kubernetes', 'deployment', 'oauth')",
                        },
                        "path": {
                            "type": "string",
                            "description": "File path or name to retrieve",
                        },
                        "pattern": {
                            "type": "string",
                            "description": "Glob pattern to filter files (e.g., '*deploy*')",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of results to return",
                            "default": 10,
                        },
                    },
                    "required": ["action"],
                },
            },
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute a documentation action."""
        action = kwargs.get("action")

        try:
            if action == "search":
                query = kwargs.get("query")
                if not query:
                    return ToolResult(success=False, output="", error="query required")

                limit = kwargs.get("limit", 10)
                results = self.connector.search(query, limit=limit)

                if not results:
                    return ToolResult(
                        success=True,
                        output=f"No documentation found matching '{query}'",
                    )

                # Format results
                output_parts = []
                for result in results:
                    output_parts.append(
                        f"## {result.file.name} (source: {result.file.source})\n"
                        f"Path: {result.file.relative_path}\n"
                        f"Score: {result.score:.1f}\n\n"
                        + "\n---\n".join(result.matches[:3])  # Limit matches per file
                    )

                return ToolResult(success=True, output="\n\n".join(output_parts))

            elif action == "get_file":
                path = kwargs.get("path")
                if not path:
                    return ToolResult(success=False, output="", error="path required")

                content = self.connector.get_file(path)
                if content is None:
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"File not found: {path}",
                    )

                return ToolResult(success=True, output=content)

            elif action == "list_files":
                pattern = kwargs.get("pattern")
                files = self.connector.list_files(pattern=pattern)

                if not files:
                    msg = "No documentation files found"
                    if pattern:
                        msg += f" matching pattern '{pattern}'"
                    return ToolResult(success=True, output=msg)

                # Format as table
                output_lines = [
                    "| Source | File | Path |",
                    "|--------|------|------|",
                ]
                for f in files[:50]:  # Limit to 50 files
                    output_lines.append(f"| {f.source} | {f.name} | {f.relative_path} |")

                if len(files) > 50:
                    output_lines.append(f"\n... and {len(files) - 50} more files")

                return ToolResult(success=True, output="\n".join(output_lines))

            elif action == "get_summary":
                summary = self.connector.get_summary()
                output = (
                    f"**Documentation Knowledge Base Summary**\n\n"
                    f"Total files: {summary['total_files']}\n\n"
                    f"**Sources:**\n"
                )
                for source, count in summary["sources"].items():
                    output += f"- {source}: {count} files\n"

                output += f"\n**Configured paths:**\n"
                for path in summary["source_paths"]:
                    output += f"- {path}\n"

                return ToolResult(success=True, output=output)

            elif action == "search_topic":
                topic = kwargs.get("topic")
                if not topic:
                    return ToolResult(success=False, output="", error="topic required")

                limit = kwargs.get("limit", 5)
                results = self.connector.search_by_topic(topic, limit=limit)

                if not results:
                    return ToolResult(
                        success=True,
                        output=f"No documentation found for topic '{topic}'",
                    )

                # Format results
                output_parts = [f"**Documentation for topic: {topic}**\n"]
                for result in results:
                    output_parts.append(
                        f"### {result.file.name}\n"
                        f"Source: {result.file.source} | Score: {result.score:.1f}\n\n"
                        + "\n".join(result.matches[:2])  # Preview
                    )

                return ToolResult(success=True, output="\n\n".join(output_parts))

            elif action == "sync":
                # Re-sync git repos and rebuild index
                self.connector._sync_repos()
                self.connector._rebuild_index()
                summary = self.connector.get_summary()
                return ToolResult(
                    success=True,
                    output=f"Documentation synced. {summary['total_files']} files indexed from {len(summary['sources'])} sources.",
                )

            else:
                return ToolResult(success=False, output="", error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))
