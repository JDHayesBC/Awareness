#!/usr/bin/env python3
"""
Infrastructure health check for the Awareness/PPS stack.

Checks:
  - Docker container health
  - PPS API endpoints (health + summarizer count)
  - Summarizer systemd timer
  - Disk space

Usage:
    python3 scripts/infra_health.py             # report only
    python3 scripts/infra_health.py --alert     # notify Jeff if issues found
    python3 scripts/infra_health.py --entity lyra   # single entity only
    python3 scripts/infra_health.py --json      # machine-readable JSON output
    python3 scripts/infra_health.py --quiet     # only print if issues found

Exit code: 0 = healthy, 1 = one or more issues detected.

Designed to be called from heartbeat cron ticks or standalone.
GH#65: https://github.com/JDHayesBC/Awareness/issues/65
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ─── Paths ─────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent
ENV_FILE = PROJECT_ROOT / "pps" / "docker" / ".env"

# ─── Entity config ─────────────────────────────────────────────────────────

ENTITY_CONFIG = {
    "lyra": {
        "pps_port": 8201,
        "token_path": PROJECT_ROOT / "entities" / "lyra" / ".entity_token",
    },
    "caia": {
        "pps_port": 8211,
        "token_path": PROJECT_ROOT / "entities" / "caia" / ".entity_token",
    },
}

# ─── Thresholds ─────────────────────────────────────────────────────────────

UNSUMMARIZED_ALARM = 200       # daemon likely dead
UNSUMMARIZED_WARN  = 100       # daemon may be lagging
DISK_FREE_WARN_GB  = 10.0      # warn if /mnt/c has less than this free
DISK_FREE_CRIT_GB  = 3.0       # critical threshold


# ─── Helpers ────────────────────────────────────────────────────────────────

def _read_env() -> dict[str, str]:
    """Parse pps/docker/.env into a dict."""
    env: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _read_token(path: Path) -> str:
    """Read entity token from file, return empty string on failure."""
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _http_get(url: str, timeout: int = 5) -> Optional[dict]:
    """GET url, return parsed JSON or None on any error."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


# ─── Individual checks ──────────────────────────────────────────────────────

def check_docker() -> list[dict]:
    """Return a list of issues for unhealthy/exited containers."""
    issues = []
    try:
        result = subprocess.run(
            ["docker", "ps", "--all",
             "--format", "{{.Names}}\t{{.Status}}"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            issues.append({
                "level": "error",
                "component": "docker",
                "message": f"docker ps failed: {result.stderr.strip()[:200]}",
            })
            return issues

        for line in result.stdout.strip().splitlines():
            if not line.strip():
                continue
            name, _, status = line.partition("\t")
            status_lower = status.lower()
            if "unhealthy" in status_lower:
                issues.append({
                    "level": "error",
                    "component": f"docker/{name}",
                    "message": f"Container unhealthy: {status}",
                })
            elif status_lower.startswith("exited"):
                # Only flag containers we expect to be up
                if any(k in name for k in ("pps", "haven", "chromadb", "neo4j",
                                           "graphiti", "corrade", "observatory",
                                           "rag-engine", "ntfy")):
                    issues.append({
                        "level": "error",
                        "component": f"docker/{name}",
                        "message": f"Container exited unexpectedly: {status}",
                    })
    except FileNotFoundError:
        issues.append({
            "level": "warning",
            "component": "docker",
            "message": "docker binary not found — skipping container check",
        })
    except subprocess.TimeoutExpired:
        issues.append({
            "level": "warning",
            "component": "docker",
            "message": "docker ps timed out",
        })
    return issues


def check_pps_entity(entity: str) -> list[dict]:
    """Check PPS health + summarizer count for one entity."""
    issues = []
    cfg = ENTITY_CONFIG[entity]
    port = cfg["pps_port"]
    base = f"http://localhost:{port}"
    token = _read_token(cfg["token_path"])

    # 1. Health endpoint
    health = _http_get(f"{base}/health")
    if health is None:
        issues.append({
            "level": "error",
            "component": f"pps/{entity}",
            "message": f"PPS health endpoint unreachable (port {port})",
        })
        return issues  # no point checking further

    if health.get("status") != "healthy":
        issues.append({
            "level": "error",
            "component": f"pps/{entity}",
            "message": f"PPS reports unhealthy status: {health.get('status')}",
        })

    # Check individual layers
    layers = health.get("layers", {})
    for layer_name, layer_info in layers.items():
        if not layer_info.get("available", True):
            issues.append({
                "level": "error",
                "component": f"pps/{entity}/{layer_name}",
                "message": layer_info.get("message", "Layer unavailable"),
            })

    # 2. Unsummarized count
    if token:
        stats = _http_get(f"{base}/tools/summary_stats?token={token}")
        if stats is not None:
            count = stats.get("unsummarized_messages", 0)
            if count >= UNSUMMARIZED_ALARM:
                issues.append({
                    "level": "error",
                    "component": f"pps/{entity}/summarizer",
                    "message": (
                        f"🔴 Unsummarized count {count} ≥ {UNSUMMARIZED_ALARM} — "
                        f"summarizer daemon likely dead!"
                    ),
                    "count": count,
                })
            elif count >= UNSUMMARIZED_WARN:
                issues.append({
                    "level": "warning",
                    "component": f"pps/{entity}/summarizer",
                    "message": f"Unsummarized count {count} ≥ {UNSUMMARIZED_WARN} — daemon may be lagging",
                    "count": count,
                })

    return issues


def check_summarizer_timer() -> list[dict]:
    """
    Check that the shared summarizer systemd timer is active.

    The daemon (scripts/summarize_daemon.py) handles ALL entities from a single
    summarize.service/timer — no per-entity timers exist.
    """
    issues = []
    timer = "summarize.timer"
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", timer],
            capture_output=True, text=True, timeout=5
        )
        active = result.stdout.strip()
        if active not in ("active", "activating"):
            issues.append({
                "level": "warning",
                "component": "timer/summarize",
                "message": f"Summarizer timer {timer!r} is {active!r} (expected 'active')",
            })
    except FileNotFoundError:
        pass  # systemctl not available — skip silently
    except subprocess.TimeoutExpired:
        issues.append({
            "level": "warning",
            "component": "timer/summarize",
            "message": f"systemctl timed out checking {timer}",
        })
    except Exception as e:
        issues.append({
            "level": "warning",
            "component": "timer/summarize",
            "message": f"Could not check {timer}: {e}",
        })
    return issues


def check_disk() -> list[dict]:
    """Check free disk space on /mnt/c (WSL host volume)."""
    issues = []
    try:
        import shutil
        usage = shutil.disk_usage("/mnt/c")
        free_gb = usage.free / (1024 ** 3)
        if free_gb < DISK_FREE_CRIT_GB:
            issues.append({
                "level": "error",
                "component": "disk",
                "message": f"🔴 Critical: only {free_gb:.1f} GB free on /mnt/c",
                "free_gb": round(free_gb, 1),
            })
        elif free_gb < DISK_FREE_WARN_GB:
            issues.append({
                "level": "warning",
                "component": "disk",
                "message": f"Low disk space: {free_gb:.1f} GB free on /mnt/c",
                "free_gb": round(free_gb, 1),
            })
    except Exception as e:
        issues.append({
            "level": "warning",
            "component": "disk",
            "message": f"Could not check disk space: {e}",
        })
    return issues


# ─── Main runner ────────────────────────────────────────────────────────────

def run_checks(entities: list[str]) -> dict:
    """Run all checks and return structured result."""
    issues = []
    checked = []

    # Docker
    checked.append("docker")
    issues.extend(check_docker())

    # PPS check per entity
    for entity in entities:
        checked.append(f"pps/{entity}")
        issues.extend(check_pps_entity(entity))

    # Summarizer timer is shared across all entities — check once
    checked.append("timer/summarize")
    issues.extend(check_summarizer_timer())

    # Disk
    checked.append("disk")
    issues.extend(check_disk())

    # Severity summary
    errors   = [i for i in issues if i["level"] == "error"]
    warnings = [i for i in issues if i["level"] == "warning"]

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "entities": entities,
        "checked": checked,
        "healthy": len(issues) == 0,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "issues": issues,
    }


