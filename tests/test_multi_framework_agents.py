"""
Tests for multi-framework agent implementations.

Tests the agents/ package with OpenHands, CrewAI, and AutoGen frameworks.
"""

import os
from unittest.mock import patch

import pytest

from agents import AgentFramework, AgentRole
from agents.config import (
    MCP_SERVERS,
    LLMConfig,
    MCPServerConfig,
    SessionConfig,
    get_mcp_config_dict,
)
from agents.sessions import (
    LocalSessionStore,
    SessionState,
    get_or_create_session,
)


class TestAgentEnums:
    """Test AgentFramework and AgentRole enums."""

    def test_agent_frameworks(self):
        """Test all framework values exist."""
        assert AgentFramework.OPENHANDS.value == "openhands"
        assert AgentFramework.CREWAI.value == "crewai"
        assert AgentFramework.AUTOGEN.value == "autogen"

    def test_agent_roles(self):
        """Test all role values exist."""
        assert AgentRole.RELEASE_ENGINEER.value == "release_engineer"
        assert AgentRole.MARKETING_MANAGER.value == "marketing_manager"
        assert AgentRole.SUPPORT_ENGINEER.value == "support_engineer"


class TestConfig:
    """Test agent configuration."""

    def test_llm_config_defaults(self):
        """Test LLM config has correct defaults."""
        config = LLMConfig()
        # Model comes from AZURE_OPENAI_DEPLOYMENT env or defaults to gpt-4.1-mini
        assert config.model is not None
        assert config.temperature == 0.7
        assert config.max_tokens == 4096

    def test_llm_config_custom(self):
        """Test LLM config with custom values."""
        config = LLMConfig(
            model="gpt-4",
            api_base="https://api.example.com",
            api_key="test-key",
            temperature=0.5,
        )
        assert config.model == "gpt-4"
        assert config.api_base == "https://api.example.com"
        assert config.api_key == "test-key"
        assert config.temperature == 0.5

    def test_session_config_defaults(self):
        """Test session config has correct defaults."""
        config = SessionConfig()
        assert config.storage_type == "local"
        # Default is /tmp/.sessions if SESSION_STORAGE_PATH not set
        assert config.storage_path == os.getenv("SESSION_STORAGE_PATH", "/tmp/.sessions")
        assert config.ttl_seconds == 86400 * 7

    def test_mcp_server_config(self):
        """Test MCP server configuration."""
        config = MCPServerConfig(
            command="npx",
            args=["-y", "test-server"],
            env={"KEY": "value"},
        )
        assert config.command == "npx"
        assert config.args == ["-y", "test-server"]
        assert config.env == {"KEY": "value"}

    def test_mcp_servers_exist(self):
        """Test standard MCP servers are configured."""
        assert "gmail" in MCP_SERVERS
        assert "gcalendar" in MCP_SERVERS
        assert "chrome" in MCP_SERVERS
        assert "github" in MCP_SERVERS
        assert "filesystem" in MCP_SERVERS
        assert "sentry" in MCP_SERVERS

    def test_get_mcp_config_dict(self):
        """Test MCP config conversion to dict."""
        servers = {"test": MCPServerConfig(command="npx", args=["test"])}
        result = get_mcp_config_dict(servers)
        assert "mcpServers" in result
        assert "test" in result["mcpServers"]
        assert result["mcpServers"]["test"]["command"] == "npx"


