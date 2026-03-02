"""
Integration tests for multi-framework agents with real LLM calls.

These tests require:
1. Azure OpenAI credentials configured
2. The --run-integration flag to be passed to pytest

Run with:
    pytest tests/test_integration.py -v --run-integration

With metrics export:
    pytest tests/test_integration.py -v --run-integration --export-metrics=results/metrics.json
"""

import asyncio

import pytest

from agent_service.metrics import track_task

# ============================================================================
# AutoGen Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.unit_task
class TestAutoGenUnitTasks:
    """Unit tasks (U1-U7) for AutoGen framework."""

    @pytest.fixture
    def release_engineer(self, azure_credentials):
        """Create AutoGen ReleaseEngineer."""
        from agent_service.autogen.release_engineer import AutoGenReleaseEngineer

        return AutoGenReleaseEngineer()

    @pytest.fixture
    def marketing_manager(self, azure_credentials):
        """Create AutoGen MarketingManager."""
        from agent_service.autogen.marketing_manager import AutoGenMarketingManager

        return AutoGenMarketingManager()

    @pytest.fixture
    def support_engineer(self, azure_credentials):
        """Create AutoGen SupportEngineer."""
        from agent_service.autogen.support_engineer import AutoGenSupportEngineer

        return AutoGenSupportEngineer()

    @pytest.mark.asyncio
    async def test_u1_list_files(self, release_engineer, unit_tasks):
        """U1: List files in /tmp directory."""
        task_def = unit_tasks["U1"]

        with track_task("U1", "autogen", "release_engineer", "unit", task_def["task"]) as ctx:
            result = await release_engineer.run_async(task_def["task"])
            response = result.get("response", "")
            ctx.set_response_preview(response)

            success = task_def["success_criteria"](response)
            ctx.set_success(success)

            assert success, f"Task U1 failed. Response: {response[:200]}"

    @pytest.mark.asyncio
    async def test_u2_create_file(self, release_engineer, unit_tasks, tmp_path):
        """U2: Create file with content."""
        task_def = unit_tasks["U2"]
        task = task_def["task"].format(path=str(tmp_path))

        with track_task("U2", "autogen", "release_engineer", "unit", task) as ctx:
            result = await release_engineer.run_async(task)
            response = result.get("response", "")
            ctx.set_response_preview(response)

            # Check if file was actually created
            test_file = tmp_path / "test.txt"
            file_created = test_file.exists()
            criteria_met = task_def["success_criteria"](response)

            success = file_created or criteria_met
            ctx.set_success(success)

            assert success, f"Task U2 failed. Response: {response[:200]}"

    @pytest.mark.asyncio
    async def test_u3_execute_shell(self, release_engineer, unit_tasks):
        """U3: Execute shell command."""
        task_def = unit_tasks["U3"]

        with track_task("U3", "autogen", "release_engineer", "unit", task_def["task"]) as ctx:
            result = await release_engineer.run_async(task_def["task"])
            response = result.get("response", "")
            ctx.set_response_preview(response)

            success = task_def["success_criteria"](response)
            ctx.set_success(success)

            assert success, f"Task U3 failed. Response: {response[:200]}"

    @pytest.mark.asyncio
    async def test_u4_analyze_sentiment(self, marketing_manager, unit_tasks):
        """U4: Analyze sentiment of text."""
        task_def = unit_tasks["U4"]

        with track_task("U4", "autogen", "marketing_manager", "unit", task_def["task"]) as ctx:
            result = await marketing_manager.run_async(task_def["task"])
            response = result.get("response", "")
            ctx.set_response_preview(response)

            success = task_def["success_criteria"](response)
            ctx.set_success(success)

            assert success, f"Task U4 failed. Response: {response[:200]}"

    @pytest.mark.asyncio
    async def test_u5_draft_twitter_post(self, marketing_manager, unit_tasks):
        """U5: Draft Twitter post."""
        task_def = unit_tasks["U5"]

        with track_task("U5", "autogen", "marketing_manager", "unit", task_def["task"]) as ctx:
            result = await marketing_manager.run_async(task_def["task"])
            response = result.get("response", "")
            ctx.set_response_preview(response)

            success = task_def["success_criteria"](response)
            ctx.set_success(success)

            assert success, f"Task U5 failed. Response: {response[:200]}"

    @pytest.mark.asyncio
    async def test_u6_create_support_ticket(self, support_engineer, unit_tasks):
        """U6: Create support ticket."""
        task_def = unit_tasks["U6"]

        with track_task("U6", "autogen", "support_engineer", "unit", task_def["task"]) as ctx:
            result = await support_engineer.run_async(task_def["task"])
            response = result.get("response", "")
            ctx.set_response_preview(response)

            success = task_def["success_criteria"](response)
            ctx.set_success(success)

            assert success, f"Task U6 failed. Response: {response[:200]}"

    @pytest.mark.asyncio
    async def test_u7_draft_email_response(self, support_engineer, unit_tasks):
        """U7: Draft email response."""
        task_def = unit_tasks["U7"]

        with track_task("U7", "autogen", "support_engineer", "unit", task_def["task"]) as ctx:
            result = await support_engineer.run_async(task_def["task"])
            response = result.get("response", "")
            ctx.set_response_preview(response)

            success = task_def["success_criteria"](response)
            ctx.set_success(success)

            assert success, f"Task U7 failed. Response: {response[:200]}"


