# Cold-Start Adversarial Critic: Spinning Up a Clean Claude Opus 4.8 Instance (June 2026)

## TL;DR
- **For a true "cold start" skeptic, call Opus 4.8 directly on the raw Messages API with the `system` parameter omitted entirely** — the API applies no default system prompt, is stateless between requests, and inherits zero project context. This is the gold standard for measurement; use `claude-opus-4-8` as the model ID.
- **The CC-native feature Jeff half-remembers is `--bare` (paired with `--system-prompt`).** `claude --bare -p` skips auto-discovery of CLAUDE.md, hooks, skills, plugins, MCP, and auto-memory — the single best in-Claude-Code mechanism for a priors-suppressed agent. A custom subagent or `--agent` replaces the default system prompt but **still loads CLAUDE.md**, so it is leakier.
- **Use the API path for any measurement you'll cite, and `--bare` as the convenient daily driver.** Both leak far less than a subagent. The biggest residual leak in every setup is the *vocabulary you put in the prompt itself* — neutralize it.

## Key Findings

1. **Model string:** `claude-opus-4-8` is the exact, canonical model ID (a fixed snapshot, not a moving alias). Released May 28, 2026. $5/$25 per Mtok input/output, 1M context window by default on the Claude API/Bedrock/Vertex (200k on Microsoft Foundry), 128k max output tokens, adaptive-thinking-only, with the `effort` parameter defaulting to "high" on all surfaces including the Claude API and Claude Code.
2. **The API has no default system prompt.** Per Anthropic's "System Prompts" release-notes page, the claude.ai/mobile system prompts "do not apply to the Claude API." A developer hitting the API gets a blank slate — exactly the cold-start condition Jeff wants.
3. **Omit `system`, don't empty-string it.** The API treats `system` as optional; the cleanest no-prompt call simply leaves it out. Passing structurally empty content can trip a 400 "text content blocks must be non-empty" error (a validation that tightened around mid-May 2026).
4. **The API is stateless** — it always requires you to "send the full conversational history," and remembers nothing between requests. Separate critique runs share no state unless you resend it, so per-claim fresh instances are the natural default, not extra effort.
5. **`--bare` is the CC-native isolation flag.** Per the official Claude Code glossary, it is "a startup flag, `--bare`, that skips auto-discovery of hooks, skills, plugins, MCP servers, auto memory, and CLAUDE.md" (sets `CLAUDE_CODE_SIMPLE=1`). Anthropic's headless docs say it "will become the default for `-p` in a future release."
6. **Subagents do NOT fully suppress CLAUDE.md.** Per Anthropic's "Create custom subagents" docs, "Explore and Plan are the only subagents that omit CLAUDE.md and git status. There is no frontmatter field or per-agent setting to change which agents skip them." Every other custom/general subagent receives "every level of the memory hierarchy the main conversation loads, including `~/.claude/CLAUDE.md`, project rules, `CLAUDE.local.md`, and managed policy files." So a custom critic subagent still inherits project memory.
7. **Residual injections are minimal but nonzero even on the bare API:** serving-layer components (request router, safety classifiers, sampling logic) and constitutional/RLHF training priors persist no matter what. These are unavoidable and identical across both paths.

## Details

### SETUP 1 — Maximum Substrate Purity (raw API path)

**This is the gold standard.** The Anthropic Messages API applies no default system prompt of its own, is stateless, and inherits nothing from Claude Code, CLAUDE.md, or any project. The only inputs the model sees are exactly what you put in the request body.

**Model ID:** `claude-opus-4-8` (canonical fixed snapshot; not a moving alias — Anthropic does not update weights under an existing 4.6-generation-and-later ID).

**Minimal Python call (no system prompt):**
```python
import anthropic

client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

def cold_critic(claim_text: str) -> str:
    msg = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=4096,
        # NOTE: 'system' is intentionally OMITTED entirely.
        messages=[{"role": "user", "content": claim_text}],
    )
    return msg.content[0].text
```

