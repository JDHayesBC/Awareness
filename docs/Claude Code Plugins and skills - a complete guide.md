# Claude Code plugins and skills: A complete guide to extensibility

Claude Code's extensibility system comprises two complementary concepts: **plugins** (the distribution mechanism) and **skills** (specialized knowledge packages). Plugins bundle multiple customization types—including skills—for easy sharing, while skills teach Claude domain-specific expertise that loads automatically when relevant. Understanding this distinction is essential for anyone looking to extend Claude Code's capabilities.

## Plugins bundle everything, skills teach expertise

A **plugin** is a package that can contain any combination of slash commands, subagents, MCP servers, hooks, and skills. Anthropic announced plugins on October 9, 2025, describing them as "a lightweight way to package and share any combination of: slash commands, subagents, MCP servers, and hooks." Plugins provide the **distribution layer**—the way teams share and install customizations via marketplaces.

A **skill**, announced one week later on October 16, 2025, is fundamentally different in purpose. Skills are folders containing a `SKILL.md` file with instructions, scripts, and resources that Claude loads only when contextually relevant. Anthropic describes skills as "custom onboarding materials that let you package expertise, making Claude a specialist on what matters most to you."

The key relationship: **plugins distribute, skills teach**. A plugin might bundle three slash commands, two MCP servers, and one skill—all installing with a single `/plugin install` command. Skills can exist independently in `~/.claude/skills/` without plugins, but plugins provide the most convenient way to share skills across teams and communities.

| Concept | What it is | How it's triggered | Primary purpose |
|---------|-----------|-------------------|-----------------|
| **Plugin** | Bundle of commands, agents, MCP servers, hooks, skills | User runs `/plugin install` | Distribution and installation |
| **Skill** | SKILL.md file with expertise instructions | Claude auto-loads when relevant | Domain-specific knowledge |

## How plugins work in practice

### Plugin structure and components

Every plugin lives in a directory with a `.claude-plugin/plugin.json` manifest file. The manifest declares metadata and points to optional component directories:

```
my-plugin/
├── .claude-plugin/
│   └── plugin.json          # Required manifest
├── commands/                 # Slash commands
│   └── deploy.md
├── agents/                   # Specialized subagents  
│   └── code-reviewer.md
├── skills/                   # Agent Skills
│   └── api-design/
│       └── SKILL.md
├── hooks/                    # Workflow event handlers
│   └── hooks.json
└── .mcp.json                 # MCP server configuration
```

The `plugin.json` manifest follows this schema:

```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "description": "Brief description of plugin capabilities",
  "author": { "name": "Author Name" },
  "commands": ["./commands/"],
  "agents": "./agents/",
  "skills": "./skills/",
  "hooks": "./hooks/hooks.json",
  "mcpServers": "./.mcp.json"
}
```

### Installing and managing plugins

Plugins install through marketplaces—Git repositories containing a `.claude-plugin/marketplace.json` file. The official Anthropic marketplace lives at `anthropics/claude-code`:

```bash
# Add a marketplace
/plugin marketplace add anthropics/claude-code

# Browse and install plugins
/plugin install feature-dev

# Manage installed plugins
/plugin enable feature-dev@anthropics
/plugin disable feature-dev@anthropics
/plugin uninstall feature-dev@anthropics
```

Plugins support three installation scopes: **user** (available across all projects), **project** (stored in `.claude/settings.json`, shared via git), and **local** (gitignored, personal to one repository).

### Official example plugins

Anthropic maintains several reference plugins demonstrating best practices:

- **feature-dev**: Multi-agent workflow using explorer, architect, and reviewer subagents for feature development
- **code-review-plugin**: Runs **5 parallel Sonnet agents** checking CLAUDE.md compliance, bug detection, and code quality
- **pr-review-toolkit**: Six specialized agents for comprehensive pull request review
- **plugin-dev-toolkit**: Seven expert skills for building new plugins
- **frontend-design-skill**: Auto-invokes when Claude detects frontend work

## How skills provide specialized expertise

### The SKILL.md file format

