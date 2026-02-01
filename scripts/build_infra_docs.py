#!/usr/bin/env python3
"""
Build Infrastructure Documentation Index for Agent Knowledge Base.

This script aggregates markdown documentation from the vibe repository
and generates an llms.txt file that agents can use as context for
infrastructure-related tasks.

Features:
- Scans specified directories for .md files
- Filters by relevance (infra, release, deployment, k8s, etc.)
- Generates concatenated llms.txt for LLM context
- Optionally updates the BM25 search index

Usage:
    # Build llms.txt from vibe repo docs
    python scripts/build_infra_docs.py

    # Specify custom source and output
    python scripts/build_infra_docs.py --source ~/workspace/vibebrowser/vibe --output docs/infra-llms.txt

    # Only generate index metadata (no llms.txt)
    python scripts/build_infra_docs.py --index-only

CI/CD:
    Add to GitHub Actions workflow to auto-rebuild on push to master.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class DocSection:
    """A documentation section."""

    filepath: str
    title: str
    content: str
    category: str
    relevance_score: float


# Categories and their keyword patterns for filtering
INFRA_CATEGORIES = {
    "kubernetes": [
        r"k3s",
        r"k8s",
        r"kubernetes",
        r"kubectl",
        r"pod",
        r"deployment",
        r"namespace",
        r"ingress",
        r"traefik",
        r"helm",
    ],
    "deployment": [
        r"deploy",
        r"release",
        r"rollout",
        r"ci.?cd",
        r"workflow",
        r"github.?action",
        r"terraform",
        r"azure",
    ],
    "infrastructure": [
        r"infra",
        r"vm",
        r"vmss",
        r"azure",
        r"cloud",
        r"network",
        r"dns",
        r"ssl",
        r"tls",
        r"cert",
        r"load.?balancer",
    ],
    "services": [
        r"litellm",
        r"stripe",
        r"langfuse",
        r"sentry",
        r"supabase",
        r"openai",
        r"api.?gateway",
        r"webhook",
    ],
    "monitoring": [
        r"monitor",
        r"observ",
        r"log",
        r"metric",
        r"alert",
        r"health.?check",
        r"sentry",
        r"langfuse",
    ],
    "security": [
        r"secret",
        r"auth",
        r"rbac",
        r"key.?vault",
        r"credential",
        r"tee",
        r"confidential",
        r"attestation",
    ],
}

# Directories to scan (relative to source root)
DOCS_DIRECTORIES = [
    "docs",
    "services",
    ".opencode/skills",
    "tests",  # for test documentation
]

# Files to always include regardless of content
ALWAYS_INCLUDE = [
    "README.md",
    "AGENTS.md",
    "docs/release.md",
    "docs/productionServices.md",
    "docs/quality.md",
    "docs/testing.md",
    "docs/CI.md",
    "services/k3s/README.md",
    "services/subscription/README.md",
    "services/subscription/docs/deployment.md",
    "services/subscription/docs/systemDesign.md",
]

# Files/patterns to exclude
EXCLUDE_PATTERNS = [
    r"node_modules",
    r"\.git",
    r"langgraphjs",  # External lib docs, not our infra
    r"terraform/\.terraform",
    r"\.blogposts",  # Blog posts, not operational docs
    r"research/",  # Research notes, not production docs
]


def extract_title(content: str, filepath: str) -> str:
    """Extract title from markdown content or filename."""
    # Try H1 header
    match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if match:
        return match.group(1).strip()

    # Fallback to filename
    return Path(filepath).stem.replace("-", " ").replace("_", " ").title()


def calculate_relevance(content: str, filepath: str) -> tuple[float, str]:
    """
    Calculate relevance score and category for infrastructure docs.

    Returns (score, category) tuple.
    """
    content_lower = content.lower()
    filepath_lower = filepath.lower()

    best_score = 0.0
    best_category = "general"

    for category, patterns in INFRA_CATEGORIES.items():
        score = 0.0
        for pattern in patterns:
            # Check filepath
            if re.search(pattern, filepath_lower):
                score += 2.0

            # Check content (count occurrences, max 10)
            matches = len(re.findall(pattern, content_lower))
            score += min(matches * 0.5, 5.0)

        if score > best_score:
            best_score = score
            best_category = category

    return best_score, best_category


def should_exclude(filepath: str) -> bool:
    """Check if file should be excluded."""
    for pattern in EXCLUDE_PATTERNS:
        if re.search(pattern, filepath):
            return True
    return False


def find_markdown_files(source_dir: str) -> list[str]:
    """Find all relevant markdown files."""
    source_path = Path(source_dir)
    files = []

    # Always include specific files
    for rel_path in ALWAYS_INCLUDE:
        full_path = source_path / rel_path
        if full_path.exists():
            files.append(str(full_path))

    # Scan directories
    for docs_dir in DOCS_DIRECTORIES:
        dir_path = source_path / docs_dir
        if dir_path.exists():
            for md_file in dir_path.rglob("*.md"):
                filepath = str(md_file)
                if not should_exclude(filepath) and filepath not in files:
                    files.append(filepath)

    return files


def build_doc_sections(
    files: list[str], source_dir: str, min_relevance: float = 0.0
) -> list[DocSection]:
    """Build documentation sections from files."""
    sections = []

    for filepath in files:
        try:
            with open(filepath, encoding="utf-8") as f:
                content = f.read()

            if not content.strip():
                continue

            # Get relative path for display
            rel_path = os.path.relpath(filepath, source_dir)

            title = extract_title(content, filepath)
            score, category = calculate_relevance(content, filepath)

            # Apply minimum relevance filter
            if score >= min_relevance:
                sections.append(
                    DocSection(
                        filepath=rel_path,
                        title=title,
                        content=content,
                        category=category,
                        relevance_score=score,
                    )
                )

        except Exception as e:
            print(f"Warning: Could not read {filepath}: {e}", file=sys.stderr)

    # Sort by relevance (highest first)
    sections.sort(key=lambda x: x.relevance_score, reverse=True)

    return sections


def generate_llms_txt(sections: list[DocSection], max_tokens: int = 100000) -> str:
    """
    Generate llms.txt content from documentation sections.

    The format follows the llms.txt spec:
    - Clear section headers with file paths
    - Markdown content preserved
    - Truncated to max token estimate
    """
    output_parts = []
    estimated_tokens = 0
    chars_per_token = 4  # Conservative estimate

    # Header
    header = f"""# VibeBrowser Infrastructure Documentation
