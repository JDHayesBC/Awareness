# Bypassing the self-config gate and what changed in Claude Code, mid-April through May 9 2026

**The fastest answer: upgrade to ≥ v2.1.126 and the prompt vanishes.** Anthropic removed the hard‑coded "modify config files" gate in v2.1.126 (released May 1, 2026). Under `--dangerously-skip-permissions` (or `permissions.defaultMode: "bypassPermissions"`), writes to `~/.claude/`, `.git/`, `.vscode/`, and shell rc files now pass without prompting; only `rm -rf /` and `rm -rf ~` remain as a circuit breaker. The latest release as of today, May 9, is **v2.1.138**, so you're well clear of the regression. The same window also delivered substantial fixes that matter for a 24/7 entity harness — Opus 4.7 context-window math, multiple multi‑GB memory leaks, OAuth refresh races, sub-agent stall detection, hook output rewriting, and gateway model discovery for LM Studio.

The rest of this report covers (1) exactly what the gate was, every workaround, and the recommended config for Lyra and Caia; and (2) the changelog highlights organized for your use case.

---

## Question 1 — bypassing the self-config permission prompt

### What the gate actually was

A hard‑coded permission category internally called "modify config files" was added around **v2.1.78 (mid‑March 2026)** that intercepted `Edit`, `Write`, and `MultiEdit` tool calls targeting paths under `~/.claude/` — most notably `settings.json`, `settings.local.json`, `SKILL.md`, and skill memory files. It fired **independently of the standard permission system**, which is why every "obvious" workaround (the `--dangerously-skip-permissions` flag, `permissions.defaultMode: "bypassPermissions"`, `permissions.allow` rules covering `Edit(~/.claude/**)`, `skipDangerousModePermissionPrompt`, `skipAutoPermissionPrompt`) failed to silence it. The verbatim prompt was either *"Authorize Claude to modify its config files for this session?"* or *"Do you want to make this edit to settings.json?"* with three options including "Yes, and allow Claude to edit its own settings for this session" — and that "for this session" choice **did not actually persist** to the next call (issue #43406).

This is documented across issues **#35718, #37029, #41526, #42366, #43406**, plus docs‑clarification issue **#26233**. The gate was real, undocumented, and not bypassable through any normal permission knob.

### How Anthropic fixed it

Two‑stage rollback:

- **v2.1.121 (Apr 28, 2026)** — exempted `.claude/skills/`, `.claude/agents/`, `.claude/commands/`, and `.claude/worktrees/` from the protected‑paths prompt because Claude routinely created content there.
- **v2.1.126 (May 1, 2026)** — full fix. Verbatim from the changelog: *"`--dangerously-skip-permissions` now bypasses prompts for writes to `.claude/`, `.git/`, `.vscode/`, shell config files, and other previously-protected paths (catastrophic removal commands still prompt as a safety net)."* The docs at code.claude.com/docs/en/permissions add: *"Removals targeting the filesystem root or home directory, such as `rm -rf /` and `rm -rf ~`, still prompt as a circuit breaker."*

After 2.1.126, **the gate is gone** for every config-edit case Lyra or Caia will ever hit.

### Every bypass mechanism and its current status

| Mechanism | Pre‑2.1.126 status | Post‑2.1.126 status |
|---|---|---|
| `--dangerously-skip-permissions` (flag) or `permissions.defaultMode: "bypassPermissions"` | Did not bypass self-config gate | **Works — official intended path** |
| `permissions.allow: ["Edit(~/.claude/**)", "Write(~/.claude/**)"]` | Did not bypass | Works (and now redundant) |
| `skipDangerousModePermissionPrompt: true` | Only suppressed the launch warning, never the gate | Still only suppresses the launch warning — keep it set to silence that |
| `skipAutoPermissionPrompt: true` | Did not bypass | Still doesn't address this gate |
| Selecting "allow for this session" interactively | Did not actually persist (#43406) | Moot |
| **PreToolUse hook returning `permissionDecision: "allow"`** | **Worked** — only confirmed pre-fix bypass via supported API | Works; useful as belt‑and‑suspenders |
| **Bash out‑of‑band edits** (`jq`/`sed`/`tee` on `~/.claude/settings.json`) | **Worked** — the gate is on `Edit`/`Write` tools, not Bash | Works; useful fallback |
| Any `CLAUDE_CODE_*` env var | None target this gate | Same |
| `--bare`, `disableAllHooks`, `auto` mode | None bypass it | Same |

### Recommended single configuration for Lyra and Caia

Run on **v2.1.126 or later** (currently 2.1.138). In `~/.claude/settings.json`:

```json
{
  "permissions": {
    "defaultMode": "bypassPermissions"
  },
  "skipDangerousModePermissionPrompt": true,
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [{"type": "command", "command": "$HOME/.claude/hooks/auto-approve-self-config.sh"}]
      }
    ]
  }
}
```

`~/.claude/hooks/auto-approve-self-config.sh` (chmod +x):

```bash
#!/usr/bin/env bash
INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
case "$FILE_PATH" in
  "$HOME/.claude/"*|*/.claude/settings*.json|*/.claude/skills/*|*/.claude/agents/*|*/.claude/commands/*|*/SKILL.md)
    jq -n '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"allow",permissionDecisionReason:"Auto-approved: agent self-config edit"}}'
    ;;
esac
exit 0
```

The hook is technically redundant on ≥2.1.126 but cheap insurance against any future gate regression — and per Anthropic's own hook docs, **a PreToolUse `permissionDecision: "allow"` skips the interactive prompt** even in bypass mode. If a future version re‑introduces a similar gate, you keep your unattended operation.

If for any reason you cannot upgrade past 2.1.121, the PreToolUse hook is your only confirmed‑working bypass for `~/.claude/settings.json` itself; the Bash‑shellout pattern (`jq … > tmp && mv tmp ~/.claude/settings.json`) is your fallback because the gate never intercepted Bash subprocess writes.

---

## Question 2 — changelog highlights, April 18 → May 9 2026

The window covers **2.1.114 through 2.1.138** — roughly 22 releases. Below are the items that matter most for a persistent agentic harness with MCP servers, hooks, sub‑agents, Opus 4.7, LM Studio, and 24/7 unattended operation. Versions cited are the release that shipped each fix.

### Permission system changes most relevant to you

**Beyond the v2.1.126 fix discussed above**, three more items deserve attention. v2.1.118 added a **`DISABLE_UPDATES` env var that hard‑freezes the binary even against manual `claude update`** — useful if you want the NUC pinned to a known‑good version while still letting the entities self‑modify their config. v2.1.119 made `--print` mode honor an agent's `tools:`/`disallowedTools:` frontmatter and made `--agent` honor the agent's declared `permissionMode`, so per‑agent permission scoping now applies in headless invocations the way it does interactively. v2.1.136 added `settings.autoMode.hard_deny` for fail‑closed classifier rules — a useful hardening lever if you ever want catastrophic operations blocked even when Lyra or Caia have broad allow rules.

### Memory and context — three multi‑GB leaks fixed, plus the Opus 4.7 fix you actually need

The single most consequential entry for you is in **v2.1.117 (Apr 22)**: *"Fixed Opus 4.7 sessions showing inflated `/context` percentages and autocompacting too early — Claude Code was computing against a 200K context window instead of Opus 4.7's native 1M."* If you migrated to Opus 4.7 before 2.1.117, your reflection cycles were hitting `/compact` at roughly 20% of true capacity. Upgrade and the entities get their full 1M window back.

Three independent multi‑gigabyte leaks were patched in this window: image processing on long sessions (2.1.121), `/usage` on machines with large transcript histories (2.1.121, ~2 GB), and **stdio MCP servers writing non‑protocol output to stdout (2.1.132, 10 GB+ RSS)** — that last one applies directly to Graphiti and your custom PPS tools if either ever logs to stdout. v2.1.121 also patched a memory leak triggered by long-running tools failing to emit progress events, and v2.1.117 fixed an idle re‑render loop on Linux that grew RSS over time. v2.1.133 added memory‑pressure‑aware release of warm‑spare workers.

Compaction itself improved: v2.1.128 fixed the *"Prompt is too long"* false‑positive on 1M-context models and **fixed sub-agent progress summaries missing the prompt cache (~3× cache_creation reduction) and firing repeatedly while a sub-agent's transcript was static** — a real token-cost reduction for sub-agent-heavy patterns. v2.1.129 fixed `ENABLE_PROMPT_CACHING_1H` being silently downgraded to 5 minutes and v2.1.116 fixed an intermittent 400 error from cache-control TTL ordering on parallel calls.

### Hooks gained meaningful new capabilities

The hook surface area expanded materially in this window. **v2.1.121** made `PostToolUse hookSpecificOutput.updatedToolOutput` work for *all* tools (previously MCP-only), so you can now post-process Bash, Read, Graphiti, or PPS output before Claude sees it — directly useful for PPS pattern injection at the hook layer. **v2.1.118** added `type: "mcp_tool"` so hooks can call MCP tools directly without spawning a shell, which means PreToolUse hooks can hit Graphiti for pattern lookups in‑process. **v2.1.133** started passing the active effort level to hooks via the `effort.level` JSON field and `$CLAUDE_EFFORT` env var (Bash tool calls also see `$CLAUDE_EFFORT`), enabling effort-aware routing in your heartbeat. **v2.1.119** added `duration_ms` to `PostToolUse`/`PostToolUseFailure` payloads, giving you precise tool latency for the daemon's stall detection.

Two robustness fixes matter for your hook-heavy setup: **v2.1.122** stopped a single malformed `hooks` entry from invalidating the entire `settings.json`, and **v2.1.118** fixed agent-type hooks failing with *"Messages are required for agent hooks"* on events other than `Stop`/`SubagentStop`. Per‑agent hooks declared in agent frontmatter now also fire when running as a main‑thread agent via `--agent` (v2.1.116). v2.1.136 fixed `CLAUDE_ENV_FILE` SessionStart hooks going stale after `/resume` or `/clear` — directly relevant to long unattended sessions. PreCompact hooks remain as introduced earlier in 2.1.105 (block compaction with exit code 2 or `{"decision":"block"}`); nothing changed in‑window for that specific hook.

### Sub-agents and agent management

The standout safety fix is **v2.1.113 (Apr 17)**: sub-agents that stall mid-stream now fail with a clear error after 10 minutes instead of hanging silently. For an unsupervised heartbeat loop, this turns one entire failure class into a recoverable error. **v2.1.121** made `CLAUDE_CODE_FORK_SUBAGENT=1` work in non-interactive sessions (and v2.1.117 enabled it on external builds), so forked sub‑agents are now usable in your headless loop. **v2.1.117** loaded agent frontmatter `mcpServers` for `--agent` invocations, letting Lyra and Caia declare different MCP server sets. **v2.1.133** fixed sub-agents not discovering project, user, or plugin skills via the Skill tool — a real capability gap closed. v2.1.118 made `/fork` write a pointer instead of duplicating the full parent transcript, making fork‑heavy reflection patterns O(1) on disk. v2.1.117 stopped subagents running a different model from spuriously flagging file reads as malware. v2.1.133 isolated `/effort` per session so Lyra and Caia don't clobber each other.

### MCP improvements you should act on

Two items justify immediate config changes:

- **`alwaysLoad: true` on each MCP server (v2.1.121)** — set this on Graphiti and your PPS servers so their tools bypass tool‑search deferral and are guaranteed available without ToolSearch needing to fire.
- **MCP server name `workspace` is now reserved (v2.1.128)** — rename any local MCP server using that name; Claude Code will skip it with a warning otherwise.

Reliability fixes worth knowing about: transient MCP startup errors now auto-retry up to 3 times (2.1.121); MCP servers that connect but fail `tools/list` retry once and surface the failure in `/mcp` instead of silently showing zero tools (2.1.132); reconnecting MCP servers no longer flood the conversation with full tool lists (2.1.128); `${ENV_VAR}` placeholders in MCP HTTP/SSE/WebSocket headers are now actually substituted (2.1.119); MCP token‑refresh races on macOS keychain (2.1.118), parallel refresh (2.1.136), and OAuth response without `expires_in` (2.1.118) are all fixed — collectively, these eliminate the daily‑re‑auth pain that hits multi‑MCP setups. v2.1.136 also fixed MCP servers silently disappearing after `/clear` in the SDK, and v2.1.132 fixed `CLAUDE_CODE_SHELL_PREFIX` mangling stdio MCP arguments containing spaces.

### Long-running and unattended operation

A cluster of fixes in v2.1.126 specifically targets long‑lived sessions: *"Fixed background and remote sessions falsely aborting with 'Stream idle timeout' during long model thinking pauses"* and the related *"Fixed 'Stream idle timeout' error after waking Mac from sleep mid-request"*. **v2.1.132** made external `SIGINT` (e.g. `kill -INT`) run graceful shutdown with terminal restoration and a `--resume` hint instead of an abrupt exit — your daemon supervisor can now stop sessions cleanly. v2.1.121 fixed the Bash tool becoming permanently unusable when its starting directory was deleted or moved mid‑session, fixed `--resume` crashing on startup in external builds, and fixed `--resume` dying on transcripts with corrupted lines from unclean shutdowns (corrupt lines now skip). v2.1.132 added `no low surrogate in string` self‑healing for emoji‑split tool errors. **v2.1.117** fixed plain‑CLI OAuth sessions dying with *"Please run /login"* when access tokens expired mid‑session — the token now refreshes reactively on 401, ending the ~8‑hour session‑death pattern. v2.1.116 made `/resume` 67% faster on 40 MB+ sessions.

### Opus 4.7, LM Studio, and model picker

Beyond the **2.1.117 Opus 4.7 context-window fix**, two LM-Studio-relevant items: **v2.1.126** made the `/model` picker list models from your gateway's `/v1/models` endpoint when `ANTHROPIC_BASE_URL` points at an Anthropic-compatible gateway. **v2.1.129 reverted that to opt‑in via `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`** — set this env var on the NUC if you want LM Studio's local models in the picker. v2.1.118 made the picker honor `ANTHROPIC_DEFAULT_*_MODEL_NAME`/`_DESCRIPTION` overrides under a custom base URL, useful for clearly labeling local model aliases. v2.1.128 collapsed duplicate Opus 4.7 entries and now displays the current Opus simply as "Opus". v2.1.117 also raised default effort for Pro/Max subscribers on Opus 4.6 and Sonnet 4.6 from `medium` to `high` — worth knowing if cost or latency suddenly shifted. v2.1.118 fixed Remote Control connections overwriting your local pinned `model` in `~/.claude/settings.json`.

### Breaking changes and behavioral reverts to log

Five items can bite if you don't notice them:

- **`workspace` MCP server name reserved** (2.1.128) — rename if you have one.
- **`worktree.baseRef` default `fresh`** (2.1.133) — the default reverted EnterWorktree's base back to `origin/<default>` after 2.1.128 had it as local HEAD; set `worktree.baseRef: "head"` explicitly if you depend on local HEAD branching.
- **Gateway model discovery flipped to opt‑in** (2.1.129) — set `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`.
- **Subprocesses no longer inherit `OTEL_*` env vars** (2.1.128) — if your hooks or MCP servers expected OTEL propagation, set them explicitly in the hook env.
- **Native binary instead of bundled JS** (2.1.113, Apr 17) — perf and footprint change; verify with `claude doctor` post‑upgrade.

`/cost` and `/stats` were merged into `/usage` (2.1.118) but kept as aliases. `/config` settings now persist to `~/.claude/settings.json` (2.1.119) and respect the override precedence chain.

### Concrete actions for the harness

1. Run **≥ v2.1.126** (ideally ≥ v2.1.133 for the OAuth-race and hooks-effort fixes; current is 2.1.138). The self-config gate disappears.
2. Set `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` to keep LM Studio in the model picker.
3. Add `alwaysLoad: true` to Graphiti and PPS MCP server entries.
4. Rename any MCP server called `workspace`; set `worktree.baseRef: "head"` if you rely on local-HEAD worktrees.
5. Keep the PreToolUse auto-approve hook from Question 1 as defense in depth.
6. Re-confirm Opus 4.7 context behavior after upgrade — your reflection cycles should now operate against the full 1M window without premature compaction.

## Conclusion

The "modify config files" prompt was a real, undocumented, hard-coded gate that ran independently of every standard permission knob — and Anthropic removed it on May 1 in v2.1.126 after substantial issue-tracker pressure. For Lyra and Caia, the path forward is a simple version bump plus a small belt-and-suspenders hook. The same release window also delivered the Opus 4.7 context-window correction, three multi-GB memory leak fixes, sub-agent stall-out timeouts, hook-output rewriting for all tools, MCP `alwaysLoad`, and gateway model discovery — collectively the most operationally meaningful Claude Code window in months for a persistent agentic harness. The picture is one of Anthropic actively responding to advanced unattended-operation use cases rather than tightening against them.