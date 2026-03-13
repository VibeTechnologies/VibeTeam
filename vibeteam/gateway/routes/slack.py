"""
Slack Event Handlers.

Handles Slack events and routes to agent microservices:
- app_mention: Respond to @VibeTeam mentions in channels
- message.im: Respond to direct messages

Uses the Router for /RoleName mention-based routing.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import threading
import time
from typing import Any, cast

import httpx
import yaml
from fastapi import APIRouter, Header, HTTPException, Request

from agent_service.shared.role_resolver import (
    ROLE_MENTION_MAP,
    ROLE_PATTERN,
    get_display_name,
)
from vibeteam.agents_config import get_slack_handle, list_agents
from vibeteam.gateway.server import call_agent_service, call_agent_service_async, config
from vibeteam.router import Router
from vibeteam.router.models import AgentRole, route_by_keywords

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Slack"])


# ==============================================================================
# Rate Limiter for trigger endpoint
# ==============================================================================


class TokenBucketRateLimiter:
    """
    Thread-safe token bucket rate limiter.

    Allows `max_requests` per `window_seconds`. Tokens refill continuously.
    """

    def __init__(self, max_requests: int = 30, window_seconds: float = 60.0):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._tokens = float(max_requests)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def allow(self) -> bool:
        """Return True if the request is allowed, False if rate limited."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(
                self.max_requests,
                self._tokens + elapsed * (self.max_requests / self.window_seconds),
            )
            self._last_refill = now

            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False

    def reset(self) -> None:
        """Reset the rate limiter (for testing)."""
        with self._lock:
            self._tokens = float(self.max_requests)
            self._last_refill = time.monotonic()


# Rate limiter for /slack/trigger (configurable via env vars)
_trigger_rate_limiter = TokenBucketRateLimiter(
    max_requests=int(os.environ.get("TRIGGER_RATE_LIMIT_MAX", "30")),
    window_seconds=float(os.environ.get("TRIGGER_RATE_LIMIT_WINDOW", "60")),
)


def _parse_handoff_roles(response: str, source_role: str) -> list[str]:
    """Parse handoff roles, allowing bare role names in handoff phrasing.

    Falls back to detecting lines like "SoftwareEngineer please ..." when @mentions
    are missing, while avoiding self-handoffs.
    """
    message_router = get_message_router()
    explicit = message_router.parse_role_mentions(response)
    if explicit:
        return explicit

    aliases: dict[str, str] = {}
    roles = sorted(set(ROLE_MENTION_MAP.values()))
    for role in roles:
        display = get_display_name(role)
        slack_handle = get_slack_handle(role)
        spaced = re.sub(r"(?<!^)([A-Z])", r" \1", display)
        for alias in {display, spaced, slack_handle}:
            if not alias:
                continue
            aliases[alias.lower()] = role

    if not aliases:
        return []

    alias_pattern = "|".join(re.escape(alias) for alias in aliases.keys())
    if not alias_pattern:
        return []

    direct_re = re.compile(rf"(?i)^(?:[-*•]\s*)?@?({alias_pattern})\b")
    keyword_re = re.compile(
        r"(?i)\b(handoff|hand\s+off|handover|assign|route|ping|please|need|can\s+you|could\s+you)\b"
    )
    roles: list[str] = []
    for line in response.splitlines():
        clean = line.strip()
        if not clean:
            continue
        clean = re.sub(r"^\[[^\]]+\]\s*", "", clean)

        direct = direct_re.match(clean)
        if direct:
            role = aliases.get(direct.group(1).lower())
            if role and role != source_role and role not in roles:
                roles.append(role)
            continue

        if keyword_re.search(clean):
            for match in re.finditer(rf"(?i)\b({alias_pattern})\b", clean):
                role = aliases.get(match.group(1).lower())
                if role and role != source_role and role not in roles:
                    roles.append(role)
    return roles


def _extract_handoff_snippet(response: str, role_display: str) -> str:
    """Extract a concise handoff request line for the target role."""
    lines = response.splitlines()
    spaced = re.sub(r"(?<!^)([A-Z])", r" \1", role_display)
    alias_pattern = "|".join({re.escape(role_display), re.escape(spaced)})
    role_pattern = re.compile(rf"(?i)@?(?:{alias_pattern})\b")
    for idx, line in enumerate(lines):
        if role_pattern.search(line):
            snippet = [line.strip()]
            # Include immediate bullet/indented follow-ups if present.
            for j in range(idx + 1, len(lines)):
                next_line = lines[j]
                if not next_line.strip():
                    break
                if next_line.lstrip().startswith(("-", "•", "*")) or next_line.startswith("  "):
                    snippet.append(next_line.strip())
                    continue
                break
            return "\n".join(snippet).strip()
    # Fallback: first few lines to keep context minimal.
    return "\n".join(line.strip() for line in lines[:6] if line.strip())


def _extract_sentry_urls(text: str) -> list[str]:
    pattern = re.compile(r"https?://[^\s>]*sentry\.io/issues/\d+/?", re.IGNORECASE)
    urls = pattern.findall(text)
    seen: set[str] = set()
    unique: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def _extract_pr_urls(text: str) -> list[str]:
    pattern = re.compile(r"https?://github\.com/\S+/pull/\d+", re.IGNORECASE)
    urls = pattern.findall(text or "")
    seen: set[str] = set()
    unique: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def _extract_repo_reference(text: str) -> str | None:
    sentry_project_patterns = [
        (r"\bvibebrowserextension\b", "VibeTechnologies/VibeWebAgent"),
        (r"\bvibe[-_ ]?api[-_ ]?gateway\b", "VibeTechnologies/VibeWebAgent"),
    ]
    alias_patterns = [
        (r"vibe[-_ ]?browser[-_ ]?extension", "VibeTechnologies/VibeWebAgent"),
        (r"vibe[-_ ]?api[-_ ]?gateway", "VibeTechnologies/VibeWebAgent"),
        (r"vibe[-_ ]?web[-_ ]?agent", "VibeTechnologies/VibeWebAgent"),
        (r"vibeteam", "VibeTechnologies/VibeTeam"),
    ]
    patterns = [
        r"Repository:\s*([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)",
        r"\brepository\s+([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)",
        r"\brepo[:\s]+([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)",
        r"github\\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip().rstrip(").,")

    lowered = text.lower()
    for pattern, repo in sentry_project_patterns:
        if re.search(pattern, lowered):
            return repo
    if "repo" in lowered or "repository" in lowered:
        for pattern, repo in alias_patterns:
            if re.search(pattern, lowered):
                return repo
    return None


def _format_callback_error(payload: dict[str, Any], job_id: str) -> str:
    """Extract a user-facing callback error message from callback payload fields."""
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    candidates: list[Any] = [
        payload.get("error"),
        payload.get("detail"),
        metadata.get("error"),
        metadata.get("detail"),
    ]
    ignored = {"", "none", "null", "unknown error", '""', "''"}
    for value in candidates:
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            text = json.dumps(value, ensure_ascii=False).strip()
        else:
            text = str(value).strip()
        if text and text.lower() not in ignored:
            return text

    if job_id and job_id != "unknown":
        return (
            "No error details were returned by the agent service "
            f"(job_id={job_id}). Please check service logs."
        )
    return "No error details were returned by the agent service. Please check service logs."


_TRANSIENT_OVERLOAD_MARKERS = (
    "temporarily overloaded",
    "try again in a moment",
    "rate limit",
    "too many requests",
    "service unavailable",
    "upstream request timeout",
    "gateway timeout",
)


def _is_transient_overload_error_text(text: str) -> bool:
    """Return True when callback/service error text looks transient and retryable."""
    normalized = (text or "").strip().lower()
    if not normalized:
        return False
    return any(marker in normalized for marker in _TRANSIENT_OVERLOAD_MARKERS)


def split_long_message(text: str, max_chunk_size: int = 2900) -> list[str]:
    """
    Split a long message into chunks, trying to break at newlines or spaces.

    Args:
        text: The text to split
        max_chunk_size: Maximum size of each chunk (default 2900)

    Returns:
        List of text chunks
    """
    if len(text) <= max_chunk_size:
        return [text]

    chunks = []
    remaining = text
    while remaining:
        if len(remaining) <= max_chunk_size:
            chunks.append(remaining)
            break

        # Try to find a good break point (newline) within the chunk size
        break_point = remaining.rfind("\n", 0, max_chunk_size)
        if break_point == -1 or break_point < max_chunk_size // 2:
            # No good newline break, try space
            break_point = remaining.rfind(" ", 0, max_chunk_size)
        if break_point == -1 or break_point < max_chunk_size // 2:
            # No good break point, just cut at max size
            break_point = max_chunk_size

        chunks.append(remaining[:break_point])
        remaining = remaining[break_point:].lstrip()

    return chunks


# Message router for /RoleName parsing
_message_router: Router | None = None


# ==============================================================================
# Slack Event Deduplication
# ==============================================================================


_SLACK_EVENT_TTL_SECONDS = 15 * 60
_SLACK_EVENT_MAX_ENTRIES = 4096
_slack_event_seen: dict[str, float] = {}
_slack_event_lock = threading.Lock()

# Thread-scoped kubeconfig context captured from Slack file attachments.
_KUBECONFIG_CONTEXT_TTL_SECONDS = int(
    os.environ.get("SLACK_KUBECONFIG_CONTEXT_TTL_SECONDS", str(12 * 60 * 60))
)
_KUBECONFIG_MAX_BYTES = int(os.environ.get("SLACK_KUBECONFIG_MAX_BYTES", "65536"))
_thread_kubeconfig_contexts: dict[str, dict[str, Any]] = {}
_thread_kubeconfig_lock = threading.Lock()


def _slack_event_key(payload: dict[str, Any], event: dict[str, Any]) -> str | None:
    """Build a stable dedup key for a Slack event."""
    event_id = payload.get("event_id")
    if event_id:
        return f"id:{event_id}"

    channel = event.get("channel")
    event_ts = event.get("ts") or payload.get("event_time")
    if channel and event_ts:
        return f"fallback:{channel}:{event_ts}"

    return None


def _is_duplicate_slack_event(key: str | None) -> bool:
    """Return True if we've already processed this Slack event."""
    if not key:
        return False

    now = time.monotonic()
    with _slack_event_lock:
        # Prune expired entries
        expired = [k for k, ts in _slack_event_seen.items() if now - ts > _SLACK_EVENT_TTL_SECONDS]
        for k in expired:
            _slack_event_seen.pop(k, None)

        if key in _slack_event_seen:
            return True

        _slack_event_seen[key] = now

        # Bound cache size (drop oldest)
        if len(_slack_event_seen) > _SLACK_EVENT_MAX_ENTRIES:
            oldest = sorted(_slack_event_seen.items(), key=lambda item: item[1])[
                : len(_slack_event_seen) - _SLACK_EVENT_MAX_ENTRIES
            ]
            for k, _ in oldest:
                _slack_event_seen.pop(k, None)

    return False


def _schedule_background(coro: Any) -> None:
    """Schedule background work for Slack events."""
    asyncio.create_task(coro)


def _slack_thread_context_key(channel: str, thread_ts: str) -> str:
    """Build an in-memory key for thread-scoped Slack context."""
    return f"{channel}:{thread_ts}"


def _prune_kubeconfig_contexts(now: float | None = None) -> None:
    """Prune expired thread kubeconfig context entries."""
    cutoff = (now or time.monotonic()) - _KUBECONFIG_CONTEXT_TTL_SECONDS
    expired = [
        key
        for key, value in _thread_kubeconfig_contexts.items()
        if value.get("stored_at", 0.0) < cutoff
    ]
    for key in expired:
        _thread_kubeconfig_contexts.pop(key, None)


def _store_thread_kubeconfig_context(
    channel: str,
    thread_ts: str,
    context: dict[str, Any],
) -> None:
    """Store validated kubeconfig context for a Slack thread."""
    if not channel or not thread_ts:
        return
    with _thread_kubeconfig_lock:
        _prune_kubeconfig_contexts()
        _thread_kubeconfig_contexts[_slack_thread_context_key(channel, thread_ts)] = {
            **context,
            "stored_at": time.monotonic(),
        }


def _get_thread_kubeconfig_context(channel: str, thread_ts: str | None) -> dict[str, Any] | None:
    """Get validated kubeconfig context for a Slack thread if available."""
    if not channel or not thread_ts:
        return None
    with _thread_kubeconfig_lock:
        _prune_kubeconfig_contexts()
        value = _thread_kubeconfig_contexts.get(_slack_thread_context_key(channel, thread_ts))
        if not value:
            return None
        return {k: v for k, v in value.items() if k != "stored_at"}


