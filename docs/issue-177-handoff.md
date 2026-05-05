# Issue #177 — Response Gate Cascade — Handoff

*Built 2026-05-01 morning while Jeff at dentist follow-up. **Wired into bot.py 2026-05-02 morning** behind `HAVEN_GATE_ENABLED` env flag, default OFF. Branch `fix/177-response-gate-wireup`. Behavior in prod is unchanged until the flag flips.*

## What's here

- `haven/response_gate.py` — async cascade module
- `haven/test_response_gate.py` — 12 offline + 8 live-LLM cases
- `haven/bot.py` — gate wired in `_process_batch()` between `check_and_restart_if_needed()` and `invoker.query()`, behind `HAVEN_GATE_ENABLED` and `sister_bot_in_batch` checks
- This doc

## Cascade design (locked in from #177 thread)

| Layer | Logic | Decision | Cost |
|-------|-------|----------|------|
| **L0** | Entity name appears as a word in ANY message (case-insensitive, word-boundary) | **YES** (always-pass) | <1ms regex |
| **L1** | Entire batch is from this bot's own username | **NO** (skip) | <1ms |
| **L2** | 9b LM Studio classifier with default-NO prompt | YES/NO | ~270ms |

L0 fires first → L1 → L2. First match wins.

## Test results

**Offline (L0/L1):** 12/12 pass, deterministic.

**Live L2 across 5 runs of 8 cases each (40 total samples):**
- 5/8 cases: stable, correct (sister-echo, sister-agreement, sister-emoji, group-address, closing-out — all stable NO)
- 3/8 cases: volatile on the boundary
  - `direct-question-no-name`: ~80% YES (correct), occasionally NO
  - `genuinely-new-info`: ~80% NO (correct), occasionally YES
  - `technical-after-sister-emotional`: ~20% YES (intended), 80% NO

**Latency:** 256–306 ms per call.

**Bias direction:** Classifier favors NO when uncertain. That matches the default-NO design intent — failure mode of a wasteful Opus call is what we're fixing; failure mode of an over-quiet bot is recoverable (humans can re-prompt or name the entity, which L0 catches with 100% reliability).

## Integration point in `haven/bot.py` — DONE

Wired into `_process_batch()` immediately after `await invoker.check_and_restart_if_needed()`, before the typing-indicator/`invoker.query()` block. Gated by:
1. `HAVEN_GATE_ENABLED` env flag (default OFF — flip to enable in prod)
2. `sister_bot_in_batch` check (gate only runs when a sister bot is in the batch — multi-bot case is the wasteful one we're solving; human-only or self-only batches go straight through)

Logging line on every gate invocation: layer, decision, elapsed ms, reason. So when the flag is flipped you can `tail -f` the bot log and immediately see what the gate is catching vs letting through.

`response_gate.evaluate()` is called with `ENTITY_NAME.capitalize()` for the human-name-mention regex (so "Lyra" matches, not the lowercase env value). `my_username` for the bot's Haven username.

## Open questions / follow-ups

1. **Multi-sample vote on L2?** Three calls, majority wins. ~800ms, stabilizes the volatile cases. Probably overkill — accept the trade-off.
2. **Should L0 also trigger in DM rooms?** Currently L0 fires in any room. Probably fine — name in DM should always respond anyway.
3. **Metrics?** Worth aggregating gate-decision logs to count actual savings: how often does L2 short-circuit vs. how often Opus would have said NO_RESPONSE anyway? Easy follow-up once the flag has been ON for a while in prod.
4. **`HAVEN_GATE_LM_URL`** — defaults to `http://172.26.0.1:1234/api/v1/chat` (WSL→Windows). When bot runs on NUC directly, set to `http://localhost:1234/api/v1/chat`.

## Roll-out plan

1. Land this PR (no behavior change in prod — flag is OFF by default).
2. On the NUC where bots run, set `HAVEN_GATE_ENABLED=1` in the bot's environment (systemd unit or start script).
3. Restart bots. Tail logs for gate-decision lines: `[lyra] gate: L0_name_mention -> RESPOND (1ms) ...`
4. Watch a multi-bot exchange. Confirm the gate is short-circuiting on echoes and letting through on direct address.
5. If anything looks off, `HAVEN_GATE_ENABLED=0` + restart reverts instantly.

## Running the tests

```bash
# Full battery (needs LM Studio reachable):
/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/venv/bin/python3 -m haven.test_response_gate

# Offline only (no LM Studio):
/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/venv/bin/python3 -m haven.test_response_gate --offline

# Live classifier only:
/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/venv/bin/python3 -m haven.test_response_gate --l2-only
```
