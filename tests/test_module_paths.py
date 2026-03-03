"""
Tests for module path consistency across the deployment stack.

These tests verify that all references to agent_service module paths are
consistent and correct across:
1. Python source code (utils.py get_prompt_path k8s branch, server.py uvicorn.run)
2. Dockerfiles (COPY paths and CMD entrypoints)
3. Shell entrypoints (entrypoint-dev.sh)
4. Kubernetes manifests (k8s overlays command overrides)
5. agents_md_loader.py (agents/ directory path in k8s)

WHY THIS EXISTS:
When the directory was renamed from agents/openhands/ to agent_service/openhands/,
several hardcoded path strings were missed, causing a 500 error in production that
was invisible to the existing test suite. The existing tests only exercised the
local-dev fallback path (os.path.dirname(__file__)) and never validated the k8s
code path which uses hardcoded strings like "agent_service" and "agents".

These tests ensure a directory rename cannot silently break production again.
No mocks or fallbacks — every test validates against the real repo structure,
exactly as production would resolve paths.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Repo root: tests/ is one level below.
# In k8s, /code/current IS the repo root. Tests use the real repo root
# so every path assertion matches production exactly.
REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_SERVICE_DIR = REPO_ROOT / "agent_service" / "openhands"
AGENTS_DIR = REPO_ROOT / "agents"

# All files that contain hardcoded module/directory paths that must stay in sync
DOCKERFILE_PROD = AGENT_SERVICE_DIR / "Dockerfile"
DOCKERFILE_DEV = AGENT_SERVICE_DIR / "Dockerfile.dev"
ENTRYPOINT_DEV = AGENT_SERVICE_DIR / "entrypoint-dev.sh"
SERVER_PY = AGENT_SERVICE_DIR / "server.py"
UTILS_PY = AGENT_SERVICE_DIR / "utils.py"
K8S_OPENHANDS_PATCH = REPO_ROOT / "k8s" / "overlays" / "dev" / "openhands-svc-patch.yaml"
AGENTS_MD_LOADER = REPO_ROOT / "agent_service" / "shared" / "agents_md_loader.py"


# ---------------------------------------------------------------------------
# Test: get_prompt_path() k8s branch resolves to a real directory/file
# ---------------------------------------------------------------------------
class TestGetPromptPathK8sBranch:
    """Verify the k8s code path in get_prompt_path() references the correct directory.

    In k8s, /code/current is the repo root. We extract the hardcoded path
    segments from source and check they resolve against the real repo root.
    No mocks — if the path is wrong, the file won't exist.
    """

    def test_k8s_path_resolves_to_existing_file(self):
        """The k8s path constructed by get_prompt_path() must point to a real file in the repo."""
        content = UTILS_PY.read_text()
        # Extract: os.path.join(_CODE_CURRENT, "agent_service", "openhands", "prompts", prompt_filename)
        match = re.search(
            r'os\.path\.join\(_CODE_CURRENT,\s*"([^"]+)",\s*"([^"]+)",\s*"([^"]+)",\s*prompt_filename\)',
            content,
        )
        assert match, "Could not find os.path.join(_CODE_CURRENT, ..., prompt_filename) in utils.py"
        seg1, seg2, seg3 = match.group(1), match.group(2), match.group(3)

        # In k8s, _CODE_CURRENT is the repo root. Verify the default prompt file exists.
        prompt_file = REPO_ROOT / seg1 / seg2 / seg3 / "agent_system.j2"
        assert prompt_file.is_file(), (
            f"get_prompt_path() k8s branch builds path "
            f"'<repo_root>/{seg1}/{seg2}/{seg3}/agent_system.j2' "
            f"but {prompt_file} does not exist. "
            f"Did you rename a directory without updating utils.py?"
        )

    def test_k8s_path_directory_exists(self):
        """The prompts directory referenced by get_prompt_path() must exist in the repo."""
        content = UTILS_PY.read_text()
        match = re.search(
            r'os\.path\.join\(_CODE_CURRENT,\s*"([^"]+)",\s*"([^"]+)",\s*"([^"]+)"',
            content,
        )
        assert match, "Could not find os.path.join(_CODE_CURRENT, ...) in utils.py"
        seg1, seg2, seg3 = match.group(1), match.group(2), match.group(3)

        real_path = REPO_ROOT / seg1 / seg2 / seg3
        assert real_path.is_dir(), (
            f"get_prompt_path() k8s branch references '{seg1}/{seg2}/{seg3}/' "
            f"but {real_path} does not exist in the repo. "
            f"Did you rename a directory without updating utils.py?"
        )


# ---------------------------------------------------------------------------
# Test: agents_md_loader.py k8s path references real agents/ directory
# ---------------------------------------------------------------------------
class TestAgentsMdLoaderK8sPath:
    """Verify agents_md_loader.py k8s branch points to the correct agents/ directory."""

    def test_k8s_path_matches_repo_agents_dir(self):
        """The k8s path 'code_current / "agents"' must match the real agents/ dir."""
        content = AGENTS_MD_LOADER.read_text()
        # Find: code_current / "agents" or similar
        match = re.search(r'code_current\s*/\s*"([^"]+)"', content)
        assert match, "Could not find code_current path in agents_md_loader.py"
        dir_name = match.group(1)
        assert (REPO_ROOT / dir_name).is_dir(), (
            f"agents_md_loader.py references '{dir_name}/' in k8s path "
            f"but {REPO_ROOT / dir_name} does not exist."
        )


# ---------------------------------------------------------------------------
# Test: Module path consistency across all deployment artifacts
# ---------------------------------------------------------------------------

# The canonical module path for the server
CANONICAL_MODULE = "agent_service.openhands.server"


class TestModulePathConsistency:
    """Ensure Dockerfiles, entrypoints, k8s patches, and server.py all use
    the same module path, and that path is actually importable."""

    def test_server_module_is_importable(self):
        """The canonical module path must be importable from the repo root."""
        import importlib

        try:
            mod = importlib.import_module(CANONICAL_MODULE)
        except ImportError as e:
            pytest.fail(
                f"Cannot import '{CANONICAL_MODULE}': {e}. "
                f"Does agent_service/__init__.py exist? "
                f"Is agent_service/openhands/__init__.py present?"
            )
        assert hasattr(mod, "app"), (
            f"Module '{CANONICAL_MODULE}' has no 'app' attribute (FastAPI app)."
        )

    def test_agent_service_is_a_package(self):
        """agent_service/ must have __init__.py to be importable."""
        init = REPO_ROOT / "agent_service" / "__init__.py"
        assert init.is_file(), (
            "agent_service/__init__.py is missing — "
            "this directory must be a Python package for 'agent_service.openhands.server' imports to work."
        )

    def test_agent_service_openhands_is_a_package(self):
        """agent_service/openhands/ must have __init__.py."""
        init = REPO_ROOT / "agent_service" / "openhands" / "__init__.py"
        assert init.is_file(), "agent_service/openhands/__init__.py is missing."

    @pytest.mark.parametrize(
        "filepath,description",
        [
            (DOCKERFILE_PROD, "Production Dockerfile CMD"),
            (DOCKERFILE_DEV, "Dev Dockerfile CMD"),
            (ENTRYPOINT_DEV, "Dev entrypoint shell script"),
            (SERVER_PY, "server.py uvicorn.run()"),
            (K8S_OPENHANDS_PATCH, "k8s dev overlay command"),
        ],
    )
    def test_file_references_canonical_module(self, filepath: Path, description: str):
        """Every deployment artifact must reference the canonical module path."""
        assert filepath.is_file(), f"{filepath} not found"
        content = filepath.read_text()
        assert CANONICAL_MODULE in content, (
            f"{description} ({filepath.name}) does not reference '{CANONICAL_MODULE}'. "
            f"All deployment artifacts must use the same module path. "
            f"Did you rename the directory without updating this file?"
        )


# ---------------------------------------------------------------------------
# Test: Dockerfile COPY paths reference existing directories
# ---------------------------------------------------------------------------
class TestDockerfileCopyPaths:
    """Verify that COPY source paths in Dockerfiles point to real repo paths."""

    @pytest.mark.parametrize(
        "dockerfile",
        [DOCKERFILE_PROD, DOCKERFILE_DEV],
        ids=["Dockerfile", "Dockerfile.dev"],
    )
    def test_copy_source_paths_exist(self, dockerfile: Path):
        """Every COPY source path in the Dockerfile must exist in the repo."""
        content = dockerfile.read_text()
        # Match COPY lines (skip --from=builder ones as those reference build stage)
        copy_pattern = re.compile(r"^COPY\s+(?!--from=)(\S+)\s+", re.MULTILINE)
        for match in copy_pattern.finditer(content):
            source = match.group(1)
            # Skip variables and special Docker syntax
            if source.startswith("$") or source.startswith("--"):
                continue
            source_path = REPO_ROOT / source
            assert source_path.exists(), (
                f"{dockerfile.name} has COPY {source} but {source_path} "
                f"does not exist in the repo. Did you rename a directory?"
            )


# ---------------------------------------------------------------------------
# Test: No stale "agents/openhands" references in deployment files
# ---------------------------------------------------------------------------
class TestNoStaleAgentsOpenhands:
    """Guard against leftover 'agents/openhands' or 'agents.openhands' references
    in files that should use 'agent_service/openhands' or 'agent_service.openhands'.

    The agents/ directory still exists (for AGENTS.md configs) but should NOT be
    referenced as a Python module path anywhere in agent_service/ or deployment files.
    """

    # Files that should NEVER contain the old module/dir pattern
    FILES_TO_CHECK = [
        UTILS_PY,
        SERVER_PY,
        DOCKERFILE_PROD,
        DOCKERFILE_DEV,
        ENTRYPOINT_DEV,
        K8S_OPENHANDS_PATCH,
    ]

    # Patterns that indicate a stale reference (Python module or dir path)
    STALE_PATTERNS = [
        (r"\bagents\.openhands\.", "Python module path 'agents.openhands.'"),
        (r"\bagents/openhands/", "Directory path 'agents/openhands/'"),
        (r'"agents",\s*"openhands"', 'os.path.join segment "agents", "openhands"'),
    ]

    @pytest.mark.parametrize("filepath", FILES_TO_CHECK, ids=lambda p: p.name)
    def test_no_stale_agents_openhands_references(self, filepath: Path):
        """Deployment files must not reference the old agents/openhands paths."""
        if not filepath.is_file():
            pytest.skip(f"{filepath} not found")
        content = filepath.read_text()
        for pattern, desc in self.STALE_PATTERNS:
            matches = re.findall(pattern, content)
            assert not matches, (
                f"{filepath.name} contains stale reference ({desc}): {matches}. "
                f"The directory was renamed to agent_service/openhands/. "
                f"Please update this file."
            )