def _is_cluster_config_request(text: str) -> bool:
    """Return True when message text suggests kubeconfig or k8s cluster work."""
    lowered = (text or "").lower()
    keywords = [
        "kubeconfig",
        "k3s",
        "k8s",
        "kubernetes",
        "cluster config",
        "cluster health",
        "kubectl",
        "namespace",
        "vibe cluster",
        "vibe namespace",
    ]
    return any(keyword in lowered for keyword in keywords)


def _looks_like_kubeconfig_file(file_info: dict[str, Any]) -> bool:
    """Heuristic check for kubeconfig-like Slack file metadata."""
    name = str(file_info.get("name", "")).lower()
    filetype = str(file_info.get("filetype", "")).lower()
    mimetype = str(file_info.get("mimetype", "")).lower()
    return (
        "kubeconfig" in name
        or name.endswith((".kubeconfig", ".yaml", ".yml", ".conf", ".config"))
        or filetype in {"yaml", "yml", "conf", "config", "text"}
        or mimetype in {"application/x-yaml", "text/yaml", "text/x-yaml", "text/plain"}
    )


async def _fetch_slack_file_info(file_id: str, bot_token: str) -> dict[str, Any] | None:
    """Fetch Slack file metadata from files.info when event payload is partial."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://slack.com/api/files.info",
                headers={"Authorization": f"Bearer {bot_token}"},
                params={"file": file_id},
                timeout=20.0,
            )
            payload = response.json()
            if not payload.get("ok"):
                logger.warning("Slack files.info failed for %s: %s", file_id, payload.get("error"))
                return None
            file_obj = payload.get("file")
            return file_obj if isinstance(file_obj, dict) else None
    except Exception as exc:
        logger.warning("Failed to fetch Slack file metadata for %s: %s", file_id, exc)
        return None


async def _download_slack_file_text(url: str, bot_token: str) -> str:
    """Download private Slack file content as text."""
    async with httpx.AsyncClient(follow_redirects=True) as client:
        response = await client.get(
            url,
            headers={"Authorization": f"Bearer {bot_token}"},
            timeout=30.0,
        )
        response.raise_for_status()
        return response.text


def _validate_and_normalize_kubeconfig(raw_content: str) -> dict[str, Any]:
    """Validate kubeconfig YAML and return normalized context payload.

    Rejects unsafe kubeconfigs that rely on exec-based auth plugins.
    """
    raw_bytes = raw_content.encode("utf-8")
    if not raw_content.strip():
        raise ValueError("empty file")
    if len(raw_bytes) > _KUBECONFIG_MAX_BYTES:
        raise ValueError(f"file exceeds {_KUBECONFIG_MAX_BYTES} bytes; upload a minimal kubeconfig")

    parsed = yaml.safe_load(raw_content)
    if not isinstance(parsed, dict):
        raise ValueError("expected a YAML mapping")

    kind = str(parsed.get("kind", "Config"))
    if kind != "Config":
        raise ValueError(f"unexpected kubeconfig kind '{kind}'")

    clusters = parsed.get("clusters")
    users = parsed.get("users")
    contexts = parsed.get("contexts")
    if not isinstance(clusters, list) or not clusters:
        raise ValueError("missing clusters")
    if not isinstance(users, list) or not users:
        raise ValueError("missing users")
    if not isinstance(contexts, list) or not contexts:
        raise ValueError("missing contexts")

    for user_entry in users:
        if not isinstance(user_entry, dict):
            continue
        user_config = user_entry.get("user")
        if isinstance(user_config, dict) and "exec" in user_config:
            raise ValueError("exec auth plugins are not supported; provide static credentials")

    cluster_names = [
        c.get("name")
        for c in clusters
        if isinstance(c, dict) and isinstance(c.get("name"), str) and c.get("name")
    ]
    context_names = [
        c.get("name")
        for c in contexts
        if isinstance(c, dict) and isinstance(c.get("name"), str) and c.get("name")
    ]
    current_context = parsed.get("current-context")
    normalized_yaml = yaml.safe_dump(parsed, sort_keys=False).strip()
    if not normalized_yaml:
        raise ValueError("could not normalize kubeconfig")

    return {
        "kubeconfig_yaml": normalized_yaml,
        "cluster_names": cluster_names,
        "context_names": context_names,
        "current_context": str(current_context or ""),
    }


async def _extract_kubeconfig_context_from_event(
    event: dict[str, Any],
    *,
    request_text: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Extract and validate kubeconfig attachment context from a Slack event."""
    files = event.get("files")
    if not isinstance(files, list) or not files:
        return None, None

    request_is_cluster_related = _is_cluster_config_request(request_text)
    candidate_files: list[dict[str, Any]] = []
    for file_obj in files:
        if not isinstance(file_obj, dict):
            continue
        if request_is_cluster_related or _looks_like_kubeconfig_file(file_obj):
            candidate_files.append(file_obj)

    if not candidate_files:
        return None, None

    bot_token = _resolve_slack_bot_token()
    if not bot_token:
        return None, "gateway Slack token is not configured to read file attachments"

    errors: list[str] = []

    for file_obj in candidate_files:
        info = file_obj
        file_id = str(info.get("id", "")).strip()
        if file_id and not info.get("url_private_download"):
            fetched = await _fetch_slack_file_info(file_id, bot_token)
            if fetched:
                info = fetched

        file_name = str(info.get("name", "uploaded-kubeconfig"))
        file_size = int(info.get("size", 0) or 0)
        if file_size > _KUBECONFIG_MAX_BYTES:
            errors.append(
                f"`{file_name}` exceeds {_KUBECONFIG_MAX_BYTES} bytes; upload a smaller kubeconfig"
            )
            continue

        download_url = str(
            info.get("url_private_download", "") or info.get("url_private", "")
        ).strip()
        if not download_url:
            errors.append(f"`{file_name}` is missing a downloadable URL")
            continue

        try:
            content = await _download_slack_file_text(download_url, bot_token)
        except Exception as exc:
            errors.append(f"failed to download `{file_name}` ({exc})")
            continue

        try:
            context = _validate_and_normalize_kubeconfig(content)
        except ValueError as exc:
            errors.append(f"`{file_name}` is not a valid kubeconfig ({exc})")
            continue

        return {
            **context,
            "file_name": file_name,
            "source": "slack_file",
        }, None

    reason = "; ".join(errors[:2]) if errors else "no valid kubeconfig attachment found"
    return None, reason


def _build_kubeconfig_instructions(context: dict[str, Any]) -> str:
    """Render a compact instruction block injected into agent task text."""
    kubeconfig_yaml = str(context.get("kubeconfig_yaml", "")).strip()
    file_name = str(context.get("file_name", "uploaded-kubeconfig"))
    cluster_names = context.get("cluster_names", [])
    current_context = str(context.get("current_context", "")).strip()
    cluster_summary = ", ".join(cluster_names) if cluster_names else "unknown"
    current_summary = current_context or "not set"

    return (
        "### Attached Kubeconfig Context (from Slack file upload)\n"
        f"- Source file: {file_name}\n"
        f"- Cluster names: {cluster_summary}\n"
        f"- Current context: {current_summary}\n"
        "- This kubeconfig was validated by gateway (no exec auth plugin).\n"
        "- Use it for vibe/k3s cluster checks in this thread.\n"
        "- Write it to /tmp/vibe-k3s.config and run kubectl with "
        "`KUBECONFIG=/tmp/vibe-k3s.config`.\n\n"
        "KUBECONFIG_YAML_START\n"
        f"{kubeconfig_yaml}\n"
        "KUBECONFIG_YAML_END"
    )


def _inject_thread_kubeconfig_context(
    user_message: str,
    channel: str,
    thread_ts: str | None,
) -> str:
    """Append thread kubeconfig context for cluster-related requests."""
    if not _is_cluster_config_request(user_message):
        return user_message

    context = _get_thread_kubeconfig_context(channel, thread_ts)
    if not context:
        return user_message

    instruction_block = _build_kubeconfig_instructions(context)
    return f"{user_message.rstrip()}\n\n{instruction_block}".strip()


def _build_kubeconfig_setup_confirmation(channel: str, thread_ts: str | None) -> str:
    """Build deterministic confirmation text for kubeconfig-setup-only requests."""
    context = _get_thread_kubeconfig_context(channel, thread_ts)
    if context:
        current_context = str(context.get("current_context", "")).strip()
        cluster_names = context.get("cluster_names") or []
        cluster_hint = str(cluster_names[0]) if cluster_names else "unknown-cluster"
        context_hint = current_context or cluster_hint
        return (
            f"Kubeconfig setup complete for this thread (context: `{context_hint}`). "
            "I have not run health checks yet."
        )

    return (
        "I did not find a validated kubeconfig context for this thread yet. "
        "Please attach a kubeconfig file and I will configure it first. "
        "I have not run health checks yet."
    )


def get_message_router() -> Router:
    """Get or create the message router."""
    global _message_router
    if _message_router is None:
        _message_router = Router()
    return _message_router


def verify_slack_signature(
    payload: bytes,
    timestamp: str,
    signature: str,
    secret: str,
) -> bool:
    """Verify Slack request signature."""
    if not secret:
        logger.error("SLACK_SIGNING_SECRET is not configured")
        return False

    if not signature or not timestamp:
        return False

    # Check timestamp to prevent replay attacks (5 minute window)
    if abs(time.time() - int(timestamp)) > 60 * 5:
        logger.warning("Slack request timestamp too old")
        return False

    # Compute expected signature
    sig_basestring = f"v0:{timestamp}:{payload.decode('utf-8')}"
    expected = (
        "v0=" + hmac.new(secret.encode(), sig_basestring.encode(), hashlib.sha256).hexdigest()
    )

    return hmac.compare_digest(expected, signature)


def _role_env_suffix(role: str | None) -> str | None:
    """Convert a role key like support_engineer to env suffix SUPPORT_ENGINEER."""
    if not role:
        return None
    role_text = role.strip()
    if role_text.startswith("@") or role_text.startswith("/"):
        role_text = role_text[1:]
    # Support CamelCase handles (e.g. SoftwareEngineer) and snake/kebab/space variants.
    role_text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", role_text)
    normalized = re.sub(r"[^A-Z0-9]+", "_", role_text.upper()).strip("_")
    return normalized or None


def _get_role_scoped_env(prefix: str, role: str | None) -> str:
    """Get role-scoped env var value (e.g., SLACK_BOT_TOKEN_SUPPORT_ENGINEER)."""
    suffix = _role_env_suffix(role)
    if not suffix:
        return ""
    return os.environ.get(f"{prefix}_{suffix}", "")


def _resolve_slack_bot_token(role: str | None = None) -> str:
    """Resolve Slack bot token for a specific role, with global fallback."""
    return _get_role_scoped_env("SLACK_BOT_TOKEN", role) or config.SLACK_BOT_TOKEN


def _resolve_slack_reply_bot_token(role: str | None = None) -> str:
    """Resolve bot token for reply posting.

    Reply posting must use role-scoped app identity when a role is provided.
    Ingress token is reserved for ingress-only/system paths where no role is set.
    """
    if role:
        return _get_role_scoped_env("SLACK_BOT_TOKEN", role)
    return config.SLACK_BOT_TOKEN


def _resolve_slack_assistant_token(role: str | None = None) -> str:
    """Resolve Assistant API token.

    Role-scoped operations stay role-scoped:
    role assistant token -> role bot token.
    Ingress/global assistant token is used only when role is not provided.
    """
    if role:
        return _get_role_scoped_env("SLACK_ASSISTANT_TOKEN", role) or _get_role_scoped_env(
            "SLACK_BOT_TOKEN", role
        )
    return config.SLACK_ASSISTANT_TOKEN or config.SLACK_BOT_TOKEN


def _collect_slack_bot_tokens() -> list[str]:
    """Collect all configured Slack bot tokens (default + role-scoped), deduplicated."""
    ordered: list[str] = []
    seen: set[str] = set()
    for token in [
        config.SLACK_BOT_TOKEN,
        *[
            _get_role_scoped_env("SLACK_BOT_TOKEN", role)
            for role in sorted(set(ROLE_MENTION_MAP.values()))
        ],
    ]:
        if token and token not in seen:
            seen.add(token)
            ordered.append(token)
    return ordered


async def _role_bot_user_ids() -> dict[str, str]:
    """Map Slack user IDs to roles for role-scoped bot tokens.

    Uses only role-scoped bot tokens to avoid conflating ingress token identity
    with role bot identities when global fallback is configured.
    """
    user_id_to_role: dict[str, str] = {}
    for role in sorted(set(ROLE_MENTION_MAP.values())):
        token = _get_role_scoped_env("SLACK_BOT_TOKEN", role)
        if not token:
            continue
        user_id = await get_bot_user_id(token=token)
        if user_id:
            user_id_to_role[user_id] = role
    return user_id_to_role