class TestSessionState:
    """Test session state management."""

    def test_create_session(self):
        """Test session creation."""
        session = SessionState.create(
            framework="autogen",
            role="release_engineer",
            context_type="issue",
            context_id="123",
        )
        assert session.framework == "autogen"
        assert session.role == "release_engineer"
        assert session.context_type == "issue"
        assert session.context_id == "123"
        assert session.messages == []
        assert session.session_id is not None

    def test_session_key(self):
        """Test session key generation."""
        session = SessionState.create(
            framework="crewai",
            role="marketing_manager",
            context_type="slack",
            context_id="channel123",
        )
        assert session.key == "crewai:marketing_manager:slack:channel123"

    def test_add_message(self):
        """Test adding messages to session."""
        session = SessionState.create(
            framework="openhands",
            role="support_engineer",
            context_type="email",
            context_id="email456",
        )
        session.add_message("user", "Hello")
        session.add_message("assistant", "Hi there")
        assert len(session.messages) == 2
        assert session.messages[0]["role"] == "user"
        assert session.messages[0]["content"] == "Hello"

    def test_session_serialization(self):
        """Test session to/from dict."""
        session = SessionState.create(
            framework="autogen",
            role="release_engineer",
            context_type="pr",
            context_id="42",
        )
        session.add_message("user", "Deploy please")

        data = session.to_dict()
        restored = SessionState.from_dict(data)

        assert restored.framework == session.framework
        assert restored.role == session.role
        assert restored.session_id == session.session_id
        assert len(restored.messages) == 1


class TestLocalSessionStore:
    """Test local filesystem session storage."""

    def test_save_and_load(self, tmp_path):
        """Test saving and loading sessions."""
        store = LocalSessionStore(str(tmp_path))
        session = SessionState.create(
            framework="autogen",
            role="release_engineer",
            context_type="test",
            context_id="1",
        )
        session.add_message("user", "Test message")

        store.save(session)
        loaded = store.load(session.key)

        assert loaded is not None
        assert loaded.session_id == session.session_id
        assert len(loaded.messages) == 1

    def test_load_nonexistent(self, tmp_path):
        """Test loading non-existent session returns None."""
        store = LocalSessionStore(str(tmp_path))
        result = store.load("nonexistent:key:here:123")
        assert result is None

    def test_delete(self, tmp_path):
        """Test deleting sessions."""
        store = LocalSessionStore(str(tmp_path))
        session = SessionState.create(
            framework="autogen",
            role="release_engineer",
            context_type="test",
            context_id="2",
        )
        store.save(session)
        store.delete(session.key)
        assert store.load(session.key) is None

    def test_list_sessions(self, tmp_path):
        """Test listing sessions with prefix."""
        store = LocalSessionStore(str(tmp_path))

        # Create multiple sessions
        for i in range(3):
            session = SessionState.create(
                framework="autogen",
                role="release_engineer",
                context_type="test",
                context_id=str(i),
            )
            store.save(session)

        # Create one with different framework
        session = SessionState.create(
            framework="crewai",
            role="release_engineer",
            context_type="test",
            context_id="0",
        )
        store.save(session)

        # List all
        all_sessions = store.list_sessions()
        assert len(all_sessions) == 4

        # List with prefix
        autogen_sessions = store.list_sessions("autogen")
        assert len(autogen_sessions) == 3


class TestGetOrCreateSession:
    """Test session retrieval/creation helper."""

    def test_creates_new_session(self, tmp_path):
        """Test creating new session when none exists."""
        store = LocalSessionStore(str(tmp_path))
        with patch("agents.sessions.get_session_store", return_value=store):
            session = get_or_create_session(
                framework="autogen",
                role="support_engineer",
                context_type="email",
                context_id="new123",
                store=store,
            )
            assert session.framework == "autogen"
            assert session.role == "support_engineer"

    def test_retrieves_existing_session(self, tmp_path):
        """Test retrieving existing session."""
        store = LocalSessionStore(str(tmp_path))

        # Create and save a session
        existing = SessionState.create(
            framework="autogen",
            role="support_engineer",
            context_type="email",
            context_id="existing123",
        )
        existing.add_message("user", "Previous message")
        store.save(existing)

        with patch("agents.sessions.get_session_store", return_value=store):
            session = get_or_create_session(
                framework="autogen",
                role="support_engineer",
                context_type="email",
                context_id="existing123",
                store=store,
            )
            assert session.session_id == existing.session_id
            assert len(session.messages) == 1


