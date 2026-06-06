# SDK & Model Audit — Awareness Project

**Date:** 2026-06-06 · **Driver:** Lyra (terminal) + researcher sweep · **Issue:** #1
**Method:** Forestry pass (`/prescribe` → `/canopy` → `/deadwood`) → exhaustive researcher sweep → policy reconcile vs. live Anthropic deprecation page.

---

## TL;DR

1. **The "June-15 cliff" is illusory for live code.** The two models retiring June 15, 2026
   (`claude-sonnet-4-20250514`, `claude-opus-4-20250514`) appear **only in a doc snippet**
   (`docs/reference/graphiti-llm-configuration.md`), never in any runtime path. The original
   #1 framing over-scoped because the source research baselined from a `.0.x` version instead
   of `.1.x`.
2. **The real finding is the opposite of a future cliff: an *already-retired* model is still
   referenced in live code.** `claude-3-haiku-20240307` was **retired April 20, 2026**
   ("requests will fail") and is hardcoded in **two** live spots → latent failures.
3. **The `pps-haiku-wrapper` is running but idle** — 0 production callers; both its historical
   jobs (Graphiti extraction; ambient-recall Haiku compression) are superseded/disabled.
4. **Everything else in live code is Active and safe** into late-2026 / 2027.

---

## §A — Policy reconcile (live code model IDs vs. Anthropic deprecation page)

Source: <https://platform.claude.com/docs/en/docs/about-claude/model-deprecations> (fetched 2026-06-06).
Policy: ≥60 days email notice before retirement; **requests to retired models fail**;
`temperature`/`top_p`/`top_k` set to non-default return **400 on Opus 4.7+** (incl. 4.8).

