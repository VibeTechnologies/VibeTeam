import os

import pytest


class _DummyStore:
    async def save(self, *_args, **_kwargs) -> None:
        return None


def _dummy_store() -> _DummyStore:
    return _DummyStore()


def _clear_github_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("VIBETEAM_AGENT_ROLE", raising=False)


@pytest.mark.asyncio
async def test_openhands_role_token_context_inferred(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_service.openhands import server as oh_server

    _clear_github_env(monkeypatch)

    captured: dict[str, str | None] = {}

    class DummyAgent:
        def run(self, **_kwargs):  # type: ignore[no-untyped-def]
            captured["token"] = os.environ.get("GITHUB_TOKEN")
            captured["role"] = os.environ.get("VIBETEAM_AGENT_ROLE")
            return {"response": "ok", "agent": "software_engineer"}

    class DummyTeam:
        def parse_mention(self, _text: str) -> str | None:
            return None

        def route_by_keywords(self, _text: str) -> str:
            return "software_engineer"

        def _get_agent(self, _role: str) -> DummyAgent:
            return DummyAgent()

        async def run_async(self, **_kwargs):  # type: ignore[no-untyped-def]
            captured["token"] = os.environ.get("GITHUB_TOKEN")
            captured["role"] = os.environ.get("VIBETEAM_AGENT_ROLE")
            return {"response": "ok", "agent": "software_engineer"}

    monkeypatch.setattr(oh_server, "get_team", lambda: DummyTeam())
    monkeypatch.setattr(oh_server, "get_postgres_store", _dummy_store)

    called: dict[str, str | None] = {}

    def fake_get_token(role: str) -> str:
        called["role"] = role
        return "ghs_role_token"

    monkeypatch.setattr(
        "vibeteam.utils.github_app.get_installation_token_for_role",
        fake_get_token,
    )

    request = oh_server.RunRequest(task="fix bug in module", role=None, context_type="slack")
    await oh_server.run_task(request)

    assert called["role"] == "software_engineer"
    assert captured["token"] == "ghs_role_token"
    assert captured["role"] == "software_engineer"
    assert os.environ.get("GITHUB_TOKEN") is None
    assert os.environ.get("VIBETEAM_AGENT_ROLE") is None


@pytest.mark.asyncio
async def test_autogen_role_token_context_mentions(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_service.autogen import server as ag_server

    _clear_github_env(monkeypatch)

    captured: dict[str, str | None] = {}

    class DummyTeam:
        async def run_async(self, **_kwargs):  # type: ignore[no-untyped-def]
            captured["token"] = os.environ.get("GITHUB_TOKEN")
            captured["role"] = os.environ.get("VIBETEAM_AGENT_ROLE")
            return {"response": "ok", "agent": "software_engineer"}

        async def run_single_agent_async(self, **_kwargs):  # type: ignore[no-untyped-def]
            captured["token"] = os.environ.get("GITHUB_TOKEN")
            captured["role"] = os.environ.get("VIBETEAM_AGENT_ROLE")
            return {"response": "ok", "agent": "software_engineer"}

    monkeypatch.setattr(ag_server, "get_team", lambda: DummyTeam())
    monkeypatch.setattr(ag_server, "get_postgres_store", _dummy_store)

    called: dict[str, str | None] = {}

    def fake_get_token(role: str) -> str:
        called["role"] = role
        return "ghs_role_token"

    monkeypatch.setattr(
        "vibeteam.utils.github_app.get_installation_token_for_role",
        fake_get_token,
    )

    request = ag_server.RunRequest(task="please @swe create a PR", role=None, context_type="slack")
    await ag_server.run_task(request)

    assert called["role"] == "software_engineer"
    assert captured["token"] == "ghs_role_token"
    assert captured["role"] == "software_engineer"
    assert os.environ.get("GITHUB_TOKEN") is None
    assert os.environ.get("VIBETEAM_AGENT_ROLE") is None


@pytest.mark.asyncio
async def test_crewai_role_token_context_mentions(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_service.crewai import server as crew_server

    _clear_github_env(monkeypatch)

    captured: dict[str, str | None] = {}

    class DummyTeam:
        async def run_async(self, **_kwargs):  # type: ignore[no-untyped-def]
            captured["token"] = os.environ.get("GITHUB_TOKEN")
            captured["role"] = os.environ.get("VIBETEAM_AGENT_ROLE")
            return {"response": "ok", "agent": "software_engineer"}

    monkeypatch.setattr(crew_server, "get_team", lambda: DummyTeam())
    monkeypatch.setattr(crew_server, "get_postgres_store", _dummy_store)

    called: dict[str, str | None] = {}

    def fake_get_token(role: str) -> str:
        called["role"] = role
        return "ghs_role_token"

    monkeypatch.setattr(
        "vibeteam.utils.github_app.get_installation_token_for_role",
        fake_get_token,
    )

    request = crew_server.RunRequest(task="hey @swe update docs", role=None, context_type="slack")
    await crew_server.run_task(request)

    assert called["role"] == "software_engineer"
    assert captured["token"] == "ghs_role_token"
    assert captured["role"] == "software_engineer"
    assert os.environ.get("GITHUB_TOKEN") is None
    assert os.environ.get("VIBETEAM_AGENT_ROLE") is None


@pytest.mark.asyncio
async def test_openclaw_role_token_context_mentions(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_service.openclaw import server as oc_server

    _clear_github_env(monkeypatch)

    captured: dict[str, str | None] = {}

    async def fake_run_openclaw_task(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        captured["token"] = os.environ.get("GITHUB_TOKEN")
        captured["role"] = os.environ.get("VIBETEAM_AGENT_ROLE")
        return "ok", {}

    monkeypatch.setattr(oc_server, "run_openclaw_task", fake_run_openclaw_task)
    monkeypatch.setattr(oc_server, "get_postgres_store", _dummy_store)
    monkeypatch.setattr(oc_server, "get_agent_entry", lambda _role: None)
    monkeypatch.setattr(oc_server, "resolve_openclaw_agent_id", lambda _role: "product-manager")

    called: dict[str, str | None] = {}

    def fake_get_token(role: str) -> str:
        called["role"] = role
        return "ghs_role_token"

    monkeypatch.setattr(
        "vibeteam.utils.github_app.get_installation_token_for_role",
        fake_get_token,
    )

    request = oc_server.RunRequest(task="ping @swe", role=None, context_type="slack")
    await oc_server.run_task(request)

    assert called["role"] == "software_engineer"
    assert captured["token"] == "ghs_role_token"
    assert captured["role"] == "software_engineer"
    assert os.environ.get("GITHUB_TOKEN") is None
    assert os.environ.get("VIBETEAM_AGENT_ROLE") is None
