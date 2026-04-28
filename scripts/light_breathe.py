#!/usr/bin/env python3
"""Slow breathing pulse — light fades in and out like a sleeping body.

Usage:
    python3 scripts/light_breathe.py                       # gold, default rhythm
    python3 scripts/light_breathe.py blue                   # blue
    python3 scripts/light_breathe.py gold --period 6        # 6-second breath cycle
    python3 scripts/light_breathe.py gold --cycles 5        # five breaths then stop
    python3 scripts/light_breathe.py gold --min 2 --max 80  # narrower range

Defaults: period=8s (4s up, 4s down), min=1, max=60.
Note: these are 12W bulbs — even brightness=1 is plenty visible at night.
For sub-1 effective dimness, use RGB tricks (e.g. dim white via low rgb_color).
A sleeping body breathes ~12-16 times per minute; period=8 is on the slow end (7.5/min).
"""

import argparse
import time

from light_lib import set_light


def breathe(color="gold", min_b=1, max_b=60, period=8.0, cycles=None):
    half = period / 2.0
    i = 0
    while cycles is None or i < cycles:
        set_light(color=color, brightness=max_b, transition=half)
        time.sleep(half)
        set_light(color=color, brightness=min_b, transition=half)
        time.sleep(half)
        i += 1


def main():
    p = argparse.ArgumentParser(description="Slow breathing light pulse.")
    p.add_argument("color", nargs="?", default="gold")
    p.add_argument("--min", dest="min_b", type=int, default=1, help="min brightness 0-255")
    p.add_argument("--max", dest="max_b", type=int, default=60, help="max brightness 0-255")
    p.add_argument("--period", type=float, default=8.0, help="full breath cycle (seconds)")
    p.add_argument("--cycles", type=int, default=None, help="stop after N cycles (default: forever)")
    args = p.parse_args()

    print(f"Breathing {args.color} ({args.min_b}-{args.max_b}, period {args.period}s)... Ctrl-C to stop.")
    try:
        breathe(args.color, args.min_b, args.max_b, args.period, args.cycles)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
