# Configuring MCP Tools in Claude Code CLI: Project vs Global

Claude Code CLI supports **three distinct scope levels** for MCP server configuration, each with specific configuration files, precedence rules, and use cases. This reference covers the exact commands, file locations, and syntax needed for implementation.

## The three MCP configuration scopes

Claude Code uses `local`, `project`, and `user` scopes (note: `global` was renamed to `user` in recent versions). The **precedence order** when servers with the same name exist at multiple levels is: **local → project → user**, with local configurations taking priority.

| Scope | Flag | Storage Location | Visibility |
|-------|------|------------------|------------|
| `local` | `--scope local` (default) | `~/.claude.json` under project path | Private to you, current project only |
| `project` | `--scope project` | `.mcp.json` in project root | Shared via version control with team |
| `user` | `--scope user` | `~/.claude.json` in mcpServers field | Private to you, across all projects |

## Project-level configuration (team-shareable)

Project-scoped servers are stored in a `.mcp.json` file at your project's root directory. This file is designed to be **checked into version control**, ensuring all team members have access to the same MCP tools.

### Adding project-scoped servers via CLI

```bash
# Add an HTTP server at project scope
claude mcp add --transport http paypal --scope project https://mcp.paypal.com/mcp

# Add a stdio server at project scope with environment variables
claude mcp add --transport stdio database --scope project \
  --env DB_HOST=localhost --env DB_PORT=5432 \
  -- npx -y @bytebase/dbhub --dsn "postgresql://user:pass@localhost/db"
```

### The `.mcp.json` file structure

The CLI automatically creates or updates this file in your project root:

```json
{
  "mcpServers": {
    "paypal": {
      "type": "http",
      "url": "https://mcp.paypal.com/mcp"
    },
    "database": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@bytebase/dbhub", "--dsn", "postgresql://user:pass@localhost/db"],
      "env": {
        "DB_HOST": "localhost",
        "DB_PORT": "5432"
      }
    }
  }
}
```

### Environment variable expansion in `.mcp.json`

Claude Code supports variable expansion for flexible, secure configurations:

```json
{
  "mcpServers": {
    "api-server": {
      "type": "http",
      "url": "${API_BASE_URL:-https://api.example.com}/mcp",
      "headers": {
        "Authorization": "Bearer ${API_KEY}"
      }
    },
    "db-tool": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@bytebase/dbhub"],
      "env": {
        "DATABASE_URL": "${DATABASE_URL}"
      }
    }
  }
}
```

Supported syntax: `${VAR}` expands to the variable value; `${VAR:-default}` uses the default if VAR is unset.

**Security note:** Claude Code prompts for approval before using project-scoped servers from `.mcp.json` files. Reset these approvals with `claude mcp reset-project-choices`.

## User-level (global) configuration

User-scoped servers are stored in `~/.claude.json` and are available across **all projects** on your machine while remaining private to your user account.

### Adding user-scoped servers via CLI

```bash
# Add an HTTP server at user scope
claude mcp add --transport http hubspot --scope user https://mcp.hubspot.com/anthropic

# Add a stdio server at user scope
claude mcp add --transport stdio omnisearch --scope user \
  --env TAVILY_API_KEY=your-key \
  -- npx -y mcp-omnisearch

# Add from JSON configuration at user scope
claude mcp add-json weather-api --scope user \
  '{"type":"http","url":"https://api.weather.com/mcp","headers":{"Authorization":"Bearer token"}}'
```

### The `~/.claude.json` file structure

User-scoped servers appear in the top-level `mcpServers` field:

```json
{
  "mcpServers": {
    "hubspot": {
      "type": "http",
      "url": "https://mcp.hubspot.com/anthropic"
    },
    "omnisearch": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "mcp-omnisearch"],
      "env": {
        "TAVILY_API_KEY": "your-key"
      }
    }
  }
}
```

## Local-scope configuration (private, project-specific)

Local scope is the **default** when no `--scope` flag is specified. These servers are private to you and only accessible in the current project directory. They are stored in `~/.claude.json` under the specific project path.

```bash
# Add local-scoped server (default behavior)
claude mcp add --transport http stripe https://mcp.stripe.com

# Explicitly specify local scope
claude mcp add --transport http stripe --scope local https://mcp.stripe.com
```

In `~/.claude.json`, local servers appear under the projects section:

```json
{
  "projects": {
    "/path/to/your/project": {
      "mcpServers": {
        "stripe": {
          "type": "http",
          "url": "https://mcp.stripe.com"
        }
      }
    }
  }
}
```

