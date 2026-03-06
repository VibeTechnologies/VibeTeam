#!/usr/bin/env python3
"""Check GitHub App permissions for VibeTeam role apps."""

from __future__ import annotations

import argparse
import os
import sys
from urllib.parse import quote
from typing import Iterable

import requests

from vibeteam.utils.github_app import get_app_info, get_installation_token, list_installations

ROLE_SUFFIXES = {
    "software_engineer": "SOFTWARE_ENGINEER",
    "support_engineer": "SUPPORT_ENGINEER",
    "release_engineer": "RELEASE_ENGINEER",
    "product_manager": "PRODUCT_MANAGER",
    "marketing_manager": "MARKETING_MANAGER",
}
DEFAULT_REPO = os.environ.get("GITHUB_TEST_REPO", "VibeTechnologies/vibeteam-eval-hello-world")


def _iter_roles(requested: Iterable[str] | None) -> list[str]:
    if not requested:
        return list(ROLE_SUFFIXES.keys())
    normalized = []
    for role in requested:
        role_key = role.strip().lower()
        if role_key in ROLE_SUFFIXES:
            normalized.append(role_key)
    return normalized


def _load_credentials(role: str) -> tuple[str | None, str | None, str | None]:
    suffix = ROLE_SUFFIXES[role]
    return (
        os.environ.get(f"GITHUB_APP_ID_{suffix}"),
        os.environ.get(f"GITHUB_APP_PRIVATE_KEY_{suffix}"),
        os.environ.get(f"GITHUB_APP_INSTALLATION_ID_{suffix}"),
    )


def _format_perm(value: str | None) -> str:
    return value if value else "missing"


def _repo_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _resolve_role_assignee(role: str) -> str:
    suffix = ROLE_SUFFIXES[role]
    return (
        os.environ.get(f"GITHUB_{suffix}_BOT_ASSIGNEE")
        or os.environ.get(f"GITHUB_APP_BOT_USERNAME_{suffix}")
        or os.environ.get(f"GITHUB_BOT_USERNAME_{suffix}")
        or ""
    ).strip()


def _check_assignee_assignable(repo: str, token: str, assignee: str) -> tuple[bool, str]:
    if not assignee:
        return False, "missing assignee env for role"

    encoded = quote(assignee, safe="")
    url = f"https://api.github.com/repos/{repo}/assignees/{encoded}"
    response = requests.get(url, headers=_repo_headers(token), timeout=20)
    if response.status_code == 204:
        return True, "assignable"

    message = ""
    try:
        message = response.json().get("message", "")
    except Exception:  # noqa: BLE001
        message = response.text[:160]
    detail = f" ({message})" if message else ""
    return False, f"not assignable status={response.status_code}{detail}"


def _validate_installation_for_repo(
    app_id: str,
    private_key: str,
    installation_id: str | None,
    repo: str | None,
) -> tuple[bool, str]:
    if not installation_id:
        return False, "missing installation_id env var"

    try:
        installations = list_installations(app_id, private_key)
    except Exception as exc:  # noqa: BLE001
        return False, f"failed listing installations ({exc})"

    matching = [i for i in installations if str(i.get("id")) == str(installation_id)]
    if not matching:
        known = ", ".join(str(i.get("id")) for i in installations if i.get("id")) or "none"
        return False, f"installation_id={installation_id} not found (known: {known})"

    if not repo:
        return True, "ok (repo check skipped)"

    try:
        installation_token = get_installation_token(app_id, private_key, installation_id)
    except Exception as exc:  # noqa: BLE001
        return False, f"failed creating installation token ({exc})"

    url = f"https://api.github.com/repos/{repo}"
    response = requests.get(url, headers=_repo_headers(installation_token), timeout=20)
    if response.status_code != 200:
        message = ""
        try:
            message = response.json().get("message", "")
        except Exception:  # noqa: BLE001
            message = response.text[:160]
        detail = f" ({message})" if message else ""
        return False, f"repo access status={response.status_code}{detail}"
    return True, "ok"


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
    parser.add_argument(
        "--repo",
        default=DEFAULT_REPO,
        help="owner/repo to verify installation token can access (default: GITHUB_TEST_REPO)",
    )
    parser.add_argument(
        "--skip-repo-check",
        action="store_true",
        help="Skip repo access verification and only validate installation ID presence",
    )
    parser.add_argument(
        "--require-assignable-assignee",
        action="store_true",
        help="Fail if role assignee env is missing or not assignable in --repo",
    )
    args = parser.parse_args()

    roles = _iter_roles(args.roles.split(",") if args.roles else None)
    if not roles:
        print("No valid roles provided")
        return 1

    exit_code = 0
    for role in roles:
        app_id, private_key, installation_id = _load_credentials(role)
        if not app_id or not private_key:
            print(f"{role}: missing GITHUB_APP_ID/PRIVATE_KEY credentials")
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

        install_ok, install_status = _validate_installation_for_repo(
            app_id,
            private_key,
            installation_id,
            None if args.skip_repo_check else args.repo,
        )
        assignee = _resolve_role_assignee(role)
        assignee_status = "skipped"
        assignee_ok = True
        if args.require_assignable_assignee:
            if args.skip_repo_check:
                assignee_status = "skipped (repo check disabled)"
            else:
                try:
                    installation_token = get_installation_token(app_id, private_key, installation_id or "")
                    assignee_ok, assignee_status = _check_assignee_assignable(
                        args.repo,
                        installation_token,
                        assignee,
                    )
                except Exception as exc:  # noqa: BLE001
                    assignee_ok = False
                    assignee_status = f"check failed ({exc})"
        print(
            f"{role}: discussions={discussions}, issues={issues}, "
            f"pull_requests={pulls}, contents={contents}, "
            f"installation_id={installation_id or 'missing'}, installation={install_status}, "
            f"assignee={assignee or 'missing'}, assignee_check={assignee_status}"
        )

        if args.require_discussions and discussions != "write":
            exit_code = 1
        if not install_ok:
            exit_code = 1
        if args.require_assignable_assignee and not assignee_ok:
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