class TestAutoGenTools:
    """Test AutoGen agent tools."""

    @pytest.mark.asyncio
    async def test_execute_shell(self):
        """Test shell command execution."""
        from agents.autogen.release_engineer import execute_shell

        result = await execute_shell("echo hello")
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_read_file(self, tmp_path):
        """Test file reading."""
        from agents.autogen.release_engineer import read_file

        # Create test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        result = await read_file(str(test_file))
        assert result == "test content"

    @pytest.mark.asyncio
    async def test_read_file_not_found(self):
        """Test reading non-existent file."""
        from agents.autogen.release_engineer import read_file

        result = await read_file("/nonexistent/path/file.txt")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_write_file(self, tmp_path):
        """Test file writing."""
        from agents.autogen.release_engineer import write_file

        test_file = tmp_path / "output.txt"
        result = await write_file(str(test_file), "new content")
        assert "Successfully" in result
        assert test_file.read_text() == "new content"

    @pytest.mark.asyncio
    async def test_list_directory(self, tmp_path):
        """Test directory listing."""
        from agents.autogen.release_engineer import list_directory

        # Create some files
        (tmp_path / "file1.txt").write_text("a")
        (tmp_path / "file2.txt").write_text("bb")
        (tmp_path / "subdir").mkdir()

        result = await list_directory(str(tmp_path))
        assert "file1.txt" in result
        assert "file2.txt" in result
        assert "[DIR]" in result
        assert "subdir" in result


class TestMarketingTools:
    """Test Marketing Manager tools."""

    @pytest.mark.asyncio
    async def test_web_search(self):
        """Test web search tool."""
        from agents.autogen.marketing_manager import web_search

        result = await web_search("test query")
        assert "test query" in result

    @pytest.mark.asyncio
    async def test_create_social_post_twitter(self):
        """Test Twitter post creation."""
        from agents.autogen.marketing_manager import create_social_post

        result = await create_social_post(
            platform="twitter",
            content="Test post",
            hashtags="#test #ai",
        )
        assert "Twitter" in result
        assert "280" in result
        assert "#test" in result

    @pytest.mark.asyncio
    async def test_create_social_post_linkedin(self):
        """Test LinkedIn post creation."""
        from agents.autogen.marketing_manager import create_social_post

        result = await create_social_post(
            platform="linkedin",
            content="Test LinkedIn post",
        )
        assert "LinkedIn" in result

    @pytest.mark.asyncio
    async def test_analyze_sentiment(self):
        """Test sentiment analysis."""
        from agents.autogen.marketing_manager import analyze_sentiment

        positive = await analyze_sentiment("This is great and amazing!")
        assert "Positive" in positive

        negative = await analyze_sentiment("This is terrible and awful!")
        assert "Negative" in negative


class TestSupportTools:
    """Test Support Engineer tools."""

    @pytest.mark.asyncio
    async def test_list_emails(self):
        """Test email listing."""
        from agents.autogen.support_engineer import list_emails

        result = await list_emails(label="INBOX", max_results=5)
        assert "INBOX" in result

    @pytest.mark.asyncio
    async def test_send_email_invalid(self):
        """Test sending to invalid email."""
        from agents.autogen.support_engineer import send_email

        result = await send_email(
            to="invalid",
            subject="Test",
            body="Test body",
        )
        assert "Invalid" in result

    @pytest.mark.asyncio
    async def test_send_email_valid(self):
        """Test sending to valid email."""
        from agents.autogen.support_engineer import send_email

        result = await send_email(
            to="test@example.com",
            subject="Test Subject",
            body="Test body content",
        )
        assert "test@example.com" in result
        assert "Test Subject" in result

    @pytest.mark.asyncio
    async def test_create_support_ticket(self):
        """Test support ticket creation."""
        from agents.autogen.support_engineer import create_support_ticket

        result = await create_support_ticket(
            customer_email="customer@test.com",
            subject="Help needed",
            description="I need help with something",
            priority="high",
        )
        assert "TKT-" in result
        assert "customer@test.com" in result
        assert "HIGH" in result


