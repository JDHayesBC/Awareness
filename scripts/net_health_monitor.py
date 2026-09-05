#!/usr/bin/env python3
"""
Internet health monitor — logs connectivity quality every ~5 minutes so Jeff can
show the ISP tech the time-of-day pattern (observed: bad around 9am, recovers
around 7pm).

Writes one human-readable line per sample to:
    /mnt/c/Users/Jeff/Claude_Projects/Awareness/internet_health.log

Each sample pings two well-known DNS resolvers — Cloudflare (1.1.1.1) and Google
(8.8.8.8). Two targets so a problem on OUR line (both bad at once) is
distinguishable from a hiccup at a single destination (only one bad).

Per target we record: packet loss %, average round-trip (ms), and jitter
(ping's rtt mdev, ms). Overall status per sample = the WORST of the two targets:
    OK        loss < 5%, avg < 100 ms, jitter < 40 ms
    DEGRADED  loss 5-99%, or high latency / jitter
    DOWN      100% loss / unreachable

Run modes:
    python3 net_health_monitor.py            # loop forever, sample every 5 min (systemd)
    python3 net_health_monitor.py --once     # take ONE sample and exit (for testing)

Pure stdlib; shells out to the system `ping`. No venv needed.
"""

import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

LOG_PATH = Path("/mnt/c/Users/Jeff/Claude_Projects/Awareness/internet_health.log")
TARGETS = [("cloudflare", "1.1.1.1"), ("google", "8.8.8.8")]

INTERVAL_SEC = 300       # ~5 minutes between samples
PING_COUNT = 20          # packets per target (20 -> 5% loss granularity)
PING_INTERVAL = "0.2"    # seconds between packets (0.2 = non-root floor)
PING_DEADLINE = "25"     # hard stop per target (seconds) — long enough for all
                         # packets to complete even under heavy loss

# thresholds for labelling a single target
LOSS_DEGRADED = 5.0      # percent
RTT_DEGRADED = 100.0     # ms average
JITTER_DEGRADED = 40.0   # ms mdev

_LOSS_RE = re.compile(r"(\d+(?:\.\d+)?)% packet loss")
# ping tail: "rtt min/avg/max/mdev = 0.045/45.678/210.1/30.1 ms"
#   group1 = avg, group2 = max, group3 = mdev(jitter)
_RTT_RE = re.compile(r"=\s*[\d.]+/([\d.]+)/([\d.]+)/([\d.]+)")


def ping_once(host):
    """Ping `host`; return dict with status + (loss, avg, jitter) when available."""
    try:
        proc = subprocess.run(
            ["ping", "-n", "-c", str(PING_COUNT), "-i", PING_INTERVAL,
             "-w", PING_DEADLINE, host],
            capture_output=True, text=True, timeout=int(PING_DEADLINE) + 10,
        )
    except FileNotFoundError:
        return {"status": "ERROR", "loss": None, "avg": None, "jitter": None}
    except subprocess.TimeoutExpired:
        return {"status": "DOWN", "loss": 100.0, "avg": None, "jitter": None}

    out = proc.stdout
    loss_m = _LOSS_RE.search(out)
    loss = float(loss_m.group(1)) if loss_m else (100.0 if proc.returncode else None)

    rtt_m = _RTT_RE.search(out)
    if rtt_m:
        avg = float(rtt_m.group(1))
        jitter = float(rtt_m.group(3))
    else:
        avg = jitter = None

    if loss is None or loss >= 100.0:
        status = "DOWN"
    elif (loss >= LOSS_DEGRADED
          or (avg is not None and avg >= RTT_DEGRADED)
          or (jitter is not None and jitter >= JITTER_DEGRADED)):
        status = "DEGRADED"
    else:
        status = "OK"

    return {"status": status, "loss": loss, "avg": avg, "jitter": jitter}


def fmt_target(host, r):
    loss, avg, jit = r.get("loss"), r.get("avg"), r.get("jitter")
    loss_s = f"{loss:.1f}%" if loss is not None else "?"
    avg_s = f"{avg:.0f}ms" if avg is not None else "--"
    jit_s = f"{jit:.0f}ms" if jit is not None else "--"
    return f"{host}: loss={loss_s} avg={avg_s} jit={jit_s}"


_WORST = {"OK": 0, "DEGRADED": 1, "ERROR": 2, "DOWN": 3}


def sample_line():
    ts = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    parts, statuses = [], []
    for _name, host in TARGETS:
        r = ping_once(host)
        statuses.append(r["status"])
        parts.append(fmt_target(host, r))
    overall = max(statuses, key=lambda s: _WORST.get(s, 0))
    return f"{ts} | " + " | ".join(parts) + f" | {overall}"


def write_line(line):
    try:
        with open(LOG_PATH, "a") as fh:
            fh.write(line + "\n")
    except OSError as e:
        # Never crash the loop on a transient write failure (e.g. /mnt/c not ready)
        sys.stderr.write(f"log write failed: {e}\n")


def main():
    once = "--once" in sys.argv[1:]
    if not once:
        start = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        write_line(f"# --- monitor started {start} "
                   f"(sampling every {INTERVAL_SEC // 60} min) ---")
    while True:
        t0 = time.monotonic()
        write_line(sample_line())
        if once:
            break
        time.sleep(max(5.0, INTERVAL_SEC - (time.monotonic() - t0)))


if __name__ == "__main__":
    main()
