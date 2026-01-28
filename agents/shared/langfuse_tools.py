"""
Shared Langfuse tool functions for all agent frameworks.

These functions wrap the LangfuseConnector and provide a consistent interface
for LLM observability across AutoGen, CrewAI, and OpenHands agents.
"""

import os


def _get_langfuse_connector():
    """Get configured Langfuse connector."""
    try:
        from vibeteam.connectors.langfuse import LangfuseConnector

        public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
        secret_key = os.getenv("LANGFUSE_SECRET_KEY")

        if not public_key or not secret_key:
            return None, "LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY not configured"

        connector = LangfuseConnector(
            public_key=public_key,
            secret_key=secret_key,
        )
        return connector

    except ImportError:
        return None, "vibeteam.connectors.langfuse module not available"
    except Exception as e:
        return None, str(e)


async def get_langfuse_traces(
    limit: int = 10,
    min_latency_ms: int = 0,
    hours: int = 24,
) -> str:
    """Get recent traces from Langfuse.

    Args:
        limit: Maximum number of traces to return (default: 10)
        min_latency_ms: Filter traces with latency above this threshold (default: 0)
        hours: Time window in hours (default: 24)

    Returns:
        Formatted list of Langfuse traces or error message
    """
    result = _get_langfuse_connector()
    if isinstance(result, tuple):
        return f"""
=== Langfuse Traces (last {hours}h) ===
Filter: latency >= {min_latency_ms}ms

Langfuse not configured: {result[1]}

To enable Langfuse:
1. Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY environment variables
2. Ensure Langfuse server is accessible

For now, please describe the observability data you want to analyze.
"""

    connector = result

    try:
        stats = connector.get_stats(hours=hours)
        anomalies = connector.detect_anomalies(hours=hours)

        output = f"=== Langfuse Stats (last {hours}h) ===\n\n"
        output += f"Total Traces: {stats.total_traces}\n"
        output += f"Total Tokens: {stats.total_tokens:,}\n"
        output += f"Avg Latency: {stats.avg_latency_ms:.0f}ms\n"
        output += f"Error Count: {stats.error_count}\n"
        output += f"Error Rate: {stats.error_rate:.1%}\n"
        output += f"Cost (USD): ${stats.cost_usd:.2f}\n\n"

        if anomalies:
            output += f"=== Anomalies Detected ({len(anomalies)}) ===\n\n"
            for anomaly in anomalies:
                output += f"**[{anomaly.severity.upper()}] {anomaly.type}**\n"
                output += f"  {anomaly.message}\n"
                output += f"  Value: {anomaly.value:.2f} (threshold: {anomaly.threshold:.2f})\n"
                if anomaly.trace_ids:
                    output += f"  Trace IDs: {', '.join(anomaly.trace_ids[:3])}\n"
                output += "\n"
        else:
            output += "No anomalies detected.\n"

        return output

    except Exception as e:
        return f"Error fetching Langfuse traces: {e}"


async def get_langfuse_stats(hours: int = 24) -> str:
    """Get aggregated stats from Langfuse.

    Args:
        hours: Time window in hours (default: 24)

    Returns:
        Formatted statistics or error message
    """
    result = _get_langfuse_connector()
    if isinstance(result, tuple):
        return f"Langfuse not configured: {result[1]}"

    connector = result

    try:
        stats = connector.get_stats(hours=hours)

        return f"""
=== Langfuse Stats (last {hours}h) ===
Total Traces: {stats.total_traces}
Total Tokens: {stats.total_tokens:,}
Average Latency: {stats.avg_latency_ms:.0f}ms
Error Count: {stats.error_count}
Error Rate: {stats.error_rate:.1%}
Estimated Cost: ${stats.cost_usd:.2f}
"""

    except Exception as e:
        return f"Error fetching Langfuse stats: {e}"


async def detect_langfuse_anomalies(hours: int = 24) -> str:
    """Detect anomalies in Langfuse traces.

    Args:
        hours: Time window in hours (default: 24)

    Returns:
        List of detected anomalies or success message
    """
    result = _get_langfuse_connector()
    if isinstance(result, tuple):
        return f"Langfuse not configured: {result[1]}"

    connector = result

    try:
        anomalies = connector.detect_anomalies(hours=hours)

        if not anomalies:
            return f"No anomalies detected in the last {hours} hours."

        output = f"=== Anomalies Detected (last {hours}h) ===\n\n"
        for anomaly in anomalies:
            output += f"**[{anomaly.severity.upper()}] {anomaly.type}**\n"
            output += f"  Message: {anomaly.message}\n"
            output += (
                f"  Value: {anomaly.value:.2f} (threshold: {anomaly.threshold:.2f})\n"
            )
            output += f"  Time: {anomaly.timestamp}\n"
            if anomaly.trace_ids:
                output += f"  Sample traces: {', '.join(anomaly.trace_ids[:5])}\n"
            output += "\n"

        return output

    except Exception as e:
        return f"Error detecting anomalies: {e}"


def get_langfuse_context(hours: int = 6) -> str:
    """Get Langfuse context for injection into agent prompts.

    This is designed for OpenHands-style context injection where we
    provide current state to the agent upfront.

    Args:
        hours: Time window in hours

    Returns:
        Formatted context string for agent prompts
    """
    result = _get_langfuse_connector()
    if isinstance(result, tuple):
        return f"## LLM Observability Status\n\nLangfuse not configured: {result[1]}"

    connector = result

    try:
        stats = connector.get_stats(hours=hours)
        anomalies = connector.detect_anomalies(hours=hours)

        context = f"## LLM Observability (last {hours}h)\n\n"
        context += f"- **Traces**: {stats.total_traces}\n"
        context += f"- **Tokens**: {stats.total_tokens:,}\n"
        context += f"- **Avg Latency**: {stats.avg_latency_ms:.0f}ms\n"
        context += f"- **Error Rate**: {stats.error_rate:.1%}\n"
        context += f"- **Cost**: ${stats.cost_usd:.2f}\n\n"

        if anomalies:
            context += f"### Anomalies ({len(anomalies)})\n\n"
            for anomaly in anomalies:
                context += (
                    f"- **[{anomaly.severity}]** {anomaly.type}: {anomaly.message}\n"
                )
        else:
            context += "No anomalies detected.\n"

        return context

    except Exception as e:
        return f"## LLM Observability Status\n\nError loading Langfuse data: {e}"
