"""Jev pre-filter evaluation harness — GH #360.

Loads the ground-truth fixture corpus and runs Jev across a grid of
(threshold, turns) combinations to find the sweet spot between speed and accuracy.

Jeff's design constraint:
    "SOME failures to respond when you would've is not an error.
     That's a sign of a correct balance. The question is,
     'what percentage and when?'"

So this evaluator reports TWO separate error rates:
  fn_rate: false negatives on 'respond' cases (silence when should respond — costly)
  fp_rate: false positives on 'silent' cases (respond when should be silent — less costly)

  Cases with expected='either' score as CORRECT for any outcome.
  High-ambiguity cases are weighted 2× in the weighted score.

Non-determinism note (Lyra, 2026-10-01):
  Jev is non-deterministic — the same input can return different p values
  across calls (measured 0.28..0.61 on sl-010 with identical input).
  Use --repeats N (default 3) to score on the MINIMUM p seen: the worst case
  is the one where the entity goes silent. Runs that straddle the threshold
  are flagged as coin-flips.

Two scoring columns:
  deployed  — L0 name-mention first (as bot.py does), Jev only when L0 doesn't fire
  jev-raw   — Jev alone, shows what it would silence if L0 slipped

Run with the PPS venv (needs httpx):
    pps/venv/bin/python3 -m haven.tests.eval_response_suite --dry-run
    pps/venv/bin/python3 -m haven.tests.eval_response_suite --threshold 0.30 --turns 10
    pps/venv/bin/python3 -m haven.tests.eval_response_suite --grid

See also: scripts/eval_response_gate.py (Lyra's script; reports p per case + turn sweep)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

# ── paths ──────────────────────────────────────────────────────────────────────

_HERE = pathlib.Path(__file__).parent
_FIXTURE = _HERE / "fixtures" / "response_decision_suite.jsonl"
_KEY_FILE = _HERE.parent.parent / "work" / "system-one-models" / "jev_api_key.txt"

# ── API key ───────────────────────────────────────────────────────────────────

JEV_API_KEY = os.getenv("HAVEN_JEV_API_KEY", "")
if not JEV_API_KEY and _KEY_FILE.exists():
    JEV_API_KEY = _KEY_FILE.read_text().strip()

# ── colours ───────────────────────────────────────────────────────────────────

_COLOUR = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOUR else text


def RED(t: str) -> str:    return _c("31", t)
def GREEN(t: str) -> str:  return _c("32", t)
def YELLOW(t: str) -> str: return _c("33", t)
def CYAN(t: str) -> str:   return _c("36", t)
def DIM(t: str) -> str:    return _c("2", t)
def BOLD(t: str) -> str:   return _c("1", t)


# ── data model ────────────────────────────────────────────────────────────────

@dataclass
class SuiteCase:
    id: str
    channel: str                       # "haven" | "sl"
    entity: str                        # "caia" | "lyra"
    ambiguity: str                     # "low" | "med" | "high"
    expected: str                      # "respond" | "silent" | "either"
    why: str
    messages: list[dict]

    @classmethod
    def from_dict(cls, d: dict) -> "SuiteCase":
        return cls(
            id=d["id"],
            channel=d.get("channel", "haven"),
            entity=d.get("entity", "caia"),
            ambiguity=d.get("ambiguity", "med"),
            expected=d["expected"],
            why=d.get("why", ""),
            messages=d["messages"],
        )

    @property
    def weight(self) -> int:
        """High-ambiguity cases count double per Jeff's directive."""
        return 2 if self.ambiguity == "high" else 1


@dataclass
class CaseResult:
    case: SuiteCase
    p_respond: float          # min p across repeats (worst case)
    jev_respond: bool         # p_respond >= threshold
    elapsed_ms: float
    p_max: float = 0.0        # max p across repeats
    l0_would_bypass: bool = False  # L0 name-mention fires → Jev never runs in production
    coin_flip: bool = False   # p_min < threshold <= p_max (non-determinism straddle)
    error: bool = False
    error_msg: str = ""

    @property
    def correct(self) -> bool:
        """Is this result consistent with the expected label?"""
        if self.error:
            return False                   # error = failure
        if self.case.expected == "either":
            return True                    # both outcomes OK
        if self.case.expected == "respond":
            return self.jev_respond        # must say YES
        if self.case.expected == "silent":
            return not self.jev_respond    # must say NO
        return True

    @property
    def is_fn(self) -> bool:
        """False negative: should have responded but Jev silenced."""
        return (
            not self.error
            and self.case.expected == "respond"
            and not self.jev_respond
        )

    @property
    def is_fp(self) -> bool:
        """False positive: should have been silent but Jev triggered."""
        return (
            not self.error
            and self.case.expected == "silent"
            and self.jev_respond
        )