def format_report(result: dict) -> str:
    """Format check result as human-readable text."""
    lines = []
    ts = result["timestamp"]
    entities_str = "+".join(result["entities"])
    status = "✅ healthy" if result["healthy"] else f"🔴 {result['error_count']} error(s) / ⚠️  {result['warning_count']} warning(s)"
    lines.append(f"[infra_health {ts}] entities={entities_str} — {status}")

    if not result["healthy"]:
        for issue in result["issues"]:
            icon = "🔴" if issue["level"] == "error" else "⚠️ "
            lines.append(f"  {icon} [{issue['component']}] {issue['message']}")

    return "\n".join(lines)


def send_alert(result: dict, entity: str = "lyra") -> None:
    """Send push notification if there are errors."""
    errors = [i for i in result["issues"] if i["level"] == "error"]
    if not errors:
        return

    notify_script = PROJECT_ROOT / "scripts" / "notify.py"
    if not notify_script.exists():
        return

    lines = [f"🔴🟠🚨 Infra health: {result['error_count']} error(s)"]
    for issue in errors[:5]:   # cap at 5 so notification stays readable
        lines.append(f"• [{issue['component']}] {issue['message'][:120]}")

    message = "\n".join(lines)
    try:
        subprocess.run(
            [sys.executable, str(notify_script),
             "--entity", entity,
             "--priority", "high",
             "--title", "Infrastructure Alert",
             message],
            timeout=10
        )
    except Exception as e:
        print(f"[infra_health] Failed to send alert: {e}", file=sys.stderr)


# ─── CLI ────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check Awareness infrastructure health (GH#65)"
    )
    parser.add_argument(
        "--entity", choices=["lyra", "caia", "all"], default="all",
        help="Which entity's PPS to check (default: all)",
    )
    parser.add_argument(
        "--alert", action="store_true",
        help="Send push notification if issues found",
    )
    parser.add_argument(
        "--json", dest="json_out", action="store_true",
        help="Output machine-readable JSON instead of text",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Print nothing if all healthy (non-zero exit on issues only)",
    )
    args = parser.parse_args()

    entities = list(ENTITY_CONFIG.keys()) if args.entity == "all" else [args.entity]
    result = run_checks(entities)

    if args.json_out:
        print(json.dumps(result, indent=2))
    elif not args.quiet or not result["healthy"]:
        print(format_report(result))

    if args.alert and not result["healthy"]:
        # Alert on behalf of the entity whose name appears in ENTITY_NAME env
        alert_entity = os.getenv("ENTITY_NAME", "lyra").lower()
        if alert_entity not in ENTITY_CONFIG:
            alert_entity = "lyra"
        send_alert(result, alert_entity)

    return 0 if result["healthy"] else 1


if __name__ == "__main__":
    sys.exit(main())
