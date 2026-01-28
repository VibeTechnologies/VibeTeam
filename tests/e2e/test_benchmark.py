"""
Benchmark Test: Compare Agent Frameworks.

Runs comprehensive benchmarks across AutoGen, CrewAI, and OpenHands,
measuring speed, quality, and tool usage.

Run with:
    pytest tests/e2e/test_benchmark.py -v -s

Run specific task:
    pytest tests/e2e/test_benchmark.py -v -s -k "sentry"

Run without quality evaluation (faster):
    pytest tests/e2e/test_benchmark.py -v -s --no-quality
"""

import subprocess
import time

import httpx
import pytest

from agents.benchmark import (
    SENTRY_SUMMARY_TASK,
    STANDARD_TASKS,
    Benchmark,
    BenchmarkResult,
    BenchmarkTask,
    ResponseValidator,
)

# ==============================================================================
# Configuration
# ==============================================================================

GATEWAY_PORT = 19081  # Different port to avoid conflicts
GATEWAY_SERVICE = "vibeteam-gateway"
NAMESPACE = "vibeteam"


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture(scope="module")
def gateway_url():
    """
    Start kubectl port-forward and return gateway URL.
    """
    proc = subprocess.Popen(
        [
            "kubectl",
            "port-forward",
            f"svc/{GATEWAY_SERVICE}",
            f"{GATEWAY_PORT}:8080",
            "-n",
            NAMESPACE,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    time.sleep(3)

    # Verify connection
    try:
        response = httpx.get(
            f"http://localhost:{GATEWAY_PORT}/health",
            timeout=10.0,
        )
        if response.status_code != 200:
            proc.terminate()
            pytest.skip(f"Gateway health check failed: {response.status_code}")
    except Exception as e:
        proc.terminate()
        pytest.skip(f"Cannot connect to gateway: {e}")

    yield f"http://localhost:{GATEWAY_PORT}"

    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture
def benchmark(gateway_url, request):
    """Create benchmark instance."""
    # Check for --no-quality flag
    no_quality = request.config.getoption("--no-quality", default=False)
    return Benchmark(
        frameworks=["autogen", "crewai", "openhands"],
        gateway_url=gateway_url,
        evaluate_quality=not no_quality,
    )


def pytest_addoption(parser):
    """Add custom pytest options."""
    parser.addoption(
        "--no-quality",
        action="store_true",
        default=False,
        help="Skip LLM-as-judge quality evaluation",
    )
    parser.addoption(
        "--export-benchmark",
        type=str,
        default=None,
        help="Export benchmark results to JSON file",
    )


# ==============================================================================
# Unit Tests for Benchmark Components
# ==============================================================================


class TestResponseValidator:
    """Test the response validator logic."""

    def test_validates_good_response(self):
        validator = ResponseValidator()
        response = """
        ## Sentry Issues Summary

        Total: 15 unresolved issues this week.

        ### Critical Issues
        - Issue #123: Login failure (3 occurrences)
        - Issue #456: Payment timeout (2 occurrences)

        ### Recommendations
        1. Prioritize login failure fix
        2. Monitor payment service
        """
        is_valid, notes = validator.validate(response)
        assert is_valid is True
        # Should contain success pattern notes
        assert len(notes) > 0

    def test_rejects_error_response(self):
        validator = ResponseValidator()
        response = "Error: vibeteam.connectors.sentry module not available"
        is_valid, notes = validator.validate(response)
        assert is_valid is False
        assert any("error" in n.lower() for n in notes)

    def test_rejects_sorry_response(self):
        validator = ResponseValidator()
        response = "I'm sorry, but I cannot access that information."
        is_valid, notes = validator.validate(response)
        assert is_valid is False

    def test_rejects_short_response(self):
        validator = ResponseValidator()
        response = "OK"
        is_valid, notes = validator.validate(response)
        assert is_valid is False
        assert any("short" in n.lower() for n in notes)


class TestBenchmarkResult:
    """Test BenchmarkResult data class."""

    def test_composite_score_success(self):
        result = BenchmarkResult(
            task_id="test",
            framework="autogen",
            role="support_engineer",
            success=True,
            latency_ms=5000,  # 5 seconds
            total_tokens=1000,
        )
        result.quality.overall = 0.8
        result.quality.accuracy = 0.8
        result.quality.completeness = 0.8

        score = result.composite_score
        assert 0 < score <= 1
        assert score > 0.5  # Should be decent with these inputs

    def test_composite_score_failure(self):
        result = BenchmarkResult(
            task_id="test",
            framework="autogen",
            role="support_engineer",
            success=False,
        )
        assert result.composite_score == 0.0

    def test_serialization(self):
        result = BenchmarkResult(
            task_id="test",
            framework="autogen",
            role="support_engineer",
            success=True,
            latency_ms=1000,
            response="Test response",
        )

        # Serialize and deserialize
        data = result.to_dict()
        restored = BenchmarkResult.from_dict(data)

        assert restored.task_id == result.task_id
        assert restored.framework == result.framework
        assert restored.latency_ms == result.latency_ms


# ==============================================================================
# Integration Benchmark Tests
# ==============================================================================


class TestSentryBenchmark:
    """Benchmark Sentry summary task across frameworks."""

    @pytest.mark.asyncio
    async def test_sentry_summary_benchmark(self, benchmark, gateway_url):
        """Run Sentry summary benchmark on all frameworks."""
        print("\n" + "=" * 70)
        print("SENTRY SUMMARY BENCHMARK")
        print("=" * 70)

        tasks = [SENTRY_SUMMARY_TASK]
        results = await benchmark.run(tasks, parallel=False)

        # Print results
        for r in results:
            status = "PASS" if r.success else "FAIL"
            print(f"\n{r.framework.upper()}: [{status}]")
            print(f"  Latency:    {r.latency_ms}ms")
            print(f"  Tokens:     {r.total_tokens}")

            if r.success and r.quality.overall > 0:
                print(f"  Quality:    {r.quality.overall:.2f}")
                print(f"  Composite:  {r.composite_score:.2f}")

            if r.error:
                print(f"  Error:      {r.error[:80]}")

            if r.validation_notes:
                print(f"  Notes:      {', '.join(r.validation_notes[:3])}")

        # At least one framework should pass
        passing = [r for r in results if r.success]
        assert len(passing) >= 1, "At least one framework should pass"

        # Print winner
        if passing:
            winner = max(passing, key=lambda r: r.composite_score)
            print(f"\n{'=' * 50}")
            print(f"WINNER: {winner.framework.upper()} (score: {winner.composite_score:.2f})")
            print(f"{'=' * 50}")


class TestFullBenchmarkSuite:
    """Run the full benchmark suite."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_full_benchmark_suite(self, benchmark, gateway_url, request):
        """Run all standard benchmark tasks."""
        print("\n" + "=" * 70)
        print("FULL BENCHMARK SUITE")
        print("=" * 70)

        results = await benchmark.run(STANDARD_TASKS, parallel=False)

        # Generate report
        report = benchmark.generate_report(results)
        print(report)

        # Export if requested
        export_path = request.config.getoption("--export-benchmark")
        if export_path:
            filepath = benchmark.export_results(results, export_path)
            print(f"\nResults exported to: {filepath}")

        # Basic assertions
        assert len(results) == len(STANDARD_TASKS) * len(benchmark.frameworks)


class TestFrameworkComparison:
    """Direct framework comparison tests."""

    @pytest.mark.asyncio
    async def test_compare_latency(self, benchmark, gateway_url):
        """Compare response latency across frameworks."""
        print("\n" + "=" * 70)
        print("LATENCY COMPARISON")
        print("=" * 70)

        task = BenchmarkTask(
            task_id="latency-test",
            prompt="What is 2 + 2?",
            expected_behavior="Should answer quickly with 4",
            role="support_engineer",
        )

        results = await benchmark.run([task], parallel=True)

        # Sort by latency
        sorted_results = sorted(results, key=lambda r: r.latency_ms)

        print("\nLatency Rankings:")
        for i, r in enumerate(sorted_results, 1):
            status = "PASS" if r.success else "FAIL"
            print(f"  {i}. {r.framework}: {r.latency_ms}ms [{status}]")

        # All should complete within reasonable time
        for r in results:
            if r.success:
                assert r.latency_ms < 30000, f"{r.framework} took too long"

    @pytest.mark.asyncio
    async def test_compare_quality_scores(self, benchmark, gateway_url):
        """Compare quality scores across frameworks."""
        if not benchmark.evaluate_quality:
            pytest.skip("Quality evaluation disabled")

        print("\n" + "=" * 70)
        print("QUALITY COMPARISON")
        print("=" * 70)

        results = await benchmark.run([SENTRY_SUMMARY_TASK], parallel=False)

        # Filter successful results with quality scores
        scored = [r for r in results if r.success and r.quality.overall > 0]

        if not scored:
            pytest.skip("No successful results with quality scores")

        print("\nQuality Rankings:")
        for r in sorted(scored, key=lambda x: x.quality.overall, reverse=True):
            print(f"\n{r.framework.upper()}:")
            print(f"  Overall:       {r.quality.overall:.2f}")
            print(f"  Accuracy:      {r.quality.accuracy:.2f}")
            print(f"  Completeness:  {r.quality.completeness:.2f}")
            print(f"  Actionability: {r.quality.actionability:.2f}")
            print(f"  Clarity:       {r.quality.clarity:.2f}")


# ==============================================================================
# Performance Regression Tests
# ==============================================================================


class TestPerformanceRegression:
    """Ensure performance doesn't regress."""

    # Baseline thresholds (adjust based on historical data)
    MAX_LATENCY_MS = 30000  # 30 seconds
    MIN_SUCCESS_RATE = 0.3  # At least 1/3 frameworks should pass

    @pytest.mark.asyncio
    async def test_latency_threshold(self, benchmark, gateway_url):
        """Ensure latency stays within acceptable bounds."""
        results = await benchmark.run([SENTRY_SUMMARY_TASK], parallel=True)

        for r in results:
            if r.success:
                assert r.latency_ms < self.MAX_LATENCY_MS, (
                    f"{r.framework} latency {r.latency_ms}ms exceeds {self.MAX_LATENCY_MS}ms"
                )

    @pytest.mark.asyncio
    async def test_success_rate_threshold(self, benchmark, gateway_url):
        """Ensure at least minimum success rate."""
        results = await benchmark.run([SENTRY_SUMMARY_TASK], parallel=True)

        success_count = sum(1 for r in results if r.success)
        success_rate = success_count / len(results)

        assert success_rate >= self.MIN_SUCCESS_RATE, (
            f"Success rate {success_rate:.0%} below minimum {self.MIN_SUCCESS_RATE:.0%}"
        )