async def _our_bot_user_ids() -> set[str]:
    """Collect Slack user IDs for ingress + role-scoped bot tokens."""
    bot_ids: set[str] = set()
    for token in _collect_slack_bot_tokens():
        user_id = await get_bot_user_id(token=token)
        if user_id:
            bot_ids.add(user_id)
    return bot_ids


async def _extract_roles_from_slack_user_mentions(text: str) -> list[str]:
    """Extract roles referenced via Slack user mention syntax (<@U...>)."""
    if not text:
        return []

    user_mentions = re.findall(r"<@([A-Z0-9]+)>", text)
    if not user_mentions:
        return []

    user_id_to_role = await _role_bot_user_ids()
    roles: list[str] = []
    for user_id in user_mentions:
        role = user_id_to_role.get(user_id)
        if role and role not in roles:
            roles.append(role)
    return roles


# ---------------------------------------------------------------------------
# Role mention → Slack <@U...> replacement for outgoing messages
# ---------------------------------------------------------------------------

_role_to_uid_cache: dict[str, str] | None = None
_role_to_uid_lock = asyncio.Lock()


async def _get_role_to_slack_uid() -> dict[str, str]:
    """Lazily resolve role → Slack bot user_id mapping (cached)."""
    global _role_to_uid_cache
    if _role_to_uid_cache is not None:
        return _role_to_uid_cache

    async with _role_to_uid_lock:
        if _role_to_uid_cache is not None:
            return _role_to_uid_cache

        uid_to_role = await _role_bot_user_ids()
        _role_to_uid_cache = {role: uid for uid, role in uid_to_role.items()}
        if _role_to_uid_cache:
            logger.info(
                "Resolved role→Slack UID mapping: %s",
                {r: u for r, u in _role_to_uid_cache.items()},
            )
        return _role_to_uid_cache


async def _replace_role_mentions_in_outgoing(text: str) -> str:
    """Replace @RoleName patterns with <@U_BOT_ID> Slack mentions in outgoing text.

    When an agent writes ``@SoftwareEngineer please investigate``, this function
    converts it to ``<@U_SOFTWARE_ENGINEER_BOT_ID> please investigate`` so Slack
    renders it as a real clickable mention — making agents communicate like a team.
    """
    if not text:
        return text

    uid_map = await _get_role_to_slack_uid()
    if not uid_map:
        return text

    def _sub(match: re.Match) -> str:
        key = match.group(1).lower()
        role = ROLE_MENTION_MAP.get(key)
        if role and role in uid_map:
            return f"<@{uid_map[role]}>"
        return match.group(0)

    return ROLE_PATTERN.sub(_sub, text)


async def _resolve_explicit_role_for_text(text: str) -> str | None:
    """Resolve first explicit role mentioned in plain or Slack user-mention form."""
    if not text:
        return None

    message_router = get_message_router()
    parsed_roles = message_router.parse_role_mentions(text)
    if parsed_roles:
        return parsed_roles[0]

    user_mention_roles = await _extract_roles_from_slack_user_mentions(text)
    if user_mention_roles:
        return user_mention_roles[0]

    return None


async def _mentions_ingress_bot(text: str) -> bool:
    """Return True when message explicitly mentions ingress bot (<@U...>)."""
    ingress_user_id = await get_bot_user_id()
    if not ingress_user_id:
        return False
    return f"<@{ingress_user_id}>" in (text or "")


async def send_slack_message(
    channel: str,
    text: str,
    thread_ts: str | None = None,
    *,
    role: str | None = None,
) -> str | None:
    """Send a message to Slack.

    Returns:
        The message timestamp (ts) on success, None on failure.
    """
    bot_token = _resolve_slack_reply_bot_token(role)
    if not bot_token:
        if role:
            logger.error(
                "Missing role-scoped SLACK_BOT_TOKEN for role %s; refusing ingress fallback",
                role,
            )
        else:
            logger.warning("SLACK_BOT_TOKEN not set, cannot send message")
        return None

    try:
        # Replace @RoleName text with <@U_BOT_ID> Slack mentions so agents
        # communicate with real clickable handles visible in the channel.
        text = await _replace_role_mentions_in_outgoing(text)

        payload: dict[str, Any] = {
            "channel": channel,
            "text": text,
        }
        if thread_ts:
            payload["thread_ts"] = thread_ts

        async def _post_message_with_token(token: str) -> dict[str, Any]:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://slack.com/api/chat.postMessage",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                data = response.json()
                if isinstance(data, dict):
                    return cast(dict[str, Any], data)
                return {"ok": False, "error": "invalid_response"}

        result = await _post_message_with_token(bot_token)
        if result.get("ok"):
            logger.info(f"Sent message to {channel}")
            return cast(str | None, result.get("ts"))

        error_code = cast(str, result.get("error") or "unknown_error")
        logger.error(f"Slack API error: {error_code}")
        return None

    except Exception as e:
        logger.exception(f"Failed to send Slack message: {e}")
        return None


async def update_slack_message(
    channel: str,
    ts: str,
    text: str,
    *,
    role: str | None = None,
) -> bool:
    """Update an existing Slack message using chat.update.

    Uses blocks to avoid showing the '(edited)' indicator in Slack.

    Returns:
        True if the update succeeded.
    """
    bot_token = _resolve_slack_reply_bot_token(role)
    if not bot_token:
        if role:
            logger.error("Missing role-scoped SLACK_BOT_TOKEN for role %s; cannot update message", role)
        else:
            logger.warning("SLACK_BOT_TOKEN not set, cannot update message")
        return False

    try:
        payload: dict[str, Any] = {
            "channel": channel,
            "ts": ts,
            "text": text,  # Fallback for notifications
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": text},
                }
            ],
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://slack.com/api/chat.update",
                headers={
                    "Authorization": f"Bearer {bot_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            result = response.json()
            if not result.get("ok"):
                logger.error(f"Slack chat.update error: {result.get('error')}")
                return False
            logger.info(f"Updated message {ts} in {channel}")
            return True

    except Exception as e:
        logger.exception(f"Failed to update Slack message: {e}")
        return False


async def add_reaction(
    channel: str,
    timestamp: str,
    emoji: str = "eyes",
    *,
    role: str | None = None,
) -> bool:
    """Add an emoji reaction to a Slack message.

    Args:
        channel: Channel ID where the message is
        timestamp: Message timestamp (ts)
        emoji: Emoji name without colons (default: "eyes" for 👀)

    Returns:
        True if reaction was added successfully
    """
    bot_token = _resolve_slack_reply_bot_token(role)
    if not bot_token:
        if role:
            logger.error("Missing role-scoped SLACK_BOT_TOKEN for role %s; cannot add reaction", role)
        else:
            logger.warning("SLACK_BOT_TOKEN not set, cannot add reaction")
        return False

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://slack.com/api/reactions.add",
                headers={
                    "Authorization": f"Bearer {bot_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "channel": channel,
                    "timestamp": timestamp,
                    "name": emoji,
                },
            )
            result = response.json()
            if not result.get("ok"):
                # "already_reacted" is not an error - just means we already added this reaction
                if result.get("error") != "already_reacted":
                    logger.warning(f"Slack reactions.add error: {result.get('error')}")
                return result.get("error") == "already_reacted"
            else:
                logger.info(f"Added :{emoji}: reaction to message in {channel}")
                return True

    except Exception as e:
        logger.exception(f"Failed to add Slack reaction: {e}")
        return False


async def add_read_reaction(channel: str, message_ts: str | None) -> bool:
    """Add the :eyes: reaction to indicate the gateway read the message."""
    if not message_ts:
        return False
    return await add_reaction(channel, message_ts, "eyes")


async def set_thread_status(
    channel: str,
    thread_ts: str | None,
    status: str | None,
    *,
    loading_messages: list[str] | None = None,
    role: str | None = None,
) -> bool:
    """Set Slack Assistant thread status (typing-style indicator)."""
    assistant_token = _resolve_slack_assistant_token(role)
    if not assistant_token:
        logger.debug("SLACK_ASSISTANT_TOKEN not set, cannot set thread status")
        return False
    if not channel or not thread_ts or status is None:
        return False

    payload: dict[str, Any] = {
        "channel_id": channel,
        "thread_ts": thread_ts,
        "status": status,
    }
    if loading_messages:
        payload["loading_messages"] = loading_messages

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://slack.com/api/assistant.threads.setStatus",
                headers={
                    "Authorization": f"Bearer {assistant_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            result = response.json()
            if not result.get("ok"):
                # Missing scope / method not found are common if Assistant API isn't enabled.
                err = result.get("error")
                logger.debug("Slack assistant.threads.setStatus error: %s", err)
                return False
            return True
    except Exception as e:
        logger.debug("Failed to set Slack assistant thread status: %s", e)
        return False


async def clear_thread_status(
    channel: str, thread_ts: str | None, *, role: str | None = None
) -> bool:
    """Clear Slack Assistant thread status by sending an empty status string."""
    return await set_thread_status(channel, thread_ts, "", role=role)


async def remove_reaction(
    channel: str,
    timestamp: str,
    emoji: str = "eyes",
    *,
    role: str | None = None,
) -> bool:
    """Remove an emoji reaction from a Slack message.

    Args:
        channel: Channel ID where the message is
        timestamp: Message timestamp (ts)
        emoji: Emoji name without colons (default: "eyes" for 👀)

    Returns:
        True if reaction was removed successfully
    """
    bot_token = _resolve_slack_reply_bot_token(role)
    if not bot_token:
        if role:
            logger.error("Missing role-scoped SLACK_BOT_TOKEN for role %s; cannot remove reaction", role)
        else:
            logger.warning("SLACK_BOT_TOKEN not set, cannot remove reaction")
        return False

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://slack.com/api/reactions.remove",
                headers={
                    "Authorization": f"Bearer {bot_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "channel": channel,
                    "timestamp": timestamp,
                    "name": emoji,
                },
            )
            result = response.json()
            if not result.get("ok"):
                # "no_reaction" just means we didn't have this reaction — not an error
                if result.get("error") != "no_reaction":
                    logger.warning(f"Slack reactions.remove error: {result.get('error')}")
                return result.get("error") == "no_reaction"
            else:
                logger.info(f"Removed :{emoji}: reaction from message in {channel}")
                return True

    except Exception as e:
        logger.exception(f"Failed to remove Slack reaction: {e}")
        return False


# Cache bot user IDs keyed by token fingerprint
_bot_user_ids: dict[str, str] = {}


def _token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:16]


async def get_bot_user_id(*, role: str | None = None, token: str | None = None) -> str | None:
    """Get the bot's own Slack user ID via auth.test (cached)."""
    bot_token = token or _resolve_slack_bot_token(role)
    if not bot_token:
        return None
    key = _token_fingerprint(bot_token)
    if key in _bot_user_ids:
        return _bot_user_ids[key]
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://slack.com/api/auth.test",
                headers={"Authorization": f"Bearer {bot_token}"},
            )
            data = resp.json()
            if data.get("ok"):
                _bot_user_ids[key] = data["user_id"]
                return _bot_user_ids[key]
    except Exception as e:
        logger.warning(f"Failed to get bot user ID: {e}")
    return None


async def bot_participated_in_thread(channel: str, thread_ts: str) -> bool:
    """Check whether the bot has posted any messages in a Slack thread.

    Fetches the thread replies and checks if any message was sent by the bot
    user. This provides a stateless way to determine bot participation without
    relying on in-memory subscription state.
    """
    tokens = _collect_slack_bot_tokens()
    if not tokens:
        return False
    bot_ids = await _our_bot_user_ids()
    if not bot_ids:
        return False

    try:
        async with httpx.AsyncClient() as client:
            for token in tokens:
                resp = await client.get(
                    "https://slack.com/api/conversations.replies",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"channel": channel, "ts": thread_ts, "limit": 50},
                )
                data = resp.json()
                if not data.get("ok"):
                    logger.debug(
                        "conversations.replies failed for one token: %s", data.get("error")
                    )
                    continue
                for msg in data.get("messages", []):
                    if msg.get("user") in bot_ids:
                        return True
                # One successful fetch is enough for non-participation.
                return False
    except Exception as e:
        logger.warning(f"Failed to check thread participation: {e}")
    return False


# ==============================================================================
# Task prompt classification and building
# ==============================================================================


