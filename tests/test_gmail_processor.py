"""
Tests for Gmail Processor K8s deployment and process_emails.py script.

Tests cover:
- K8s manifest structure validation (YAML parsing, required fields)
- Gmail processor deployment configuration
- Secret template structure
- Kustomization resource references
- EmailProcessor class behavior (unit tests)
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

# Project root
PROJECT_ROOT = Path(__file__).parent.parent
K8S_BASE = PROJECT_ROOT / "k8s" / "base"


# ---------------------------------------------------------------------------
# K8s Manifest Validation
# ---------------------------------------------------------------------------


class TestGmailProcessorManifest:
    """Validate gmail-processor.yaml K8s manifest."""

    @pytest.fixture
    def manifest_path(self) -> Path:
        return K8S_BASE / "gmail-processor.yaml"

    @pytest.fixture
    def manifest(self, manifest_path: Path) -> dict:
        assert manifest_path.exists(), f"Missing: {manifest_path}"
        with open(manifest_path) as f:
            docs = list(yaml.safe_load_all(f))
        # Filter out None docs (from trailing ---)
        return [d for d in docs if d is not None]

    def test_manifest_exists(self, manifest_path: Path):
        assert manifest_path.exists()

    def test_manifest_is_valid_yaml(self, manifest: list[dict]):
        assert len(manifest) >= 1, "Expected at least one YAML document"

    def test_deployment_kind(self, manifest: list[dict]):
        deployment = manifest[0]
        assert deployment["kind"] == "Deployment"
        assert deployment["apiVersion"] == "apps/v1"

    def test_deployment_metadata(self, manifest: list[dict]):
        meta = manifest[0]["metadata"]
        assert meta["name"] == "gmail-processor"
        assert meta["namespace"] == "vibeteam"
        assert meta["labels"]["app"] == "gmail-processor"
        assert meta["labels"]["team"] == "vibeteam"

    def test_deployment_selector(self, manifest: list[dict]):
        spec = manifest[0]["spec"]
        assert spec["replicas"] == 1
        assert spec["selector"]["matchLabels"]["app"] == "gmail-processor"

    def test_pod_template_labels(self, manifest: list[dict]):
        pod_labels = manifest[0]["spec"]["template"]["metadata"]["labels"]
        assert pod_labels["app"] == "gmail-processor"
        assert pod_labels["team"] == "vibeteam"

    def test_image_pull_secrets(self, manifest: list[dict]):
        pod_spec = manifest[0]["spec"]["template"]["spec"]
        assert any(s["name"] == "ghcr-pull-secret" for s in pod_spec["imagePullSecrets"])

    def test_init_container_copies_credentials(self, manifest: list[dict]):
        pod_spec = manifest[0]["spec"]["template"]["spec"]
        init_containers = pod_spec.get("initContainers", [])
        assert len(init_containers) >= 1, "Need init container to copy Gmail credentials"

        copy_init = init_containers[0]
        assert copy_init["name"] == "copy-token"
        # Must mount both secrets (read-only) and writable volume
        mount_names = [m["name"] for m in copy_init["volumeMounts"]]
        assert "gmail-secrets" in mount_names
        assert "gmail-writable" in mount_names

    def test_main_container_command(self, manifest: list[dict]):
        container = manifest[0]["spec"]["template"]["spec"]["containers"][0]
        assert container["name"] == "gmail-processor"
        assert "process_emails.py" in " ".join(container["command"])
        assert "--daemon" in container["args"]
        assert "--interval" in container["args"]

    def test_daemon_interval_is_reasonable(self, manifest: list[dict]):
        container = manifest[0]["spec"]["template"]["spec"]["containers"][0]
        args = container["args"]
        interval_idx = args.index("--interval")
        interval = int(args[interval_idx + 1])
        # Between 1 minute and 30 minutes
        assert 60 <= interval <= 1800, f"Interval {interval}s seems unreasonable"

    def test_credential_paths_point_to_writable_volume(self, manifest: list[dict]):
        container = manifest[0]["spec"]["template"]["spec"]["containers"][0]
        args = container["args"]
        creds_idx = args.index("--credentials")
        token_idx = args.index("--token")
        creds_path = args[creds_idx + 1]
        token_path = args[token_idx + 1]

        # Both should point to the writable mount, not the secret mount
        mount_paths = [m["mountPath"] for m in container["volumeMounts"]]
        # At least one mount should be a prefix of the credential paths
        assert any(creds_path.startswith(mp) for mp in mount_paths), (
            f"Credentials path {creds_path} not under any mount: {mount_paths}"
        )
        assert any(token_path.startswith(mp) for mp in mount_paths), (
            f"Token path {token_path} not under any mount: {mount_paths}"
        )

    def test_resource_limits_set(self, manifest: list[dict]):
        container = manifest[0]["spec"]["template"]["spec"]["containers"][0]
        resources = container.get("resources", {})
        assert "requests" in resources, "Missing resource requests"
        assert "limits" in resources, "Missing resource limits"
        assert "cpu" in resources["requests"]
        assert "memory" in resources["requests"]

    def test_volumes_defined(self, manifest: list[dict]):
        volumes = manifest[0]["spec"]["template"]["spec"]["volumes"]
        vol_names = [v["name"] for v in volumes]
        assert "gmail-secrets" in vol_names, "Missing gmail-secrets volume"
        assert "gmail-writable" in vol_names, "Missing gmail-writable volume"

        # gmail-secrets should reference the K8s secret
        secrets_vol = next(v for v in volumes if v["name"] == "gmail-secrets")
        assert "secret" in secrets_vol
        assert secrets_vol["secret"]["secretName"] == "gmail-oauth-secret"

        # gmail-writable should be emptyDir (writable)
        writable_vol = next(v for v in volumes if v["name"] == "gmail-writable")
        assert "emptyDir" in writable_vol

    def test_uses_vibeteam_image(self, manifest: list[dict]):
        """Gmail processor should use the main vibeteam image (has scripts/ included)."""
        container = manifest[0]["spec"]["template"]["spec"]["containers"][0]
        assert "ghcr.io/vibetechnologies/vibeteam" in container["image"]

    def test_service_account(self, manifest: list[dict]):
        pod_spec = manifest[0]["spec"]["template"]["spec"]
        assert pod_spec.get("serviceAccountName") == "vibeteam-agent"


class TestGmailSecretsManifest:
    """Validate gmail-secrets.yaml template."""

    @pytest.fixture
    def manifest_path(self) -> Path:
        return K8S_BASE / "gmail-secrets.yaml"

    @pytest.fixture
    def manifest(self, manifest_path: Path) -> dict:
        assert manifest_path.exists(), f"Missing: {manifest_path}"
        with open(manifest_path) as f:
            docs = list(yaml.safe_load_all(f))
        return [d for d in docs if d is not None]

    def test_manifest_exists(self, manifest_path: Path):
        assert manifest_path.exists()

    def test_secret_kind(self, manifest: list[dict]):
        secret = manifest[0]
        assert secret["kind"] == "Secret"
        assert secret["type"] == "Opaque"

    def test_secret_name_matches_deployment_reference(self, manifest: list[dict]):
        """Secret name must match what gmail-processor.yaml references."""
        assert manifest[0]["metadata"]["name"] == "gmail-oauth-secret"

    def test_secret_namespace(self, manifest: list[dict]):
        assert manifest[0]["metadata"]["namespace"] == "vibeteam"

    def test_contains_credentials_key(self, manifest: list[dict]):
        string_data = manifest[0].get("stringData", {})
        assert "gmail-credentials.json" in string_data, "Missing gmail-credentials.json key"

    def test_contains_token_key(self, manifest: list[dict]):
        string_data = manifest[0].get("stringData", {})
        assert "gmail-token.json" in string_data, "Missing gmail-token.json key"

    def test_credentials_has_placeholder_values(self, manifest: list[dict]):
        """Template should have REPLACE_ placeholders, not real credentials."""
        creds = manifest[0]["stringData"]["gmail-credentials.json"]
        assert "REPLACE_" in creds, "Template should have placeholder values"

    def test_token_has_required_oauth_fields(self, manifest: list[dict]):
        """Token template should have the expected OAuth2 fields."""
        import json

        token_str = manifest[0]["stringData"]["gmail-token.json"]
        token = json.loads(token_str)
        required_fields = ["token", "refresh_token", "token_uri", "client_id", "client_secret"]
        for field in required_fields:
            assert field in token, f"Missing required field: {field}"


class TestKustomizationIncludesGmail:
    """Verify gmail-processor is referenced in kustomization.yaml."""

    @pytest.fixture
    def kustomization(self) -> dict:
        path = K8S_BASE / "kustomization.yaml"
        assert path.exists()
        with open(path) as f:
            return yaml.safe_load(f)

    def test_gmail_processor_in_resources(self, kustomization: dict):
        resources = kustomization.get("resources", [])
        assert "gmail-processor.yaml" in resources, (
            f"gmail-processor.yaml not in kustomization resources: {resources}"
        )


# ---------------------------------------------------------------------------
# EmailProcessor Unit Tests
# ---------------------------------------------------------------------------


class TestEmailProcessorUnit:
    """Unit tests for the EmailProcessor class in process_emails.py."""

    @pytest.fixture
    def mock_gmail(self):
        """Create a mock GmailConnector."""
        gmail = MagicMock()
        gmail.fetch_unread_emails.return_value = []
        gmail.mark_as_read.return_value = True
        gmail.send_reply.return_value = "msg-123"
        return gmail

    @pytest.fixture
    def processor(self, mock_gmail):
        """Create an EmailProcessor with mock Gmail."""
        # Import from the script
        import importlib
        import sys

        # Add the connectors path so the script can import gmail module
        connectors_path = str(PROJECT_ROOT / "vibeteam" / "connectors")
        if connectors_path not in sys.path:
            sys.path.insert(0, connectors_path)

        spec = importlib.util.spec_from_file_location(
            "process_emails",
            PROJECT_ROOT / "scripts" / "process_emails.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        return mod.EmailProcessor(gmail=mock_gmail, dry_run=True)

    def test_processor_initializes(self, processor):
        assert processor.dry_run is True
        assert processor.stats["processed"] == 0

    def test_no_emails_returns_empty_stats(self, processor):
        stats = asyncio.run(processor.process_emails())
        assert stats["processed"] == 0
        assert stats["skipped"] == 0

    def test_non_support_email_is_skipped(self, processor, mock_gmail):
        """Emails not matching docs portal format should be skipped."""
        from gmail import Email

        mock_email = Email(
            id="msg-1",
            thread_id="thread-1",
            subject="npm security advisory: lodash",
            sender="npm <noreply@npmjs.com>",
            sender_email="noreply@npmjs.com",
            recipient="support@vibebrowser.app",
            date="2026-01-15",
            body="A security vulnerability was found in lodash...",
            snippet="A security vulnerability...",
            labels=["INBOX", "UNREAD"],
        )
        mock_gmail.fetch_unread_emails.return_value = [mock_email]

        stats = asyncio.run(processor.process_emails())
        assert stats["skipped"] == 1
        assert stats["processed"] == 0

    def test_docs_portal_escalation_is_processed(self, processor, mock_gmail):
        """Emails matching [Docs Support #...] format should be processed."""
        from gmail import Email

        mock_email = Email(
            id="msg-2",
            thread_id="thread-2",
            subject="[Docs Support #ABC-123] New request from user@example.com",
            sender="noreply@vibebrowser.app",
            sender_email="noreply@vibebrowser.app",
            recipient="support@vibebrowser.app",
            date="2026-01-15",
            body="How do I configure the browser extension?",
            snippet="How do I configure...",
            labels=["INBOX", "UNREAD"],
        )
        mock_gmail.fetch_unread_emails.return_value = [mock_email]

        stats = asyncio.run(processor.process_emails())
        assert stats["processed"] == 1
        assert stats["skipped"] == 0

    def test_billing_email_triggers_escalation(self, processor, mock_gmail):
        """Emails about billing should be escalated."""
        from gmail import Email

        mock_email = Email(
            id="msg-3",
            thread_id="thread-3",
            subject="[Docs Support #BILL-001] New request from billing@example.com",
            sender="noreply@vibebrowser.app",
            sender_email="noreply@vibebrowser.app",
            recipient="support@vibebrowser.app",
            date="2026-01-15",
            body="I was charged twice for my subscription. Please refund.",
            snippet="I was charged twice...",
            labels=["INBOX", "UNREAD"],
        )
        mock_gmail.fetch_unread_emails.return_value = [mock_email]

        stats = asyncio.run(processor.process_emails())
        assert stats["escalated"] == 1
        assert stats["responded"] == 0

    def test_how_to_question_gets_response(self, processor, mock_gmail):
        """Simple how-to questions should get auto-response."""
        from gmail import Email

        mock_email = Email(
            id="msg-4",
            thread_id="thread-4",
            subject="[Docs Support #HELP-001] New request from newuser@example.com",
            sender="noreply@vibebrowser.app",
            sender_email="noreply@vibebrowser.app",
            recipient="support@vibebrowser.app",
            date="2026-01-15",
            body="How do I install VibeBrowser on Linux?",
            snippet="How do I install...",
            labels=["INBOX", "UNREAD"],
        )
        mock_gmail.fetch_unread_emails.return_value = [mock_email]

        stats = asyncio.run(processor.process_emails())
        assert stats["responded"] == 1
        assert stats["escalated"] == 0

    def test_dry_run_does_not_mark_as_read(self, processor, mock_gmail):
        """In dry run mode, emails should NOT be marked as read."""
        from gmail import Email

        mock_email = Email(
            id="msg-5",
            thread_id="thread-5",
            subject="[Docs Support #DRY-001] New request from test@example.com",
            sender="noreply@vibebrowser.app",
            sender_email="noreply@vibebrowser.app",
            recipient="support@vibebrowser.app",
            date="2026-01-15",
            body="This is a test question about VibeBrowser.",
            snippet="This is a test...",
            labels=["INBOX", "UNREAD"],
        )
        mock_gmail.fetch_unread_emails.return_value = [mock_email]

        asyncio.run(processor.process_emails())
        mock_gmail.mark_as_read.assert_not_called()

    def test_response_validation_catches_internal_urls(self, processor):
        """Response validator should reject responses with internal URLs."""
        result = processor._validate_response("Check out http://localhost:8080/admin")
        assert not result["valid"]
        assert any("localhost" in issue for issue in result["issues"])

    def test_response_validation_catches_secrets(self, processor):
        """Response validator should reject responses that might contain secrets."""
        result = processor._validate_response("Use api_key=abc123 to authenticate")
        assert not result["valid"]
        assert any("api_key" in issue for issue in result["issues"])

    def test_response_validation_passes_clean_response(self, processor):
        """Clean responses should pass validation."""
        result = processor._validate_response(
            "Thanks for reaching out! Check https://docs.vibebrowser.app for help."
        )
        assert result["valid"]

    def test_ticket_extraction_from_subject(self, processor):
        """Should extract ticket ID and customer email from subject."""
        from gmail import Email

        email = Email(
            id="x",
            thread_id="x",
            subject="[Docs Support #XYZ-789] New request from alice@corp.com",
            sender="noreply@vibebrowser.app",
            sender_email="noreply@vibebrowser.app",
            recipient="support@vibebrowser.app",
            date="2026-01-15",
            body="test",
            snippet="test",
            labels=[],
        )
        info = processor._extract_ticket_info(email)
        assert info["ticket_id"] == "XYZ-789"
        assert info["customer_email"] == "alice@corp.com"
