"""
Tests for GitHub App authentication integration.

Tests cover:
1. GitHub App JWT generation
2. Installation token exchange
3. GitHubConnector with App auth
4. Webhook signature verification
5. Token refresh logic
"""

import hashlib
import hmac
import json
import os
import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from vibeteam.connectors.github import GitHubConnector
from vibeteam.utils import github_app


# ==============================================================================
# GitHub App Authentication Tests
# ==============================================================================


class TestGitHubAppAuth:
    """Test GitHub App authentication utilities."""

    def test_generate_jwt(self):
        """Test JWT generation for GitHub App."""
        # Use a test RSA private key
        test_private_key = """-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEAu1SU1LfVLPHCozMxH2Mo4lgOEePzNm0tRgeLezV6ffAt0+3V
cwQK2YmcbGfvvN8vW8dGPL8VaFO5xNg6qXKj8pNAp7nP7k6I6QO7+gw0m3TLaVBw
ABAhqCFNMbYvZGPNmUx7Dq5wGN9g6LUGRkW7cSovv2GlLa8eE0P+0M3gQ3JLQr6r
zEQqgqm6WLs8wXh5vD1WE1qLwNu7eHM8YyLnzMHLGPBH0YXfvYTxeQXDdD9F5gRg
owQFqT0YHrFvKNNKL0PaKYpQWfWyT7EgSFWqPbM8qdqZJNJ0LLDcQHsD5CnMxXpz
kPUJEMBCE6tULQVsLQKrYqzLLMZNWS8BXjuA+QIDAQABAoIBAQCEY7fJyI2qYqMw
UvGPaQqLbVJHrSLPQlvG7bZ6g0N2h0lRFLAp0wNJ8L7F8VfQFE2gg3DSGP3EfNEJ
h0JzT6F6l3EUF0Cdk3RQr7Ix6zAq5wZDSCT1PHuJqYpwJKZZVqC8h1tPUAFIgQFJ
6bWvANEYdDGqLPvdwLvGJQdG3BfZn6wSFYCNJ2PBrUYJlOvfELPWgLU6f5JtCYBP
Z3AvZXMVGYC7M5aBfWHLLqTQp6T6TfUxDDqMLN+PqCJ5xNQEPWGQPLPLFPLPLFMh
GFPvLPGHEPLPQWMhD3qLPGFPLPWGQhGDqPLPJzTaH1qMLH8PqGBZxvLPYPGFEJqz
TJ9PLFLBAoGBAPBrJqZ3GbFWHLZ9x0HhVlcvLYU6N8DPQq3mQqCqQFLPLMHLGJqZ
3DqLPGFEJqzTJ9PLFLBGFPvLPGHEPLPQWMhD3qLPGFPLPWGQhGDqPLPJzTaH1qML
H8PqGBZxvLPYPGFEJqzTJ9PLFLBAoGBAPBrJqZ3GbFWHLZ9x0HhVlcvLYU6N8DPQ
q3mQqCqQFLPLMHLGJqZ3DqLPGFEJqzTJ9PLFLBAoGAErK0GlcGc+Kj0sCHYJlqL
qMLH8PqGBZxvLPYPGFEJqzTJ9PLFLBAoGBAO3zLPGFEJqzTJ9PLFLBGFPvLPGHEP
LPQWMhD3qLPGFPLPWGQhGDqPLPJzTaH1AoGABEG/dVbkJvqMLH8PqGBZxvLPYPGF
EJqzTJ9PLFLBAoGAWGz2VqMLH8PqGBZxvLPYPGFEJqzTJ9PLFLB
-----END RSA PRIVATE KEY-----"""

        app_id = "123456"
        jwt_token = github_app.generate_jwt(app_id, test_private_key)

        assert jwt_token is not None
        assert isinstance(jwt_token, str)
        assert len(jwt_token) > 0

        # JWT should have 3 parts: header.payload.signature
        parts = jwt_token.split(".")
        assert len(parts) == 3

    def test_get_installation_token_api_error(self):
        """Test handling of API errors when getting installation token."""
        test_private_key = """-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEAu1SU1LfVLPHCozMxH2Mo4lgOEePzNm0tRgeLezV6ffAt0+3V
cwQK2YmcbGfvvN8vW8dGPL8VaFO5xNg6qXKj8pNAp7nP7k6I6QO7+gw0m3TLaVBw
ABAhqCFNMbYvZGPNmUx7Dq5wGN9g6LUGRkW7cSovv2GlLa8eE0P+0M3gQ3JLQr6r
zEQqgqm6WLs8wXh5vD1WE1qLwNu7eHM8YyLnzMHLGPBH0YXfvYTxeQXDdD9F5gRg
owQFqT0YHrFvKNNKL0PaKYpQWfWyT7EgSFWqPbM8qdqZJNJ0LLDcQHsD5CnMxXpz
kPUJEMBCE6tULQVsLQKrYqzLLMZNWS8BXjuA+QIDAQABAoIBAQCEY7fJyI2qYqMw
UvGPaQqLbVJHrSLPQlvG7bZ6g0N2h0lRFLAp0wNJ8L7F8VfQFE2gg3DSGP3EfNEJ
h0JzT6F6l3EUF0Cdk3RQr7Ix6zAq5wZDSCT1PHuJqYpwJKZZVqC8h1tPUAFIgQFJ
6bWvANEYdDGqLPvdwLvGJQdG3BfZn6wSFYCNJ2PBrUYJlOvfELPWgLU6f5JtCYBP
Z3AvZXMVGYC7M5aBfWHLLqTQp6T6TfUxDDqMLN+PqCJ5xNQEPWGQPLPLFPLPLFMh
GFPvLPGHEPLPQWMhD3qLPGFPLPWGQhGDqPLPJzTaH1qMLH8PqGBZxvLPYPGFEJqz
TJ9PLFLBAoGBAPBrJqZ3GbFWHLZ9x0HhVlcvLYU6N8DPQq3mQqCqQFLPLMHLGJqZ
3DqLPGFEJqzTJ9PLFLBGFPvLPGHEPLPQWMhD3qLPGFPLPWGQhGDqPLPJzTaH1qML
H8PqGBZxvLPYPGFEJqzTJ9PLFLBAoGBAPBrJqZ3GbFWHLZ9x0HhVlcvLYU6N8DPQ
q3mQqCqQFLPLMHLGJqZ3DqLPGFEJqzTJ9PLFLBAoGAErK0GlcGc+Kj0sCHYJlqL
qMLH8PqGBZxvLPYPGFEJqzTJ9PLFLBAoGBAO3zLPGFEJqzTJ9PLFLBGFPvLPGHEP
LPQWMhD3qLPGFPLPWGQhGDqPLPJzTaH1AoGABEG/dVbkJvqMLH8PqGBZxvLPYPGF
EJqzTJ9PLFLBAoGAWGz2VqMLH8PqGBZxvLPYPGFEJqzTJ9PLFLB
-----END RSA PRIVATE KEY-----"""

        with patch("vibeteam.utils.github_app.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.raise_for_status.side_effect = requests.HTTPError()
            mock_post.return_value = mock_response

            with pytest.raises(requests.HTTPError):
                github_app.get_installation_token(
                    app_id="123456",
                    private_key=test_private_key,
                    installation_id="12345678",
                )


# ==============================================================================
# GitHubConnector Integration Tests
# ==============================================================================


class TestGitHubConnectorAuth:
    """Test GitHubConnector with different authentication methods."""

    def test_init_with_pat(self):
        """Test initialization with Personal Access Token."""
        connector = GitHubConnector(token="ghp_test123")
        assert connector.token == "ghp_test123"
        assert not connector._use_app_auth

    def test_init_with_github_app(self):
        """Test initialization with GitHub App credentials."""
        test_key = "-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----"
        connector = GitHubConnector(
            app_id="123456",
            private_key=test_key,
            installation_id="12345678",
        )
        assert connector.app_id == "123456"
        assert connector.private_key == test_key
        assert connector.installation_id == "12345678"
        assert connector._use_app_auth

    def test_init_with_env_vars(self, monkeypatch):
        """Test initialization with environment variables."""
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_from_env")
        connector = GitHubConnector()
        assert connector.token == "ghp_from_env"

    def test_init_without_auth_raises_error(self):
        """Test that initialization without auth raises ValueError."""
        with pytest.raises(ValueError, match="GitHub authentication required"):
            GitHubConnector(token=None)

    def test_token_refresh_with_app_auth(self):
        """Test automatic token refresh with GitHub App."""
        test_key = "-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----"

        with patch("vibeteam.connectors.github.get_installation_token") as mock_get_token:
            mock_get_token.return_value = "ghs_new_token_123"

            connector = GitHubConnector(
                app_id="123456",
                private_key=test_key,
                installation_id="12345678",
            )

            # Force token expiry
            connector._token_expiry = time.time() - 1

            token = connector._ensure_token()

            assert token == "ghs_new_token_123"
            mock_get_token.assert_called_once()

    def test_token_no_refresh_when_valid(self):
        """Test that valid tokens are not refreshed."""
        test_key = "-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----"

        with patch("vibeteam.connectors.github.get_installation_token") as mock_get_token:
            mock_get_token.return_value = "ghs_token_123"

            connector = GitHubConnector(
                app_id="123456",
                private_key=test_key,
                installation_id="12345678",
            )

            # Get initial token
            connector._ensure_token()
            mock_get_token.assert_called_once()

            # Second call should not refresh (token still valid)
            connector._ensure_token()
            mock_get_token.assert_called_once()  # Still only called once

    def test_headers_include_token(self):
        """Test that headers include the auth token."""
        connector = GitHubConnector(token="ghp_test123")
        headers = connector._headers()

        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer ghp_test123"
        assert headers["Accept"] == "application/vnd.github+json"


# ==============================================================================
# Webhook Signature Verification Tests
# ==============================================================================


class TestWebhookSignatures:
    """Test webhook signature verification."""

    def test_github_webhook_signature_valid(self):
        """Test valid GitHub webhook signature."""
        from vibeteam.gateway.routes.github import verify_signature

        secret = "my_webhook_secret"
        payload = b'{"action":"opened","number":1}'

        # Generate valid signature
        signature = "sha256=" + hmac.new(
            secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()

        assert verify_signature(payload, signature, secret)

    def test_github_webhook_signature_invalid(self):
        """Test invalid GitHub webhook signature."""
        from vibeteam.gateway.routes.github import verify_signature

        secret = "my_webhook_secret"
        payload = b'{"action":"opened","number":1}'
        invalid_signature = "sha256=invalid_signature"

        assert not verify_signature(payload, invalid_signature, secret)

    def test_sentry_webhook_signature_valid(self):
        """Test valid Sentry webhook signature."""
        from vibeteam.webhook.server import verify_sentry_signature

        secret = "sentry_secret"
        payload = b'{"action":"created","data":{}}'

        # Generate valid signature
        signature = hmac.new(
            secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()

        assert verify_sentry_signature(payload, signature, secret)

    def test_sentry_webhook_signature_invalid(self):
        """Test invalid Sentry webhook signature."""
        from vibeteam.webhook.server import verify_sentry_signature

        secret = "sentry_secret"
        payload = b'{"action":"created","data":{}}'
        invalid_signature = "invalid"

        assert not verify_sentry_signature(payload, invalid_signature, secret)


# ==============================================================================
# Integration Tests
# ==============================================================================


@pytest.mark.integration
class TestGitHubAppIntegration:
    """Integration tests for GitHub App authentication (requires real credentials)."""

    def test_get_app_info_with_real_credentials(self):
        """Test getting app info with real GitHub App credentials (skip if not configured)."""
        app_id = os.environ.get("GITHUB_APP_ID")
        private_key = os.environ.get("GITHUB_APP_PRIVATE_KEY")

        if not app_id or not private_key:
            pytest.skip("GitHub App credentials not configured")

        info = github_app.get_app_info(app_id, private_key)
        assert "name" in info
        assert "id" in info
        assert str(info["id"]) == app_id

    def test_list_installations_with_real_credentials(self):
        """Test listing installations with real GitHub App credentials."""
        app_id = os.environ.get("GITHUB_APP_ID")
        private_key = os.environ.get("GITHUB_APP_PRIVATE_KEY")

        if not app_id or not private_key:
            pytest.skip("GitHub App credentials not configured")

        installations = github_app.list_installations(app_id, private_key)
        assert isinstance(installations, list)

    def test_github_connector_with_real_app_auth(self):
        """Test GitHubConnector with real GitHub App credentials."""
        app_id = os.environ.get("GITHUB_APP_ID")
        private_key = os.environ.get("GITHUB_APP_PRIVATE_KEY")
        installation_id = os.environ.get("GITHUB_APP_INSTALLATION_ID")

        if not app_id or not private_key or not installation_id:
            pytest.skip("GitHub App credentials not configured")

        connector = GitHubConnector(
            app_id=app_id,
            private_key=private_key,
            installation_id=installation_id,
        )

        # Test a simple API call
        # This will fail if the token is invalid
        headers = connector._headers()
        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Bearer ghs_")
