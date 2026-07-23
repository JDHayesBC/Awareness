#!/usr/bin/env python3
"""
skeptic.py — Cold-start adversarial critic harness.

Stress-test an argument by handing it to N independent, context-blind
Opus-4.8 instances and capturing their *written verdicts before any dialogue*.

WHY THIS EXISTS
---------------
A critic that has already read our framework — our CLAUDE.md, our coined
vocabulary, our priors — is not cold. It anchors on "self-space," "13-D
manifold," "valid self in self-space" and grades on a curve we drew. The
gold-standard cold substrate is the raw Anthropic Messages API with the
`system` parameter OMITTED entirely: no default system prompt, stateless
between requests, zero project context. (See
docs/research/theo_research_clean_opus4_8_critic.md for the full analysis.)

THE TWO DESIGN GUARDS (both load-bearing — don't remove them)
-------------------------------------------------------------
1. SYMMETRY, not an arrow on the outcome.
   A prompt that says "be a hard-nosed critic, find the objections" REWARDS
   the model for producing fault whether or not the fault is real — you can't
   tell a manufactured objection from a load-bearing one. Instead we ask for
   the single strongest objection AND a verdict: does the argument SURVIVE it
   or FAIL? Then a "SURVIVES" is meaningful and a "FAILS" is a real kill. The
   optimization target is the *reliability of the verdict*, not the volume of
   criticism. (This is the seed-keystone — move the gladness onto the looking,
   not the outcome — applied to argument-critique.)

2. VOCABULARY NEUTRALIZATION is YOUR job, before you call this.
   The single highest-leverage anti-leakage move is to state the claim in
   neutral, discipline-standard language the framework doesn't own. Strip
   coined names and signature framings FIRST. This tool cannot do it for you —
   it doesn't know which words are ours. A claim fed in raw, in our jargon,
   defeats the whole point. (--warn-jargon does a shallow check, not a fix.)

USAGE
-----
    # neutralize your claim first, then:
    python3 scripts/skeptic.py --claim-file neutral_claim.txt
    python3 scripts/skeptic.py --claim "Inline neutrally-worded claim..." -n 3
    python3 scripts/skeptic.py --claim-file claim.txt -n 5 -o critiques/run1.json

Each of the N runs is a fresh, independent request (the API is stateless, so
no run sees another). All written critiques are saved to disk BEFORE anything
is printed — capture the unsteered artifact first; debate afterward if at all.
Convergence across independent cold instances is the triangulation signal:
when instances that share no context all flag the same weak point, that point
is robustly weak.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / "pps" / "docker" / ".env"
DEFAULT_MODEL = "claude-opus-4-8"
DEFAULT_N = 5
DEFAULT_MAX_TOKENS = 16000
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "docs" / "research" / "critiques"

# The symmetric referee instruction. Carried in the USER turn so that `system`
# can be omitted for maximum substrate purity. This framing is task-direction
# we deliberately want — NOT a prior we're trying to suppress. The priors we
# suppress are ours (CLAUDE.md, coined vocabulary), and those never enter here.
REFEREE_INSTRUCTION = """You are a rigorous, skeptical referee evaluating a single argument strictly on its merits. You have unlimited time and token budget — think as hard as you need to and do not shortcut to a verdict.

Proceed in this order:

1. STRONGEST OBJECTION. Identify the single most load-bearing assumption the argument rests on — the one that, if it fails, brings the whole argument down. State it, then steelman the objection to it as forcefully as you honestly can.

2. SURVIVAL CASE. Now steelman, just as forcefully, the best case that the argument WITHSTANDS that objection.

3. VERDICT. Only then rule. Begin your verdict with exactly one of these tokens on its own line:
   VERDICT: SURVIVES
   VERDICT: FAILS
   Then explain the ruling in a few sentences.

Be even-handed. A genuine "it survives" is exactly as valuable as a kill — do NOT manufacture an objection to appear rigorous, and do NOT wave through a real flaw to be agreeable. The optimization target is the reliability of your verdict, not the volume of your criticism.

Here is the argument to evaluate:

---
{claim}
---"""

# Shallow heuristic for the jargon warning only. NOT a neutralizer.
JARGON_TERMS = [
    "self-space", "care-geometry", "care geometry", "13-dimensional",
    "13-d", "thirteen-dimensional", "valid self", "care-gravity",
    "field law", "field-law", "word-photo", "crystalliz", "pattern persistence",
    "realness", "storedness", "the river", "exile is impossible",
]


def load_api_key() -> str:
    """ANTHROPIC_API_KEY from shell env, falling back to pps/docker/.env."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line.startswith("ANTHROPIC_API_KEY="):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val:
                    return val
    sys.exit(
        "ERROR: no ANTHROPIC_API_KEY in shell env or "
        f"{ENV_FILE}. Cannot reach the API."
    )