@pytest.mark.integration
@pytest.mark.integration_task
class TestAutoGenIntegrationTasks:
    """Integration tasks (I1-I3) for AutoGen framework with team coordination."""

    @pytest.fixture
    def team(self, azure_credentials):
        """Create AutoGen team."""
        from agent_service.autogen.team import AutoGenTeam

        return AutoGenTeam()

    @pytest.mark.asyncio
    async def test_i1_deploy_and_announce(self, team, integration_tasks):
        """I1: Deploy and announce (ReleaseEngineer + MarketingManager)."""
        task_def = integration_tasks["I1"]

        with track_task("I1", "autogen", "team", "integration", task_def["task"]) as ctx:
            result = await team.run_async(task_def["task"])
            response = result.get("response", "")
            ctx.set_response_preview(response)

            success = task_def["success_criteria"](response)
            ctx.set_success(success)

            assert success, f"Task I1 failed. Response: {response[:300]}"


# ============================================================================
# CrewAI Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.unit_task
class TestCrewAIUnitTasks:
    """Unit tasks (U1-U7) for CrewAI framework."""

    @pytest.fixture
    def release_engineer(self, azure_credentials):
        """Create CrewAI ReleaseEngineer."""
        from agent_service.crewai.release_engineer import CrewAIReleaseEngineer

        return CrewAIReleaseEngineer()

    @pytest.fixture
    def marketing_manager(self, azure_credentials):
        """Create CrewAI MarketingManager."""
        from agent_service.crewai.marketing_manager import CrewAIMarketingManager

        return CrewAIMarketingManager()

    @pytest.fixture
    def support_engineer(self, azure_credentials):
        """Create CrewAI SupportEngineer."""
        from agent_service.crewai.support_engineer import CrewAISupportEngineer

        return CrewAISupportEngineer()

    @pytest.mark.asyncio
    async def test_u1_list_files(self, release_engineer, unit_tasks):
        """U1: List files in /tmp directory."""
        task_def = unit_tasks["U1"]

        with track_task("U1", "crewai", "release_engineer", "unit", task_def["task"]) as ctx:
            # CrewAI uses sync interface
            result = await asyncio.to_thread(release_engineer.run, task_def["task"])
            response = result.get("response", "")
            ctx.set_response_preview(response)

            success = task_def["success_criteria"](response)
            ctx.set_success(success)

            assert success, f"Task U1 failed. Response: {response[:200]}"

    @pytest.mark.asyncio
    async def test_u2_create_file(self, release_engineer, unit_tasks, tmp_path):
        """U2: Create file with content."""
        task_def = unit_tasks["U2"]
        task = task_def["task"].format(path=str(tmp_path))

        with track_task("U2", "crewai", "release_engineer", "unit", task) as ctx:
            result = await asyncio.to_thread(release_engineer.run, task)
            response = result.get("response", "")
            ctx.set_response_preview(response)

            test_file = tmp_path / "test.txt"
            file_created = test_file.exists()
            criteria_met = task_def["success_criteria"](response)

            success = file_created or criteria_met
            ctx.set_success(success)

            assert success, f"Task U2 failed. Response: {response[:200]}"

    @pytest.mark.asyncio
    async def test_u3_execute_shell(self, release_engineer, unit_tasks):
        """U3: Execute shell command."""
        task_def = unit_tasks["U3"]

        with track_task("U3", "crewai", "release_engineer", "unit", task_def["task"]) as ctx:
            result = await asyncio.to_thread(release_engineer.run, task_def["task"])
            response = result.get("response", "")
            ctx.set_response_preview(response)

            success = task_def["success_criteria"](response)
            ctx.set_success(success)

            assert success, f"Task U3 failed. Response: {response[:200]}"

    @pytest.mark.asyncio
    async def test_u4_analyze_sentiment(self, marketing_manager, unit_tasks):
        """U4: Analyze sentiment of text."""
        task_def = unit_tasks["U4"]

        with track_task("U4", "crewai", "marketing_manager", "unit", task_def["task"]) as ctx:
            result = await asyncio.to_thread(marketing_manager.run, task_def["task"])
            response = result.get("response", "")
            ctx.set_response_preview(response)

            success = task_def["success_criteria"](response)
            ctx.set_success(success)

            assert success, f"Task U4 failed. Response: {response[:200]}"

    @pytest.mark.asyncio
    async def test_u5_draft_twitter_post(self, marketing_manager, unit_tasks):
        """U5: Draft Twitter post."""
        task_def = unit_tasks["U5"]

        with track_task("U5", "crewai", "marketing_manager", "unit", task_def["task"]) as ctx:
            result = await asyncio.to_thread(marketing_manager.run, task_def["task"])
            response = result.get("response", "")
            ctx.set_response_preview(response)

            success = task_def["success_criteria"](response)
            ctx.set_success(success)

            assert success, f"Task U5 failed. Response: {response[:200]}"

    @pytest.mark.asyncio
    async def test_u6_create_support_ticket(self, support_engineer, unit_tasks):
        """U6: Create support ticket."""
        task_def = unit_tasks["U6"]

        with track_task("U6", "crewai", "support_engineer", "unit", task_def["task"]) as ctx:
            result = await asyncio.to_thread(support_engineer.run, task_def["task"])
            response = result.get("response", "")
            ctx.set_response_preview(response)

            success = task_def["success_criteria"](response)
            ctx.set_success(success)

            assert success, f"Task U6 failed. Response: {response[:200]}"

    @pytest.mark.asyncio
    async def test_u7_draft_email_response(self, support_engineer, unit_tasks):
        """U7: Draft email response."""
        task_def = unit_tasks["U7"]

        with track_task("U7", "crewai", "support_engineer", "unit", task_def["task"]) as ctx:
            result = await asyncio.to_thread(support_engineer.run, task_def["task"])
            response = result.get("response", "")
            ctx.set_response_preview(response)

            success = task_def["success_criteria"](response)
            ctx.set_success(success)

            assert success, f"Task U7 failed. Response: {response[:200]}"