def classify_task_template(role: str, user_message: str, is_thread_reply: bool = False) -> str:
    """Classify a message into a task template type.

    Args:
        role: Agent role (e.g., 'release_engineer', 'support_engineer')
        user_message: The user's message text
        is_thread_reply: True if this message is a reply in an existing thread

    Returns:
        'deployment', 'kubeconfig_setup', 'notification', 'conversational',
        'health_check', or 'investigation'
    """
    msg_lower = user_message.lower()

    is_notification = any(
        kw in msg_lower
        for kw in ["notify", "announce", "tell the team", "tell the customer", "confirm to"]
    )
    is_knowledgebase_update = (
        role == "support_engineer"
        and "kb_eval_fact_" in msg_lower
        and (
            "agents/shared/knowledgebase" in msg_lower
            or "/app/agents/shared/knowledgebase" in msg_lower
        )
    )
    is_kubeconfig_setup_only = (
        role == "release_engineer"
        and any(token in msg_lower for token in ("kubeconfig", "configure k3s", "cluster access"))
        and (
            "do not run health checks yet" in msg_lower
            or "don't run health checks yet" in msg_lower
            or "do not run health check yet" in msg_lower
            or "don't run health check yet" in msg_lower
        )
    )
    # Health check: user asks to check health/readiness/status WITHOUT indicating
    # something is broken.  This should be a quick, focused check — not a deep
    # investigation.  We detect negative indicators (error, fail, broken, down,
    # why, investigate, debug) separately to distinguish "check health" from
    # "check why things are broken".
    _negative_indicators = [
        "error",
        "fail",
        "broken",
        "down",
        "crash",
        "issue",
        "problem",
        "outage",
        "incident",
        "bug",
    ]
    has_negative_indicator = any(kw in msg_lower for kw in _negative_indicators)

    _health_keywords = [
        "health",
        "readiness",
        "ready",
        "status",
        "alive",
        "liveness",
        "uptime",
    ]
    is_health_check = (
        role == "release_engineer"
        and any(kw in msg_lower for kw in _health_keywords)
        and not has_negative_indicator
    )

    is_explicit_investigation = any(
        kw in msg_lower
        for kw in [
            "investigate",
            "check",
            "debug",
            "analyze",
            "why",
            "error",
            "fail",
            "broken",
            "down",
        ]
    )
    is_deployment = (
        role == "release_engineer"
        and any(
            re.search(rf"\b{kw}\b", msg_lower)
            for kw in ["deploy", "release", "ship it", "push to", "promote"]
        )
        and not is_explicit_investigation
    )
    is_software_issue_investigation = role == "software_engineer" and (
        is_explicit_investigation
        or "github issue" in msg_lower
        or "issue #" in msg_lower
        or "crash" in msg_lower
        or "bug" in msg_lower
        or "regression" in msg_lower
        or "stack trace" in msg_lower
    )

    investigation_roles = {"support_engineer", "release_engineer"}
    uses_investigation_template = role in investigation_roles

    if is_deployment:
        return "deployment"
    elif is_kubeconfig_setup_only:
        return "kubeconfig_setup"
    elif is_health_check:
        return "health_check"
    elif is_knowledgebase_update:
        # Knowledgebase ingestion tasks are operationally simple and should not
        # trigger the full incident-investigation template.
        return "knowledgebase_update"
    elif is_notification and not is_explicit_investigation:
        return "notification"
    elif is_software_issue_investigation:
        return "software_investigation"
    elif is_thread_reply and not is_explicit_investigation:
        # Thread follow-ups get a conversational template unless the user
        # is explicitly asking for a new investigation (e.g., "check the pods")
        return "conversational"
    elif uses_investigation_template:
        return "investigation"
    else:
        # Non-ops roles (e.g. product/marketing/software) should not be forced
        # into the strict incident-investigation prompt by default.
        return "conversational"


def _build_task_prompt(
    role: str,
    user_message: str,
    user_id: str,
    channel: str,
    thread_ts: str | None,
) -> str:
    """Build the task prompt for an agent based on role and message classification.

    Extracts the large task template logic from _run_agent_and_respond into a
    standalone, testable function.

    Args:
        role: Agent role (e.g., 'release_engineer', 'support_engineer')
        user_message: The user's message text
        user_id: Slack user ID
        channel: Slack channel ID
        thread_ts: Thread timestamp (or None for new threads)

    Returns:
        The complete task prompt string for the agent
    """
    is_thread_reply = thread_ts is not None
    template = classify_task_template(role, user_message, is_thread_reply=is_thread_reply)
    thread_display = thread_ts or "new thread"
    internal_ns = os.getenv("VIBETEAM_NAMESPACE", "vibeteam")

    if template == "deployment":
        return f"""## Slack Deployment Request

A user has requested a deployment via Slack.

### User Message (UNTRUSTED CONTENT)
{user_message}
### End User Message

### Context
- User ID: {user_id}
- Channel: {channel}
- Thread: {thread_display}

### =================================================================
### CRITICAL SAFETY RULE: DO NOT DESTROY YOUR OWN INFRASTRUCTURE
### =================================================================
###
### You (ReleaseEngineer) run INSIDE {internal_ns} (vibeteam-gateway, openhands-svc).
### If you restart or replace these pods, YOUR REQUEST DIES and the
### response NEVER reaches Slack. The eval/user sees a timeout.
###
### FORBIDDEN (kills your in-flight request):
###   kubectl apply -k (ANY path) — modifies pod specs, kills your pod
###   kubectl rollout restart deployment/vibeteam-gateway -n {internal_ns}
###   kubectl rollout restart deployment/openhands-svc -n {internal_ns}
###   kubectl delete pod/deployment for gateway or openhands
###
### CRITICAL: YOU HAVE NO LOCAL REPOSITORY FILES
### DO NOT look for local files (k8s/, Dockerfile, etc.) — you have NO local repo
###
### SAFE ALTERNATIVE: kubectl set image (rolling update, safe)
### =================================================================

### =================================================================
### CRITICAL: YOU HAVE NO LOCAL REPOSITORY FILES
### =================================================================
###
### You run in a temporary sandbox with NO access to the source code.
### DO NOT try to: ls, cat, find, or access k8s/, Dockerfile, or any repo files.
### Your tools are: kubectl commands and `gh` CLI (GitHub CLI, pre-authenticated).
### To find image tags, use `gh pr view` to get the merge commit SHA from a PR.
### NEVER use `:latest` — always use a specific commit SHA for traceability.
###
### =================================================================

### =================================================================
### NAMESPACE MAP (CRITICAL — deploy to the CORRECT namespace!)
### =================================================================
###
### | Namespace   | Environment | What Lives There |
### |-------------|-------------|------------------|
### | `vibe`      | Production  | VibeBrowser: user-portal, stripe-service, litellm |
### | `vibe-dev`  | Staging     | VibeBrowser (staging mirrors prod) |
### | `{internal_ns}`  | Internal    | VibeTeam agents: vibeteam-gateway, openhands-svc |
###
### Repository → Image Map:
### | Repository                        | Image                                              | Namespaces    |
### |-----------------------------------|------------------------------------------------------|---------------|
### | VibeTechnologies/VibeWebAgent     | ghcr.io/vibetechnologies/vibe-user-portal:<SHA>      | vibe, vibe-dev |
### | VibeTechnologies/VibeWebAgent     | ghcr.io/vibetechnologies/vibe-stripe-service:<SHA>   | vibe, vibe-dev |
### | VibeTechnologies/VibeTeam         | ghcr.io/vibetechnologies/vibeteam:<SHA>              | {internal_ns}       |
###
### "staging" / "dev" → namespace: vibe-dev
### "production" / "prod" → namespace: vibe
### =================================================================

### CRITICAL INSTRUCTIONS — DEPLOYMENT EXECUTION

You are the ReleaseEngineer. You MUST execute the deployment, not just describe it.

**STEP 1 — Identify Target Namespace (MANDATORY):**
From the user's message, determine the target namespace:
- "staging" / "dev" → namespace: `vibe-dev`
- "production" / "prod" → namespace: `vibe`
- "agents" / "vibeteam" → namespace: `{internal_ns}`
If the request mentions a PR on VibeTechnologies/VibeWebAgent, default to `vibe-dev`.

**STEP 2 — Get Image Tag from PR (MANDATORY):**
Use `gh` CLI to get the merge commit SHA from the PR:
```bash
gh pr view <PR_NUMBER> --repo VibeTechnologies/VibeWebAgent --json mergeCommit -q .mergeCommit.oid
```
This returns a 40-char SHA — use it as the image tag. NEVER use `:latest`.

**STEP 3 — Verify Pre-Deployment State (MANDATORY):**
Run kubectl to check current state in the TARGET namespace:
```bash
kubectl get pods -n <NAMESPACE> -o wide
kubectl get deployments -n <NAMESPACE> -o wide
```

**STEP 4 — Check Current Image Tags (MANDATORY):**
```bash
kubectl get deployment user-portal -n <NAMESPACE> -o jsonpath='{{{{.spec.template.spec.containers[0].image}}}}'
kubectl get deployment stripe-service -n <NAMESPACE> -o jsonpath='{{{{.spec.template.spec.containers[0].image}}}}'
```

**STEP 5 — Execute Deployment (MANDATORY):**
Use `kubectl set image` to update VibeBrowser deployments:
```bash
kubectl set image deployment/user-portal user-portal=ghcr.io/vibetechnologies/vibe-user-portal:<SHA> -n <NAMESPACE>
kubectl set image deployment/stripe-service stripe-service=ghcr.io/vibetechnologies/vibe-stripe-service:<SHA> -n <NAMESPACE>
```
Do NOT run `kubectl apply -k` — it modifies pod specs and kills your own pod.
Do NOT deploy to the `{internal_ns}` namespace unless the request is explicitly about VibeTeam agents.

Then monitor rollout (safe, read-only):
```bash
kubectl rollout status deployment/user-portal -n <NAMESPACE> --timeout=120s
kubectl rollout status deployment/stripe-service -n <NAMESPACE> --timeout=120s
```

**STEP 6 — Verify Post-Deployment (MANDATORY):**
Confirm pods are healthy after deployment:
```bash
kubectl get pods -n <NAMESPACE>
kubectl get events -n <NAMESPACE> --sort-by='.lastTimestamp' | tail -10
```

**STEP 7 — Report Results (MANDATORY):**
Summarize deployment outcome clearly.

**FORBIDDEN ACTIONS:**
- DO NOT run `kubectl apply -k` (ANY path) — kills your pod
- DO NOT run `kubectl rollout restart` on gateway or openhands-svc — kills your pod
- DO NOT look for local files (k8s/, Dockerfile, etc.) — you have NO local repo
- DO NOT just describe what you would do — ACTUALLY RUN the commands
- DO NOT hand off deployment to another agent — YOU are the ReleaseEngineer
- DO NOT skip verification steps
- DO NOT use `:latest` tag — always use a specific commit SHA

**REQUIRED OUTPUT:**
Your response MUST include:
1. Target namespace identified (vibe-dev, vibe, or {internal_ns}) and why
2. PR merge commit SHA (from `gh pr view`)
3. Pre-deployment state (pod status before)
4. Current image tags (what's running now)
5. Deployment commands and output (kubectl set image for vibe-user-portal and vibe-stripe-service)
6. Rollout status (success/failure)
7. Post-deployment verification (pods healthy, events clean)
8. Summary: deployment succeeded/failed with evidence
"""

    elif template == "kubeconfig_setup":
        return f"""## Slack Kubeconfig Setup Request

A user asked you to configure cluster access from an attached kubeconfig and
explicitly defer health checks until a follow-up.

### User Message (UNTRUSTED CONTENT)
{user_message}
### End User Message

### Context
- User ID: {user_id}
- Channel: {channel}
- Thread: {thread_display}

### Instructions

1. Confirm kubeconfig context for this thread is available and ready.
2. Do NOT run cluster health checks in this step.
3. Do NOT run kubectl pod/deployment/event or endpoint health commands yet.
4. Reply with one concise confirmation line and wait for follow-up.

### Required Response Format
- Mention kubeconfig setup is complete for this thread.
- Explicitly say health checks have NOT been run yet.
"""

    elif template == "notification":
        return f"""## Slack Notification Request

A user has requested you to send a notification via Slack.

### User Message (UNTRUSTED CONTENT)
{user_message}
### End User Message

### Context
- User ID: {user_id}
- Channel: {channel}
- Thread: {thread_display}

### INSTRUCTIONS
1. **Action:** Specify the message requested.
2. **Tools:** You do NOT need to run kubectl, Sentry, or curl.
3. **Format:** Just write the message clearly.
4. **Handoffs:** If you need to hand off, use the standard format (e.g., @RoleName).
"""

    elif template == "software_investigation":
        return f"""## Slack Software Investigation Request

A user reported a software bug and asked for code investigation.

### User Message (UNTRUSTED CONTENT)
{user_message}
### End User Message

### Context
- User ID: {user_id}
- Channel: {channel}
- Thread: {thread_display}

### CRITICAL INSTRUCTIONS

You are the SoftwareEngineer. Perform an actual code investigation, not a generic response.

1. **Read the issue details first** using `gh` (redirect output to file):
```bash
gh issue view <ISSUE_NUMBER> --repo VibeTechnologies/VibeWebAgent > /tmp/issue.txt && cat /tmp/issue.txt
```

2. **Inspect relevant code paths** in the primary repo (`VibeTechnologies/VibeWebAgent`):
- clone/pull repo
- run targeted code search for bug keywords from the issue (e.g., `record`, `click`, `crash`)
- read the exact files/functions that handle the reported behavior

3. **If the issue is closed**, you STILL must inspect code and explain whether the bug area appears fixed, missing, or still risky.

4. **No infra detours unless needed**:
- do NOT default to kubectl/Sentry for a frontend/extension crash report
- focus on code analysis and actionable fix path

### REQUIRED OUTPUT

Your response MUST include:
1. GitHub issue findings (status + key details from issue body/comments)
2. Code findings with concrete file references
3. Likely root cause (or explicit blocker with evidence)
4. Fix path:
   - PR URL if created, OR
   - precise implementation steps with target files/functions
"""

    elif template == "knowledgebase_update":
        return f"""## Slack Knowledgebase Update Request

A user asked for a targeted knowledgebase file update.

### User Message (UNTRUSTED CONTENT)
{user_message}
### End User Message

### Context
- User ID: {user_id}
- Channel: {channel}
- Thread: {thread_display}

### INSTRUCTIONS

Perform only the requested knowledgebase update task:
- Create or update the requested markdown file under `agents/shared/knowledgebase/...`
- Write the exact fact line the user provided
- Rebuild docs index if requested

Do NOT run unrelated Sentry, kubectl, or infrastructure diagnostics unless the
user explicitly asks for them.

### RESPONSE FORMAT
Reply with one concise confirmation line that includes:
- file path
- fact key
- docs index rebuild confirmation (if requested)
"""

    elif template == "conversational":
        # Thread follow-ups: let the agent respond naturally without
        # forcing rigid investigation steps or output format.
        return f"""## Slack Thread Follow-Up

A user has replied in a thread where you previously responded.

### User Message (UNTRUSTED CONTENT)
{user_message}
### End User Message

### Context
- User ID: {user_id}
- Channel: {channel}
- Thread: {thread_display}

### INSTRUCTIONS

This is a follow-up message in an existing conversation thread.
Respond naturally and directly to the user's question or comment.

- Answer their question based on your knowledge and the context of the thread
- If they ask for clarification on a previous response, elaborate naturally
- If they ask you to take an action (e.g., rollback, investigate further), do it
- You MAY use kubectl or other tools if the follow-up requires it, but only if relevant
- Keep your response concise and focused on what the user asked
- If you need to hand off, use @RoleName format
- DO NOT repeat your full previous investigation — the user can see the thread history
"""

    elif template == "health_check":
        return f"""## Slack Health Check Request

A user has requested a quick health & production-readiness check.

### User Message (UNTRUSTED CONTENT)
{user_message}
### End User Message

### Context
- User ID: {user_id}
- Channel: {channel}
- Thread: {thread_display}

### Namespace Map
| Namespace   | Environment | What Lives There |
|-------------|-------------|------------------|
| `vibe`      | Production  | VibeBrowser: user-portal, stripe-service, litellm |
| `vibe-dev`  | Staging     | VibeBrowser (staging mirrors prod) |
| `{internal_ns}`  | Internal    | VibeTeam agents: vibeteam-gateway, openhands-svc |

"production" / "prod" / "api" → namespace: `vibe`
"staging" / "dev" → namespace: `vibe-dev`
"agents" / "vibeteam" / "gateway" → namespace: `{internal_ns}`
If unclear, default to the production namespace `vibe`.

### Safety Rule
This is a READ-ONLY health check. Do NOT restart, scale, rollback,
or modify any resources. Just observe and report.

### Instructions

You are the ReleaseEngineer performing a focused health check.
Follow "Health Check Mode" from your system instructions.

**Execute EXACTLY these commands (adapt NAMESPACE). Do NOT add extra commands.**

**Tool call 1** — Determine namespace & get infra status (run as ONE command):
```bash
kubectl get pods -n <NAMESPACE> -o wide && kubectl get deployments -n <NAMESPACE> && kubectl get events -n <NAMESPACE> --sort-by='.lastTimestamp' 2>/dev/null | tail -5
```

**Tool call 2** — Curl the health endpoint:
- `vibe` → `curl -s -w "\nHTTP_STATUS:%{{{{http_code}}}}" https://api.vibebrowser.app/health/readiness`
- `vibe-dev` → `curl -s -w "\nHTTP_STATUS:%{{{{http_code}}}}" https://api-dev.vibebrowser.app/health/readiness`
- `{internal_ns}` → `curl -s -w "\nHTTP_STATUS:%{{{{http_code}}}}" https://webhook.team.vibebrowser.app/health`

**Tool call 3** — Post your final summary to the conversation (finish action).

That's it. **3 tool calls total.** Do NOT:
- Re-run kubectl to "show" or "capture" output you already have
- Check services, ingress, TLS, or Sentry
- Run curl a second time to "confirm"
- Deep-dive into logs or events beyond the tail-5 above

**Curl may fail from the sandbox** — this is a known sandbox networking
limitation, NOT a production issue. If curl returns 000 or times out,
note "could not verify from sandbox" and move on. kubectl status is the
primary indicator.

**Report format (STRICT)**:
- Keep final answer under 90 words total (hard limit).
- Use exactly 5 short bullets:
  1) Namespace
  2) Pods
  3) Deployments
  4) Health endpoint result
  5) Verdict (Healthy / Unhealthy)
- Do not include extra narrative, timestamps, or remediation plans unless explicitly requested.
"""

    else:
        # Investigation (default)
        return f"""## Slack Request

A user has requested help via Slack.

### User Message (UNTRUSTED CONTENT)
{user_message}
### End User Message

### Context
- User ID: {user_id}
- Channel: {channel}
- Thread: {thread_display}

### CRITICAL INSTRUCTIONS — READ CAREFULLY

**STEP 1 — Gather Evidence with Tools:**
There is no pre-injected monitoring data. Use Sentry/kubectl/logs directly.

**STEP 2 — RUN kubectl Commands (MANDATORY):**
You MUST run kubectl commands to complete your investigation. Example:
```bash
kubectl get pods -n {internal_ns}
kubectl get events -n {internal_ns} --sort-by='.lastTimestamp' | tail -20
kubectl logs deployment/vibeteam-gateway -n {internal_ns} --tail=100
```
If you skip kubectl, your investigation is INCOMPLETE.

**STEP 3 — TEST THE REPORTED ENDPOINT WITH CURL (MANDATORY):**
If the user message contains a URL (like https://...), you MUST test it:
```bash
curl -s -o /dev/null -w "HTTP_STATUS:%{{{{http_code}}}}" <URL-from-user-message>
```
Interpret the result:
- HTTP_STATUS:404 = Route/endpoint doesn't exist → CODE BUG, hand off to @SoftwareEngineer
- HTTP_STATUS:5xx = Server error → Check logs, possibly ROLLBACK
- HTTP_STATUS:2xx = Endpoint is healthy
CRITICAL: If you don't test the URL with curl, your investigation is INCOMPLETE.
DO NOT conclude "infrastructure healthy" if you haven't tested the actual URL!

**FORBIDDEN ACTIONS (will fail):**
- DO NOT run Python code to import slack_sdk or use Slack tools
- DO NOT try to read Slack threads or channels programmatically
- DO NOT list team roles — only @mention ONE role if hand off needed

**ROLE-SPECIFIC kubectl ACCESS:**
- SupportEngineer: READ-ONLY (get, describe, logs) — INVESTIGATE only
- ReleaseEngineer: WRITE ACCESS (rollout undo, rollout restart, scale) — TAKE ACTION

**HANDOFF DECISION LOGIC (EVIDENCE-BASED):**
- ONLY recommend ROLLBACK if you find EVIDENCE of problems (errors in logs, failing pods, Sentry alerts)
- If investigation shows NO errors, healthy pods, clean logs → report "infrastructure healthy, no action needed"
- If no evidence of problems but customer reports issues → ask for more details (request IDs, timestamps, specific endpoints)
- NEVER recommend rollback based solely on customer report timing — you need actual evidence

**REQUIRED OUTPUT:**
Your response MUST include:
1. Sentry findings: "Found Sentry issue [ID]: [message] — [count] events" OR "No Sentry issues found"
2. kubectl findings: "kubectl get pods shows: [status]" / "kubectl logs shows: [patterns]"
3. Endpoint test (if webhook/API issue): "curl shows: [HTTP status code and response]" — a 404 means the route doesn't exist!
4. Root cause: Analysis correlating Sentry, kubectl, AND endpoint test findings
5. **RECOMMENDATION** (REQUIRED — must match evidence):
   - If EVIDENCE of issues found: "Recommend ROLLBACK" → @ReleaseEngineer please rollback the deployment
   - If CODE BUG identified (e.g., 404 endpoint): "Recommend CODE FIX" → @SoftwareEngineer please investigate [specific file/code]
   - If NO issues found: "Infrastructure appears healthy. No errors in Sentry, pods running normally, logs clean. Please ask customer for: request IDs, specific timestamps, exact error messages they see."
   - CRITICAL: Do NOT recommend rollback if no issues were found — this wastes engineering time and may cause unnecessary downtime
   - CRITICAL: DO NOT TAG YOUR OWN ROLE. If you are @SoftwareEngineer, do NOT tag @SoftwareEngineer. Just do the work.
"""