## Complete command reference

### Adding servers with different transports

```bash
# HTTP transport (recommended for remote servers)
claude mcp add --transport http \<name\> \<url\>
claude mcp add --transport http notion https://mcp.notion.com/mcp

# SSE transport (deprecated, use HTTP when available)
claude mcp add --transport sse asana https://mcp.asana.com/sse

# Stdio transport (for local processes)
claude mcp add --transport stdio \<name\> -- \<command\> [args...]
claude mcp add --transport stdio airtable --env AIRTABLE_API_KEY=KEY -- npx -y airtable-mcp-server
```

### The `--` separator explained

The double-dash separates Claude CLI flags from the server command:
- **Before `--`**: Claude options (`--env`, `--scope`, `--transport`, `--header`)
- **After `--`**: The actual command to run the MCP server

```bash
# Claude flags before --, server command after --
claude mcp add --transport stdio myserver --env KEY=value --scope project -- python server.py --port 8080
```

### Server management commands

```bash
claude mcp list                        # List all configured servers
claude mcp get \<name\>                  # Get details for a specific server  
claude mcp remove \<name\>               # Remove a server
claude mcp reset-project-choices       # Reset project server approval choices
claude mcp add-from-claude-desktop     # Import servers from Claude Desktop
/mcp                                   # Check status within Claude Code session
```

### Adding servers from JSON

```bash
# HTTP server from JSON
claude mcp add-json api-server '{"type":"http","url":"https://api.example.com/mcp","headers":{"Authorization":"Bearer token"}}'

# Stdio server from JSON  
claude mcp add-json local-tool '{"type":"stdio","command":"/path/to/cli","args":["--config","file.json"],"env":{"KEY":"value"}}'
```

## Choosing the right scope

| Use Case | Recommended Scope |
|----------|-------------------|
| Personal dev servers, experimental configs | `local` (default) |
| Sensitive credentials for one project | `local` |
| Team-shared tools, project-specific services | `project` |
| Personal utilities across multiple projects | `user` |
| Development tools you use everywhere | `user` |

## Behavior differences between scopes

**Project scope** creates a `.mcp.json` file that can be committed to version control. Claude Code will prompt users for approval before using these servers (security measure). This enables consistent tooling across a team.

**IMPORTANT: Manual activation required for project-scoped servers.** Simply having the `.mcp.json` file is not sufficient. After Claude Code restarts, you must manually enable project-scoped servers:

1. Run `/mcp` inside Claude Code to see server status
2. Use `/mcp enable <server-name>` to activate the server
3. The server should then appear in your available tools

This is a security feature—project-scoped configs require explicit user consent before activation.

**User scope** stores configuration privately in `~/.claude.json`, making servers available in every project you work on without requiring per-project setup. These are never visible to team members.

**Local scope** combines privacy with project-specificity—useful for credentials or experimental configurations that shouldn't be shared but only apply to one project.

## Windows-specific syntax

Windows requires the `cmd /c` wrapper for `npx` commands:

```bash
claude mcp add --transport stdio my-server -- cmd /c npx -y @some/package
```

## Runtime environment variables

Set these before running Claude Code to adjust MCP behavior:

```bash
MCP_TIMEOUT=10000 claude          # 10-second server startup timeout
MAX_MCP_OUTPUT_TOKENS=50000 claude # Increase output limit (default: 25,000)
```

## Configuration file summary

| Scope | Configuration File | Version Controlled |
|-------|-------------------|-------------------|
| `local` | `~/.claude.json` (under project path) | No |
| `project` | `.mcp.json` (project root) | **Yes** |
| `user` | `~/.claude.json` (mcpServers field) | No |
| Enterprise | `managed-mcp.json` (system directories) | IT-managed |

This reference reflects the official Anthropic documentation for Claude Code CLI as of January 2026.

---

## Awareness Project Philosophy: Light Touch on Global

**For this project, we use project scope (`.mcp.json`) for MCP servers.**

Why:
- **Portability**: Steve (or anyone) clones the repo and gets the config automatically
- **No global pollution**: We don't touch `~/.claude.json` user-level mcpServers
- **Self-contained**: Everything needed is in the project directory

The local venv (`pps/venv/`) keeps Python dependencies project-local. The `.mcp.json` keeps MCP config project-scoped. Nothing reaches into user-global space.

**Remember**: After restart, project-scoped servers need manual activation via `/mcp enable <name>`.