class TestTeamRouting:
    """Test team routing logic."""

    def test_parse_mention_release_engineer(self):
        """Test @ReleaseEngineer mention parsing."""
        from agents.autogen.team import AutoGenTeam

        # Skip if AutoGen not available
        try:
            team = AutoGenTeam.__new__(AutoGenTeam)
        except Exception:
            pytest.skip("AutoGen not available")

        assert team.parse_mention("@ReleaseEngineer deploy") == "release_engineer"
        assert team.parse_mention("@release build") == "release_engineer"
        assert team.parse_mention("@einstein help") == "release_engineer"

    def test_parse_mention_marketing_manager(self):
        """Test @MarketingManager mention parsing."""
        from agents.autogen.team import AutoGenTeam

        try:
            team = AutoGenTeam.__new__(AutoGenTeam)
        except Exception:
            pytest.skip("AutoGen not available")

        assert team.parse_mention("@MarketingManager post") == "marketing_manager"
        assert team.parse_mention("@marketing content") == "marketing_manager"
        assert team.parse_mention("@ada tweet") == "marketing_manager"

    def test_parse_mention_support_engineer(self):
        """Test @SupportEngineer mention parsing."""
        from agents.autogen.team import AutoGenTeam

        try:
            team = AutoGenTeam.__new__(AutoGenTeam)
        except Exception:
            pytest.skip("AutoGen not available")

        assert team.parse_mention("@SupportEngineer help") == "support_engineer"
        assert team.parse_mention("@support email") == "support_engineer"
        assert team.parse_mention("@grace calendar") == "support_engineer"

    def test_parse_mention_none(self):
        """Test no mention returns None."""
        from agents.autogen.team import AutoGenTeam

        try:
            team = AutoGenTeam.__new__(AutoGenTeam)
        except Exception:
            pytest.skip("AutoGen not available")

        assert team.parse_mention("just a regular message") is None


class TestOpenHandsTeamRouting:
    """Test OpenHands team routing logic."""

    def test_parse_mention(self):
        """Test mention parsing in OpenHands team."""
        from agents.openhands.team import OpenHandsTeam

        team = OpenHandsTeam.__new__(OpenHandsTeam)

        assert team.parse_mention("@ReleaseEngineer deploy") == "release_engineer"
        assert team.parse_mention("@marketing post") == "marketing_manager"
        assert team.parse_mention("@support help") == "support_engineer"
        assert team.parse_mention("no mention") is None

    def test_route_by_keywords(self):
        """Test keyword-based routing in OpenHands team."""
        from agents.openhands.team import OpenHandsTeam

        team = OpenHandsTeam.__new__(OpenHandsTeam)

        assert team.route_by_keywords("deploy to production") == "release_engineer"
        assert team.route_by_keywords("post on twitter") == "marketing_manager"
        assert team.route_by_keywords("send email to customer") == "support_engineer"
        assert team.route_by_keywords("random message") == "support_engineer"


class TestCrewAITeamRouting:
    """Test CrewAI team routing logic."""

    def test_parse_mention(self):
        """Test mention parsing in CrewAI team."""
        try:
            from agents.crewai.crew import CrewAITeam
        except ImportError:
            pytest.skip("CrewAI not available")

        team = CrewAITeam.__new__(CrewAITeam)

        assert team.parse_mention("@ReleaseEngineer deploy") == "release_engineer"
        assert team.parse_mention("@marketing post") == "marketing_manager"
        assert team.parse_mention("@support help") == "support_engineer"

    def test_route_by_keywords(self):
        """Test keyword-based routing in CrewAI team."""
        try:
            from agents.crewai.crew import CrewAITeam
        except ImportError:
            pytest.skip("CrewAI not available")

        team = CrewAITeam.__new__(CrewAITeam)

        assert team.route_by_keywords("deploy to k8s") == "release_engineer"
        assert team.route_by_keywords("create blog post") == "marketing_manager"
        assert team.route_by_keywords("check sentry errors") == "support_engineer"