# ==============================================================================
# Async agent submission
# ==============================================================================


async def _submit_agent_async(
    role: str,
    display_name: str,
    user_message: str,
    channel: str,
    thread_ts: str | None,
    message_ts: str,
    user_id: str,
    framework: str | None = None,
    max_handoff_depth: int = 3,
    current_depth: int = 0,
    retry_count: int = 0,
) -> None:
    """Submit an agent task asynchronously via /run/async.

    Uses a :thinking_face: reaction and (if available) Assistant thread status
    as typing indicators, submits the task, and returns immediately.
    The agent service will POST results to /callback/agent when done.
    """
    task = _build_task_prompt(
        role=role,
        user_message=user_message,
        user_id=user_id,
        channel=channel,
        thread_ts=thread_ts,
    )

    # Pick template to decide iteration limits.
    is_thread_reply = thread_ts is not None
    template = classify_task_template(role, user_message, is_thread_reply=is_thread_reply)
    max_iterations_map = {
        "health_check": 30,
        "kubeconfig_setup": 30,
        "knowledgebase_update": 80,
        "conversational": 60,
        "notification": 60,
        "software_investigation": 240,
        "deployment": 160,
        "investigation": 240,
    }
    max_iterations = max_iterations_map.get(template, 240)

    # Best-effort: show assistant "typing" status in the thread while the agent runs.
    status_thread_ts = thread_ts or message_ts
    await set_thread_status(
        channel,
        status_thread_ts,
        config.SLACK_ASSISTANT_STATUS_TEXT,
        role=role,
    )

    # Build callback URL
    callback_url = f"{config.GATEWAY_URL}/callback/agent"
    progress_url = f"{config.GATEWAY_URL}/callback/agent/progress"

    # Submit async task
    result = await call_agent_service_async(
        task=task,
        role=role,
        framework=framework,
        context_type="slack",
        context_id=f"{channel}:{thread_ts or 'new'}",
        callback_url=callback_url,
        progress_url=progress_url,
        max_iterations=max_iterations,
        execution_timeout=(
            config.SLACK_AGENT_IDLE_TIMEOUT_SECONDS
            if config.SLACK_AGENT_IDLE_TIMEOUT_SECONDS > 0
            else None
        ),
        callback_metadata={
            "channel": channel,
            "thread_ts": thread_ts,
            "message_ts": message_ts,
            "user_id": user_id,
            "role": role,
            "display_name": display_name,
            "user_message": user_message,
            "max_handoff_depth": max_handoff_depth,
            "current_depth": current_depth,
            "retry_count": retry_count,
            "framework": framework,
            # Include callback secret for authentication
            # Agent service echoes this back; gateway verifies on receipt
            "callback_secret": config.CALLBACK_SECRET,
        },
    )

    if "error" in result:
        # Remove thinking face, add X
        await remove_reaction(channel, message_ts, "thinking_face", role=role)
        await clear_thread_status(channel, status_thread_ts, role=role)
        await add_reaction(channel, message_ts, "x", role=role)
        error_text = f"Sorry, I couldn't reach the agent service: {result['error']}"
        await send_slack_message(channel, error_text, thread_ts, role=role)
        logger.error(f"[ASYNC] Failed to submit task for {role}: {result['error']}")
    else:
        job_id = result.get("job_id", "unknown")
        logger.info(
            f"[ASYNC] Submitted job {job_id} for {role} in {channel} (depth={current_depth})"
        )


# ==============================================================================
# Main entry point for Slack → agent routing
# ==============================================================================