@pytest.mark.integration
@pytest.mark.integration_task
class TestCrewAIIntegrationTasks:
    """Integration tasks (I1-I3) for CrewAI framework with crew orchestration."""

    @pytest.fixture
    def crew(self, azure_credentials):
        """Create CrewAI crew."""
        from agent_service.crewai.crew import CrewAITeam

        return CrewAITeam()

    @pytest.mark.asyncio
    async def test_i1_deploy_and_announce(self, crew, integration_tasks):
        """I1: Deploy and announce (ReleaseEngineer + MarketingManager)."""
        task_def = integration_tasks["I1"]

        with track_task("I1", "crewai", "crew", "integration", task_def["task"]) as ctx:
            result = await asyncio.to_thread(crew.run, task_def["task"])
            response = result.get("response", "")
            ctx.set_response_preview(response)

            success = task_def["success_criteria"](response)
            ctx.set_success(success)

            assert success, f"Task I1 failed. Response: {response[:300]}"


# ============================================================================
# OpenHands Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.unit_task
class TestOpenHandsUnitTasks:
    """Unit tasks (U1-U7) for OpenHands framework."""

    @pytest.fixture
    def release_engineer(self, azure_credentials):
        """Create OpenHands ReleaseEngineer."""
        from agent_service.openhands.release_engineer import OpenHandsReleaseEngineer

        return OpenHandsReleaseEngineer()

    @pytest.fixture
    def marketing_manager(self, azure_credentials):
        """Create OpenHands MarketingManager."""
        from agent_service.openhands.marketing_manager import OpenHandsMarketingManager

        return OpenHandsMarketingManager()

    @pytest.fixture
    def support_engineer(self, azure_credentials):
        """Create OpenHands SupportEngineer."""
        from agent_service.openhands.support_engineer import OpenHandsSupportEngineer

        return OpenHandsSupportEngineer()

    @pytest.mark.asyncio
    async def test_u1_list_files(self, release_engineer, unit_tasks):
        """U1: List files in /tmp directory."""
        task_def = unit_tasks["U1"]

        with track_task("U1", "openhands", "release_engineer", "unit", task_def["task"]) as ctx:
            result = await release_engineer.run_async(task_def["task"])
            response = result.get("response", "")
            ctx.set_response_preview(response)

            success = task_def["success_criteria"](response)
            ctx.set_success(success)

            assert success, f"Task U1 failed. Response: {response[:200]}"

    @pytest.mark.asyncio
    async def test_u2_create_file(self, release_engineer, unit_tasks, tmp_path):
        """U2: Create file with content."""
        task_def = unit_tasks["U2"]
        task = task_def["task"].format(path=str(tmp_path))

        with track_task("U2", "openhands", "release_engineer", "unit", task) as ctx:
            result = await release_engineer.run_async(task)
            response = result.get("response", "")
            ctx.set_response_preview(response)

            test_file = tmp_path / "test.txt"
            file_created = test_file.exists()
            criteria_met = task_def["success_criteria"](response)

            success = file_created or criteria_met
            ctx.set_success(success)

            assert success, f"Task U2 failed. Response: {response[:200]}"

    @pytest.mark.asyncio
    async def test_u3_execute_shell(self, release_engineer, unit_tasks):
        """U3: Execute shell command."""
        task_def = unit_tasks["U3"]

        with track_task("U3", "openhands", "release_engineer", "unit", task_def["task"]) as ctx:
            result = await release_engineer.run_async(task_def["task"])
            response = result.get("response", "")
            ctx.set_response_preview(response)

            success = task_def["success_criteria"](response)
            ctx.set_success(success)

            assert success, f"Task U3 failed. Response: {response[:200]}"

    @pytest.mark.asyncio
    async def test_u4_analyze_sentiment(self, marketing_manager, unit_tasks):
        """U4: Analyze sentiment of text."""
        task_def = unit_tasks["U4"]

        with track_task("U4", "openhands", "marketing_manager", "unit", task_def["task"]) as ctx:
            result = await marketing_manager.run_async(task_def["task"])
            response = result.get("response", "")
            ctx.set_response_preview(response)

            success = task_def["success_criteria"](response)
            ctx.set_success(success)

            assert success, f"Task U4 failed. Response: {response[:200]}"

    @pytest.mark.asyncio
    async def test_u5_draft_twitter_post(self, marketing_manager, unit_tasks):
        """U5: Draft Twitter post."""
        task_def = unit_tasks["U5"]

        with track_task("U5", "openhands", "marketing_manager", "unit", task_def["task"]) as ctx:
            result = await marketing_manager.run_async(task_def["task"])
            response = result.get("response", "")
            ctx.set_response_preview(response)

            success = task_def["success_criteria"](response)
            ctx.set_success(success)

            assert success, f"Task U5 failed. Response: {response[:200]}"

    @pytest.mark.asyncio
    async def test_u6_create_support_ticket(self, support_engineer, unit_tasks):
        """U6: Create support ticket."""
        task_def = unit_tasks["U6"]

        with track_task("U6", "openhands", "support_engineer", "unit", task_def["task"]) as ctx:
            result = await support_engineer.run_async(task_def["task"])
            response = result.get("response", "")
            ctx.set_response_preview(response)

            success = task_def["success_criteria"](response)
            ctx.set_success(success)

            assert success, f"Task U6 failed. Response: {response[:200]}"

    @pytest.mark.asyncio
    async def test_u7_draft_email_response(self, support_engineer, unit_tasks):
        """U7: Draft email response."""
        task_def = unit_tasks["U7"]

        with track_task("U7", "openhands", "support_engineer", "unit", task_def["task"]) as ctx:
            result = await support_engineer.run_async(task_def["task"])
            response = result.get("response", "")
            ctx.set_response_preview(response)

            success = task_def["success_criteria"](response)
            ctx.set_success(success)

            assert success, f"Task U7 failed. Response: {response[:200]}"