| Model ID found in our code | Where (live) | Anthropic status | Retirement | Verdict / action |
|---|---|---|---|---|
| `claude-3-haiku-20240307` | `pps/docker/server_http.py:3223`; `pps/docker/cc_openai_wrapper.py:815` | **RETIRED** | **Apr 20, 2026 (past)** | 🔴 **FIX** → `claude-haiku-4-5-20251001` (Anthropic's named replacement). Latent failure. |
| `claude-sonnet-4-5-20250929` | `cc_openai_wrapper.py:818` | Active | ≥ Sep 29, 2026 | 🟢 ok (optional refresh to 4.6) |
| `claude-opus-4-5-20251101` | `cc_openai_wrapper.py:821` | Active | ≥ Nov 24, 2026 | 🟢 ok (optional refresh to 4.8) |
| `claude-haiku-4-5-20251001` | `pps/web/app.py:1329` | Active | ≥ Oct 15, 2026 | 🟢 ok (this is the GOOD copy of the dup feature) |
| `claude-opus-4-8` | `haven/systemd/lyra-haven.service:19`, `caia-haven.service:19` | Active | ≥ May 28, 2027 | 🟢 ok |
| `claude-sonnet-4-20250514` | **doc only** `docs/reference/graphiti-llm-configuration.md:83` | Deprecated | Jun 15, 2026 | 🟡 doc hygiene only (no live exposure) |
| `claude-opus-4-20250514` | doc only | Deprecated | Jun 15, 2026 | 🟡 doc hygiene only |

Daemon/Haven runtime model selection uses the friendly aliases (`CLAUDE_MODEL`, default `"sonnet"`)
resolved by the Claude Code CLI at runtime — **no dated IDs to rot.** Haven systemd overrides to
`claude-opus-4-8` (Active). Graphiti/extraction uses the **local NUC** (`qwen3.5-9b-...` via
LM Studio at `172.26.0.1:1234`), not Anthropic.

**Param-deprecation watch:** verify no direct `messages.create` call sets `temperature`/`top_p`/`top_k`
(would 400 on Opus 4.7+). The two recollection endpoints set only `max_tokens` + `messages` (clean);
re-check `cc_openai_wrapper.py:835` fallback if the wrapper is kept.

---

## §B — Deadwood classification (proposed — Jeff decides removals)

| Component | Class | Rationale / revival condition |
|---|---|---|
| `daemon/cc_invoker/invoker.py` (`ClaudeInvoker`) | **ACTIVE** | Load-bearing: every daemon/Haven/reflection response. Uses alias, no dated ID. |
| `pps/docker/cc_openai_wrapper.py` + `pps-haiku-wrapper` container + `Dockerfile.cc-wrapper` + `requirements-cc-wrapper.txt` | **PIONEER → SUSPECT** | Succeeded (eliminated Graphiti OpenAI cost), then superseded by NUC LLM. 0 prod callers. **Revival condition:** revive if Graphiti returns to OpenAI-compat routing OR ambient Haiku-compression (`PPS_HAIKU_SUMMARIZE=true`) is enabled. |
| `hooks/inject_context.py` (root copy) | **DEADWOOD (propose removal)** | Older, Lyra-hardcoded, lower-capability. Superseded by `.claude/hooks/inject_context.py` (canonical, entity-aware, symlinked-active per #232). |
| `daemon/lyra_discord.py` | **SUSPECT** | Researcher flags as older/alternate of `daemon/lyra_daemon.py`. Confirm which is the live Discord entrypoint before touching. |
| `daemon/lyra_daemon_legacy.py` | **NURSE/PIONEER** | Known fallback (CLI subprocess, pre-invoker). Already tracked. |
| `simple_discord_daemon/` | **SUSPECT** | Standalone CLI bot; confirm if still used. |
| Entity-summary feature: `server_http.py:3223` **and** `app.py:1329` | **DIVERGENT** | Same feature, two homes, drifted models. Consolidate to one (the `app.py` copy is on the current model). |

**Defects to fix (not deadwood — live bugs):**
- 🔴 `server_http.py:3223` retired-model ref → swap to `claude-haiku-4-5-20251001`.
- 🔴 `cc_openai_wrapper.py:815` retired-model ref → swap (or removed if wrapper retired).

---

## §C — Decisions for Jeff (architecture / high-level)

- **C1 — The `pps-haiku-wrapper`:** retire it (stop container, archive `cc_openai_wrapper.py` to root
  bank), or keep dormant as documented fallback? *(Retiring subsumes one of the two retired-model fixes.)*
  **Verify-before-retire:** confirm `PPS_HAIKU_SUMMARIZE` is not `true` in any live env, and nothing
  external POSTs to :8204.
- **C2 — Duplicated entity-summary feature:** consolidate to one home, or leave both? (Fix the
  `server_http` model regardless if that path stays.)
- **C3 — Centralize model IDs** into a single config/registry (one place to bump) vs. leave inline?
  Natural candidate entry for the #266 architectural-patterns catalog.

---

## §D — Full call-site inventory (researcher sweep, reference)

18 SDK/API call-sites total (10 runtime · 6 test/legacy · 2 conditional-hook). Two SDKs:
`claude-agent-sdk` (wraps the CC CLI; used by all daemons via `ClaudeInvoker`) and `anthropic`
(raw API; wrapper json_schema path + the two recollection endpoints).

**Runtime SDK users (all via `ClaudeInvoker`, alias-model, no dated IDs):**
`haven/bot.py`, `daemon/lyra_daemon.py`, `daemon/lyra_discord.py`, `daemon/lyra_reflection.py`,
`daemon/caia_reflection.py`, `daemon/shared/claude_invoker.py`, `simple_discord_daemon/bot.py`
(CLI subprocess), `daemon/lyra_daemon_legacy.py` (CLI subprocess).

**Raw `anthropic` API users:** `cc_openai_wrapper.py` (fallback), `server_http.py:3218`,
`pps/web/app.py:1326`.

**Wrapper (:8204) callers:** `.claude/hooks/inject_context.py` + `hooks/inject_context.py`
(both gated `PPS_HAIKU_SUMMARIZE=false`), `scripts/sandbox_test.py --no-proxy`,
`scripts/logging_proxy.py`. `pps/docker/.env` Graphiti→:8204 route is **commented out**.

**SDK pins:** `claude-agent-sdk>=0.1.20` (root; `0.1.58` installed), `>=0.1.0` (wrapper),
`anthropic>=0.39.0`/`>=0.45.0` (wrapper/docker/web), `mcp>=1.0.0`. All loose lower-bounds —
an un-pinned `-U` could pull a breaking SDK change into the daemons.

---
*Forestry artifact. Canopy + deadwood by Lyra; exhaustive call-site sweep by researcher (sonnet);
policy reconcile vs. live Anthropic page. Removals/architecture pending Jeff's calls (§C).*
