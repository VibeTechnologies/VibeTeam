"""
SharedMessageState - Shared message context for supervisor visibility.

This module implements the shared state that enables full message visibility
across all agents in the Swarm pattern. The supervisor can see all messages
from sub-agents, enabling true collaborative workflows.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass
class SwarmMessage:
    """A message in the swarm conversation."""

    role: str  # "system", "user", "assistant", "tool"
    content: str
    name: str | None = None  # Agent name or tool name
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    tool_call_id: str | None = None
    tool_calls: list[dict] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result: dict[str, Any] = {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
        }
        if self.name:
            result["name"] = self.name
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            result["tool_calls"] = self.tool_calls
        if self.metadata:
            result["metadata"] = self.metadata
        return result

    def to_llm_message(self) -> dict[str, Any]:
        """Convert to LLM-compatible message format."""
        msg: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name and self.role == "tool":
            msg["name"] = self.name
        if self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            msg["tool_calls"] = self.tool_calls
        return msg


@dataclass
class SharedMessageState:
    """
    Shared message state for supervisor visibility.

    All agents in the swarm read from and write to this shared state.
    This enables:
    - Full supervisor visibility into sub-agent conversations
    - Context sharing between agents during handoffs
    - Complete audit trail of the swarm session
    """

    messages: list[SwarmMessage] = field(default_factory=list)
    current_agent: str = "supervisor"
    session_id: str = field(default_factory=lambda: str(uuid4()))
    task_context: dict[str, Any] = field(default_factory=dict)
    agents_used: list[str] = field(default_factory=list)
    iteration_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def add_message(
        self,
        role: str,
        content: str,
        agent_name: str | None = None,
        tool_call_id: str | None = None,
        tool_calls: list[dict] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SwarmMessage:
        """
        Add a message to shared state.

        Args:
            role: Message role (system, user, assistant, tool)
            content: Message content
            agent_name: Name of the agent that produced this message
            tool_call_id: Tool call ID if this is a tool response
            tool_calls: Tool calls if this is an assistant message with tool invocations
            metadata: Additional metadata

        Returns:
            The created SwarmMessage
        """
        message = SwarmMessage(
            role=role,
            content=content,
            name=agent_name,
            tool_call_id=tool_call_id,
            tool_calls=tool_calls,
            metadata=metadata or {},
        )
        self.messages.append(message)

        # Track agent usage
        if agent_name and agent_name not in self.agents_used:
            self.agents_used.append(agent_name)

        return message

    def add_handoff(self, from_agent: str, to_agent: str, task: str) -> SwarmMessage:
        """
        Record a handoff between agents.

        Args:
            from_agent: Agent handing off
            to_agent: Agent receiving the handoff
            task: Task being handed off

        Returns:
            The created handoff message
        """
        self.current_agent = to_agent
        return self.add_message(
            role="system",
            content=f"[Handoff] {from_agent} -> {to_agent}: {task}",
            agent_name=from_agent,
            metadata={"type": "handoff", "from": from_agent, "to": to_agent, "task": task},
        )

    def get_context_for_agent(self, agent_name: str, include_system: bool = True) -> list[dict]:
        """
        Get relevant context for an agent.

        Returns messages in LLM-compatible format.

        Args:
            agent_name: Name of the agent requesting context
            include_system: Whether to include system messages

        Returns:
            List of messages in LLM format
        """
        result = []
        for msg in self.messages:
            if not include_system and msg.role == "system":
                continue
            result.append(msg.to_llm_message())
        return result

    def get_recent_messages(self, count: int = 10) -> list[SwarmMessage]:
        """Get the most recent messages."""
        return self.messages[-count:]

    def get_messages_by_agent(self, agent_name: str) -> list[SwarmMessage]:
        """Get all messages from a specific agent."""
        return [m for m in self.messages if m.name == agent_name]

    def get_last_user_message(self) -> SwarmMessage | None:
        """Get the most recent user message."""
        for msg in reversed(self.messages):
            if msg.role == "user":
                return msg
        return None

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of the state."""
        return {
            "session_id": self.session_id,
            "current_agent": self.current_agent,
            "message_count": len(self.messages),
            "agents_used": self.agents_used,
            "iteration_count": self.iteration_count,
            "created_at": self.created_at.isoformat(),
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize the entire state to a dictionary."""
        return {
            "session_id": self.session_id,
            "current_agent": self.current_agent,
            "messages": [m.to_dict() for m in self.messages],
            "task_context": self.task_context,
            "agents_used": self.agents_used,
            "iteration_count": self.iteration_count,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SharedMessageState":
        """Deserialize state from a dictionary."""
        state = cls(
            session_id=data.get("session_id", str(uuid4())),
            current_agent=data.get("current_agent", "supervisor"),
            task_context=data.get("task_context", {}),
            agents_used=data.get("agents_used", []),
            iteration_count=data.get("iteration_count", 0),
        )

        if "created_at" in data:
            state.created_at = datetime.fromisoformat(data["created_at"])

        for msg_data in data.get("messages", []):
            state.messages.append(
                SwarmMessage(
                    role=msg_data["role"],
                    content=msg_data["content"],
                    name=msg_data.get("name"),
                    timestamp=datetime.fromisoformat(
                        msg_data.get("timestamp", datetime.now(timezone.utc).isoformat())
                    ),
                    tool_call_id=msg_data.get("tool_call_id"),
                    tool_calls=msg_data.get("tool_calls"),
                    metadata=msg_data.get("metadata", {}),
                )
            )

        return state

    def clear(self) -> None:
        """Clear all messages and reset state."""
        self.messages = []
        self.agents_used = []
        self.iteration_count = 0
        self.current_agent = "supervisor"
