"""
Graphiti error categorization utilities.

Provides structured error information for ingestion failures,
enabling callers to distinguish transient errors (retry) from
permanent errors (require config changes).
"""


def categorize_graphiti_error(exception: Exception) -> dict:
    """
    Categorize a Graphiti/embedding exception by type.

    Returns a dict with:
        category (str): One of: rate_limit, quota_exceeded, auth_failure,
                        network_timeout, neo4j_error, unknown
        is_transient (bool): True if retry may succeed, False if config fix required
        advice (str): Suggested next action
    """
    msg = str(exception).lower()

    if "rate limit" in msg or "429" in msg or "too many requests" in msg:
        return {
            "category": "rate_limit",
            "is_transient": True,
            "advice": "Wait and retry with longer pause between batches (--pause 120)",
        }

    if "quota" in msg or "insufficient" in msg or "billing" in msg or "credit balance" in msg:
        api = "Anthropic (ANTHROPIC_API_KEY)" if "anthropic" in msg else "OpenAI (OPENAI_API_KEY)"
        return {
            "category": "quota_exceeded",
            "is_transient": False,
            "advice": f"{api} quota exhausted — add credits. See secrets/api_keys.env",
        }

    if "auth" in msg or "401" in msg or "403" in msg or "invalid api key" in msg or "api key" in msg:
        api = "Anthropic (ANTHROPIC_API_KEY)" if "anthropic" in msg else "OpenAI (OPENAI_API_KEY)"
        return {
            "category": "auth_failure",
            "is_transient": False,
            "advice": f"Check {api} in pps/docker/.env — key may be invalid or revoked",
        }

    # Neo4j errors take priority over generic connection errors
    if "neo4j" in msg or "bolt" in msg or "cypher" in msg or "constraint" in msg:
        return {
            "category": "neo4j_error",
            "is_transient": False,
            "advice": "Neo4j error — check Neo4j container logs: docker logs pps-neo4j",
        }

    if "timeout" in msg or "timed out" in msg or "read timeout" in msg or "connection timeout" in msg:
        return {
            "category": "network_timeout",
            "is_transient": True,
            "advice": "Network timeout — check Neo4j/internet connectivity, retry with longer timeout",
        }

    if "connection refused" in msg or "connection reset" in msg or "connection error" in msg:
        return {
            "category": "network_timeout",
            "is_transient": True,
            "advice": "Connection error — check that Neo4j and PPS containers are running",
        }

    return {
        "category": "unknown",
        "is_transient": False,
        "advice": f"Unclassified error — inspect logs and exception: {str(exception)[:200]}",
    }