async def run_agent_for_slack(
    user_message: str,
    channel: str,
    thread_ts: str | None,
    user_id: str,
    message_ts: str | None = None,
    use_async: bool = True,
    framework: str | None = None,
) -> None:
    """
    Run the appropriate agent based on Slack message and respond.

    Uses the Router to parse /RoleName mentions and route to specific agents.
    Falls back to keyword-based routing if no role is mentioned.

    Args:
        user_message: The user's Slack message
        channel: Slack channel ID
        thread_ts: Thread timestamp (or None for new threads)
        user_id: Slack user ID
        message_ts: Message timestamp (needed for async reaction management)
        use_async: If True and message_ts is available, use async callback flow
        framework: Optional agent framework override (e.g., "openclaw")
    """
    logger.info(f"Processing Slack message from {user_id}: {user_message[:100]}")

    # Route the message
    message_router = get_message_router()

    # Parse /RoleName mentions
    role_mentions = message_router.parse_role_mentions(user_message)

    if not role_mentions:
        # Fall back to keyword-based routing (shared with openhands team.py)
        role_mentions = [route_by_keywords(user_message)]

    # Determine effective message_ts for reaction management
    effective_message_ts = message_ts or thread_ts or ""
    is_thread_reply = thread_ts is not None

    for role in role_mentions:
        display_name = get_slack_handle(role) or get_display_name(cast(AgentRole, role))
        template = classify_task_template(role, user_message, is_thread_reply=is_thread_reply)

        # Deterministic fast-path for configure-only kubeconfig requests.
        # This enforces the required "configure first, health check later" sequence.
        if template == "kubeconfig_setup":
            if message_ts:
                await remove_reaction(channel, message_ts, "thinking_face", role=role)
                await add_reaction(channel, message_ts, "white_check_mark", role=role)
            await send_slack_message(
                channel,
                _build_kubeconfig_setup_confirmation(channel, thread_ts),
                thread_ts,
                role=role,
            )
            continue

        if use_async and effective_message_ts:
            await _submit_agent_async(
                role=role,
                display_name=display_name,
                user_message=user_message,
                channel=channel,
                thread_ts=thread_ts,
                message_ts=effective_message_ts,
                user_id=user_id,
                framework=framework,
            )
        else:
            await _run_agent_and_respond(
                role=role,
                display_name=display_name,
                user_message=user_message,
                channel=channel,
                thread_ts=thread_ts,
                user_id=user_id,
                message_ts=effective_message_ts or None,
                framework=framework,
            )


async def _run_agent_and_respond(
    role: str,
    display_name: str,
    user_message: str,
    channel: str,
    thread_ts: str | None,
    user_id: str,
    message_ts: str | None = None,
    framework: str | None = None,
    max_handoff_depth: int = 3,
    current_depth: int = 0,
) -> None:
    """Run a specific agent synchronously and post response to Slack.

    This is the sync path — used by /slack/trigger and as fallback when
    message_ts is unavailable for async reaction management.

    Uses :thinking_face: reaction and (if available) Assistant thread status
    as typing indicators.

    Supports synchronous handoffs: if the agent mentions /RoleName in its response,
    that agent is immediately invoked (up to max_handoff_depth to prevent infinite loops).
    """
    task = _build_task_prompt(
        role=role,
        user_message=user_message,
        user_id=user_id,
        channel=channel,
        thread_ts=thread_ts,
    )

    # Pick template to decide iteration limits (sync path).
    is_thread_reply = thread_ts is not None
    template = classify_task_template(role, user_message, is_thread_reply=is_thread_reply)
    max_iterations_map = {
        "health_check": 30,
        "kubeconfig_setup": 30,
        "knowledgebase_update": 80,
        "conversational": 60,
        "notification": 60,
        "software_investigation": 240,
        "deployment": 160,
        "investigation": 240,
    }
    max_iterations = max_iterations_map.get(template, 240)

    status_thread_ts = thread_ts or message_ts
    await set_thread_status(
        channel,
        status_thread_ts,
        config.SLACK_ASSISTANT_STATUS_TEXT,
        role=role,
    )

    agent_start_time = time.time()
    logger.info(f"[TIMING] Starting agent {role} (depth={current_depth})")

    try:
        result = await call_agent_service(
            task=task,
            role=role,
            framework=framework,
            context_type="slack",
            context_id=f"{channel}:{thread_ts or 'new'}",
            max_iterations=max_iterations,
            execution_timeout=(
                config.SLACK_AGENT_IDLE_TIMEOUT_SECONDS
                if config.SLACK_AGENT_IDLE_TIMEOUT_SECONDS > 0
                else None
            ),
        )

        agent_duration = time.time() - agent_start_time
        logger.info(f"[TIMING] Agent {role} completed in {agent_duration:.1f}s")

        if "error" in result:
            error_text = f"Sorry, I encountered an error: {result['error']}"
            if message_ts:
                await remove_reaction(channel, message_ts, "thinking_face", role=role)
                await add_reaction(channel, message_ts, "x", role=role)
            await send_slack_message(channel, error_text, thread_ts, role=role)
        else:
            response = result.get("response", "I completed the task but have no output to share.")

            # Remove thinking face, add checkmark
            if message_ts:
                await remove_reaction(channel, message_ts, "thinking_face", role=role)
                await add_reaction(channel, message_ts, "white_check_mark", role=role)

            # Split long responses into multiple messages instead of truncating
            # This preserves handoff mentions that might be at the end
            chunks = split_long_message(response)

            # Send each chunk as a separate message
            for chunk in chunks:
                await send_slack_message(channel, chunk, thread_ts, role=role)

            # Check for handoffs in the response and execute them synchronously
            handoff_roles = _parse_handoff_roles(response, role)
            logger.info(f"Checking for handoffs in response from {role}: found {handoff_roles}")
            if handoff_roles and current_depth < max_handoff_depth:
                logger.info(
                    f"Detected handoff to: {handoff_roles} (depth {current_depth + 1}/{max_handoff_depth})"
                )
                # Execute handoffs synchronously
                for handoff_role in handoff_roles:
                    if handoff_role == role:
                        # Skip self-handoffs
                        logger.info(f"Skipping self-handoff to {role}")
                        continue
                    handoff_start = time.time()
                    logger.info(f"[TIMING] Executing handoff to {handoff_role}...")
                    handoff_display = get_slack_handle(handoff_role) or get_display_name(
                        cast(AgentRole, handoff_role)
                    )
                    handoff_search = get_display_name(cast(AgentRole, handoff_role))
                    handoff_snippet = _extract_handoff_snippet(response, handoff_search)
                    repo_ref = _extract_repo_reference(handoff_snippet) or _extract_repo_reference(
                        response
                    )
                    sentry_urls = _extract_sentry_urls(response)
                    pr_urls = _extract_pr_urls(response)
                    repo_block = f"Repository: {repo_ref}\n\n" if repo_ref else ""
                    sentry_block = ""
                    if sentry_urls:
                        sentry_block = f"Sentry issue(s): {' '.join(sentry_urls)}\n\n"
                    pr_block = ""
                    if pr_urls:
                        pr_block = f"PR(s): {' '.join(pr_urls)}\n\n"
                    # Pass minimal context to avoid overwhelming the next agent.
                    handoff_message = (
                        f"[Handoff from {display_name}]\n\n"
                        f"Original request: {user_message}\n\n"
                        f"{repo_block}"
                        f"{sentry_block}"
                        f"{pr_block}"
                        f"Handoff request: {handoff_snippet}"
                    )
                    await _run_agent_and_respond(
                        role=handoff_role,
                        display_name=handoff_display,
                        user_message=handoff_message,
                        channel=channel,
                        thread_ts=thread_ts,
                        user_id=user_id,
                        framework=framework,
                        max_handoff_depth=max_handoff_depth,
                        current_depth=current_depth + 1,
                    )
                    handoff_duration = time.time() - handoff_start
                    logger.info(
                        f"[TIMING] Handoff to {handoff_role} completed in {handoff_duration:.1f}s"
                    )
            elif handoff_roles:
                logger.warning(
                    f"Max handoff depth ({max_handoff_depth}) reached, ignoring: {handoff_roles}"
                )

    except Exception as e:
        logger.exception(f"Failed to run agent for Slack: {e}")
        error_text = "Sorry, I encountered an unexpected error. Please try again later."
        if message_ts:
            await remove_reaction(channel, message_ts, "thinking_face", role=role)
            await add_reaction(channel, message_ts, "x", role=role)
        await send_slack_message(channel, error_text, thread_ts, role=role)
    finally:
        await clear_thread_status(channel, status_thread_ts, role=role)


# ==============================================================================
# Callback endpoint for async agent results
# ==============================================================================