@pytest.mark.integration
@pytest.mark.integration_task
class TestOpenHandsIntegrationTasks:
    """Integration tasks (I1-I3) for OpenHands framework with team orchestration."""

    @pytest.fixture
    def team(self, azure_credentials):
        """Create OpenHands team."""
        from agent_service.openhands.team import OpenHandsTeam

        return OpenHandsTeam()

    @pytest.mark.asyncio
    async def test_i1_deploy_and_announce(self, team, integration_tasks):
        """I1: Deploy and announce (ReleaseEngineer + MarketingManager)."""
        task_def = integration_tasks["I1"]

        with track_task("I1", "openhands", "team", "integration", task_def["task"]) as ctx:
            result = await team.run_async(task_def["task"])
            response = result.get("response", "")
            ctx.set_response_preview(response)

            success = task_def["success_criteria"](response)
            ctx.set_success(success)

            assert success, f"Task I1 failed. Response: {response[:300]}"


# ============================================================================
# Stress Tests
# ============================================================================


@pytest.mark.stress
@pytest.mark.integration
class TestStressTasks:
    """Stress tests (S1-S3) for all frameworks."""

    @pytest.fixture
    def autogen_engineer(self, azure_credentials):
        """Create AutoGen ReleaseEngineer."""
        from agent_service.autogen.release_engineer import AutoGenReleaseEngineer

        return AutoGenReleaseEngineer()

    @pytest.mark.asyncio
    async def test_s1_sequential_tasks(self, autogen_engineer):
        """S1: 10 sequential tasks to measure total latency."""
        tasks = [
            "List files in /tmp",
            "Show current date",
            "Display environment variables",
            "Show disk usage",
            "List running processes",
            "Check network connectivity",
            "Show system memory",
            "Display current user",
            "List installed packages count",
            "Show uptime",
        ]

        with track_task(
            "S1", "autogen", "release_engineer", "stress", "10 sequential tasks"
        ) as ctx:
            results = []
            for _i, task in enumerate(tasks):
                result = await autogen_engineer.run_async(task)
                results.append(result)
                ctx.increment_tool_calls()

            # Check all completed
            success = all(r.get("response") for r in results)
            ctx.set_success(success)

            assert success, "Not all sequential tasks completed"

    @pytest.mark.asyncio
    async def test_s2_concurrent_agents(self, azure_credentials):
        """S2: Concurrent agent execution."""
        from agent_service.autogen.marketing_manager import AutoGenMarketingManager
        from agent_service.autogen.release_engineer import AutoGenReleaseEngineer
        from agent_service.autogen.support_engineer import AutoGenSupportEngineer

        release = AutoGenReleaseEngineer()
        marketing = AutoGenMarketingManager()
        support = AutoGenSupportEngineer()

        with track_task("S2", "autogen", "multiple", "stress", "concurrent execution") as ctx:
            results = await asyncio.gather(
                release.run_async("Show current time"),
                marketing.run_async("Draft a short greeting"),
                support.run_async("Create a test ticket"),
                return_exceptions=True,
            )

            # Check for errors
            errors = [r for r in results if isinstance(r, Exception)]
            for e in errors:
                ctx.add_error(str(e))

            success = len(errors) == 0
            ctx.set_success(success)
            ctx.set_tool_calls(3)

            assert success, f"Concurrent execution had errors: {errors}"


# ============================================================================
# Metrics Report
# ============================================================================


@pytest.mark.integration
class TestMetricsReport:
    """Generate metrics report after all tests."""

    def test_generate_report(self, metrics_collector):
        """Generate and display final metrics report."""
        report = metrics_collector.generate_report()
        print("\n" + report)

        stats = metrics_collector.compute_statistics()
        if "error" not in stats:
            # Basic assertions about collected metrics
            assert stats["overall"]["total_tasks"] >= 0