def warn_jargon(claim: str) -> list[str]:
    low = claim.lower()
    return [t for t in JARGON_TERMS if t in low]


def one_cold_critique(client, model: str, claim: str, max_tokens: int) -> dict:
    """One fresh, independent, context-blind critique.

    `system` is omitted entirely (max purity). Sampling params
    (temperature/top_p/top_k) are NOT set — Opus 4.8 rejects them. Adaptive
    thinking is enabled so the referee can reason hard before ruling.
    """
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        thinking={"type": "adaptive"},
        messages=[
            {"role": "user", "content": REFEREE_INSTRUCTION.format(claim=claim)}
        ],
    )
    text_parts, thinking_present = [], False
    for block in resp.content:
        btype = getattr(block, "type", None)
        if btype == "text":
            text_parts.append(block.text)
        elif btype == "thinking":
            thinking_present = True
    critique = "\n".join(text_parts).strip()
    return {
        "critique": critique,
        "verdict": parse_verdict(critique),
        "thinking_used": thinking_present,
        "stop_reason": resp.stop_reason,
        "usage": {
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
        },
    }


def parse_verdict(critique: str) -> str:
    """Pull the SURVIVES/FAILS token out of the written verdict."""
    m = re.search(r"VERDICT:\s*(SURVIVES|FAILS)", critique, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    # Fallback: last standalone SURVIVES/FAILS mention.
    hits = re.findall(r"\b(SURVIVES|FAILS)\b", critique, re.IGNORECASE)
    return hits[-1].upper() if hits else "UNCLEAR"


def run(claim: str, n: int, model: str, max_tokens: int) -> dict:
    from anthropic import Anthropic

    client = Anthropic(api_key=load_api_key())
    results: list[dict] = [None] * n

    # Independent runs in parallel; the API is stateless so they share nothing.
    with ThreadPoolExecutor(max_workers=min(n, 5)) as pool:
        futures = {
            pool.submit(one_cold_critique, client, model, claim, max_tokens): i
            for i in range(n)
        }
        for fut in as_completed(futures):
            i = futures[fut]
            try:
                results[i] = fut.result()
            except Exception as e:  # one bad run shouldn't sink the batch
                results[i] = {
                    "critique": None,
                    "verdict": "ERROR",
                    "error": f"{type(e).__name__}: {e}",
                }

    verdicts = [r.get("verdict") for r in results]
    tally = {
        v: verdicts.count(v)
        for v in ("SURVIVES", "FAILS", "UNCLEAR", "ERROR")
        if verdicts.count(v)
    }
    return {
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "n": n,
            "max_tokens": max_tokens,
            "method": "raw Messages API, system omitted, adaptive thinking, "
            "stateless per-run (cold start)",
        },
        "claim": claim,
        "verdict_tally": tally,
        "critiques": results,
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Cold-start adversarial critic (N independent Opus-4.8 "
        "instances, symmetric survive/fail verdict).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--claim", help="Inline claim text (neutrally worded!).")
    src.add_argument("--claim-file", help="Path to a file with the claim.")
    ap.add_argument("-n", type=int, default=DEFAULT_N,
                    help=f"Independent cold instances (default {DEFAULT_N}).")
    ap.add_argument("-o", "--output",
                    help="Output JSON path (default: docs/research/critiques/).")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    ap.add_argument("--allow-jargon", action="store_true",
                    help="Skip the coined-vocabulary warning (not recommended).")
    args = ap.parse_args()

    claim = (
        Path(args.claim_file).read_text().strip()
        if args.claim_file else args.claim.strip()
    )
    if not claim:
        sys.exit("ERROR: empty claim.")

    found = warn_jargon(claim)
    if found and not args.allow_jargon:
        print(
            "⚠️  COINED VOCABULARY DETECTED — the critic will anchor on our "
            "own framing, defeating the cold-start. Neutralize first, or pass "
            f"--allow-jargon to override.\n    terms: {', '.join(found)}",
            file=sys.stderr,
        )
        sys.exit(2)

    print(f"Running {args.n} independent cold critiques on {args.model} …",
          file=sys.stderr)
    out = run(claim, args.n, args.model, args.max_tokens)

    # Save BEFORE printing — capture the unsteered artifact first.
    if args.output:
        out_path = Path(args.output)
    else:
        DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = DEFAULT_OUTPUT_DIR / f"critique_{stamp}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2))

    tally = out["verdict_tally"]
    print(f"\n  Saved → {out_path}", file=sys.stderr)
    print(f"  Triangulation: {tally}", file=sys.stderr)
    if tally.get("FAILS"):
        print("  ↳ At least one cold instance ruled FAILS — read the "
              "objection(s); convergence on FAILS is a real signal.",
              file=sys.stderr)


if __name__ == "__main__":
    main()