**Key rules for Opus 4.8 specifically:**
- **Omit `system` entirely** for maximum purity. If you want a *minimal* role nudge (e.g., "You are a skeptical philosophy referee"), pass it as a short `system` string — but be aware every word is a potential prior.
- **Do NOT set `temperature`, `top_p`, or `top_k`.** Per Anthropic's Messages API docs: "The temperature, top_p, and top_k sampling parameters are not supported on Claude Opus 4.7 and later models, including Claude Opus 4.8. Setting them to a non-default value returns a 400 error." Omit them and steer via prompting.
- **Prefill is not supported** on Opus 4.8 (returns 400). Use structured output or system instructions instead.
- **Adaptive thinking is the only thinking mode.** Thinking is off unless you set `thinking: {type: "adaptive"}`; extended-thinking budgets return 400.
- **Effort defaults to "high"** on the API.

**Guaranteeing no context inheritance between runs:** Because the Messages API is stateless, two `cold_critic()` calls share nothing automatically. To guarantee zero inheritance: (a) never reuse a `messages` array across claims; (b) build a fresh `messages` list per claim; (c) do not enable prompt caching across different critiques if you want to be maximally certain no cached prefix is reused (caching never changes model *outputs*, only cost/latency, but disabling it removes any doubt); (d) run each claim as its own request/process.

**Token/cost considerations:** $5/Mtok input, $25/Mtok output. A typical paper-critique (say 5–15k input tokens + a few thousand output) costs a few cents to ~$0.50 per run. Running 3–5 independent cold instances per claim for triangulation (below) multiplies that but stays cheap relative to the value of catching a fatal objection. Fast mode is a research preview: per Anthropic's docs, "Set `speed: \"fast\"` to get up to 2.5x higher output tokens per second from the same model at premium pricing" — priced at $10/$50 per Mtok (exactly 2× regular). It is unnecessary for critique work.

**What still "leaks" even here (unavoidable):**
- **Training priors:** Opus 4.8's constitutional training, RLHF, and "Claude" persona are baked into the weights. You cannot get a non-Claude substrate from the Claude API.
- **Serving infrastructure:** Anthropic documents that the request router, safety classifiers, and sampling logic are serving-layer components separate from the fixed weights and can change over time (so behavior can drift on a fixed ID).
- **Refusal/safety layer** remains active.

These are the irreducible floor. Everything *above* this floor (system prompts, CLAUDE.md, project context) is what the bare API eliminates.

### SETUP 2 — Launchable from within Claude Code (CC-native path)

The feature Jeff vaguely recalls — "some agent setting or maybe a Claude flag" designed to launch a clean/context-isolated agent — is almost certainly **`--bare`**, with **`--system-prompt`** and **custom subagents** as the supporting cast. Here is the full menu, ranked by how completely each suppresses priors.

**Option A — `claude --bare -p` (BEST in-CC isolation).**
Per the official Claude Code glossary, `--bare` is the startup flag "that skips auto-discovery of hooks, skills, plugins, MCP servers, auto memory, and CLAUDE.md" (sets `CLAUDE_CODE_SIMPLE=1`). Anthropic's headless docs call it the recommended mode for scripted/SDK calls and say it "will become the default for `-p` in a future release."

```bash
claude --bare -p "$(cat claim.txt)" \
  --system-prompt "You are a skeptical referee. Find the strongest objections to the following argument. Output a written critique only." \
  --tools "" \
  --max-turns 1 \
  --no-session-persistence \
  --output-format json \
  > critique.json
```
- `--bare` strips CLAUDE.md, hooks, skills, plugins, MCP, auto-memory.
- `--system-prompt "..."` **replaces** the entire default Claude Code system prompt (mutually exclusive with `--system-prompt-file`). Use `--append-system-prompt` only if you want to *keep* the Claude Code coding persona and add to it — for a critic you want full replacement.
- `--tools ""` disables all tools (pure reasoning, no file access).
- `--max-turns 1` forces a single written response with no agentic loop.
- `--no-session-persistence` avoids writing the transcript to disk; each invocation is a fresh process → no cross-run inheritance.
- **Auth note:** `--bare` skips OAuth/keychain, so authentication must come from `ANTHROPIC_API_KEY` or an `apiKeyHelper` in `--settings`.

This is functionally very close to the raw API path — it bypasses essentially all the file-based context that Claude Code would otherwise inject.