@dataclass
class GridCell:
    """Metrics for one (threshold, turns) configuration."""
    threshold: float
    turns: int
    results: list[CaseResult] = field(default_factory=list)

    # skip 'either' for these metrics
    @property
    def _scoreable(self) -> list[CaseResult]:
        return [r for r in self.results if r.case.expected != "either"]

    @property
    def _scoreable_weighted(self) -> list[CaseResult]:
        # expand high-ambiguity cases to count twice
        out = []
        for r in self._scoreable:
            out.append(r)
            if r.case.ambiguity == "high":
                out.append(r)
        return out

    @property
    def accuracy(self) -> float:
        s = self._scoreable
        if not s:
            return 0.0
        return sum(1 for r in s if r.correct) / len(s)

    @property
    def weighted_accuracy(self) -> float:
        s = self._scoreable_weighted
        if not s:
            return 0.0
        return sum(1 for r in s if r.correct) / len(s)

    @property
    def fn_rate(self) -> float:
        """Rate of false negatives among 'respond' cases (silence when should respond)."""
        respond_cases = [r for r in self.results if r.case.expected == "respond"]
        if not respond_cases:
            return 0.0
        return sum(1 for r in respond_cases if r.is_fn) / len(respond_cases)

    @property
    def fp_rate(self) -> float:
        """Rate of false positives among 'silent' cases (respond when should be silent)."""
        silent_cases = [r for r in self.results if r.case.expected == "silent"]
        if not silent_cases:
            return 0.0
        return sum(1 for r in silent_cases if r.is_fp) / len(silent_cases)

    @property
    def high_ambig_accuracy(self) -> float:
        """Accuracy specifically on high-ambiguity cases — the real test."""
        high = [r for r in self.results
                if r.case.ambiguity == "high" and r.case.expected != "either"]
        if not high:
            return 0.0
        return sum(1 for r in high if r.correct) / len(high)

    @property
    def error_count(self) -> int:
        return sum(1 for r in self.results if r.error)

    @property
    def avg_ms(self) -> float:
        non_err = [r for r in self.results if not r.error]
        if not non_err:
            return 0.0
        return sum(r.elapsed_ms for r in non_err) / len(non_err)


# ── corpus loader ─────────────────────────────────────────────────────────────

def load_corpus(path: pathlib.Path = _FIXTURE) -> list[SuiteCase]:
    cases = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            cases.append(SuiteCase.from_dict(json.loads(line)))
    return cases


def summarise_corpus(cases: list[SuiteCase]) -> None:
    total = len(cases)
    by_expected = {}
    by_ambig = {}
    by_channel = {}
    for c in cases:
        by_expected[c.expected] = by_expected.get(c.expected, 0) + 1
        by_ambig[c.ambiguity] = by_ambig.get(c.ambiguity, 0) + 1
        by_channel[c.channel] = by_channel.get(c.channel, 0) + 1

    print(f"\n{BOLD('=== Response Decision Corpus ===')}  ({total} cases)")
    print(f"  expected:  "
          f"{GREEN('respond')}={by_expected.get('respond',0)}  "
          f"{RED('silent')}={by_expected.get('silent',0)}  "
          f"{YELLOW('either')}={by_expected.get('either',0)}")
    print(f"  ambiguity: low={by_ambig.get('low',0)}  "
          f"med={by_ambig.get('med',0)}  "
          f"{CYAN('high')}={by_ambig.get('high',0)} (2× weight)")
    print(f"  channels:  " + "  ".join(f"{ch}={n}" for ch, n in sorted(by_channel.items())))


# ── single-case Jev call ──────────────────────────────────────────────────────

