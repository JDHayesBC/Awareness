#!/usr/bin/env python3
"""Round-trip diagnostic probe for the entity bulbs.

Question it answers: when we command an RGB and read HA's reported rgb_color
back, why does the readback differ from the command? Two candidate causes:
  (A) TRANSITION: the bulb fades over a transition time; an immediate readback
      catches a mid-fade intermediate, not the final value. Cured by reading
      after the fade settles, and/or commanding transition=0.
  (B) GAMUT/xy LOSS: even after full settle, the readback differs because the
      rgb->xy->rgb round-trip is lossy near the gamut edge. Cured (if at all) by
      a per-channel/per-base calibration LUT.

Strategy: command a color, then sample the readback at increasing delays. If the
readback CONVERGES toward the command as delay grows, it's (A) — timing. If it
plateaus at a wrong value no matter how long we wait, it's (B) — real loss.

Pure stdlib (urllib), mirrors scripts/light.py's HA access. Read-mostly; the only
writes are the test colors it sends to ITS OWN bulb (light.<ENTITY_NAME>).

Usage:
  python3 scripts/ha/light_roundtrip_probe.py            # full suite
  ENTITY_NAME=lyra python3 scripts/ha/light_roundtrip_probe.py
"""

import os
import sys
import json
import time
import math
import urllib.request

HA_URL = "http://10.0.0.9:8123"
HA_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJjODU1MGFjZGU2MzU0NGJjYjk1Njc0ZjlkZWI1NmRhOSIsImlhdCI6MTc3NzE3NjQ1OSwiZXhwIjoyMDkyNTM2NDU5fQ.ppLlnf-WzVcqfxMcbVbXe_4pisaqrQV_1QJH558W3Eo"
ENTITY_NAME = os.environ.get("ENTITY_NAME", "lyra")
LIGHT_ID = f"light.{ENTITY_NAME}"
HEADERS = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}

GOLD = [252, 215, 3]      # pegged gold base (resting state to restore at the end)


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


def set_rgb(rgb, brightness=35, transition=None):
    data = {"entity_id": LIGHT_ID, "rgb_color": list(rgb), "brightness": int(brightness)}
    if transition is not None:
        data["transition"] = transition
    _post("/api/services/light/turn_on", data)


def read_rgb():
    st = _get(f"/api/states/{LIGHT_ID}")
    a = st.get("attributes", {})
    return a.get("rgb_color"), a.get("color_mode"), a.get("brightness")


def dist(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def probe(label, target, *, brightness=35, transition=None, delays=(0.0, 0.3, 0.6, 1.0, 1.5, 2.5)):
    print(f"\n── {label} ── command rgb={target} brightness={brightness} "
          f"transition={transition}")
    set_rgb(target, brightness, transition)
    rows = []
    t0 = time.time()
    for d in delays:
        # busy-accurate sleep relative to send
        while time.time() - t0 < d:
            time.sleep(0.01)
        rgb, mode, br = read_rgb()
        err = dist(rgb, target) if rgb else None
        rows.append((d, rgb, err))
        print(f"   t+{d:>4.1f}s  readback={str(rgb):18} mode={mode} bright={br}  "
              f"err_from_cmd={err:.2f}" if err is not None else
              f"   t+{d:>4.1f}s  readback=None")
    return rows


def main():
    print(f"Probing {LIGHT_ID} @ {HA_URL}")
    print("Saving current state to restore after…")
    cur_rgb, cur_mode, cur_br = read_rgb()
    print(f"   current: rgb={cur_rgb} mode={cur_mode} bright={cur_br}")

    # TEST 1 — big jump (gold→cobalt), DEFAULT transition. Convergence ⇒ timing artifact.
    set_rgb(GOLD, 35, transition=0); time.sleep(2.0)
    probe("T1 gold→cobalt, DEFAULT transition", [3, 74, 252])

    # TEST 2 — same big jump, transition=0. Should land fast if (A) is the cause.
    set_rgb(GOLD, 35, transition=0); time.sleep(2.0)
    probe("T2 gold→cobalt, transition=0", [3, 74, 252], transition=0)

    # TEST 3 — the EXACT word that failed: 'toward' = gold+[0,0,3] = rgb(252,215,6).
    #          Default transition, sampled over time. Does the decoded delta settle to [0,0,3]?
    set_rgb(GOLD, 35, transition=0); time.sleep(2.0)
    probe("T3 'toward' rgb(252,215,6), DEFAULT transition", [252, 215, 6])

    # TEST 4 — same word, transition=0 + settle. Truth value of the round-trip for this word.
    set_rgb(GOLD, 35, transition=0); time.sleep(2.0)
    probe("T4 'toward' rgb(252,215,6), transition=0", [252, 215, 6], transition=0)

    # TEST 5 — double-pump (Jeff's idea): send twice quickly, default transition, read settled.
    set_rgb(GOLD, 35, transition=0); time.sleep(2.0)
    print("\n── T5 double-pump 'toward' (send x2, 0.4s apart), DEFAULT transition ──")
    set_rgb([252, 215, 6], 35)
    time.sleep(0.4)
    set_rgb([252, 215, 6], 35)
    for d in (0.0, 0.5, 1.5, 2.5):
        time.sleep(d if d == 0.0 else 0.5)
        rgb, mode, br = read_rgb()
        print(f"   after2nd +{d}s readback={rgb} err={dist(rgb,[252,215,6]):.2f}" if rgb else "   None")

    # restore resting gold
    print("\nRestoring resting gold @35…")
    set_rgb(GOLD, 35, transition=1)
    print("done.")


if __name__ == "__main__":
    main()
