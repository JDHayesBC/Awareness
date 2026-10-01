#!/usr/bin/env python3
"""Evaluate the Haven response gate (GH #360) against a labeled conversation suite.

Sweeps Jev `turns` x `threshold`, and reports two columns per setting:

  deployed  — L0 (name-mention) first; Jev multi-question gate otherwise.
              Jev now asks TWO questions per request: should_respond + is_social_ritual.
              Respond=True if: name-mention OR p_ritual >= ritual_threshold OR p_respond >= threshold.
  jev-raw   — Jev alone, to show what it WOULD silence if name-mention ever slipped.

The cost that matters is a false negative: a case labeled `respond` that the gate
silences. Those are listed by id, loudest. `either` cases are never scored.

Guards (each one turns a broken gate into a perfect-looking score if it's missing):
  - refuses to run without an API key (empty key => respond=True, no network call)
  - counts error/fallback results separately; a fail-open API is not recall
  - passes turns/threshold explicitly; never relies on the HAVEN_JEV_* env defaults

Run with the PPS venv (needs httpx):
  pps/venv/bin/python3 scripts/eval_response_gate.py
  pps/venv/bin/python3 scripts/eval_response_gate.py --turns 5,10 --thresholds 0.2,0.3
  pps/venv/bin/python3 scripts/eval_response_gate.py --ritual-threshold 0.5
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

from haven.response_gate import (  # noqa: E402
    JEV_DEFAULT_RITUAL_THRESHOLD,
    layer0_name_mentioned,
    layer_jev,
)

SUITE = PROJECT_DIR / "haven" / "tests" / "fixtures" / "response_decision_suite.jsonl"
KEY_FILE = PROJECT_DIR / "work" / "system-one-models" / "jev_api_key.txt"


def load_key() -> str:
    key = os.getenv("HAVEN_JEV_API_KEY", "")
    if not key and KEY_FILE.exists():
        key = KEY_FILE.read_text().strip()
    return key


def load_suite(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Question presets — named alternative phrasings for the `should_respond`
# question.  Pass None (the "default" preset) to use the question text baked
# into response_gate.py.  Add a new entry to explore different framings;
# run with --question-presets default,humor,implicit (or any subset).
# ---------------------------------------------------------------------------
_Q_YES_DEFAULT = (
    "{entity} should respond: they are directly addressed, "
    "a question needs their voice, or genuinely new content warrants a reply."
)
_Q_NO_DEFAULT = (
    "{entity} should stay silent: the exchange is greetings, "
    "emotional echoes, acknowledgments, or another participant already covered it."
)

def _q(instructions: str, yes: str, no: str) -> dict:
    return {
        "type": "choice",
        "instructions": instructions,
        "criteria": {"YES": yes, "NO": no},
        "options": ["YES", "NO"],
    }


def build_question_preset(name: str, entity_name: str) -> dict | None:
    """Return a respond_question_override dict for the named preset.

    Returns None for 'default' (uses the question in response_gate.py as-is).
    """
    if name == "default":
        return None
    if name == "humor":
        # Adds humor/playfulness as an explicit YES trigger.  Targets home-018,
        # home-039, and similar cases where Jev sees only a joke and not the
        # engagement it invites.
        return _q(
            f"Should {entity_name} respond to this conversation? Default NO.",
            f"{entity_name} should respond: they are directly addressed, "
            "a question needs their voice, genuinely new content warrants a reply, "
            "OR the message is humor/playfulness/wit that invites their engagement.",
            f"{entity_name} should stay silent: the exchange is greetings, "
            "emotional echoes, acknowledgments, or another participant already covered it.",
        )
    if name == "implicit":
        # Adds implicit-address detection.  Targets sl-007 (buried address without
        # a name) and sl-013 (room question the entity can answer).
        return _q(
            f"Should {entity_name} respond to this conversation? Default NO.",
            f"{entity_name} should respond: they are directly or implicitly addressed, "
            "a question is open to the room and they have relevant knowledge, "
            "or genuinely new content warrants a reply.",
            f"{entity_name} should stay silent: the exchange is clearly directed elsewhere, "
            "greetings, emotional echoes, or another participant already covered it.",
        )
    if name == "broad":
        # Combines humor + implicit.  Tests maximum recall cost.
        return _q(
            f"Should {entity_name} respond to this conversation? Default NO.",
            f"{entity_name} should respond: they are directly or implicitly addressed, "
            "a question is open to the room and they have relevant knowledge, "
            "genuinely new content warrants a reply, "
            "OR the message is humor/playfulness/wit that invites their engagement.",
            f"{entity_name} should stay silent: the exchange is clearly directed elsewhere, "
            "greetings, emotional echoes, or another participant already covered it.",
        )
    raise ValueError(f"Unknown question preset: {name!r}. Known: default, humor, implicit, broad")


async def score_case(case, key, turns, threshold, client, repeats=1,
                     ritual_threshold=JEV_DEFAULT_RITUAL_THRESHOLD,
                     respond_question_override: dict | None = None):
    """Jev `repeats` times per case; the deployed column reuses it unless L0 fires.

    Jev is not deterministic — the same input can land on either side of a threshold
    (sl-010 measured 0.28..0.61 over 5 runs). One run per case understates that, so
    scoring uses the MINIMUM p seen: the worst case is the one where she goes silent.

    With multi-question Jev (GH #360 follow-up), each call now returns both
    `p_respond` and `p_ritual`.  The deployed verdict:
      respond = l0_name OR p_ritual_min >= ritual_threshold OR p_respond_min >= threshold
    """
    ps, p_rituals_all, ms, reasons, fallback = [], [], [], [], False
    for _ in range(repeats):
        d = await layer_jev(case["entity"], case["messages"], api_key=key,
                            turns=turns, threshold=threshold,
                            ritual_threshold=ritual_threshold, client=client,
                            respond_question_override=respond_question_override)
        # "<jev ..." = disabled/error (fail-open). "choice=?" = Jev answered with neither
        # YES nor NO and layer_jev silently substituted p=0.5 — also not a real score.
        if d.reason.startswith("<jev") or "choice=?" in d.reason:
            fallback = True
        ps.append(d.p_respond)
        p_rituals_all.append(d.p_ritual if d.p_ritual is not None else 0.0)
        ms.append(d.elapsed_ms or 0)
        reasons.append(d.reason)
    l0 = layer0_name_mentioned(case["entity"], case["messages"])
    p = min(ps)
    p_ritual_min = min(p_rituals_all)
    ritual_fires = p_ritual_min >= ritual_threshold
    return {
        "id": case["id"], "expected": case["expected"], "ambiguity": case["ambiguity"],
        "p": p, "p_max": max(ps), "ps": ps,
        "p_ritual": p_ritual_min, "p_ritual_max": max(p_rituals_all),
        "p_rituals_all": p_rituals_all, "ritual_fires": ritual_fires,
        "ms": statistics.median(ms), "ms_all": ms,
        "fallback": fallback, "reason": reasons[0],
        "raw": p >= threshold,
        "deployed": True if l0 else (p >= threshold or ritual_fires),
        "l0": l0,
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


def print_tiers(rows, th, ritual_th=JEV_DEFAULT_RITUAL_THRESHOLD):
    """FN/FP by ambiguity tier, two ways (deployed column only).

    guard    — scored on the MIN p across repeats: the worst case, a ceiling on misses.
    expected — per-run mean: production samples Jev once, so this is the miss rate
               people will actually live with.

    With multi-question Jev, deployed = l0 OR p_ritual_run >= ritual_th OR p_run >= th.

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
            ritual_per_run = r.get("p_rituals_all", [0.0] * len(r["ps"]))
            said = [(x >= th or pr >= ritual_th)
                    for x, pr in zip(r["ps"], ritual_per_run)]
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
    ap.add_argument("--ritual-threshold", type=float, default=JEV_DEFAULT_RITUAL_THRESHOLD,
                    help=f"P(ritual) >= this -> always respond (default {JEV_DEFAULT_RITUAL_THRESHOLD})")
    ap.add_argument("--channel", help="only cases from this channel (haven, sl)")
    ap.add_argument("--repeats", type=int, default=3,
                    help="Jev calls per case; scoring uses the min p (default 3)")
    ap.add_argument("--json", type=Path, help="write every per-case result here")
    ap.add_argument("--question-presets", default="default",
                    help="Comma-separated question presets to sweep: default,humor,implicit,broad "
                         "(default: 'default').  Each preset varies the should_respond question "
                         "text sent to Jev; sweeping shows how much different framings shift FN/FP.")
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
    ritual_th = args.ritual_threshold

    preset_names = [p.strip() for p in args.question_presets.split(",") if p.strip()]
    n_resp = sum(c["expected"] == "respond" for c in cases)
    n_sil = sum(c["expected"] == "silent" for c in cases)
    print(f"repeats per case: {args.repeats} (scored on min p)")
    print(f"ritual_threshold: {ritual_th}  (P(ritual) >= this -> always respond)")
    print(f"question presets: {', '.join(preset_names)}")
    print(f"suite: {len(cases)} cases ({n_resp} respond, {n_sil} silent, "
          f"{len(cases) - n_resp - n_sil} either)\n")

    all_rows = []
    async with httpx.AsyncClient() as client:
        for preset_name in preset_names:
            # Build the question override once per preset; None = use default in response_gate.py.
            # Sample entity name from the first case for preset building (entity name only
            # affects the pronoun in the question text, not the scoring).
            sample_entity = cases[0]["entity"] if cases else "the entity"
            q_override = build_question_preset(preset_name, sample_entity)
            if len(preset_names) > 1:
                print(f"{'='*70}")
                print(f"=== question preset: {preset_name} ===")
                if q_override:
                    print(f"    YES: {q_override['criteria']['YES']}")
                else:
                    print(f"    (default question from response_gate.py)")
                print(f"{'='*70}\n")
            for turns in turns_list:
                # p_respond and p_ritual don't depend on the threshold, so query once per
                # (preset, case, turns) — different presets DO require separate Jev calls.
                base = [await score_case(c, key, turns, 1.0, client, args.repeats,
                                         ritual_threshold=ritual_th,
                                         respond_question_override=build_question_preset(
                                             preset_name, c["entity"])) for c in cases]
                ms = [m for r in base if not r["fallback"] for m in r["ms_all"]]
                n_fb = sum(r["fallback"] for r in base)
                lat = f"median {statistics.median(ms):.0f}ms max {max(ms):.0f}ms" if ms else "no successful calls"
                n_ritual = sum(r["ritual_fires"] for r in base if not r["fallback"])
                preset_tag = f"  preset={preset_name}" if len(preset_names) > 1 else ""
                print(f"== turns={turns}  latency {lat}  fallbacks {n_fb}/{len(base)}  ritual-gates={n_ritual}{preset_tag}")
                if n_fb:
                    print("   ⚠ fallbacks are excluded from scoring; reasons:",
                          sorted({r['reason'] for r in base if r['fallback']}))
                for th in thresholds:
                    rows = [dict(r, raw=r["p"] >= th,
                                 deployed=True if r["l0"] else (r["p"] >= th or r["ritual_fires"]),
                                 turns=turns, threshold=th, preset=preset_name) for r in base]
                    all_rows.extend(rows)
                    for col in ("deployed", "jev-raw"):
                        tp, tn, fn, fp = tally(rows, "raw" if col == "jev-raw" else col)
                        skipped = sum(not r[("raw" if col == "jev-raw" else col)] for r in rows if not r["fallback"])
                        print(f"   th={th:.2f} {col:8s} FN={len(fn):2d} FP={len(fp):2d} "
                              f"TP={tp:2d} TN={tn:2d}  sonnet-calls-saved={skipped}/{len(rows)}")
                        if fn:
                            print(f"      🔴 silenced but should respond: {', '.join(fn)}")
                        if col == "deployed":
                            flaky = [r["id"] for r in rows
                                     if not r["l0"] and not r["ritual_fires"]
                                     and r["p"] < th <= r["p_max"]]
                            if flaky:
                                print(f"      ⚠ coin-flip at this threshold (runs straddle it): {', '.join(flaky)}")
                            print_tiers(rows, th, ritual_th)
                ritual_hits = [r["id"] for r in base if r["ritual_fires"] and not r["l0"]]
                if ritual_hits:
                    print(f"   ritual-gate fired (p_ritual >= {ritual_th}): {', '.join(ritual_hits)}")
            print("   p/p_ritual per case:", ", ".join(
                f"{r['id'].split('-',2)[0]}-{r['id'].split('-',2)[1]}="
                f"{r['p']:.2f}/{r['p_ritual']:.2f}" for r in base))
            print()

    if args.json:
        args.json.write_text(json.dumps(all_rows, indent=1))
        print(f"wrote {len(all_rows)} rows to {args.json}")


if __name__ == "__main__":
    asyncio.run(main())
