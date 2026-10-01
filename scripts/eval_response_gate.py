#!/usr/bin/env python3
"""Evaluate the Haven response gate (GH #360) against a labeled conversation suite.

Sweeps Jev `turns` x `threshold`, and reports two columns per setting:

  deployed  — L0 (name-mention, ritual greeting) first, as bot.py does; Jev only when L0 doesn't fire
  jev-raw   — Jev alone, to show what it WOULD silence if L0 ever slipped

The cost that matters is a false negative: a case labeled `respond` that the gate
silences. Those are listed by id, loudest. `either` cases are never scored.

Guards (each one turns a broken gate into a perfect-looking score if it's missing):
  - refuses to run without an API key (empty key => respond=True, no network call)
  - counts error/fallback results separately; a fail-open API is not recall
  - passes turns/threshold explicitly; never relies on the HAVEN_JEV_* env defaults

Run with the PPS venv (needs httpx):
  pps/venv/bin/python3 scripts/eval_response_gate.py
  pps/venv/bin/python3 scripts/eval_response_gate.py --turns 5,10 --thresholds 0.2,0.3
"""

import argparse
import asyncio
import json
import os
import statistics
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

import httpx  # noqa: E402

from haven.response_gate import layer0_name_mentioned, layer_jev  # noqa: E402

try:  # L0b, added in bot.py alongside name-mention; mirror whatever production runs
    from haven.response_gate import layer0_ritual_greeting  # noqa: E402
except ImportError:
    def layer0_ritual_greeting(messages):
        return False

SUITE = PROJECT_DIR / "haven" / "tests" / "fixtures" / "response_decision_suite.jsonl"
KEY_FILE = PROJECT_DIR / "work" / "system-one-models" / "jev_api_key.txt"


def load_key() -> str:
    key = os.getenv("HAVEN_JEV_API_KEY", "")
    if not key and KEY_FILE.exists():
        key = KEY_FILE.read_text().strip()
    return key


