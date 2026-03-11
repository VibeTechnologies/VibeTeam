"""Shared LLM utilities for OpenHands agents.

Azure OpenAI doesn't support the Responses API endpoint. All agents must use
AzureLLM (which forces the completion API) instead of the base LLM class.

This module is the single source of truth for AzureLLM — do NOT define it
in individual agent files.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests

logger = logging.getLogger(__name__)

RESPONSES_ONLY_MODELS = {"gpt-5.2-codex"}
RESPONSES_MIN_API_VERSION = (2025, 3, 1)


def _parse_api_version(version: str | None) -> tuple[int, int, int] | None:
    if not version:
        return None
    parts = version.split("-")
    if len(parts) < 3:
        return None
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None


def _azure_api_version_supports_responses(version: str | None) -> bool:
    parsed = _parse_api_version(version)
    if not parsed:
        return False
    return parsed >= RESPONSES_MIN_API_VERSION


def _azure_allow_responses_models() -> bool:
    flag = os.getenv("AZURE_ALLOW_RESPONSES_MODELS", "").lower() in {"1", "true", "yes"}
    if not flag:
        return False
    return _azure_api_version_supports_responses(os.getenv("AZURE_API_VERSION"))


try:
    from openhands.sdk import LLM

    OPENHANDS_LLM_AVAILABLE = True

    class AzureLLM(LLM):
        """LLM subclass with Azure-specific Responses API handling.

        Azure OpenAI supports the Responses API only for newer API versions.
        We default to chat completions unless responses are explicitly enabled.
        """

        def uses_responses_api(self) -> bool:
            """Enable responses API only when explicitly allowed and required."""
            if not _azure_allow_responses_models():
                return False
            model_name = _normalize_model_name(getattr(self, "model", None))
            return model_name in RESPONSES_ONLY_MODELS

except ImportError:
    OPENHANDS_LLM_AVAILABLE = False

    class LLM:  # type: ignore[no-redef]
        """Fallback LLM client for environments without OpenHands SDK.

        Uses Azure OpenAI Chat Completions directly so OpenHands role tests can
        execute on Python 3.11 where openhands-ai is unavailable.
        """

        def __init__(
            self,
            model: str,
            api_key: str | None = None,
            base_url: str | None = None,
            api_version: str | None = None,
            max_output_tokens: int = 4096,
            timeout: int = 300,
            num_retries: int = 3,
            **kwargs: Any,
        ):
            self.model = model
            self.api_key = api_key or os.getenv("AZURE_API_KEY")
            self.base_url = (
                base_url or os.getenv("AZURE_OPENAI_ENDPOINT") or os.getenv("AZURE_API_BASE")
            )
            self.api_version = api_version or os.getenv("AZURE_API_VERSION", "2024-08-01-preview")
            self.max_output_tokens = max_output_tokens
            self.timeout = timeout
            self.num_retries = num_retries
            self.extra_kwargs = kwargs

        def uses_responses_api(self) -> bool:
            return False

        def _deployment_name(self) -> str:
            return self.model.split("/", 1)[1] if self.model.startswith("azure/") else self.model

        @staticmethod
        def _normalize_azure_endpoint(api_base: str | None) -> str | None:
            if not api_base:
                return None
            raw = api_base.rstrip("/")
            parsed = urlsplit(raw)
            if not parsed.scheme or not parsed.netloc:
                return raw

            path = parsed.path.rstrip("/")
            if path.endswith("/openai"):
                path = path[: -len("/openai")]
            elif "/openai/" in path:
                path = path.split("/openai/", 1)[0]
            if path and not path.startswith("/"):
                path = f"/{path}"
            return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))

        @staticmethod
        def _coerce_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
            normalized: list[dict[str, str]] = []
            for message in messages:
                role = str(message.get("role", "user"))
                content = message.get("content", "")
                if isinstance(content, list):
                    parts: list[str] = []
                    for item in content:
                        if isinstance(item, dict):
                            parts.append(str(item.get("text", item.get("content", ""))))
                        else:
                            parts.append(str(item))
                    text = "\n".join(part for part in parts if part)
                else:
                    text = str(content)
                normalized.append({"role": role, "content": text})
            return normalized

        def complete(self, messages: list[dict[str, Any]]) -> str:
            endpoint = self._normalize_azure_endpoint(self.base_url)
            if not self.api_key or not endpoint:
                raise RuntimeError("Azure LLM fallback missing AZURE_API_KEY or AZURE_API_BASE")

            from openai import AzureOpenAI

            client = AzureOpenAI(
                api_key=self.api_key,
                azure_endpoint=endpoint,
                api_version=self.api_version,
                timeout=self.timeout,
                max_retries=self.num_retries,
            )

            response = client.chat.completions.create(
                model=self._deployment_name(),
                messages=self._coerce_messages(messages),
                max_tokens=self.max_output_tokens,
            )
            message = response.choices[0].message.content if response.choices else ""
            if isinstance(message, list):
                return "".join(
                    part.get("text", "") if isinstance(part, dict) else str(part) for part in message
                ).strip()
            return (message or "").strip()

    class AzureLLM(LLM):  # type: ignore[no-redef]
        """Fallback Azure-specific LLM wrapper."""


def resolve_azure_model(
    model: str | None,
    *,
    api_base: str | None = None,
    allow_responses_models: bool | None = None,
    api_version: str | None = None,
) -> str | None:
    """Resolve Azure model names that are Responses-only.

    Azure OpenAI does not currently support the /responses API. If a model is
    marked as responses-only in LiteLLM (e.g., gpt-5.2-codex), we must fall back
    to a chat-completions-compatible model to avoid 404s.
    """
    if not model:
        return None

    normalized = model.split("/", 1)[1] if model.startswith("azure/") else model
    api_base = _normalize_api_base(
        api_base or os.getenv("AZURE_OPENAI_ENDPOINT") or os.getenv("AZURE_API_BASE")
    )

    if not api_base or "openai.azure.com" not in api_base:
        return model

    if allow_responses_models is None:
        allow_responses_models = _azure_allow_responses_models()

    if allow_responses_models and _azure_api_version_supports_responses(
        api_version or os.getenv("AZURE_API_VERSION")
    ):
        return model

    if normalized in RESPONSES_ONLY_MODELS:
        logger.warning(
            "Azure does not support /responses; falling back from %s to gpt-5.2",
            model,
        )
        return "gpt-5.2"

    return model


def _normalize_model_name(model: str | None) -> str | None:
    if not model:
        return None
    if model.startswith("azure/"):
        return model.split("/", 1)[1]
    return model


def _normalize_api_base(api_base: str | None) -> str | None:
    if not api_base:
        return None
    return api_base.rstrip("/")


def _is_azure_endpoint(api_base: str | None) -> bool:
    if not api_base:
        return False
    return "openai.azure.com" in api_base


def _extract_context_window(data: Any) -> int | None:
    """Extract a context window integer from a nested API response."""
    if not data:
        return None

    preferred_keys = [
        "context_window",
        "context_length",
        "max_context_length",
        "max_input_tokens",
        "input_token_limit",
        "n_ctx",
        "max_sequence_length",
        "max_seq_len",
    ]

    def _coerce_int(value: Any) -> int | None:
        try:
            if isinstance(value, bool):
                return None
            if isinstance(value, (int, float)):
                return int(value)
            if isinstance(value, str) and value.isdigit():
                return int(value)
        except Exception:
            return None
        return None

    def _find_key(obj: Any, key: str) -> int | None:
        if isinstance(obj, dict):
            if key in obj:
                val = _coerce_int(obj.get(key))
                if val:
                    return val
            for v in obj.values():
                found = _find_key(v, key)
                if found:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = _find_key(item, key)
                if found:
                    return found
        return None

    for k in preferred_keys:
        found = _find_key(data, k)
        if found:
            return found

    return None


@lru_cache(maxsize=16)
def get_model_context_window(
    model: str | None,
    *,
    api_base: str | None = None,
    api_key: str | None = None,
    api_version: str | None = None,
    timeout: float = 5.0,
) -> int | None:
    """Fetch model context window via API, if available.

    Tries Azure deployment metadata first when using Azure, then falls back
    to OpenAI's models endpoint when possible.
    """
    model_name = _normalize_model_name(model)
    if not model_name:
        return None

    api_base = _normalize_api_base(api_base)
    api_version = api_version or os.getenv("AZURE_API_VERSION", "2024-08-01-preview")

    # Azure OpenAI deployment metadata
    if _is_azure_endpoint(api_base):
        if not api_key:
            api_key = os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("AZURE_API_KEY")
        if not api_key or not api_base:
            return None

        try:
            url = f"{api_base}/openai/deployments/{model_name}"
            resp = requests.get(
                url,
                headers={"api-key": api_key},
                params={"api-version": api_version},
                timeout=timeout,
            )
            if resp.ok:
                data = resp.json()
                ctx = _extract_context_window(data)
                if ctx:
                    return ctx

                # If deployment metadata doesn't include context, try model name
                model_id = data.get("model") or data.get("model_name")
                if model_id:
                    model_id = _normalize_model_name(model_id)
                    ctx = get_model_context_window(
                        model_id,
                        api_base=os.getenv("OPENAI_API_BASE"),
                        api_key=os.getenv("OPENAI_API_KEY"),
                        timeout=timeout,
                    )
                    if ctx:
                        return ctx
            else:
                logger.debug(
                    "Azure deployment metadata fetch failed (%s): %s",
                    resp.status_code,
                    resp.text[:200],
                )
        except Exception as e:
            logger.debug("Azure deployment metadata fetch error: %s", e)

        # Azure models listing (best-effort; may not be supported)
        try:
            url = f"{api_base}/openai/models"
            resp = requests.get(
                url,
                headers={"api-key": api_key},
                params={"api-version": api_version},
                timeout=timeout,
            )
            if resp.ok:
                data = resp.json()
                ctx = _extract_context_window(data)
                if ctx:
                    return ctx
        except Exception:
            pass

    # OpenAI models endpoint
    if not api_base:
        api_base = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
    if not api_key:
        api_key = os.getenv("OPENAI_API_KEY")
    if api_base and api_key:
        api_base = _normalize_api_base(api_base)
        if not api_base.endswith("/v1"):
            api_base = f"{api_base}/v1"
        try:
            url = f"{api_base}/models/{model_name}"
            resp = requests.get(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=timeout,
            )
            if resp.ok:
                data = resp.json()
                ctx = _extract_context_window(data)
                if ctx:
                    return ctx
            else:
                logger.debug(
                    "OpenAI model metadata fetch failed (%s): %s",
                    resp.status_code,
                    resp.text[:200],
                )
        except Exception as e:
            logger.debug("OpenAI model metadata fetch error: %s", e)

    return None


__all__ = [
    "AzureLLM",
    "LLM",
    "OPENHANDS_LLM_AVAILABLE",
    "get_model_context_window",
    "resolve_azure_model",
]
