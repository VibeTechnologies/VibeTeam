from __future__ import annotations

"""
Session management for agent state persistence.

Supports multiple storage backends:
- Local filesystem
- Redis
- S3

Session keys follow the format: {framework}:{role}:{context_type}:{context_id}
"""

import json
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.config import SessionConfig


@dataclass
class SessionState:
    """Represents the state of an agent session."""

    session_id: str
    framework: str
    role: str
    context_type: str  # "issue", "pr", "slack", "email"
    context_id: str
    messages: list[dict[str, Any]]
    metadata: dict[str, Any]
    created_at: str
    updated_at: str

    @classmethod
    def create(
        cls,
        framework: str,
        role: str,
        context_type: str,
        context_id: str,
    ) -> SessionState:
        """Create a new session state."""
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            session_id=str(uuid.uuid4()),
            framework=framework,
            role=role,
            context_type=context_type,
            context_id=context_id,
            messages=[],
            metadata={},
            created_at=now,
            updated_at=now,
        )

    @property
    def key(self) -> str:
        """Generate session key."""
        return f"{self.framework}:{self.role}:{self.context_type}:{self.context_id}"

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        """Add a message to the session."""
        self.messages.append(
            {
                "role": role,
                "content": content,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **kwargs,
            }
        )
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionState:
        """Create from dictionary."""
        return cls(**data)


class SessionStore(ABC):
    """Abstract base class for session storage."""

    @abstractmethod
    def save(self, session: SessionState) -> None:
        """Save a session."""
        pass

    @abstractmethod
    def load(self, key: str) -> SessionState | None:
        """Load a session by key."""
        pass

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete a session."""
        pass

    @abstractmethod
    def list_sessions(self, prefix: str = "") -> list[str]:
        """List session keys matching prefix."""
        pass


class LocalSessionStore(SessionStore):
    """Local filesystem session storage."""

    def __init__(self, storage_path: str = "./.sessions"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

    def _key_to_path(self, key: str) -> Path:
        """Convert session key to file path."""
        safe_key = key.replace(":", "_").replace("/", "_")
        return self.storage_path / f"{safe_key}.json"

    def save(self, session: SessionState) -> None:
        """Save session to local file."""
        path = self._key_to_path(session.key)
        with open(path, "w") as f:
            json.dump(session.to_dict(), f, indent=2)

    def load(self, key: str) -> SessionState | None:
        """Load session from local file."""
        path = self._key_to_path(key)
        if not path.exists():
            return None
        with open(path) as f:
            data = json.load(f)
        return SessionState.from_dict(data)

    def delete(self, key: str) -> None:
        """Delete session file."""
        path = self._key_to_path(key)
        if path.exists():
            path.unlink()

    def list_sessions(self, prefix: str = "") -> list[str]:
        """List session keys matching prefix."""
        safe_prefix = prefix.replace(":", "_").replace("/", "_")
        keys = []
        for path in self.storage_path.glob(f"{safe_prefix}*.json"):
            # Convert back from safe key to original
            key = path.stem.replace("_", ":", 3)  # Only replace first 3 for framework:role:type:id
            keys.append(key)
        return keys


class RedisSessionStore(SessionStore):
    """Redis session storage."""

    client: Any  # redis.Redis - typed as Any to avoid type checker issues
    ttl: int

    def __init__(self, redis_url: str, ttl_seconds: int = 86400 * 7):
        try:
            import redis

            self.client = redis.from_url(redis_url)
            self.ttl = ttl_seconds
        except ImportError as err:
            raise ImportError("redis package required for RedisSessionStore") from err

    def save(self, session: SessionState) -> None:
        """Save session to Redis."""
        self.client.setex(
            f"session:{session.key}",
            self.ttl,
            json.dumps(session.to_dict()),
        )

    def load(self, key: str) -> SessionState | None:
        """Load session from Redis."""
        data = self.client.get(f"session:{key}")
        if not data:
            return None
        data_str: str = data.decode() if isinstance(data, bytes) else str(data)
        return SessionState.from_dict(json.loads(data_str))

    def delete(self, key: str) -> None:
        """Delete session from Redis."""
        self.client.delete(f"session:{key}")

    def list_sessions(self, prefix: str = "") -> list[str]:
        """List session keys matching prefix."""
        pattern = f"session:{prefix}*"
        keys_list = list(self.client.keys(pattern))
        result: list[str] = []
        for k in keys_list:
            key_str: str = k.decode() if isinstance(k, bytes) else str(k)
            result.append(key_str.replace("session:", ""))
        return result


def create_session_store(config: SessionConfig) -> SessionStore:
    """Factory function to create appropriate session store."""
    if config.storage_type == "local":
        return LocalSessionStore(config.storage_path)
    elif config.storage_type == "redis":
        if not config.redis_url:
            raise ValueError("redis_url required for Redis storage")
        return RedisSessionStore(config.redis_url, config.ttl_seconds)
    else:
        raise ValueError(f"Unknown storage type: {config.storage_type}")


# Global session store (initialized on first use)
_session_store: SessionStore | None = None


def get_session_store(config: SessionConfig | None = None) -> SessionStore:
    """Get or create the global session store."""
    global _session_store
    if _session_store is None:
        if config is None:
            config = SessionConfig()
        _session_store = create_session_store(config)
    return _session_store


def get_or_create_session(
    framework: str,
    role: str,
    context_type: str,
    context_id: str,
    store: SessionStore | None = None,
) -> SessionState:
    """Get existing session or create a new one."""
    if store is None:
        store = get_session_store()

    key = f"{framework}:{role}:{context_type}:{context_id}"
    session = store.load(key)

    if session is None:
        session = SessionState.create(framework, role, context_type, context_id)
        store.save(session)

    return session