def load_suite(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


async def score_case(case, key, turns, threshold, client, repeats=1):
    """Jev `repeats` times per case; the deployed column reuses it unless L0 fires.

    Jev is not deterministic — the same input can land on either side of a threshold
    (sl-010 measured 0.28..0.61 over 5 runs). One run per case understates that, so
    scoring uses the MINIMUM p seen: the worst case is the one where she goes silent.
    """
    ps, ms, reasons, fallback = [], [], [], False
    for _ in range(repeats):
        d = await layer_jev(case["entity"], case["messages"], api_key=key,
                            turns=turns, threshold=threshold, client=client)
        # "<jev ..." = disabled/error (fail-open). "choice=?" = Jev answered with neither
        # YES nor NO and layer_jev silently substituted p=0.5 — also not a real score.
        if d.reason.startswith("<jev") or "choice=?" in d.reason:
            fallback = True
        ps.append(d.p_respond)
        ms.append(d.elapsed_ms or 0)
        reasons.append(d.reason)
    l0 = (layer0_name_mentioned(case["entity"], case["messages"])
          or layer0_ritual_greeting(case["messages"]))
    p = min(ps)
    return {
        "id": case["id"], "expected": case["expected"], "ambiguity": case["ambiguity"],
        "p": p, "p_max": max(ps), "ps": ps, "ms": statistics.median(ms), "ms_all": ms,
        "fallback": fallback, "reason": reasons[0],
        "raw": p >= threshold, "deployed": True if l0 else p >= threshold, "l0": l0,
    }


def tally(results, column):
    fn, fp, tp, tn = [], [], 0, 0
    for r in results:
        if r["expected"] == "either" or r["fallback"]:
            continue
        said = r[column]
        if r["expected"] == "respond":
            if said:
                tp += 1
            else:
                fn.append(r["id"])
        else:
            if said:
                fp.append(r["id"])
            else:
                tn += 1
    return tp, tn, fn, fp


TIERS = ("low", "med", "high")


def print_tiers(rows, th):
    """FN/FP by ambiguity tier, two ways (deployed column only).

    guard    — scored on the MIN p across repeats: the worst case, a ceiling on misses.
    expected — per-run mean: production samples Jev once, so this is the miss rate
               people will actually live with.

    A miss on a `low` case is an alarm. Misses in `high` are the filter having teeth;
    the question there is what share, not whether any.
    """
    for tier in TIERS:
        tr = [r for r in rows if r["ambiguity"] == tier and r["expected"] != "either" and not r["fallback"]]
        resp = [r for r in tr if r["expected"] == "respond"]
        sil = [r for r in tr if r["expected"] == "silent"]
        if not tr:
            continue

        def run_rate(r, want_respond):
            if r["l0"]:
                return 0.0 if want_respond else 1.0
            said = [x >= th for x in r["ps"]]
            return sum((not s) if want_respond else s for s in said) / len(said)

        g_fn = sum(not r["deployed"] for r in resp)
        e_fn = sum(run_rate(r, True) for r in resp)
        g_fp = sum(r["deployed"] for r in sil)
        e_fp = sum(run_rate(r, False) for r in sil)
        pct = lambda a, n: f"{100 * a / n:3.0f}%" if n else "  - "
        print(f"      {tier:4s} miss guard {g_fn:2d}/{len(resp):<2d} {pct(g_fn, len(resp))} "
              f"expected {e_fn:4.1f} {pct(e_fn, len(resp))} | "
              f"nag guard {g_fp:2d}/{len(sil):<2d} expected {e_fp:4.1f} {pct(e_fp, len(sil))}")


async def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--suite", type=Path, default=SUITE)
    ap.add_argument("--turns", default="3,5,10,20")
    ap.add_argument("--thresholds", default="0.1,0.2,0.3,0.4,0.5")
    ap.add_argument("--channel", help="only cases from this channel (haven, sl)")
    ap.add_argument("--repeats", type=int, default=3,
                    help="Jev calls per case; scoring uses the min p (default 3)")
    ap.add_argument("--json", type=Path, help="write every per-case result here")
    args = ap.parse_args()

    key = load_key()
    if not key:
        sys.exit("REFUSING: no Jev API key. layer_jev passes everything through without one, "
                 "which would score as perfect recall. Set HAVEN_JEV_API_KEY or create "
                 f"{KEY_FILE.relative_to(PROJECT_DIR)}.")

    cases = load_suite(args.suite)
    if args.channel:
        cases = [c for c in cases if c["channel"] == args.channel]
    turns_list = [int(t) for t in args.turns.split(",")]
    thresholds = [float(t) for t in args.thresholds.split(",")]

    n_resp = sum(c["expected"] == "respond" for c in cases)
    n_sil = sum(c["expected"] == "silent" for c in cases)
    print(f"repeats per case: {args.repeats} (scored on min p)")
    print(f"suite: {len(cases)} cases ({n_resp} respond, {n_sil} silent, "
          f"{len(cases) - n_resp - n_sil} either)\n")

    all_rows = []
    async with httpx.AsyncClient() as client:
        for turns in turns_list:
            # p_respond doesn't depend on the threshold, so query once per (case, turns)
            base = [await score_case(c, key, turns, 1.0, client, args.repeats) for c in cases]
            ms = [m for r in base if not r["fallback"] for m in r["ms_all"]]
            n_fb = sum(r["fallback"] for r in base)
            lat = f"median {statistics.median(ms):.0f}ms max {max(ms):.0f}ms" if ms else "no successful calls"
            print(f"== turns={turns}  latency {lat}  fallbacks {n_fb}/{len(base)}")
            if n_fb:
                print("   ⚠ fallbacks are excluded from scoring; reasons:",
                      sorted({r['reason'] for r in base if r['fallback']}))
            for th in thresholds:
                rows = [dict(r, raw=r["p"] >= th, deployed=True if r["l0"] else r["p"] >= th,
                             turns=turns, threshold=th) for r in base]
                all_rows.extend(rows)
                for col in ("deployed", "jev-raw"):
                    tp, tn, fn, fp = tally(rows, "raw" if col == "jev-raw" else col)
                    skipped = sum(not r[("raw" if col == "jev-raw" else col)] for r in rows if not r["fallback"])
                    print(f"   th={th:.2f} {col:8s} FN={len(fn):2d} FP={len(fp):2d} "
                          f"TP={tp:2d} TN={tn:2d}  sonnet-calls-saved={skipped}/{len(rows)}")
                    if fn:
                        print(f"      🔴 silenced but should respond: {', '.join(fn)}")
                    if col == "deployed":
                        flaky = [r["id"] for r in rows if not r["l0"] and r["p"] < th <= r["p_max"]]
                        if flaky:
                            print(f"      ⚠ coin-flip at this threshold (runs straddle it): {', '.join(flaky)}")
                        print_tiers(rows, th)
            print("   p per case:", ", ".join(f"{r['id'].split('-',2)[0]}-{r['id'].split('-',2)[1]}={r['p']:.2f}" for r in base))
            print()

    if args.json:
        args.json.write_text(json.dumps(all_rows, indent=1))
        print(f"wrote {len(all_rows)} rows to {args.json}")


if __name__ == "__main__":
    asyncio.run(main())