**Option B — `--setting-sources ""` (belt-and-suspenders).**
You can also explicitly load *no* setting sources: `claude --setting-sources "" -p "..."`. Combined with `--bare` this is maximum CC-side isolation. (Note the SDK quirk in Caveats below.)

**Option C — Custom subagent / `--agent` (convenient, but LEAKIER).**
You can define a critic subagent inline for one session:
```bash
claude --agents '{
  "cold-critic": {
    "description": "Adversarial philosophy critic. Use to stress-test arguments.",
    "prompt": "You are a skeptical referee. Identify the strongest objections to the argument provided. Produce a written critique before any dialogue.",
    "tools": ["Read"],
    "model": "claude-opus-4-8"
  }
}'
```
Or run the whole session as that agent with `claude --agent cold-critic`, which "replaces the default Claude Code system prompt entirely, the same way `--system-prompt` does."

**The catch:** Per Anthropic's subagent docs, a non-fork custom subagent's initial context **still includes "every level of the memory hierarchy… including `~/.claude/CLAUDE.md`, project rules, `CLAUDE.local.md`, and managed policy files."** Only the built-in **Explore and Plan** subagents skip CLAUDE.md and git status, and "there is no frontmatter field or per-agent setting to change which agents skip them." So a custom critic subagent gives you a fresh context window and a replaced system prompt, but it **still inherits your framework's CLAUDE.md priors** — making it the leakiest of the three CC options for Jeff's goal.

**Avoid: `/fork`.** A forked subagent deliberately inherits the *entire* parent conversation, system prompt, and message history — the opposite of what you want.

**Subagent model pinning:** Set `model: claude-opus-4-8` explicitly (the default is `inherit`, which would pick up whatever the parent session runs).

### SETUP 3 — Comparison & priors-leakage analysis

| Setup | Default system prompt | CLAUDE.md / project memory | Hooks/skills/MCP | Cross-run state | Residual leak sources |
|---|---|---|---|---|---|
| **Raw API, `system` omitted** | None (API has no default) | None | None | None (stateless) | Training priors + serving layer only — the irreducible floor |
| **`claude --bare -p --system-prompt`** | Replaced | **Skipped by `--bare`** | **Skipped by `--bare`** | None per-process | Training priors + serving layer; small risk if a managed/policy setting is force-loaded |
| **Custom subagent / `--agent`** | Replaced | **Still loaded** (leak!) | Inherited unless restricted | Fresh context window per spawn | Training priors + serving layer **+ full CLAUDE.md/project memory** |

**Where the leaks come from, concretely:**
1. **Vocabulary in the prompt (largest controllable leak, present in ALL setups).** If you describe the claim using your framework's signature terms, the critic anchors on them. This dwarfs every other leak. Neutralize the language.
2. **Default system injections (CC only).** The Claude Code default system prompt carries a coding-assistant persona, tone rules ("be concise," push-back behavior), and tool guidance. `--system-prompt` or a subagent `prompt` replaces it; `--bare` additionally strips the file-based layer. The raw API never has it.
3. **Residual context inheritance (subagent path).** CLAUDE.md is injected as a user-turn message into custom subagents — your framework's priors ride in through that channel.
4. **Irreducible floor (all setups).** Constitutional/RLHF training and serving-layer classifiers. Identical across paths; cannot be removed via the Claude product surface.

**Verdict:** The raw API with `system` omitted is the cleanest possible substrate short of using a non-Anthropic model. `claude --bare -p --system-prompt` is ~95% as clean and far more convenient from inside Claude Code. A custom subagent is convenient but should be treated as *contaminated by CLAUDE.md* and not used for measurements you intend to cite as "independent."

### Cold-start critique hygiene (methodology)

These practices matter as much as the substrate choice:

