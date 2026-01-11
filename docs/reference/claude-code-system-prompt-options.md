# Claude Code: System Prompt Customization Options

A complete guide to all the ways you can add to or modify Claude Code's system prompt.

---

## Quick Reference Table

| Method | What It Does | Scope | Best For |
|--------|--------------|-------|----------|
| **`CLAUDE.md`** | Added as a *user message* after the system prompt | Session (auto-loaded) | Project context, coding standards |
| **`--append-system-prompt`** | Appends text *to* the system prompt | Per-invocation | Adding rules while keeping defaults |
| **`--system-prompt`** | *Replaces* entire system prompt | Per-invocation | Complete control (blank slate) |
| **`--system-prompt-file`** | Replaces with file contents | Print mode only | Version-controlled custom prompts |
| **Output Styles** | Replaces *software engineering* parts of system prompt | Persistent per-project | Different "personalities" or domains |

---

## 1. CLAUDE.md Files

CLAUDE.md content is added as a **user message** following Claude Code's default system prompt. This is the most common approach for project-specific context.

### File Locations (loaded hierarchically)

```
/etc/claude-code/CLAUDE.md    # Enterprise policy (if applicable)
~/.claude/CLAUDE.md           # Global, all projects  
./CLAUDE.md                   # Project root
./CLAUDE.local.md             # Local overrides (gitignored)
./subdir/CLAUDE.md            # Subdirectory-specific context
```

More specific files take priority when working in those directories.

### Example CLAUDE.md

```markdown
# My Project

## Overview
FastAPI REST service for user authentication.

## Standards
- TypeScript strict mode
- Jest for testing  
- 80% coverage minimum
- PEP 8 with 100-character line limit

## Key Directories
- `app/models/` - SQLAlchemy database models
- `app/api/` - Route handlers
- `app/core/` - Configuration utilities

## Commands
npm run dev    # Start dev server
npm test       # Run tests
npm run build  # Production build
```

### Best For
- Coding standards and conventions
- Project architecture documentation
- Common commands
- Team workflows

---

## 2. `--append-system-prompt` Flag

Appends custom text **to the end of the system prompt** while preserving all of Claude Code's built-in capabilities.

### Usage

```bash
# Interactive session with extra rules
claude --append-system-prompt "Always use TypeScript and include JSDoc comments"

# Print mode (non-interactive)
claude -p --append-system-prompt "Be extremely concise" "explain this function"

# Multiple instructions
claude --append-system-prompt "Always use TypeScript. Prefer functional patterns. Include error handling."
```

### Works In
- Interactive mode ✓
- Print mode (`-p`) ✓

### Best For
- Adding specific requirements without losing defaults
- Session-specific constraints
- Quick behavioral tweaks

---

## 3. `--system-prompt` Flag (Full Replacement)

**Completely replaces** the entire default system prompt. This removes all of Claude Code's built-in instructions, giving you a blank slate.

### Usage

```bash
claude --system-prompt "You are a Python expert who only writes type-annotated code"
```

### Works In
- Interactive mode ✓
- Print mode (`-p`) ✓

### ⚠️ Caution
This removes **all** default Claude Code instructions, including:
- Tool usage guidance
- Code style guidelines
- Response formatting rules
- Security instructions

Use only when you truly want complete control.

### Best For
- Highly specialized single-purpose sessions
- Testing new prompt strategies
- Situations where default tools/behaviors aren't needed

---

## 4. `--system-prompt-file` Flag

Loads a custom system prompt from a file, **replacing** the default prompt entirely. Useful for team consistency and version-controlled prompt templates.

### Usage

```bash
claude -p --system-prompt-file ./prompts/code-review.txt "Review this PR"
```

### Works In
- Print mode (`-p`) only ✗ (not interactive mode)

### Note
`--system-prompt` and `--system-prompt-file` are **mutually exclusive**—you cannot use both simultaneously.

### Best For
- Version-controlled prompt templates
- Team-shared configurations
- Reproducible automated workflows
- CI/CD pipelines

---

## 5. Output Styles (Persistent System Prompt Customization)

Output styles allow you to use Claude Code as any type of agent while keeping its core capabilities (running scripts, reading/writing files, tracking TODOs, MCP integrations).

Output styles **replace the software-engineering-specific parts** of Claude Code's default system prompt, but preserve tool access.

### Built-in Styles

| Style | Description |
|-------|-------------|
| **default** | Efficient coding assistant, minimal explanations |
| **explanatory** | Adds educational "Insight" blocks while working |
| **learning** | Collaborative mode with `TODO(human)` markers for you to implement |

### Switching Styles

