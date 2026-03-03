#!/usr/bin/env python3
"""Check GitHub App permissions for VibeTeam role apps."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Iterable

from vibeteam.utils.github_app import get_app_info

ROLE_SUFFIXES = {
    "software_engineer": "SOFTWARE_ENGINEER",
    "support_engineer": "SUPPORT_ENGINEER",
    "release_engineer": "RELEASE_ENGINEER",
    "product_manager": "PRODUCT_MANAGER",
    "marketing_manager": "MARKETING_MANAGER",
}


def _iter_roles(requested: Iterable[str] | None) -> list[str]:
    if not requested:
        return list(ROLE_SUFFIXES.keys())
    normalized = []
    for role in requested:
        role_key = role.strip().lower()
        if role_key in ROLE_SUFFIXES:
            normalized.append(role_key)
    return normalized


def _load_credentials(role: str) -> tuple[str | None, str | None]:
    suffix = ROLE_SUFFIXES[role]
    return (
        os.environ.get(f"GITHUB_APP_ID_{suffix}"),
        os.environ.get(f"GITHUB_APP_PRIVATE_KEY_{suffix}"),
    )


def _format_perm(value: str | None) -> str:
    return value if value else "missing"


def main() -> int:
    parser = argparse.ArgumentParser(description="Check GitHub App permissions for role bots")
    parser.add_argument(
        "--roles",
        help="Comma-separated roles to check (default: all roles)",
    )
    parser.add_argument(
        "--require-discussions",
        action="store_true",
        help="Fail if Discussions permission is not write",
    )
    args = parser.parse_args()

    roles = _iter_roles(args.roles.split(",") if args.roles else None)
    if not roles:
        print("No valid roles provided")
        return 1

    exit_code = 0
    for role in roles:
        app_id, private_key = _load_credentials(role)
        if not app_id or not private_key:
            print(f"{role}: missing GITHUB_APP_ID/PRIVATE_KEY")
            exit_code = 1
            continue

        try:
            info = get_app_info(app_id, private_key)
        except Exception as exc:  # noqa: BLE001 - surface app auth failures
            print(f"{role}: failed to fetch app info ({exc})")
            exit_code = 1
            continue

        permissions = info.get("permissions", {}) if isinstance(info, dict) else {}
        discussions = _format_perm(permissions.get("discussions"))
        issues = _format_perm(permissions.get("issues"))
        pulls = _format_perm(permissions.get("pull_requests"))
        contents = _format_perm(permissions.get("contents"))

        print(
            f"{role}: discussions={discussions}, issues={issues}, "
            f"pull_requests={pulls}, contents={contents}"
        )

        if args.require_discussions and discussions != "write":
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
