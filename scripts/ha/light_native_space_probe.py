#!/usr/bin/env python3
"""Native-space resolution probe for the entity bulbs.

WHY THIS EXISTS (2026-05-30):
  The bulb's `supported_color_modes` is `[color_temp, xy]` — it has NO native
  RGB mode. So HA's reported `rgb_color` is a *derived, lossy* back-projection
  from the bulb's real xy state (peak-channel normalized → the dominant channel
  is pinned to 255, and saturated bases fold many xy points to one rgb). The
  side-band decoder was reading that lossy derived attribute, which is why ±3
  deltas vanished and why Jeff sees the wobble in HA's *reporting* but never in
  the bulb's actual *operation* (the bulb displays the xy faithfully).

QUESTION THIS ANSWERS:
  If we command and read back in the bulb's NATIVE space (xy), how small a step
  still round-trips distinctly? That sets the true minimum side-band delta —
  and may make the ±8-on-rgb plan unnecessary (or let words ride any base,
  since xy has no peak channel to normalize).

WHAT IT DOES (read-mostly; sub-perceptual writes to its OWN bulb only):
  1. Command gold natively in xy, baseline read (xy + hs + rgb + brightness).
  2. Repeat the SAME command twice → measure readback jitter (is it stable?).
  3. Step x then y by an increasing ladder of deltas; read back each. Report
     readback-vs-command error and whether each step is distinguishable from
     the base in the native attribute. Gold is a saturated base, so this is
     already the hard case.
  4. Restore resting gold.

Pure stdlib (urllib), mirrors scripts/light.py + light_roundtrip_probe.py.

Usage:
  python3 scripts/ha/light_native_space_probe.py
  ENTITY_NAME=lyra python3 scripts/ha/light_native_space_probe.py
"""

import os
import time
import json
import math
import urllib.request

HA_URL = "http://10.0.0.50:8123"
HA_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJjODU1MGFjZGU2MzU0NGJjYjk1Njc0ZjlkZWI1NmRhOSIsImlhdCI6MTc3NzE3NjQ1OSwiZXhwIjoyMDkyNTM2NDU5fQ.ppLlnf-WzVcqfxMcbVbXe_4pisaqrQV_1QJH558W3Eo"
ENTITY_NAME = os.environ.get("ENTITY_NAME", "lyra")
LIGHT_ID = f"light.{ENTITY_NAME}"
HEADERS = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}

# Gold base in the bulb's native space (from Jeff's HA dev-tools dump 2026-05-30:
# rgb 255,217,0 ↔ xy 0.491,0.477). This is a SATURATED base — the hard case.
GOLD_XY = [0.491, 0.477]
GOLD_RGB = [252, 215, 3]
SETTLE = 0.8   # let the command settle before reading (transition=0 still has Zigbee latency)


def _post(path, data):
    req = urllib.request.Request(
        f"{HA_URL}{path}", data=json.dumps(data).encode(), headers=HEADERS, method="POST"
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode())


def _get(path):
    req = urllib.request.Request(f"{HA_URL}{path}", headers=HEADERS, method="GET")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode())


def set_xy(xy, brightness=35):
    """Command natively in xy — the bulb's real working space."""
    _post("/api/services/light/turn_on", {
        "entity_id": LIGHT_ID,
        "xy_color": [round(xy[0], 4), round(xy[1], 4)],
        "brightness": int(brightness),
        "transition": 0,
    })


def read_state():
    a = _get(f"/api/states/{LIGHT_ID}").get("attributes", {})
    return {
        "xy": a.get("xy_color"),
        "hs": a.get("hs_color"),
        "rgb": a.get("rgb_color"),
        "mode": a.get("color_mode"),
        "bright": a.get("brightness"),
    }


def xy_dist(a, b):
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def cmd_and_read(label, xy, brightness=35):
    set_xy(xy, brightness)
    time.sleep(SETTLE)
    s = read_state()
    err = xy_dist(s["xy"], xy) if s["xy"] else None
    print(f"  {label:22} cmd_xy={xy}  ->  read_xy={s['xy']} hs={s['hs']} rgb={s['rgb']} "
          f"mode={s['mode']}  err={err:.5f}" if err is not None
          else f"  {label:22} cmd_xy={xy}  ->  read=None")
    return s


def main():
    print(f"Native-space probe — {LIGHT_ID} @ {HA_URL}")
    print(f"Base = gold xy={GOLD_XY} (saturated base, the hard case)\n")

    # 0. Baseline
    print("── baseline ──")
    base = cmd_and_read("gold", GOLD_XY)

    # 1. Jitter: same command twice. If readback differs, the floor is noise, not quantization.
    print("\n── jitter (same command x3) ──")
    reads = [cmd_and_read(f"gold rep{i+1}", GOLD_XY)["xy"] for i in range(3)]
    jit = max(xy_dist(reads[0], r) for r in reads[1:]) if all(reads) else None
    print(f"  → max jitter between identical commands: {jit:.5f}" if jit is not None else "  → jitter n/a")

    # 2. Resolution ladder: step x, then y, by increasing deltas. Find smallest
    #    step whose readback is distinguishable from the base (> jitter floor).
    ladder = [0.001, 0.002, 0.003, 0.005, 0.008, 0.012]
    for axis, idx in (("+x", 0), ("+y", 1)):
        print(f"\n── resolution ladder, {axis} ──")
        for d in ladder:
            xy = list(GOLD_XY)
            xy[idx] = round(xy[idx] + d, 4)
            s = cmd_and_read(f"{axis} +{d}", xy)
            sep = xy_dist(s["xy"], base["xy"]) if (s["xy"] and base["xy"]) else None
            flag = ""
            if sep is not None and jit is not None:
                flag = "  ✓ distinct" if sep > 2 * jit else "  ✗ in-noise"
            print(f"     sep_from_base={sep:.5f}{flag}" if sep is not None else "     sep=n/a")

    # 3. Restore
    print("\nRestoring resting gold…")
    _post("/api/services/light/turn_on", {
        "entity_id": LIGHT_ID, "rgb_color": GOLD_RGB, "brightness": 35, "transition": 1,
    })
    print("done.")


if __name__ == "__main__":
    main()
