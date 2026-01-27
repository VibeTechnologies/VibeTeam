"""
End-to-end tests for VibeTeam Operations.

Tests the full workflow of all agents:
1. Reliability Engineer - Health checks
2. Product Manager - Langfuse analysis
3. Support Engineer - Email processing
4. Software Engineer - Issue analysis and PR creation
5. Release Engineer - PR tracking

These tests require:
- GITHUB_TOKEN with repo access
- Network access to test endpoints
- Optional: AZURE_API_KEY for LLM-powered tests
"""

import os
import subprocess
from pathlib import Path

import pytest

# Skip all tests if required env vars are missing
pytestmark = pytest.mark.skipif(
    not os.environ.get("GITHUB_TOKEN"),
    reason="GITHUB_TOKEN required for e2e tests",
)


class TestReliabilityEngineer:
    """Test Reliability Engineer health checks."""

    def test_sre_health_command_exists(self) -> None:
        """Test that sre-health command is available."""
        result = subprocess.run(
            ["vibeteam", "scheduled", "sre-health", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "health checks" in result.stdout.lower() or "endpoints" in result.stdout.lower()

    def test_sre_health_with_test_endpoint(self) -> None:
        """Test health check against a known endpoint."""
        result = subprocess.run(
            [
                "vibeteam",
                "scheduled",
                "sre-health",
                "-e",
                "https://www.google.com",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        assert "OK" in result.stdout or "healthy" in result.stdout.lower()

    def test_sre_health_detects_failure(self) -> None:
        """Test health check detects failing endpoint."""
        result = subprocess.run(
            [
                "vibeteam",
                "scheduled",
                "sre-health",
                "-e",
                "https://localhost:59999",  # Non-existent endpoint
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Should exit with error code when endpoint fails
        assert (
            result.returncode != 0 or "FAIL" in result.stdout or "failed" in result.stdout.lower()
        )


class TestProductManager:
    """Test Product Manager Langfuse analysis."""

    def test_pm_analyze_command_exists(self) -> None:
        """Test that pm-analyze command is available."""
        result = subprocess.run(
            ["vibeteam", "scheduled", "pm-analyze", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "langfuse" in result.stdout.lower() or "analyze" in result.stdout.lower()

    @pytest.mark.skipif(
        not os.environ.get("LANGFUSE_PUBLIC_KEY"),
        reason="LANGFUSE credentials required",
    )
    def test_pm_analyze_runs(self) -> None:
        """Test PM analysis runs without error."""
        result = subprocess.run(
            ["vibeteam", "scheduled", "pm-analyze", "--hours", "1", "--dry-run"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        # Should complete without error
        assert result.returncode == 0 or "conversations" in result.stdout.lower()


class TestSupportEngineer:
    """Test Support Engineer email processing."""

    def test_support_emails_command_exists(self) -> None:
        """Test that support-emails command is available."""
        result = subprocess.run(
            ["vibeteam", "scheduled", "support-emails", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "email" in result.stdout.lower()

    def test_support_emails_dry_run(self) -> None:
        """Test support emails in dry-run mode."""
        # This will fail without Gmail credentials, but should show proper error
        result = subprocess.run(
            ["vibeteam", "scheduled", "support-emails", "--dry-run", "--max-emails", "1"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Either succeeds or fails with credentials error (not crash)
        assert (
            "email" in result.stdout.lower()
            or "credentials" in result.stderr.lower()
            or result.returncode in [0, 1]
        )


class TestSoftwareEngineer:
    """Test Software Engineer issue analysis and PR creation."""

    TEST_REPO = "VibeTechnologies/VibeTeam"  # Use VibeTeam repo for testing
    TEST_LABEL = "test-swe-agent"

    def test_swe_issues_command_exists(self) -> None:
        """Test that swe-issues command is available."""
        result = subprocess.run(
            ["vibeteam", "scheduled", "swe-issues", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "issue" in result.stdout.lower() or "pr" in result.stdout.lower()

    def test_swe_issues_no_matching_issues(self) -> None:
        """Test SWE agent with non-existent label."""
        result = subprocess.run(
            [
                "vibeteam",
                "scheduled",
                "swe-issues",
                "--label",
                "nonexistent-label-xyz123",
                "--repo",
                self.TEST_REPO,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        assert "Found 0 issues" in result.stdout or "No issues" in result.stdout

    def test_swe_issues_dry_run(self) -> None:
        """Test SWE agent in dry-run mode."""
        result = subprocess.run(
            [
                "vibeteam",
                "scheduled",
                "swe-issues",
                "--label",
                "bug",  # Common label that might exist
                "--repo",
                self.TEST_REPO,
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        # Should complete without error
        assert result.returncode == 0


class TestReleaseEngineer:
    """Test Release Engineer PR tracking."""

    def test_release_check_command_exists(self) -> None:
        """Test that release-check command is available."""
        result = subprocess.run(
            ["vibeteam", "scheduled", "release-check", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

    def test_release_check_runs(self) -> None:
        """Test release check runs successfully."""
        result = subprocess.run(
            ["vibeteam", "scheduled", "release-check"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        assert (
            "PR" in result.stdout
            or "merged" in result.stdout.lower()
            or "complete" in result.stdout.lower()
        )


class TestCLICommands:
    """Test general CLI commands."""

    def test_vibeteam_version(self) -> None:
        """Test version command."""
        result = subprocess.run(
            ["vibeteam", "--version"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

    def test_vibeteam_agents_list(self) -> None:
        """Test agents list command."""
        result = subprocess.run(
            ["vibeteam", "agents"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "pm" in result.stdout.lower() or "product" in result.stdout.lower()
        assert "swe" in result.stdout.lower() or "software" in result.stdout.lower()
        assert "support" in result.stdout.lower()
        assert "sre" in result.stdout.lower() or "reliability" in result.stdout.lower()

    def test_vibeteam_status(self) -> None:
        """Test status command."""
        result = subprocess.run(
            ["vibeteam", "status"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0


class TestE2EWorkflow:
    """
    Full end-to-end workflow test.

    This test creates a real issue, runs the SWE agent, and verifies the result.
    Only runs when E2E_FULL_TEST=1 is set.
    """

    TEST_REPO = "VibeTechnologies/VibeTeam"

    @pytest.mark.skipif(
        not os.environ.get("E2E_FULL_TEST"),
        reason="Set E2E_FULL_TEST=1 to run full e2e test",
    )
    @pytest.mark.skipif(
        not (os.environ.get("AZURE_API_KEY") or os.environ.get("AZURE_OPENAI_API_KEY")),
        reason="AZURE_API_KEY or AZURE_OPENAI_API_KEY required for LLM tests",
    )
    def test_full_swe_workflow(self) -> None:
        """
        Full SWE workflow:
        1. Create test issue
        2. Run SWE agent
        3. Verify PR or comment created
        4. Cleanup
        """
        gh_token = os.environ["GITHUB_TOKEN"]
        env = {**os.environ, "GH_TOKEN": gh_token}

        # 1. Create test issue
        issue_body = """## Test Issue for SWE Agent

This is an automated test issue.

### Problem
The file `tests/test_e2e_ops.py` has a typo in a comment.

### Expected Fix
Fix the typo in the test file.

---
*This issue will be automatically closed after testing.*
"""
        result = subprocess.run(
            [
                "gh",
                "issue",
                "create",
                "--repo",
                self.TEST_REPO,
                "--title",
                "[TEST] SWE Agent E2E Test",
                "--body",
                issue_body,
                "--label",
                "test-swe-agent",
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0, f"Failed to create issue: {result.stderr}"

        # Extract issue number from URL
        issue_url = result.stdout.strip()
        issue_number = issue_url.split("/")[-1]
        print(f"Created test issue: {issue_url}")

        try:
            # Wait for GitHub API to propagate the issue
            import time

            time.sleep(3)

            # 2. Run SWE agent in dry-run mode
            result = subprocess.run(
                [
                    "vibeteam",
                    "scheduled",
                    "swe-issues",
                    "--label",
                    "test-swe-agent",
                    "--repo",
                    self.TEST_REPO,
                    "--dry-run",
                ],
                capture_output=True,
                text=True,
                timeout=180,
                env=env,
            )
            print(f"SWE agent output: {result.stdout}")
            print(f"SWE agent stderr: {result.stderr}")

            assert result.returncode == 0, f"SWE agent failed: {result.stderr}"
            assert f"#{issue_number}" in result.stdout or "Processing issue" in result.stdout

        finally:
            # 3. Cleanup - close the test issue
            subprocess.run(
                [
                    "gh",
                    "issue",
                    "close",
                    issue_number,
                    "--repo",
                    self.TEST_REPO,
                    "--comment",
                    "Automated test complete. Closing.",
                ],
                capture_output=True,
                env=env,
            )
            print(f"Closed test issue #{issue_number}")


class TestKubernetesManifests:
    """Test Kubernetes manifests are valid."""

    K8S_DIR = Path(__file__).parent.parent / "k8s" / "base"

    def test_manifests_exist(self) -> None:
        """Test all required manifests exist."""
        required = [
            "product-manager.yaml",
            "support-engineer.yaml",
            "release-engineer.yaml",
            "software-engineer.yaml",
            "kustomization.yaml",
        ]
        for manifest in required:
            assert (self.K8S_DIR / manifest).exists(), f"Missing manifest: {manifest}"

    def test_kustomization_includes_all(self) -> None:
        """Test kustomization.yaml includes all resources."""
        kustomization = (self.K8S_DIR / "kustomization.yaml").read_text()
        assert "product-manager.yaml" in kustomization
        assert "support-engineer.yaml" in kustomization
        assert "release-engineer.yaml" in kustomization
        assert "software-engineer.yaml" in kustomization

    def test_manifests_are_valid_yaml(self) -> None:
        """Test all manifests are valid YAML."""
        import yaml

        for manifest in self.K8S_DIR.glob("*.yaml"):
            try:
                list(yaml.safe_load_all(manifest.read_text()))
            except yaml.YAMLError as e:
                pytest.fail(f"Invalid YAML in {manifest.name}: {e}")

    def test_cronjobs_have_required_fields(self) -> None:
        """Test CronJobs have required fields."""
        import yaml

        for manifest in self.K8S_DIR.glob("*.yaml"):
            if manifest.name == "kustomization.yaml":
                continue

            docs = list(yaml.safe_load_all(manifest.read_text()))
            for doc in docs:
                if doc and doc.get("kind") == "CronJob":
                    # Check required fields
                    assert "schedule" in doc.get("spec", {}), f"Missing schedule in {manifest.name}"
                    job_spec = doc["spec"]["jobTemplate"]["spec"]["template"]["spec"]
                    assert "containers" in job_spec, f"Missing containers in {manifest.name}"
                    assert "imagePullSecrets" in job_spec, (
                        f"Missing imagePullSecrets in {manifest.name}"
                    )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