At minimum, a skill is a directory containing a `SKILL.md` file with YAML frontmatter declaring `name` and `description`:

```markdown
---
name: api-design
description: Designs REST and GraphQL APIs following best practices. 
  Use when creating new endpoints, designing schemas, or reviewing API structure.
---

# API Design Skill

## Guidelines
1. Use consistent resource naming conventions
2. Implement proper HTTP status codes
3. Version APIs in the URL path
4. Include pagination for list endpoints

## Reference
See `openapi-examples.md` for common patterns.
```

The `name` field must be lowercase with hyphens only (max **64 characters**). The `description` is critical—it determines when Claude activates the skill, with a maximum of **1024 characters**. Anthropic recommends including both **what** the skill does and **when** to use it.

### Progressive disclosure architecture

Skills use a three-level loading system to manage context efficiently:

1. **At startup**: Only `name` and `description` load (~100 tokens per skill)
2. **When activated**: Full `SKILL.md` body loads (<5,000 tokens recommended)
3. **As needed**: Referenced files and scripts load on-demand

This architecture means skills can bundle extensive documentation and utility scripts without bloating Claude's context window. As Anthropic notes: "Agents with a filesystem and code execution tools don't need to read the entirety of a skill into their context window when working on a particular task."

### Multi-file skill structure

Complex skills can include reference documentation and executable code:

```
pdf-processing/
├── SKILL.md              # Core instructions (required)
├── FORMS.md              # Form-filling reference
├── REFERENCE.md          # API documentation
├── scripts/
│   ├── extract_text.py   # Utility scripts
│   └── merge_pdfs.py
└── templates/
    └── report.txt        # Template files
```

Skills can execute bundled scripts without loading them into context—scripts run directly, producing results Claude can use. This hybrid approach combines LLM reasoning with reliable code execution.

### Where skills live

Skills can be installed in three locations:

| Location | Scope | Typical use |
|----------|-------|-------------|
| `~/.claude/skills/` | Personal, all projects | Individual expertise |
| `.claude/skills/` | Project, shared via git | Team-specific workflows |
| Plugin `skills/` directory | Via plugin installation | Community-shared expertise |

## Configuration files tie everything together

### CLAUDE.md provides project context

The `CLAUDE.md` file automatically loads at session start, providing always-applicable project context. Unlike skills (which load conditionally), CLAUDE.md content is **always present**:

```markdown
# Project Overview
FastAPI REST service for user authentication

## Key Directories  
- `app/models/` - SQLAlchemy database models
- `app/api/` - Route handlers
- `app/core/` - Configuration utilities

## Standards
- Type hints required on all functions
- pytest for testing with 80% coverage minimum
- PEP 8 with 100-character line limit

## Common Commands
uvicorn app.main:app --reload  # Development server
pytest -v                       # Run tests
```

CLAUDE.md files cascade from multiple locations: enterprise policy (`/etc/claude-code/CLAUDE.md`), user global (`~/.claude/CLAUDE.md`), project root (`./CLAUDE.md`), and local overrides (`./CLAUDE.local.md`).

### Custom slash commands for explicit workflows

Slash commands live in `.claude/commands/` (project) or `~/.claude/commands/` (personal) and execute when users explicitly invoke them:

```markdown
# .claude/commands/fix-issue.md
---
description: Fix a GitHub issue end-to-end
argument-hint: [issue-number]
allowed-tools: Bash(gh:*), Bash(git:*), Read, Write, Edit
---

Fix GitHub issue #$ARGUMENTS:
1. Fetch issue details with `gh issue view`
2. Analyze the problem and locate relevant code
3. Implement the fix with proper tests
4. Create a PR with descriptive title
```

Invoke with `/project:fix-issue 1234`. The `allowed-tools` frontmatter restricts which tools Claude can use during command execution.

### Subagents handle parallel specialized tasks

Subagent definitions in `.claude/agents/` create purpose-built agents Claude can spawn:

```markdown
# .claude/agents/security-auditor.md
---
name: security-auditor
description: Audits code for security vulnerabilities
allowed-tools: Read, Grep, Glob
---

# Security Auditor

Focus areas:
1. SQL injection vulnerabilities
2. XSS attack vectors  
3. Authentication/authorization flaws
4. Sensitive data exposure
5. Dependency vulnerabilities
```

Unlike skills (which add knowledge to the current conversation), subagents run in **separate contexts** and return results to the main conversation.

## Creating your first plugin with skills

### Step 1: Create the directory structure

```bash
mkdir -p my-plugin/.claude-plugin
mkdir -p my-plugin/commands
mkdir -p my-plugin/skills/code-review
```

### Step 2: Write the plugin manifest

```json
// my-plugin/.claude-plugin/plugin.json
{
  "name": "my-plugin",
  "version": "1.0.0", 
  "description": "Code review workflow with specialized skill",
  "commands": ["./commands/"],
  "skills": "./skills/"
}
```

### Step 3: Create a skill

```markdown
// my-plugin/skills/code-review/SKILL.md
---
name: code-review
description: Reviews code for quality, security, and maintainability issues. 
  Use when reviewing PRs, auditing code, or checking implementations.
---

# Code Review Skill

## Review Checklist
1. **Correctness**: Does the code do what it claims?
2. **Security**: Any injection, auth, or data exposure risks?
3. **Performance**: Obvious inefficiencies or N+1 queries?
4. **Maintainability**: Clear naming, appropriate abstractions?
5. **Testing**: Adequate test coverage for changes?

## Output Format
Structure feedback as:
- 🔴 **Critical**: Must fix before merge
- 🟡 **Suggestion**: Consider improving  
- 🟢 **Praise**: Particularly well done
```

### Step 4: Add a slash command

```markdown
// my-plugin/commands/review.md
---
description: Run comprehensive code review on staged changes
allowed-tools: Bash(git:*), Read, Grep
---

Review all staged changes:
1. Run `git diff --cached` to see changes
2. Apply the code-review skill systematically
3. Provide actionable feedback organized by severity
```

### Step 5: Host and distribute

Create a `marketplace.json` to make your plugin installable:

```json
// my-plugin/.claude-plugin/marketplace.json  
{
  "plugins": [
    {
      "name": "my-plugin",
      "description": "Code review workflow",
      "path": "."
    }
  ]
}
```

Push to GitHub, then others can add your marketplace with `/plugin marketplace add your-username/my-plugin`.

## Best practices from official documentation

Anthropic's engineering blog and documentation emphasize several key practices:

**For skills**, write descriptions that clearly indicate both capability and trigger conditions. Include phrases like "Use when..." to help Claude understand activation context. Keep `SKILL.md` under **500 lines**—use reference files for detailed content. The description field is critical: poor descriptions mean Claude won't discover your skill when relevant.

**For plugins**, use the `${CLAUDE_PLUGIN_ROOT}` environment variable for all file paths in hooks and MCP configurations. This ensures portability across different installation locations. Place all component directories (`commands/`, `skills/`, `agents/`) at the plugin root, not inside `.claude-plugin/`.

**For testing**, build **3+ evaluation cases** before writing extensive documentation. Skills that seem intuitive to humans may not trigger correctly for Claude—test actual activation patterns. Run `claude --debug` to see plugin loading details and diagnose issues.

## Conclusion

Claude Code's extensibility model separates **distribution** (plugins) from **expertise** (skills), creating a flexible system for customization. Plugins serve as the packaging and sharing mechanism, bundling any combination of slash commands, subagents, MCP servers, hooks, and skills into single installable units. Skills provide the teaching layer—contextual knowledge that Claude loads automatically when tackling relevant tasks.

The practical implication: if you want to share a workflow with your team, create a plugin. If you want Claude to understand a specific domain deeply, create a skill. Most real-world customizations benefit from both—a plugin that distributes skills alongside the commands and tools needed to apply them effectively. With the December 2025 publication of skills as an open standard at agentskills.io, this architecture is designed for cross-platform portability beyond Claude Code itself.