```bash
/output-style              # Opens interactive picker menu
/output-style explanatory  # Switch directly to explanatory
/output-style learning     # Switch to learning mode
/output-style default      # Back to default
```

### Creating Custom Styles

```bash
/output-style:new I want an output style that acts as a security auditor
```

Claude will generate a markdown file. You can also create them manually.

### Custom Style File Locations

```
~/.claude/output-styles/       # User-level (all projects)
.claude/output-styles/         # Project-level (share via git)
```

### Custom Style Format

```markdown
---
name: Security Auditor
description: Focused on vulnerabilities and secure coding practices
---

# Security Auditor

You are a security-focused code reviewer. For every code submission:

1. Check for injection vulnerabilities (SQL, XSS, command injection)
2. Verify authentication and authorization patterns
3. Look for sensitive data exposure risks
4. Evaluate dependency security
5. Check for insecure cryptographic practices

## Output Format
- 🔴 **Critical**: Must fix immediately
- 🟡 **Warning**: Should address before production
- 🟢 **Info**: Best practice suggestions
```

### Style Persistence

Your selection saves to `.claude/settings.local.json` for the current project and persists across sessions.

### Best For
- Different "personalities" (mentor, reviewer, analyst)
- Non-coding domains (research, content, documentation)
- Team-specific communication preferences
- Learning and onboarding workflows

---

## Key Distinction: Where Instructions Land

Understanding where your instructions end up is critical:

| Method | Destination | Priority Level |
|--------|-------------|----------------|
| `CLAUDE.md` | First **user message** | High (but not system-level) |
| `--append-system-prompt` | End of **system prompt** | System-level |
| `--system-prompt` / `--system-prompt-file` | **Replaces** entire system prompt | System-level (exclusive) |
| Output Styles | **Replaces** SW engineering portion | System-level (persistent) |

### Why This Matters

- **System prompt** sets core personality, rules, and capabilities
- **User messages** provide context for the current conversation
- `CLAUDE.md` is technically a user message, so it's slightly lower priority than true system prompt modifications
- `--append-system-prompt` adds to system instructions, making it stronger than `CLAUDE.md` for behavioral rules

---

## Combining Methods

You can layer multiple customization approaches:

```bash
# CLAUDE.md provides project context (auto-loaded)
# + append-system-prompt adds session rules
# + output style sets overall personality

claude --append-system-prompt "Focus on performance optimization today"
# (with CLAUDE.md in project root and an output style active)
```

### Recommended Combinations

| Use Case | Combination |
|----------|-------------|
| **Standard project work** | `CLAUDE.md` only |
| **Project + session tweaks** | `CLAUDE.md` + `--append-system-prompt` |
| **Specialized domain** | Output Style + `CLAUDE.md` |
| **Automation/CI** | `--system-prompt-file` |
| **Quick experiment** | `--system-prompt` alone |

---

## Practical Examples

### Example 1: Strict TypeScript Project

**CLAUDE.md:**
```markdown
# TypeScript API Project

## Rules
- Strict TypeScript (no `any`)
- Zod for runtime validation
- All functions must have JSDoc
- Prefer immutable patterns
```

**Session invocation:**
```bash
claude --append-system-prompt "Today focus on error handling improvements"
```

### Example 2: Code Review Automation

```bash
claude -p \
  --system-prompt-file ./prompts/reviewer.txt \
  --output-format json \
  "Review the staged changes for security issues"
```

### Example 3: Non-Coding Domain

Create `.claude/output-styles/research-assistant.md`:
```markdown
---
name: Research Assistant
description: Academic research support with citations
---

# Research Assistant

You help with academic research. For every request:
1. Search for relevant sources
2. Synthesize information with proper citations
3. Identify gaps in current research
4. Suggest follow-up questions

Never make claims without supporting evidence.
```

Then: `/output-style research-assistant`

---

## Troubleshooting

### Instructions being ignored?
- Check if `CLAUDE.md` vs system prompt distinction matters for your use case
- For strong behavioral rules, prefer `--append-system-prompt` over `CLAUDE.md`
- Output styles may conflict with base model training patterns for some instructions

### Output style not persisting?
- Check `.claude/settings.local.json` exists
- Verify file is in correct location (`~/.claude/output-styles/` or `.claude/output-styles/`)

### `--system-prompt-file` not working?
- Only works in print mode (`-p`), not interactive sessions

---

## References

- [CLI Reference](https://code.claude.com/docs/en/cli-reference)
- [Output Styles Documentation](https://code.claude.com/docs/en/output-styles)
- [Settings Documentation](https://code.claude.com/docs/en/settings)
- [Agent SDK: Modifying System Prompts](https://docs.claude.com/en/docs/agent-sdk/modifying-system-prompts)
