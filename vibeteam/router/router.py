"""
Message Router for VibeTeam.

Routes messages to appropriate agents based on @RoleName mentions
and thread subscriptions.
"""

import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from agent_service.shared.role_resolver import (
    get_display_name as _get_display_name,
)
from agent_service.shared.role_resolver import (
    parse_role_mentions as _parse_role_mentions,
)
from vibeteam.router.db import SubscriptionDB, get_subscription_db
from vibeteam.router.models import (
    AgentRole,
    MessageSource,
    ThreadSubscription,
    UnifiedMessage,
)

logger = logging.getLogger(__name__)


@dataclass
class RouteResult:
    """Result of routing a message."""

    message: UnifiedMessage
    mentioned_roles: Sequence[AgentRole]  # Roles explicitly mentioned in this message
    subscribed_roles: Sequence[AgentRole]  # All roles subscribed to this thread
    is_new_thread: bool  # True if this message started a new thread


class Router:
    """
    Thread-based message router with @RoleName mentions.

    Workflow:
    1. Parse @RoleName mentions from message content
    2. Subscribe mentioned agents to the thread
    3. Forward message to all subscribed agents

    Mention patterns:
    - @SoftwareEngineer, @ReleaseEngineer, etc. (@ prefix - preferred)
    - /SoftwareEngineer, /ReleaseEngineer, etc. (/ prefix - also supported)
    - @einstein, @grace, @ada, etc. (persona names)
    - @swe, @pm, @dev, etc. (short aliases)
    """

    def __init__(
        self,
        db: SubscriptionDB | None = None,
        on_forward: Callable[[UnifiedMessage, AgentRole, str], None] | None = None,
    ):
        """
        Initialize the router.

        Args:
            db: Subscription database. Uses singleton if not provided.
            on_forward: Callback when forwarding message to an agent.
                       Receives (message, role, session_id).
        """
        self.db = db or get_subscription_db()
        self.on_forward = on_forward

    def parse_role_mentions(self, text: str) -> list[AgentRole]:
        """
        Extract role mentions from message text.

        Delegates to agents.shared.role_resolver.parse_role_mentions
        which is the single source of truth for role parsing.

        Args:
            text: Message content to parse

        Returns:
            List of normalized role names (e.g., ["software_engineer"])
        """
        return _parse_role_mentions(text)

    async def route_message(self, message: UnifiedMessage) -> RouteResult:
        """
        Route a message to appropriate agents.

        Steps:
        1. Parse /RoleName mentions from message
        2. Subscribe mentioned agents to thread
        3. Get all subscribed agents
        4. Forward to each agent via callback

        Args:
            message: The unified message to route

        Returns:
            RouteResult with routing details
        """
        # 1. Parse role mentions
        mentioned_roles = self.parse_role_mentions(message.content)
        logger.info(
            f"Parsed mentions from message: {mentioned_roles}",
            extra={"thread_id": message.thread_id, "source": message.source},
        )

        # 2. Subscribe mentioned agents
        for role in mentioned_roles:
            session_id = str(uuid.uuid4())
            await self.db.subscribe(
                source=message.source,
                thread_id=message.thread_id,
                agent_role=role,
                session_id=session_id,
            )
            logger.info(
                f"Subscribed {role} to thread {message.thread_id}",
                extra={"session_id": session_id},
            )

        # 3. Get all subscribed agents
        subscriptions = await self.db.get_subscribed_agents(
            source=message.source,
            thread_id=message.thread_id,
        )
        subscribed_roles: list[AgentRole] = [s.agent_role for s in subscriptions]

        # 4. Forward to each subscribed agent
        is_new_thread = len(subscriptions) == len(mentioned_roles)

        if self.on_forward and not message.is_bot:
            for sub in subscriptions:
                try:
                    self.on_forward(message, sub.agent_role, sub.session_id)
                except Exception as e:
                    logger.error(
                        f"Error forwarding to {sub.agent_role}: {e}",
                        extra={"session_id": sub.session_id},
                    )

        return RouteResult(
            message=message,
            mentioned_roles=mentioned_roles,
            subscribed_roles=subscribed_roles,
            is_new_thread=is_new_thread,
        )

    async def handle_bot_message(self, message: UnifiedMessage) -> RouteResult:
        """
        Handle a message from our bot (for handoff detection).

        When the bot posts a message with /RoleName mentions,
        those agents are subscribed to the thread and the message
        is forwarded to them.

        Args:
            message: Bot message to process

        Returns:
            RouteResult with routing details
        """
        if not message.is_bot:
            logger.warning("handle_bot_message called with non-bot message")
            return await self.route_message(message)

        # Parse role mentions (handoffs)
        mentioned_roles = self.parse_role_mentions(message.content)

        if not mentioned_roles:
            # No handoff, nothing to do
            return RouteResult(
                message=message,
                mentioned_roles=[],
                subscribed_roles=[],
                is_new_thread=False,
            )

        logger.info(
            f"Detected handoff to: {mentioned_roles}",
            extra={"thread_id": message.thread_id},
        )

        # Subscribe and forward to mentioned agents
        for role in mentioned_roles:
            session_id = str(uuid.uuid4())
            await self.db.subscribe(
                source=message.source,
                thread_id=message.thread_id,
                agent_role=role,
                session_id=session_id,
            )

            if self.on_forward:
                try:
                    self.on_forward(message, role, session_id)
                except Exception as e:
                    logger.error(f"Error forwarding handoff to {role}: {e}")

        # Get updated subscriptions
        subscriptions = await self.db.get_subscribed_agents(
            source=message.source,
            thread_id=message.thread_id,
        )

        return RouteResult(
            message=message,
            mentioned_roles=mentioned_roles,
            subscribed_roles=[s.agent_role for s in subscriptions],
            is_new_thread=False,
        )

    async def get_subscriptions(
        self,
        source: MessageSource,
        thread_id: str,
    ) -> list[ThreadSubscription]:
        """Get all subscriptions for a thread."""
        return await self.db.get_subscribed_agents(source, thread_id)

    @staticmethod
    def get_display_name(role: AgentRole) -> str:
        """Get the display name for a role (for message prefixes)."""
        return _get_display_name(role)
