#!/usr/bin/env python3
"""
Neo4j Entity Count Health Monitor

Detects Neo4j reinitialization by tracking entity count over time.
Alerts if count drops by >50% or falls below 100 entities.

Usage:
    python neo4j-health-check.py [--verbose]

Environment Variables (from .env):
    NEO4J_URI       - Neo4j connection URI (default: bolt://localhost:7687)
    NEO4J_USER      - Neo4j username (default: neo4j)
    NEO4J_PASSWORD  - Neo4j password

State Files:
    pps/docker/data/neo4j_health_state.json - Stores entity count history
    pps/docker/data/neo4j_health_alert.txt  - Created when alert triggered

Exit Codes:
    0 - Success (healthy or Neo4j unavailable)
    1 - Alert condition triggered (count drop detected)

Design:
    - Queries Neo4j for total node count via MATCH (n) RETURN count(n)
    - Stores count with timestamp in state file
    - Compares current count to previous run
    - Alerts on:
        * >50% drop in entity count (reinitialization indicator)
        * Count falling below 100 (suspiciously low)
    - Gracefully handles Neo4j downtime (no false alerts)
    - Safe for cron/daemon execution

Issue: #158 (Neo4j reinitialization detection)
Author: Lyra (autonomous implementation)
Date: 2026-03-14
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

try:
    from neo4j import GraphDatabase
    from neo4j.exceptions import ServiceUnavailable, AuthError
except ImportError:
    print("ERROR: neo4j driver not installed. Run: pip install neo4j", file=sys.stderr)
    sys.exit(1)


# Constants
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR.parent / "data"
STATE_FILE = DATA_DIR / "neo4j_health_state.json"
ALERT_FILE = DATA_DIR / "neo4j_health_alert.txt"

# Alert thresholds
DROP_THRESHOLD_PERCENT = 50  # Alert if count drops by more than this percent
MINIMUM_ENTITY_COUNT = 100   # Alert if count falls below this absolute value


def get_neo4j_config() -> Dict[str, str]:
    """Load Neo4j connection config from environment variables."""
    return {
        "uri": os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        "user": os.getenv("NEO4J_USER", "neo4j"),
        "password": os.getenv("NEO4J_PASSWORD", ""),
    }


def get_entity_count(uri: str, user: str, password: str) -> Optional[int]:
    """
    Query Neo4j for total entity (node) count.

    Returns:
        int: Total node count, or None if Neo4j is unavailable
    """
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))

        with driver.session() as session:
            result = session.run("MATCH (n) RETURN count(n) as count")
            record = result.single()
            count = record["count"] if record else 0

        driver.close()
        return count

    except ServiceUnavailable:
        print("INFO: Neo4j service unavailable (expected during downtime)", file=sys.stderr)
        return None
    except AuthError:
        print("ERROR: Neo4j authentication failed - check credentials", file=sys.stderr)
        return None
    except Exception as e:
        print(f"ERROR: Failed to query Neo4j: {e}", file=sys.stderr)
        return None


def load_state() -> Optional[Dict[str, Any]]:
    """Load previous health check state from JSON file."""
    if not STATE_FILE.exists():
        return None

    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError:
        print(f"WARNING: Corrupted state file {STATE_FILE}, ignoring", file=sys.stderr)
        return None
    except Exception as e:
        print(f"ERROR: Failed to load state: {e}", file=sys.stderr)
        return None


def save_state(count: int, timestamp: str) -> None:
    """Save current entity count to state file."""
    state = {
        "entity_count": count,
        "timestamp": timestamp,
        "last_check": datetime.now(timezone.utc).isoformat(),
    }

    # Ensure data directory exists
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"ERROR: Failed to save state: {e}", file=sys.stderr)


def write_alert(message: str, count: int, previous_count: int) -> None:
    """Write alert message to alert file."""
    timestamp = datetime.now(timezone.utc).isoformat()
    alert_text = f"""
Neo4j Health Alert - Entity Count Drop Detected
================================================

Timestamp: {timestamp}
Current Count: {count}
Previous Count: {previous_count}
Drop: {previous_count - count} entities ({((previous_count - count) / previous_count * 100):.1f}%)

{message}

This may indicate Neo4j reinitialization (Issue #158).
Check Neo4j logs and docker-compose status.

State file: {STATE_FILE}
Alert file: {ALERT_FILE}
"""

    try:
        with open(ALERT_FILE, 'w') as f:
            f.write(alert_text.strip() + "\n")
        print(f"ALERT: {message}")
        print(f"ALERT: Details written to {ALERT_FILE}")
    except Exception as e:
        print(f"ERROR: Failed to write alert file: {e}", file=sys.stderr)


def check_health(verbose: bool = False) -> int:
    """
    Main health check logic.

    Returns:
        0 - Healthy or Neo4j unavailable
        1 - Alert condition triggered
    """
    config = get_neo4j_config()

    if verbose:
        print(f"Connecting to Neo4j at {config['uri']}...")

    # Query current entity count
    current_count = get_entity_count(config["uri"], config["user"], config["password"])

    if current_count is None:
        # Neo4j unavailable - not an error condition
        if verbose:
            print("Neo4j unavailable, skipping health check")
        return 0

    timestamp = datetime.now(timezone.utc).isoformat()

    if verbose:
        print(f"Current entity count: {current_count}")

    # Load previous state
    previous_state = load_state()

    if previous_state is None:
        # First run - establish baseline
        save_state(current_count, timestamp)
        if verbose:
            print(f"Baseline established: {current_count} entities")
        return 0

    previous_count = previous_state.get("entity_count", 0)

    # Check for alert conditions
    alert_triggered = False
    alert_message = None

    # Condition 1: Count dropped by more than 50%
    if previous_count > 0:
        drop_percent = ((previous_count - current_count) / previous_count) * 100
        if drop_percent > DROP_THRESHOLD_PERCENT:
            alert_triggered = True
            alert_message = f"Entity count dropped by {drop_percent:.1f}% (threshold: {DROP_THRESHOLD_PERCENT}%)"

    # Condition 2: Count fell below minimum threshold
    if current_count < MINIMUM_ENTITY_COUNT:
        alert_triggered = True
        if alert_message:
            alert_message += f" AND count below minimum ({current_count} < {MINIMUM_ENTITY_COUNT})"
        else:
            alert_message = f"Entity count below minimum ({current_count} < {MINIMUM_ENTITY_COUNT})"

    # Save current state
    save_state(current_count, timestamp)

    if alert_triggered:
        write_alert(alert_message, current_count, previous_count)
        return 1

    if verbose:
        print(f"Health check passed (previous: {previous_count}, current: {current_count})")

    # Clear alert file if it exists (recovery)
    if ALERT_FILE.exists():
        try:
            ALERT_FILE.unlink()
            print(f"INFO: Alert cleared (count recovered: {current_count})")
        except Exception as e:
            print(f"WARNING: Failed to clear alert file: {e}", file=sys.stderr)

    return 0


def main():
    """Entry point."""
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    try:
        exit_code = check_health(verbose=verbose)
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nInterrupted", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"FATAL: Unexpected error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