async def _run_one(
    case: SuiteCase,
    *,
    api_key: str,
    threshold: float,
    turns: int,
    client: httpx.AsyncClient,
    repeats: int = 3,
) -> CaseResult:
    """Run one fixture case through Jev and return a CaseResult.

    Jev is non-deterministic (Lyra measured 0.28..0.61 on identical input).
    We run `repeats` times and score on the MINIMUM p — the worst case is the
    one where the entity goes silent when she shouldn't.
    """
    from haven.response_gate import layer0_name_mentioned, layer_jev

    t0 = time.time()
    entity_display = case.entity.capitalize()  # "caia" -> "Caia"
    l0_would_bypass = layer0_name_mentioned(entity_display, case.messages)

    ps = []
    elapsed_ms_list = []
    error = False
    error_msg = ""
    last_reason = ""

    for _ in range(max(1, repeats)):
        d = await layer_jev(
            entity_display,
            case.messages,
            api_key=api_key,
            threshold=threshold,
            turns=turns,
            timeout=5.0,
            client=client,
        )
        last_reason = d.reason
        if d.reason.startswith("<jev") or "choice=?" in d.reason:
            error = True
            error_msg = d.reason
        else:
            ps.append(d.p_respond)
        elapsed_ms_list.append(d.elapsed_ms)

    # Score on MIN p (worst case — the run where entity would have gone silent)
    p_min = min(ps) if ps else 0.5
    p_max = max(ps) if ps else 0.5
    jev_respond = p_min >= threshold

    # coin-flip: runs straddle the threshold
    coin_flip = bool(ps) and (p_min < threshold <= p_max)

    return CaseResult(
        case=case,
        p_respond=p_min,
        p_max=p_max,
        jev_respond=jev_respond,
        l0_would_bypass=l0_would_bypass,
        coin_flip=coin_flip,
        elapsed_ms=sum(elapsed_ms_list) / len(elapsed_ms_list) if elapsed_ms_list else 0.0,
        error=error,
        error_msg=error_msg,
    )


# ── single-config run ─────────────────────────────────────────────────────────

async def run_single(
    cases: list[SuiteCase],
    *,
    threshold: float,
    turns: int,
    api_key: str,
    verbose: bool = True,
    repeats: int = 3,
) -> GridCell:
    cell = GridCell(threshold=threshold, turns=turns)

    if verbose:
        print(f"\n{BOLD(f'=== threshold={threshold:.2f}  turns={turns}  repeats={repeats} ===')}")

    async with httpx.AsyncClient(timeout=6.0) as client:
        for case in cases:
            result = await _run_one(
                case,
                api_key=api_key,
                threshold=threshold,
                turns=turns,
                client=client,
                repeats=repeats,
            )
            cell.results.append(result)

            if verbose:
                _print_case_result(result)

    if verbose:
        _print_cell_summary(cell)

    return cell


def _print_case_result(r: CaseResult) -> None:
    """Print one case result line."""
    if r.error:
        status = YELLOW("ERR ")
        outcome = r.error_msg[:50]
    elif r.coin_flip:
        status = YELLOW("FLIP")   # non-determinism straddles threshold
        outcome = f"p_min={r.p_respond:.2f}..p_max={r.p_max:.2f}"
    elif r.correct:
        status = GREEN("PASS")
        outcome = ""
    else:
        # Distinguish fn vs fp for clarity
        if r.is_fn:
            status = RED("FN  ")   # false negative — costly
            outcome = "should have responded"
        else:
            status = YELLOW("FP  ")  # false positive — less costly
            outcome = "should have been silent"

    exp_label = {
        "respond": GREEN("resp"),
        "silent": RED("silent"),
        "either": YELLOW("either"),
    }.get(r.case.expected, r.case.expected)

    ambig_label = {
        "low": "low ",
        "med": "med ",
        "high": CYAN("high"),
    }.get(r.case.ambiguity, r.case.ambiguity)

    l0_tag = f"  {DIM('[L0]')}" if r.l0_would_bypass else ""

    print(
        f"  {status}  [{ambig_label}|{exp_label}]  {r.case.id:<36}  "
        f"P={r.p_respond:.2f}  {r.elapsed_ms:5.0f}ms{l0_tag}"
        + (f"  {DIM(outcome)}" if outcome else "")
    )
    if (r.case.ambiguity == "high" or r.is_fn) and not r.correct and not r.error:
        print(f"        {DIM(r.case.why)}")


