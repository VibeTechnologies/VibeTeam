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

import time

import jwt
import requests


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
    return jwt.encode(payload, private_key, algorithm="RS256")


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

    body = {}
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