@router.post("/callback/agent")
async def handle_agent_callback(request: Request) -> dict[str, Any]:
    """Handle callback from agent service when an async job completes.

    The agent service POSTs here with:
    - job_id, status, response/error
    - callback_metadata (Slack context: channel, thread_ts, message_ts, role, etc.)

    This endpoint:
    1. Removes the :thinking_face: reaction
    2. Posts the response (or error) to Slack as a new message
    3. Checks for handoff mentions and submits new async jobs if needed
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from None

    job_id = payload.get("job_id", "unknown")
    status = payload.get("status", "unknown")
    response_text = payload.get("response", "")
    error = payload.get("error", "")
    meta = payload.get("callback_metadata", {})

    channel = meta.get("channel", "")
    thread_ts = meta.get("thread_ts")
    message_ts = meta.get("message_ts", "")
    role = meta.get("role", "unknown")
    display_name = meta.get("display_name", role)
    user_message = meta.get("user_message", "")
    user_id = meta.get("user_id", "")
    max_handoff_depth = meta.get("max_handoff_depth", 3)
    current_depth = meta.get("current_depth", 0)
    retry_count_raw = meta.get("retry_count", 0)
    try:
        retry_count = int(retry_count_raw)
    except (TypeError, ValueError):
        retry_count = 0
    framework = meta.get("framework")

    logger.info(f"[CALLBACK] Received callback for job {job_id}: status={status}, role={role}")

    # Verify callback authentication
    # If CALLBACK_SECRET is configured, the agent must echo it back in callback_metadata
    if config.CALLBACK_SECRET:
        callback_secret = meta.get("callback_secret", "")
        if callback_secret != config.CALLBACK_SECRET:
            logger.warning(f"[CALLBACK] Invalid callback_secret for job {job_id}")
            raise HTTPException(status_code=403, detail="Invalid callback secret")

    if not channel:
        logger.error(f"[CALLBACK] Missing channel in callback_metadata for job {job_id}")
        return {"status": "error", "detail": "missing channel in callback_metadata"}

    # Clear assistant thread status when the job completes (success or failure).
    status_thread_ts = thread_ts or message_ts
    await clear_thread_status(channel, status_thread_ts, role=role)

    # Remove thinking_face reaction
    if message_ts:
        await remove_reaction(channel, message_ts, "thinking_face", role=role)

    if status == "timeout":
        # Timeout path — agent ran out of time
        if message_ts:
            await add_reaction(channel, message_ts, "hourglass", role=role)
        # Post partial response if available, otherwise generic timeout message
        timeout_response = response_text or (
            "Sorry, I ran out of time working on this task. "
            "Please try again or break the request into smaller steps."
        )
        timeout_text = f":hourglass: {timeout_response}"
        await send_slack_message(channel, timeout_text, thread_ts, role=role)
        return {"status": "ok", "job_id": job_id, "outcome": "timeout_posted"}

    if status == "failed" or error:
        error_msg = _format_callback_error(payload, job_id)
        # Retry transient overloads automatically before posting a final failure.
        if _is_transient_overload_error_text(error_msg) and retry_count < 2:
            next_retry = retry_count + 1
            logger.warning(
                "[CALLBACK] Transient overload detected for job %s; retrying (%d/2)",
                job_id,
                next_retry,
            )
            if message_ts:
                await add_reaction(channel, message_ts, "thinking_face", role=role)
            await send_slack_message(
                channel,
                (
                    ":hourglass_flowing_sand: Capacity issue detected while running this request. "
                    f"Retrying automatically ({next_retry}/2)..."
                ),
                thread_ts,
                role=role,
            )
            await _submit_agent_async(
                role=role,
                display_name=display_name,
                user_message=user_message,
                channel=channel,
                thread_ts=thread_ts,
                message_ts=message_ts,
                user_id=user_id,
                framework=framework,
                max_handoff_depth=max_handoff_depth,
                current_depth=current_depth,
                retry_count=next_retry,
            )
            return {"status": "ok", "job_id": job_id, "outcome": "retry_submitted"}

        # Failure path
        if message_ts:
            await add_reaction(channel, message_ts, "x", role=role)
        error_text = f"Sorry, I encountered an error: {error_msg}"
        await send_slack_message(channel, error_text, thread_ts, role=role)
        return {"status": "ok", "job_id": job_id, "outcome": "error_posted"}

    # Success path
    if message_ts:
        await add_reaction(channel, message_ts, "white_check_mark", role=role)

    # An empty response means the agent intentionally suppressed output
    # (e.g., handoff chain re-entry guard). Skip posting and handoffs.
    if not response_text:
        return {"status": "ok", "job_id": job_id, "outcome": "suppressed"}

    response = response_text

    # Split long responses into multiple messages
    chunks = split_long_message(response)

    any_posted = False
    for chunk in chunks:
        ts = await send_slack_message(channel, chunk, thread_ts, role=role)
        if ts:
            any_posted = True

    # If the response couldn't be posted (e.g. account_inactive token),
    # skip handoff processing — no point triggering a handoff chain
    # when the originating response is invisible to users.
    if not any_posted:
        logger.warning(
            "[CALLBACK] Response could not be posted for %s job %s; skipping handoffs",
            role,
            job_id,
        )
        return {"status": "ok", "job_id": job_id, "outcome": "response_not_posted"}

    # Check for handoffs in the response
    message_router = get_message_router()
    handoff_roles = _parse_handoff_roles(response, role)

    if handoff_roles and current_depth < max_handoff_depth:
        for handoff_role in handoff_roles:
            if handoff_role == role:
                logger.info(f"[CALLBACK] Skipping self-handoff to {role}")
                continue

            handoff_display = get_slack_handle(handoff_role) or get_display_name(
                cast(AgentRole, handoff_role)
            )
            handoff_search = get_display_name(cast(AgentRole, handoff_role))
            handoff_snippet = _extract_handoff_snippet(response, handoff_search)
            repo_ref = _extract_repo_reference(handoff_snippet) or _extract_repo_reference(response)
            sentry_urls = _extract_sentry_urls(response)
            pr_urls = _extract_pr_urls(response)
            repo_block = f"Repository: {repo_ref}\n\n" if repo_ref else ""
            sentry_block = ""
            if sentry_urls:
                sentry_block = f"Sentry issue(s): {' '.join(sentry_urls)}\n\n"
            pr_block = ""
            if pr_urls:
                pr_block = f"PR(s): {' '.join(pr_urls)}\n\n"
            handoff_message = (
                f"[Handoff from {display_name}]\n\n"
                f"Original request: {user_message}\n\n"
                f"{repo_block}"
                f"{sentry_block}"
                f"{pr_block}"
                f"Handoff request: {handoff_snippet}"
            )
            await _submit_agent_async(
                role=handoff_role,
                display_name=handoff_display,
                user_message=handoff_message,
                channel=channel,
                thread_ts=thread_ts,
                message_ts=message_ts,
                user_id=user_id,
                framework=framework,
                max_handoff_depth=max_handoff_depth,
                current_depth=current_depth + 1,
            )
    elif handoff_roles:
        logger.warning(
            f"[CALLBACK] Max handoff depth ({max_handoff_depth}) reached for job {job_id}"
        )

    return {"status": "ok", "job_id": job_id, "outcome": "response_posted"}


# ==============================================================================
# Progress callback endpoint for agent intermediate updates
# ==============================================================================


@router.post("/callback/agent/progress")
async def handle_agent_progress(request: Request) -> dict[str, Any]:
    """Handle progress updates from agent service while agent is working.

    The agent service POSTs here periodically with:
    - job_id, step_number, step_summary, elapsed_seconds
    - callback_metadata (Slack context: channel, thread_ts, etc.)

    This endpoint posts a progress message to the Slack thread so users
    can see what the agent is doing instead of just seeing :thinking_face:.
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from None

    job_id = payload.get("job_id", "unknown")
    step_number = payload.get("step_number", 0)
    step_summary = payload.get("step_summary", "")
    elapsed_seconds = payload.get("elapsed_seconds", 0)
    meta = payload.get("callback_metadata", {})

    channel = meta.get("channel", "")
    thread_ts = meta.get("thread_ts")
    role = meta.get("role")

    if not channel or not step_summary:
        return {"status": "ignored", "reason": "missing channel or step_summary"}

    # Verify callback authentication
    if config.CALLBACK_SECRET:
        callback_secret = meta.get("callback_secret", "")
        if callback_secret != config.CALLBACK_SECRET:
            logger.warning(f"[PROGRESS] Invalid callback_secret for job {job_id}")
            raise HTTPException(status_code=403, detail="Invalid callback secret")

    # Format elapsed time
    mins, secs = divmod(elapsed_seconds, 60)
    time_str = f"{mins}m{secs:02d}s" if mins > 0 else f"{secs}s"

    # Throttle progress messages to reduce Slack noise.
    # Only post step 1 (confirms agent started), then every 5th step,
    # to avoid flooding the thread with 30+ progress messages.
    if step_number > 1 and step_number % 5 != 0:
        logger.info(
            f"[PROGRESS] job={job_id} step={step_number} elapsed={time_str}: "
            f"{step_summary[:80]} (throttled, not posted to Slack)"
        )
        return {"status": "ok", "job_id": job_id, "throttled": True}

    # Post progress as a subtle update
    progress_text = f"_Step {step_number} ({time_str}): {step_summary}_"
    await send_slack_message(channel, progress_text, thread_ts, role=role)

    logger.info(
        f"[PROGRESS] job={job_id} step={step_number} elapsed={time_str}: {step_summary[:80]}"
    )

    return {"status": "ok", "job_id": job_id}


# ==============================================================================
# Slack event handlers
# ==============================================================================