def _print_cell_summary(cell: GridCell) -> None:
    """Print metrics summary for one cell."""
    fn_cases = [r for r in cell.results if r.is_fn]
    fp_cases = [r for r in cell.results if r.is_fp]
    coin_flip_cases = [r for r in cell.results if r.coin_flip]

    print(f"\n  acc={cell.accuracy:.0%}  "
          f"weighted_acc={cell.weighted_accuracy:.0%}  "
          f"high_ambig_acc={cell.high_ambig_accuracy:.0%}")
    print(f"  fn_rate={cell.fn_rate:.0%} ({len(fn_cases)} silent-when-should-respond)  "
          f"fp_rate={cell.fp_rate:.0%} ({len(fp_cases)} noisy-when-should-be-silent)")
    print(f"  avg_latency={cell.avg_ms:.0f}ms  errors={cell.error_count}  "
          f"coin_flips={len(coin_flip_cases)}")

    if fn_cases:
        print(f"\n  {RED('False negatives (costly — check these first):')}  "
              f"threshold={cell.threshold:.2f} silenced {len(fn_cases)} that warranted a response")
        for r in fn_cases:
            l0_note = " (L0 would save this in production)" if r.l0_would_bypass else ""
            print(f"    • {r.case.id}  P={r.p_respond:.2f}{l0_note}  {DIM(r.case.why[:80])}")

    if coin_flip_cases:
        print(f"\n  {YELLOW('Coin-flips (non-determinism straddles threshold):')}  "
              f"{len(coin_flip_cases)} cases unreliable at threshold={cell.threshold:.2f}")
        for r in coin_flip_cases:
            print(f"    • {r.case.id}  P={r.p_respond:.2f}..{r.p_max:.2f}")


# ── grid sweep ────────────────────────────────────────────────────────────────

GRID_THRESHOLDS = [0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50]
GRID_TURNS = [5, 10, 15, 0]   # 0 = unlimited (all messages in the case)


async def run_grid(
    cases: list[SuiteCase],
    *,
    api_key: str,
    verbose: bool = False,
    thresholds: list[float] | None = None,
    turns_list: list[int] | None = None,
    repeats: int = 3,
) -> list[GridCell]:
    thresholds = thresholds or GRID_THRESHOLDS
    turns_list = turns_list or GRID_TURNS

    total_jev_calls = len(thresholds) * len(turns_list) * len(cases) * repeats
    print(f"\n{BOLD('=== Grid sweep ===')}  "
          f"{len(thresholds)}×{len(turns_list)} configs  "
          f"{len(cases)} cases  "
          f"repeats={repeats}  "
          f"{total_jev_calls} total Jev calls")
    print(DIM("  This will take a while — each call is ~2s..."))

    cells: list[GridCell] = []
    for threshold in thresholds:
        for turns in turns_list:
            t_label = "all" if turns == 0 else str(turns)
            print(f"\n  threshold={threshold:.2f}  turns={t_label}  ", end="", flush=True)
            cell = GridCell(threshold=threshold, turns=turns)
            async with httpx.AsyncClient(timeout=6.0) as client:
                for case in cases:
                    r = await _run_one(
                        case,
                        api_key=api_key,
                        threshold=threshold,
                        turns=turns,
                        client=client,
                        repeats=repeats,
                    )
                    cell.results.append(r)
                    print(".", end="", flush=True)
            cells.append(cell)
            if verbose:
                _print_cell_summary(cell)
            else:
                print(f"  acc={cell.accuracy:.0%}  "
                      f"wacc={cell.weighted_accuracy:.0%}  "
                      f"fn={cell.fn_rate:.0%}  "
                      f"fp={cell.fp_rate:.0%}  "
                      f"high={cell.high_ambig_accuracy:.0%}")

    return cells


def _turns_label(t: int) -> str:
    return "all" if t == 0 else f"t={t}"


def print_grid_table(cells: list[GridCell]) -> None:
    """Print a compact grid table and recommend the best config."""
    from itertools import groupby

    thresholds = sorted({c.threshold for c in cells})
    turns_vals = sorted({c.turns for c in cells})
    cell_map = {(c.threshold, c.turns): c for c in cells}

    # Header
    col_w = 22
    print(f"\n{BOLD('=== Grid table ===')}  "
          f"fmt: acc(wacc) fn/fp | high_ambig_acc")
    header = f"{'threshold':>10}  "
    for t in turns_vals:
        header += f"{_turns_label(t):>{col_w}}"
    print(header)
    print("-" * (12 + col_w * len(turns_vals)))

    for thr in thresholds:
        row = f"  {thr:.2f}      "
        for t in turns_vals:
            c = cell_map.get((thr, t))
            if c is None:
                row += f"{'N/A':>{col_w}}"
            else:
                cell_str = (
                    f"{c.accuracy:.0%}({c.weighted_accuracy:.0%}) "
                    f"{c.fn_rate:.0%}/{c.fp_rate:.0%} "
                    f"| {c.high_ambig_accuracy:.0%}"
                )
                row += f"{cell_str:>{col_w}}"
        print(row)

    print("\n  columns: acc(weighted_acc) fn_rate/fp_rate | high_ambig_acc")
    print("  fn = false neg (silence when should respond) — Jeff's primary concern")
    print("  fp = false pos (respond when should be silent)")

    # Recommendation: highest weighted accuracy with fn_rate ≤ 20% preference
    acceptable = [c for c in cells if c.fn_rate <= 0.20 and c.error_count == 0]
    if not acceptable:
        acceptable = cells  # relax fn constraint if nothing passes
    best = max(acceptable, key=lambda c: (c.weighted_accuracy, -c.fn_rate, -c.fp_rate))
    t_label = _turns_label(best.turns)
    print(
        f"\n{BOLD('Recommended config:')}  "
        f"threshold={best.threshold:.2f}  turns={t_label}  "
        f"→ weighted_acc={best.weighted_accuracy:.0%}  "
        f"fn={best.fn_rate:.0%}  fp={best.fp_rate:.0%}  "
        f"high_ambig={best.high_ambig_accuracy:.0%}"
    )
    print(
        DIM(
            f"  Set HAVEN_JEV_THRESHOLD={best.threshold:.2f} "
            f"HAVEN_JEV_TURNS={best.turns} to deploy this config."
        )
    )