# Generated: {datetime.now().isoformat()}
# Source: https://github.com/VibeTechnologies/VibeWebAgent
# 
# This file contains infrastructure and deployment documentation for agents.
# Use this context to understand k3s cluster, services, deployment processes.

"""
    output_parts.append(header)
    estimated_tokens += len(header) // chars_per_token

    # Table of contents
    toc = "## Table of Contents\n\n"
    for i, section in enumerate(sections, 1):
        toc += f"{i}. [{section.title}](#{section.filepath}) ({section.category})\n"
    toc += "\n---\n\n"
    output_parts.append(toc)
    estimated_tokens += len(toc) // chars_per_token

    # Add sections
    for section in sections:
        section_header = f"## {section.title}\n**File:** `{section.filepath}`\n**Category:** {section.category}\n\n"
        section_content = section.content + "\n\n---\n\n"

        section_tokens = (len(section_header) + len(section_content)) // chars_per_token

        if estimated_tokens + section_tokens > max_tokens:
            # Truncate section if needed
            remaining_chars = (max_tokens - estimated_tokens) * chars_per_token
            if remaining_chars > 500:
                truncated = (
                    section_content[: remaining_chars - 100] + "\n\n[...truncated...]\n\n---\n\n"
                )
                output_parts.append(section_header + truncated)
            break

        output_parts.append(section_header + section_content)
        estimated_tokens += section_tokens

    return "".join(output_parts)


def generate_index_metadata(sections: list[DocSection]) -> dict:
    """Generate index metadata for documentation search."""
    return {
        "version": "1.0",
        "generated": datetime.now().isoformat(),
        "total_files": len(sections),
        "categories": list(set(s.category for s in sections)),
        "files": [
            {
                "path": s.filepath,
                "title": s.title,
                "category": s.category,
                "relevance": s.relevance_score,
            }
            for s in sections
        ],
        "content_hash": hashlib.sha256("".join(s.content for s in sections).encode()).hexdigest()[
            :16
        ],
    }


def main():
    parser = argparse.ArgumentParser(
        description="Build infrastructure documentation index for agents"
    )
    parser.add_argument(
        "--source",
        default=os.path.expanduser("~/workspace/vibebrowser/vibe"),
        help="Source repository root (default: ~/workspace/vibebrowser/vibe)",
    )
    parser.add_argument(
        "--output",
        default="docs/infra-llms.txt",
        help="Output llms.txt file path (default: docs/infra-llms.txt)",
    )
    parser.add_argument(
        "--index-output",
        default="docs/infra-index.json",
        help="Output index metadata JSON (default: docs/infra-index.json)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=100000,
        help="Maximum estimated tokens for llms.txt (default: 100000)",
    )
    parser.add_argument(
        "--min-relevance",
        type=float,
        default=0.0,
        help="Minimum relevance score to include (default: 0.0)",
    )
    parser.add_argument(
        "--index-only",
        action="store_true",
        help="Only generate index metadata, skip llms.txt",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be generated without writing files",
    )

    args = parser.parse_args()

    # Validate source directory
    if not os.path.isdir(args.source):
        print(f"Error: Source directory not found: {args.source}", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning {args.source} for infrastructure documentation...")

    # Find and process files
    files = find_markdown_files(args.source)
    print(f"Found {len(files)} markdown files")

    sections = build_doc_sections(files, args.source, args.min_relevance)
    print(f"Built {len(sections)} documentation sections")

    # Print category breakdown
    categories = {}
    for s in sections:
        categories[s.category] = categories.get(s.category, 0) + 1
    print("\nCategories:")
    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {count} files")

    if args.dry_run:
        print("\n[Dry run - no files written]")
        print("\nTop 10 sections by relevance:")
        for s in sections[:10]:
            print(f"  {s.relevance_score:.1f} | {s.category:15} | {s.title}")
        return

    # Ensure output directory exists
    output_dir = os.path.dirname(args.output) or "."
    os.makedirs(output_dir, exist_ok=True)

    # Generate index metadata
    metadata = generate_index_metadata(sections)
    with open(args.index_output, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
    print(f"\nWrote index metadata to {args.index_output}")

    # Generate llms.txt
    if not args.index_only:
        llms_txt = generate_llms_txt(sections, args.max_tokens)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(llms_txt)

        # Calculate stats
        char_count = len(llms_txt)
        est_tokens = char_count // 4
        print(f"Wrote llms.txt to {args.output}")
        print(f"  Size: {char_count:,} chars (~{est_tokens:,} tokens)")

    print("\nDone!")


if __name__ == "__main__":
    main()