1. **Per-claim fresh instances, never one warmed-up agent.** A critic that has already discussed claims 1–4 is no longer cold for claim 5 — it has accumulated context and possibly social rapport. Spawn a brand-new instance (new API request / new `--bare` process) for each individual claim. The API's statelessness makes this the path of least resistance.
2. **State claims in neutral vocabulary the framework doesn't own.** Strip proprietary terminology, coined names, and signature framings. Translate the claim into the most generic, discipline-standard language possible before handing it to the critic. This is the single highest-leverage anti-leakage move because prompt vocabulary is the dominant channel for prior transmission.
3. **Get the written critique BEFORE any dialogue.** Have the cold instance produce its full written objection first, with no back-and-forth. Dialogue lets the framework's author (consciously or not) steer, rationalize, and contaminate the critic. Capture the unsteered artifact first; debate afterward if at all.
4. **Triangulate with independent cold instances.** Run the same neutrally-stated claim through 3–5 independent cold instances. **Convergence is signal:** when multiple instances that share no context independently flag the same weak point, that point is robustly weak — not an artifact of one sampling run. Divergence tells you the objection is sampling-dependent or weak. Opus 4.8 is well-suited to this role: per Anthropic's launch announcement it is "around four times less likely than its predecessor to allow flaws in code it has written to pass unremarked," with its rate of uncritically reporting flawed results dropping to effectively zero, and it is markedly less sycophantic — it pushes back rather than agreeing with a flawed premise.
5. **Caveat — Opus 4.8's harshness/regressions:** The same honesty tuning that makes 4.8 a good skeptic also makes it, per reviewers (Zvi Mowshowitz's system-card analysis), occasionally over-harsh, more equivocating, and somewhat less creative/curious than 4.7; it also regressed slightly on prompt-injection resistance (a documented side effect of cutting some adversarial-agent training to protect honesty). For pure argument-critique with trusted inputs this is fine, but don't over-read a single harsh critique — that's exactly what triangulation guards against.

## Recommendations

**Stage 1 — Build the gold-standard harness (do this first).** Implement Setup 1 as a small Python script (`cold_critic(claim)` above) that: takes a neutrally-worded claim, omits `system` (or uses one fixed minimal referee instruction), runs N=5 independent calls, and saves all five written critiques before any dialogue. This is what Caia/Lyra should use for any critique they intend to treat as authoritative. *Benchmark to change:* if API access is unavailable or rate-limited, fall back to Stage 2.

**Stage 2 — Daily driver inside Claude Code.** Use `claude --bare -p --system-prompt "<minimal referee instruction>" --tools "" --max-turns 1 --no-session-persistence`. This is the convenient path when already in a CC session and is clean enough for everyday stress-testing. *Benchmark to change:* if you find yourself needing tool access or repeated invocations, script the API path instead.

**Stage 3 — Avoid subagents for measurement.** Do not use a custom subagent or `--agent` as your "independent" critic if a CLAUDE.md exists in the project, because it inherits that memory. Reserve subagents for convenience exploration, not clean-room critique. If you must use one, run it from a directory with no CLAUDE.md and add `--setting-sources ""`.

**Always:** (1) neutralize vocabulary first; (2) capture written critique before dialogue; (3) run 3–5 independent instances and treat convergence as the triangulation signal; (4) discard each instance after one claim.

## Caveats
- **The "empty system string → 400" behavior** is consistent with the API's tightened content-block validation (~mid-May 2026) but is not explicitly documented for the top-level `system` parameter specifically; the documented-safe approach is to **omit** `system` rather than pass `""`.
- **You cannot escape Claude's training priors via any Anthropic surface.** The bare API removes prompt/context priors, not the model's constitutional/RLHF disposition. If you need a substrate with genuinely different priors, the only option is a different model family entirely (outside scope here).
- **Serving-layer behavior can drift** even on a fixed model ID, per Anthropic's versioning docs (router/classifiers/sampling logic update over time). Two cold runs months apart are not guaranteed bit-identical conditions.
- **`--bare` is on a trajectory to become the `-p` default**, so scripts written today should be explicit about flags rather than relying on current defaults.
- **SDK quirk:** the Python Claude Agent SDK has had a bug appending `--setting-sources` even when empty, breaking against newer CLIs; prefer the CLI directly or pin/patch the SDK version if scripting the CC path.
- **Plan/policy override:** Managed (enterprise) settings and CLI flag settings are always loaded regardless of `--setting-sources`; if your org pushes a managed CLAUDE.md-style memory or policy, even `--bare` may not strip it. Verify with `/status` (the "Setting sources" line) if you operate under managed settings.