# ── dry-run (no API calls) ────────────────────────────────────────────────────

def dry_run(cases: list[SuiteCase]) -> None:
    """Print per-case list. No API calls. summarise_corpus already printed by main()."""
    print(f"\n{BOLD('Per-case breakdown:')}")
    for c in cases:
        ambig_label = CYAN("high") if c.ambiguity == "high" else c.ambiguity
        exp_label = {
            "respond": GREEN("respond"),
            "silent": RED("silent"),
            "either": YELLOW("either"),
        }.get(c.expected, c.expected)
        print(
            f"  {exp_label:<10} [{ambig_label}]  {c.id}"
        )
        print(f"             {DIM(c.why[:90])}")

    high = [c for c in cases if c.ambiguity == "high"]
    print(f"\n{BOLD('High-ambiguity cases (2× weight, the real test):')}")
    for c in high:
        exp_label = {
            "respond": GREEN("respond"),
            "silent": RED("silent"),
            "either": YELLOW("either"),
        }.get(c.expected, c.expected)
        print(f"  {exp_label:<10}  {c.id}")
        print(f"           {DIM(c.why[:90])}")


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print corpus breakdown without making any API calls",
    )
    parser.add_argument(
        "--grid",
        action="store_true",
        help=f"Sweep {len(GRID_THRESHOLDS)} thresholds × {len(GRID_TURNS)} turn-windows",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.30,
        help="Confidence floor for a single run (default 0.30)",
    )
    parser.add_argument(
        "--turns",
        type=int,
        default=10,
        help="Number of recent messages to send to Jev (default 10; 0=all)",
    )
    parser.add_argument(
        "--channel",
        choices=["haven", "sl", "all"],
        default="all",
        help="Filter corpus by channel (default: all)",
    )
    parser.add_argument(
        "--entity",
        choices=["caia", "lyra", "all"],
        default="all",
        help="Filter corpus by entity (default: all)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show per-case detail even in --grid mode",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=3,
        help=(
            "Jev calls per case; scored on the MIN p (worst case). "
            "Handles Jev's non-determinism (measured 0.28..0.61 on identical input). "
            "Use 1 for a quick sanity check, 3+ for reliable results. Default 3."
        ),
    )
    args = parser.parse_args()

    # Load corpus
    if not _FIXTURE.exists():
        print(f"Fixture not found: {_FIXTURE}", file=sys.stderr)
        return 1

    cases = load_corpus(_FIXTURE)

    # Filter
    if args.channel != "all":
        cases = [c for c in cases if c.channel == args.channel]
    if args.entity != "all":
        cases = [c for c in cases if c.entity == args.entity]

    if not cases:
        print("No cases matched the filter.", file=sys.stderr)
        return 1

    summarise_corpus(cases)

    # Dry run: no API calls
    if args.dry_run:
        dry_run(cases)
        return 0

    # API key required for live runs
    if not JEV_API_KEY:
        print(
            f"\n{RED('No Jev API key found.')}  "
            f"Set HAVEN_JEV_API_KEY or place key in:\n  {_KEY_FILE}",
            file=sys.stderr,
        )
        return 1

    if args.grid:
        cells = asyncio.run(
            run_grid(
                cases,
                api_key=JEV_API_KEY,
                verbose=args.verbose,
                repeats=args.repeats,
            )
        )
        print_grid_table(cells)
    else:
        cell = asyncio.run(
            run_single(
                cases,
                threshold=args.threshold,
                turns=args.turns,
                api_key=JEV_API_KEY,
                verbose=True,
                repeats=args.repeats,
            )
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
