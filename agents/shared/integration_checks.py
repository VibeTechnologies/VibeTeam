from __future__ import annotations

import logging
import os
from pathlib import Path

from agents.shared.gmail_tools import DEFAULT_CREDENTIALS_PATH, DEFAULT_TOKEN_PATH

logger = logging.getLogger(__name__)


def _github_configured() -> bool:
    if os.environ.get("GITHUB_TOKEN"):
        return True
    if all(
        os.environ.get(k)
        for k in ("GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY", "GITHUB_APP_INSTALLATION_ID")
    ):
        return True
    # Role-scoped GitHub App credentials
    app_ids = {
        key.split("GITHUB_APP_ID_", 1)[1]
        for key in os.environ
        if key.startswith("GITHUB_APP_ID_")
    }
    for suffix in app_ids:
        if all(
            os.environ.get(k)
            for k in (
                f"GITHUB_APP_ID_{suffix}",
                f"GITHUB_APP_PRIVATE_KEY_{suffix}",
                f"GITHUB_APP_INSTALLATION_ID_{suffix}",
            )
        ):
            return True
    return False


def _gmail_paths() -> tuple[Path, Path]:
    creds = Path(os.environ.get("GMAIL_CREDENTIALS_PATH", DEFAULT_CREDENTIALS_PATH))
    token = Path(os.environ.get("GMAIL_TOKEN_PATH", DEFAULT_TOKEN_PATH))
    return creds, token


def validate_required_integrations(service_name: str) -> None:
    """Fail fast when required integrations are not configured.

    This should be called at service startup so missing integrations are
    obvious and block execution instead of producing silent partial output.
    """
    missing: list[str] = []

    if not os.environ.get("SENTRY_AUTH_TOKEN"):
        missing.append("SENTRY_AUTH_TOKEN (Sentry API auth token)")

    if not _github_configured():
        missing.append(
            "GITHUB_TOKEN or (GITHUB_APP_ID + GITHUB_APP_PRIVATE_KEY + GITHUB_APP_INSTALLATION_ID)"
        )

    creds_path, token_path = _gmail_paths()
    gmail_missing = []
    if not creds_path.exists():
        gmail_missing.append(f"GMAIL_CREDENTIALS_PATH missing: {creds_path}")
    if not token_path.exists():
        gmail_missing.append(f"GMAIL_TOKEN_PATH missing: {token_path}")
    if gmail_missing:
        missing.extend(gmail_missing)

    if missing:
        details = "\n- ".join(missing)
        raise RuntimeError(
            f"[{service_name}] Required integrations not configured:\n- {details}\n"
            "Service will not start until these are provided."
        )
