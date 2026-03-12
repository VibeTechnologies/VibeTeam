"""GitHub App authentication utilities for VibeTeam agents.

This module provides functions to generate GitHub App tokens for API authentication.
GitHub Apps are the recommended way for bots to authenticate with GitHub.

Usage:
    token = get_installation_token(
        app_id="123456",
        private_key=private_key_pem,
        installation_id="12345678"
    )
    # Use token for GitHub API calls
"""

import os
import re
import time

import jwt
import requests


def _normalize_private_key(private_key: str) -> str:
    if not private_key:
        return private_key
    normalized = private_key.replace("\\n", "\n")
    return normalized.replace("BEGIN_RSA_PRIVATE_KEY", "BEGIN RSA PRIVATE KEY").replace(
        "END_RSA_PRIVATE_KEY", "END RSA PRIVATE KEY"
    )


def generate_jwt(app_id: str, private_key: str) -> str:
    """Generate a JWT for GitHub App authentication.

    Args:
        app_id: The GitHub App ID.
        private_key: The private key in PEM format.

    Returns:
        A signed JWT string valid for 10 minutes.
    """
    now = int(time.time())
    payload = {
        "iat": now - 60,  # issued at (60s buffer for clock drift)
        "exp": now + 600,  # expires in 10 minutes (max allowed by GitHub)
        "iss": app_id,
    }
    normalized_key = _normalize_private_key(private_key)
    return jwt.encode(payload, normalized_key, algorithm="RS256")


def _normalize_role(role: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", role or "").strip("_")
    return cleaned.upper()


def get_role_app_credentials(role: str) -> tuple[str | None, str | None, str | None]:
    """Return GitHub App credentials for a specific agent role from env vars."""
    suffix = _normalize_role(role)
    if not suffix:
        return None, None, None
    return (
        os.environ.get(f"GITHUB_APP_ID_{suffix}"),
        os.environ.get(f"GITHUB_APP_PRIVATE_KEY_{suffix}"),
        os.environ.get(f"GITHUB_APP_INSTALLATION_ID_{suffix}"),
    )


def get_installation_token_for_role(role: str) -> str | None:
    """Return an installation token for a specific role.

    Role-scoped requests are strict: if role-specific credentials are missing,
    return None instead of falling back to global app credentials.
    """
    normalized_role = _normalize_role(role)
    app_id, private_key, installation_id = get_role_app_credentials(role)
    if app_id and private_key and installation_id:
        return get_installation_token(app_id, private_key, installation_id)

    # For explicit role requests, do not fall back to shared/global app creds.
    if normalized_role and normalized_role != "DEFAULT":
        return None

    default_app_id = os.environ.get("GITHUB_APP_ID")
    default_private_key = os.environ.get("GITHUB_APP_PRIVATE_KEY")
    default_installation_id = os.environ.get("GITHUB_APP_INSTALLATION_ID")
    if default_app_id and default_private_key and default_installation_id:
        return get_installation_token(default_app_id, default_private_key, default_installation_id)
    return None


def get_installation_token(
    app_id: str,
    private_key: str,
    installation_id: str,
    permissions: dict | None = None,
    repositories: list[str] | None = None,
) -> str:
    """Exchange JWT for an installation access token.

    Args:
        app_id: The GitHub App ID.
        private_key: The private key in PEM format.
        installation_id: The installation ID for the target org/repo.
        permissions: Optional dict to request specific permissions.
            Example: {"contents": "read", "issues": "write"}
        repositories: Optional list of repository names to scope the token to.

    Returns:
        An installation access token valid for 1 hour.

    Raises:
        requests.HTTPError: If the token exchange fails.
    """
    jwt_token = generate_jwt(app_id, private_key)

    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    body: dict = {}
    if permissions:
        body["permissions"] = permissions
    if repositories:
        body["repositories"] = repositories

    response = requests.post(url, headers=headers, json=body if body else None)
    response.raise_for_status()

    return response.json()["token"]


def get_app_info(app_id: str, private_key: str) -> dict:
    """Get information about the authenticated GitHub App.

    Useful for verifying App credentials are correct.

    Args:
        app_id: The GitHub App ID.
        private_key: The private key in PEM format.

    Returns:
        Dict containing app info including name, owner, and permissions.
    """
    jwt_token = generate_jwt(app_id, private_key)

    response = requests.get(
        "https://api.github.com/app",
        headers={
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    response.raise_for_status()
    return response.json()


def list_installations(app_id: str, private_key: str) -> list[dict]:
    """List all installations of the GitHub App.

    Useful for finding the installation_id for a specific org/repo.

    Args:
        app_id: The GitHub App ID.
        private_key: The private key in PEM format.

    Returns:
        List of installation objects.
    """
    jwt_token = generate_jwt(app_id, private_key)

    response = requests.get(
        "https://api.github.com/app/installations",
        headers={
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    response.raise_for_status()
    return response.json()