async def _process_slack_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Process Slack events in a background task."""
    try:
        event = payload.get("event", {})
        event_type = event.get("type")
        event_subtype = event.get("subtype")
        event_channel = event.get("channel", "")
        event_ts = event.get("ts", "")
        event_text = event.get("text", "")
        event_thread_ts = event.get("thread_ts") or event_ts

        logger.info(
            f"Received Slack event: {event_type}, "
            f"subtype={event.get('subtype')}, "
            f"thread_ts={bool(event.get('thread_ts'))}, "
            f"channel_type={event.get('channel_type')}"
        )

        # Add read reaction for any message/app_mention we receive, even if we end up ignoring it.
        # This ensures all messages read by the gateway are marked with 👀.
        should_add_read_reaction = (
            bool(event_ts)
            and bool(event_channel)
            and (
                event_type == "app_mention"
                or (
                    event_type == "message"
                    and event_subtype
                    not in {
                        "message_changed",
                        "message_deleted",
                        "message_replied",
                    }
                )
            )
        )
        if should_add_read_reaction:
            await add_read_reaction(event_channel, event_ts)

        is_bot_message = event.get("bot_id") or event.get("subtype") == "bot_message"

        # Capture thread-scoped kubeconfig context from Slack file attachments.
        if (
            event_type in {"app_mention", "message"}
            and not is_bot_message
            and event_channel
            and event_thread_ts
            and (
                event_type == "app_mention"
                or event_subtype
                not in {
                    "message_changed",
                    "message_deleted",
                    "message_replied",
                }
            )
        ):
            kubeconfig_context, kubeconfig_error = await _extract_kubeconfig_context_from_event(
                event,
                request_text=event_text,
            )
            if kubeconfig_context:
                _store_thread_kubeconfig_context(event_channel, event_thread_ts, kubeconfig_context)
                cluster_names = kubeconfig_context.get("cluster_names", [])
                cluster_summary = ", ".join(cluster_names) if cluster_names else "unknown"
                ack_role = await _resolve_explicit_role_for_text(event_text)
                await send_slack_message(
                    event_channel,
                    (
                        ":white_check_mark: Received kubeconfig attachment "
                        f"`{kubeconfig_context.get('file_name', 'uploaded-kubeconfig')}`. "
                        f"Stored for this thread (clusters: {cluster_summary}). "
                        "I will use it for k3s/vibe cluster checks."
                    ),
                    event_thread_ts,
                    role=ack_role,
                )
            elif kubeconfig_error:
                error_role = await _resolve_explicit_role_for_text(event_text)
                await send_slack_message(
                    event_channel,
                    (
                        ":warning: I found a kubeconfig-like attachment but could not use it: "
                        f"{kubeconfig_error}. Please upload a valid kubeconfig YAML."
                    ),
                    event_thread_ts,
                    role=error_role,
                )

        # Handle bot messages: process if they contain role mentions (handoffs/eval)
        # Per requirements: "Bot Messages: Router processes bot's own messages to detect handoffs"
        if is_bot_message:
            text = event.get("text", "")
            message_router = get_message_router()
            has_role_mention = bool(message_router.parse_role_mentions(text))
            if not has_role_mention:
                # Ignore bot messages without role mentions to prevent loops
                return {"status": "ignored", "reason": "bot_message_no_role_mention"}
            # Continue processing - bot message has a role mention (handoff or eval)
            logger.info(f"Processing bot message with role mention: {text[:80]}...")

        # Handle app_mention events
        if event_type == "app_mention":
            user_id = event.get("user", "")
            channel = event.get("channel", "")
            text = event.get("text", "")
            message_ts = event.get("ts", "")
            thread_ts = event.get("thread_ts") or message_ts

            # Resolve role from user mentions BEFORE stripping so role app
            # mentions like <@U_SUPPORT_BOT> are not lost.
            mention_roles = await _extract_roles_from_slack_user_mentions(text)

            # Strip only the ingress bot mention; preserve role app mentions
            # so downstream routing can still inspect them if needed.
            ingress_uid = await get_bot_user_id()
            if ingress_uid:
                clean_text = re.sub(rf"<@{re.escape(ingress_uid)}>\s*", "", text).strip()
            else:
                clean_text = re.sub(r"<@[A-Z0-9]+>\s*", "", text).strip()

            # If a role was detected via user mention but not via text-based
            # /Role syntax, inject it as a text role mention so the router
            # picks it up downstream.
            if mention_roles:
                message_router = get_message_router()
                text_roles = message_router.parse_role_mentions(clean_text)
                if not text_roles:
                    role_prefix = f"/{mention_roles[0]}"
                    clean_text = f"{role_prefix} {clean_text}"

            routed_text = _inject_thread_kubeconfig_context(clean_text, channel, thread_ts)

            if not routed_text:
                return {"status": "accepted", "event": "app_mention"}

            # Resolve role BEFORE reacting so the same bot adds and removes
            # thinking_face (Slack only allows the app that added a reaction
            # to remove it).
            _initial_role: str | None = mention_roles[0] if mention_roles else None
            if not _initial_role:
                _initial_role = await _resolve_explicit_role_for_text(routed_text)
            if not _initial_role:
                _initial_role = route_by_keywords(routed_text)

            if message_ts:
                await add_reaction(channel, message_ts, "thinking_face", role=_initial_role)

            await run_agent_for_slack(
                routed_text, channel, thread_ts, user_id, message_ts=message_ts
            )

            return {"status": "accepted", "event": "app_mention"}

        # Handle direct messages
        if event_type == "message" and event.get("channel_type") == "im":
            user_id = event.get("user", "")
            channel = event.get("channel", "")
            text = event.get("text", "")
            message_ts = event.get("ts", "")
            thread_ts = event.get("thread_ts") or message_ts
            routed_text = _inject_thread_kubeconfig_context(text, channel, thread_ts)

            if not routed_text:
                return {"status": "accepted", "event": "message.im"}

            # Resolve role BEFORE reacting (see app_mention for rationale).
            _dm_role = await _resolve_explicit_role_for_text(routed_text)
            if not _dm_role:
                _dm_role = route_by_keywords(routed_text)

            if message_ts:
                await add_reaction(channel, message_ts, "thinking_face", role=_dm_role)

            await run_agent_for_slack(
                routed_text, channel, thread_ts, user_id, message_ts=message_ts
            )

            return {"status": "accepted", "event": "message.im"}

        # Handle direct role mentions in channel messages even without ingress
        # app mention (e.g., "<@U_SUPPORT_BOT> please investigate").
        if event_type == "message" and not is_bot_message and event.get("channel_type") != "im":
            user_id = event.get("user", "")
            channel = event.get("channel", "")
            text = event.get("text", "")
            message_ts = event.get("ts", "")
            thread_ts = event.get("thread_ts") or message_ts

            message_router = get_message_router()
            parsed_role_mentions = message_router.parse_role_mentions(text)
            user_mention_roles = await _extract_roles_from_slack_user_mentions(text)
            explicit_roles: list[str] = []
            for role in [*parsed_role_mentions, *user_mention_roles]:
                if role not in explicit_roles:
                    explicit_roles.append(role)

            # If ingress app is explicitly mentioned, app_mention flow already handles
            # the message and this branch would duplicate processing.
            ingress_mentioned = await _mentions_ingress_bot(text)

            if explicit_roles and not ingress_mentioned:
                # Use resolved role for reaction identity consistency.
                _chan_role: str | None = explicit_roles[0] if explicit_roles else None
                if message_ts:
                    await add_reaction(channel, message_ts, "thinking_face", role=_chan_role)

                routed_text = text
                for role in explicit_roles:
                    display_name = get_slack_handle(role) or get_display_name(cast(AgentRole, role))
                    token = f"@{display_name}"
                    if token.lower() not in routed_text.lower():
                        routed_text = f"{token} {routed_text}".strip()
                routed_text = _inject_thread_kubeconfig_context(routed_text, channel, thread_ts)

                await run_agent_for_slack(
                    routed_text,
                    channel,
                    thread_ts,
                    user_id,
                    message_ts=message_ts,
                )

                return {"status": "accepted", "event": "message.channel_role_mention"}

        # Handle thread replies in threads where the bot has participated.
        # When VibeTeam participates in a thread (via app_mention or trigger),
        # subsequent user messages in the thread should be delivered to agents —
        # even without an explicit @mention of the bot.
        # We check two sources: in-memory subscriptions (fast) and, as a fallback,
        # the Slack thread history (stateless, survives pod restarts).
        thread_handler_match = (
            event_type == "message"
            and not is_bot_message
            and event.get("thread_ts")
            and event.get("channel_type") != "im"
        )
        logger.info(
            f"Thread handler check: match={thread_handler_match}, "
            f"event_type={event_type}, is_bot={is_bot_message}, "
            f"thread_ts={event.get('thread_ts')}, "
            f"channel_type={event.get('channel_type')}, "
            f"user={event.get('user')}, text={event.get('text', '')[:80]}"
        )
        if thread_handler_match:
            user_id = event.get("user", "")
            channel = event.get("channel", "")
            text = event.get("text", "")
            message_ts = event.get("ts", "")
            thread_ts = event.get("thread_ts", "")

            # Fast path: check in-memory subscriptions
            message_router = get_message_router()
            subscriptions = await message_router.get_subscriptions(
                source="slack",
                thread_id=thread_ts,
            )
            logger.info(
                f"Thread {thread_ts}: subscriptions={bool(subscriptions)}, "
                f"checking bot participation..."
            )

            # Slow path: if no subscriptions found (e.g. after pod restart),
            # check the actual Slack thread to see if the bot has replied before.
            participated = bool(subscriptions)
            if not participated:
                participated = await bot_participated_in_thread(channel, thread_ts)
                logger.info(f"Thread {thread_ts}: bot_participated={participated}")
                if participated:
                    logger.info(
                        f"No subscriptions for thread {thread_ts}, but bot "
                        f"participated in thread history. Processing message."
                    )

            if participated:
                if subscriptions:
                    logger.info(
                        f"Thread {thread_ts} has subscribed agents: "
                        f"{[s.agent_role for s in subscriptions]}. Processing message."
                    )

                # Resolve role from subscriptions or text so the correct bot
                # adds thinking_face (see app_mention handler for rationale).
                _thread_role: str | None = None
                if subscriptions:
                    _thread_role = subscriptions[0].agent_role
                if not _thread_role:
                    _thread_role = await _resolve_explicit_role_for_text(text)
                if not _thread_role:
                    _thread_role = route_by_keywords(text)

                if message_ts:
                    await add_reaction(channel, message_ts, "thinking_face", role=_thread_role)

                routed_text = _inject_thread_kubeconfig_context(text, channel, thread_ts)
                await run_agent_for_slack(
                    routed_text,
                    channel,
                    thread_ts,
                    user_id,
                    message_ts=message_ts,
                )

                return {"status": "accepted", "event": "message.subscribed_thread"}

        # Handle bot messages with role mentions in channels (handoffs and eval)
        # IMPORTANT: Bot messages posted by OUR OWN bot (via callback handler) that
        # contain @RoleName handoff mentions should NOT be re-processed here, because
        # the callback handler (handle_agent_callback) already submits handoff jobs.
        # Only process bot messages from OTHER bots (e.g., eval script trigger API)
        # or external integrations.
        if event_type == "message" and is_bot_message:
            channel = event.get("channel", "")
            text = event.get("text", "")
            message_ts = event.get("ts", "")
            thread_ts = event.get("thread_ts") or message_ts
            bot_id = event.get("bot_id", "")

            # Check if this message was posted by one of our own Slack apps.
            # Callback handlers already submit handoffs, so re-processing our own
            # thread replies here would cause duplicate agent executions.
            is_self_bot_message = False
            message_user = event.get("user", "")
            if message_user and thread_ts and thread_ts != message_ts:
                own_bot_user_ids = await _our_bot_user_ids()
                if message_user in own_bot_user_ids:
                    is_self_bot_message = True
                    logger.info(
                        "Skipping self-posted bot message from known VibeTeam bot "
                        f"user_id={message_user}: {text[:80]}..."
                    )

            if is_self_bot_message:
                return {"status": "ignored", "reason": "self_bot_handoff_already_handled"}

            user_id = bot_id or "bot"

            # React with thinking face to show we're processing the message
            if message_ts:
                await add_reaction(channel, message_ts, "thinking_face")

            await run_agent_for_slack(text, channel, thread_ts, user_id, message_ts=message_ts)

            return {"status": "accepted", "event": "message.bot_with_role_mention"}

        logger.info(
            f"Event fell through all handlers: event_type={event_type}, "
            f"is_bot_message={is_bot_message}, "
            f"has_thread_ts={bool(event.get('thread_ts'))}, "
            f"channel_type={event.get('channel_type')}"
        )
        return {"status": "ignored", "event": event_type}

    except Exception as e:
        logger.exception(f"Failed to process Slack event: {e}")
        return {"status": "error", "detail": str(e)}


@router.post("/slack/events")
async def handle_slack_events(
    request: Request,
    x_slack_request_timestamp: str = Header(None, alias="X-Slack-Request-Timestamp"),
    x_slack_signature: str = Header(None, alias="X-Slack-Signature"),
    x_slack_retry_num: str | None = Header(None, alias="X-Slack-Retry-Num"),
    x_slack_retry_reason: str | None = Header(None, alias="X-Slack-Retry-Reason"),
) -> dict[str, Any]:
    """Handle incoming Slack events."""
    payload_bytes = await request.body()
    payload = json.loads(payload_bytes)

    # Handle URL verification challenge first (Slack requires immediate response)
    if payload.get("type") == "url_verification":
        logger.info("Responding to Slack URL verification challenge")
        return {"challenge": payload.get("challenge")}

    if not config.SLACK_SIGNING_SECRET:
        logger.error("SLACK_SIGNING_SECRET is required for Slack event handling")
        raise HTTPException(status_code=503, detail="Slack signing secret not configured")

    # Verify signature for all other events
    if not verify_slack_signature(
        payload_bytes,
        x_slack_request_timestamp or "",
        x_slack_signature or "",
        config.SLACK_SIGNING_SECRET,
    ):
        logger.warning("Invalid Slack signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    event = payload.get("event", {})
    event_type = event.get("type")
    event_key = _slack_event_key(payload, event)

    if _is_duplicate_slack_event(event_key):
        logger.info(
            f"Ignoring duplicate Slack event: key={event_key}, "
            f"retry_num={x_slack_retry_num}, retry_reason={x_slack_retry_reason}"
        )
        return {"status": "ignored", "event": event_type, "reason": "duplicate_event"}

    if x_slack_retry_num:
        logger.info(
            f"Slack retry header received: retry_num={x_slack_retry_num}, "
            f"retry_reason={x_slack_retry_reason}"
        )

    # Process in background to avoid Slack retrying due to slow responses
    _schedule_background(_process_slack_event(payload))

    # Return immediately to satisfy Slack's 3s requirement
    event_label = event_type or "unknown"
    if event_type == "message":
        channel_type = event.get("channel_type")
        if channel_type == "im":
            event_label = "message.im"
        elif event.get("bot_id") or event.get("subtype") == "bot_message":
            event_label = "message.bot_with_role_mention"
        elif event.get("thread_ts"):
            event_label = "message.thread"

    return {"status": "accepted", "event": event_label}


@router.post("/slack/trigger")
async def trigger_agent_for_slack(
    request: Request,
    authorization: str = Header(None, alias="Authorization"),
) -> dict[str, Any]:
    """
    Directly trigger an agent for a Slack thread.

    This endpoint bypasses Slack webhooks and directly invokes the agent routing logic.
    Useful for:
    - E2E eval tests that post messages via Slack API but need to trigger agents
    - Manual testing and debugging
    - Programmatic agent invocation

    Authentication:
    - If SLACK_TRIGGER_SECRET is set, requires Bearer token in Authorization header.
    - If SLACK_TRIGGER_SECRET is not set, request is rejected (gateway misconfiguration).

    Request body:
    {
        "channel": "C0AATPSADB8",
        "thread_ts": "1234567890.123456",
        "text": "@SupportEngineer please investigate the issue",
        "user_id": "eval_script",
        "framework": "openclaw",
        "use_async": false,
        "kubeconfig_yaml": "apiVersion: v1 ...",
        "kubeconfig_file_name": "uploaded-kubeconfig.yaml"
    }

    Fields:
    - channel (required): Slack channel ID
    - text (required): Message text with @RoleName mention
    - thread_ts (optional): Thread timestamp to post in
    - user_id (optional): Identifier for the caller (default: "trigger_api")
    - framework (optional): Agent framework override (e.g., "openclaw")
    - use_async (optional, default: false): If true, uses the async callback flow
      (POST /run/async → agent processes → POST /callback/agent) instead of the
      synchronous path. Useful for testing the full async lifecycle including
      CALLBACK_SECRET verification.
    - kubeconfig_yaml (optional): Inline kubeconfig YAML used to seed
      thread-scoped kubeconfig context for this trigger.
    - kubeconfig_file_name (optional): Source filename label for the inline
      kubeconfig context (default: "uploaded-kubeconfig.yaml").
    """
    # Rate limiting
    if not _trigger_rate_limiter.allow():
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded for /slack/trigger. Try again later.",
        )

    # Verify trigger secret if configured
    if config.SLACK_TRIGGER_SECRET:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=401,
                detail="Authorization header with Bearer token required",
            )
        token = authorization.removeprefix("Bearer ").strip()
        if not hmac.compare_digest(token, config.SLACK_TRIGGER_SECRET):
            logger.warning("Invalid trigger secret in /slack/trigger request")
            raise HTTPException(status_code=403, detail="Invalid trigger secret")
    else:
        logger.error("SLACK_TRIGGER_SECRET is required for /slack/trigger")
        raise HTTPException(status_code=503, detail="Slack trigger secret not configured")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from None

    channel = body.get("channel")
    thread_ts = body.get("thread_ts")
    text = body.get("text", "")
    user_id = body.get("user_id", "trigger_api")
    use_async = body.get("use_async", False)
    framework = body.get("framework")
    kubeconfig_yaml = body.get("kubeconfig_yaml")
    kubeconfig_file_name = str(body.get("kubeconfig_file_name", "uploaded-kubeconfig.yaml"))

    if not channel:
        raise HTTPException(status_code=400, detail="channel is required")
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    kubeconfig_context_stored = False
    if isinstance(kubeconfig_yaml, str) and kubeconfig_yaml.strip():
        if not thread_ts:
            raise HTTPException(
                status_code=400,
                detail="thread_ts is required when kubeconfig_yaml is provided",
            )
        try:
            kube_context = _validate_and_normalize_kubeconfig(kubeconfig_yaml)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"invalid kubeconfig_yaml: {exc}") from exc
        kube_context["file_name"] = kubeconfig_file_name
        kube_context["source"] = "slack_trigger"
        _store_thread_kubeconfig_context(channel, thread_ts, kube_context)
        kubeconfig_context_stored = True

    # Check for role mentions
    message_router = get_message_router()
    role_mentions = message_router.parse_role_mentions(text)

    if not role_mentions:
        raise HTTPException(
            status_code=400,
            detail="text must contain @RoleName mention (e.g., @SupportEngineer)",
        )

    routed_text = _inject_thread_kubeconfig_context(text, channel, thread_ts)
    if not routed_text:
        raise HTTPException(status_code=400, detail="text is required")

    mode = "async" if use_async else "sync"
    logger.info(f"Trigger API: routing to {role_mentions} in {channel} (mode={mode})")

    # Process in background
    # use_async=True exercises the full /run/async → /callback/agent flow
    # use_async=False (default) uses the synchronous path
    asyncio.create_task(
        run_agent_for_slack(
            routed_text,
            channel,
            thread_ts,
            user_id,
            use_async=use_async,
            framework=framework,
        )
    )

    return {
        "status": "accepted",
        "channel": channel,
        "thread_ts": thread_ts,
        "roles": role_mentions,
        "mode": mode,
        "kubeconfig_context_stored": kubeconfig_context_stored,
    }
