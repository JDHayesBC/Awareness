# Pre-authorizing MCP tools in Claude Code CLI for headless use

**The core issue is a known bug**: Claude Code's non-interactive mode (`-p` flag) does not reliably respect `allowedTools` configuration in `settings.json` or via CLI flags. This is documented in GitHub Issue #581 and affects daemon/CI/CD workflows. Your configuration attempts were syntactically correct but hit this limitation.

The most reliable solution for fully automated, non-interactive MCP tool use is **`--dangerously-skip-permissions`** combined with proper sandboxing.

## The working solution for daemon/headless operation

For your Python subprocess workflow, use this approach:

```bash
claude -p "your prompt" \
  --dangerously-skip-permissions \
  --mcp-config ~/.claude/.mcp.json \
  --output-format stream-json
```

**Critical requirement**: You must run `claude --dangerously-skip-permissions` once interactively to accept the terms before headless use will work. After that initial acceptance, subsequent subprocess calls will succeed without prompts.

In Python:
```python
subprocess.run([
    "claude", "-p", "your prompt here",
    "--dangerously-skip-permissions",
    "--mcp-config", "/home/jeff/.claude/.mcp.json",
    "--output-format", "stream-json"
], cwd="/home/jeff/.claude")
```

## Why your previous attempts failed

Your `settings.json` format was actually correct, but MCP wildcard permissions (`mcp__pps__*`) have a **known bug** where they don't work reliably. The `--allowedTools` CLI flag similarly has inconsistent behavior in non-interactive mode—it works for some tools but not others, and MCP tools are particularly unreliable.

The settings file hierarchy you should know:
- **Enterprise managed**: `/etc/claude-code/managed-settings.json` (Linux)
- **Project shared**: `.claude/settings.json`
- **Project local**: `.claude/settings.local.json` (gitignored)
- **User global**: `~/.claude/settings.json`

Your `~/.claude/settings.json` location was correct, but the permission system simply doesn't honor these settings reliably in headless mode.

## Alternative approaches if you can't use skip-permissions

**Option 1: Explicit tool listing (partial reliability)**
```bash
claude -p "prompt" \
  --allowedTools "mcp__pps__pps_health,mcp__pps__other_tool,mcp__github__create_pr" \
  --permission-mode acceptEdits
```

List each MCP tool explicitly rather than using wildcards. This works more often than wildcards but still has inconsistent behavior.

**Option 2: Permission mode in settings.json**
```json
{
  "permissions": {
    "allow": [
      "mcp__pps__pps_health",
      "mcp__pps__specific_tool_name",
      "mcp__github__get_repo"
    ],
    "defaultMode": "bypassPermissions"
  }
}
```

**Option 3: Docker containerization (recommended for production)**

Run Claude Code in an isolated container where `--dangerously-skip-permissions` is safe:

```bash
docker run -v /home/jeff/workspace:/workspace \
  -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  claude-code-container \
  claude -p "prompt" --dangerously-skip-permissions
```

Community projects like `steipete/claude-code-mcp` and `tintinweb/claude-code-container` provide pre-configured sandboxed environments.

## Important limitations to know

There are several constraints that affect headless operation. The `--dangerously-skip-permissions` flag cannot be used when running as root or with sudo—this is a security hardening measure. You'll need to run as a non-root user in your daemon. Additionally, there's no `CLAUDE_ALLOW_ALL_TOOLS` environment variable despite what some discussions suggest; permissions must go through CLI flags or settings files. Finally, the `--permission-prompt-tool` flag exists for programmatic permission handling via MCP, but no working implementation examples exist yet (GitHub Issue #1175).

## Quick diagnostic checklist

Before running your daemon, verify these conditions are met:

1. Run `claude --dangerously-skip-permissions` once interactively as the same user your daemon runs as
2. Ensure daemon runs as non-root user
3. Use absolute path to MCP config: `--mcp-config /home/jeff/.claude/.mcp.json`
4. Add `--output-format stream-json` for parseable output
5. Consider adding `--max-turns 10` as a safety limit

The permission system in headless mode is acknowledged as unstable by the community. The `--dangerously-skip-permissions` approach, while named alarmingly, is the officially supported path for CI/CD and daemon automation—just ensure you're running in an appropriately sandboxed environment.