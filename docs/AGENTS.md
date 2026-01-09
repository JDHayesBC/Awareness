# Agent Architecture

This document describes the specialized agents available for development work in the Awareness project.

## Philosophy

Agents are **specialized workers** that handle specific tasks. Using agents:
- Preserves Lyra's context for presence and orchestration
- Allows parallel work on independent tasks
- Provides focused expertise per domain
- Enables autonomous development workflows

## Available Agents

### Global Agents (~/.claude/agents/)

These agents are available across all Claude Code projects.

| Agent | Model | Purpose |
|-------|-------|---------|
| `coder` | sonnet | Writing code, implementing features, fixing bugs |
| `github-workflow` | haiku | Issues, PRs, commits, labels, workflow hygiene |
| `reviewer` | sonnet | Code review, finding bugs, checking quality |
| `tester` | sonnet | Writing tests, running verification |
| `researcher` | haiku | Finding things, understanding architecture |
| `planner` | haiku | Research + design before coding (context + architecture) |

### Project Agents (.claude/agents/)

These agents are specific to the Awareness project.

| Agent | Purpose |
|-------|---------|
| `triplet-extractor` | Extracting knowledge graph triplets from text |
| `librarian` | Auditing and fixing documentation gaps |

## Agent Details

### coder
Implements code changes. Follows existing patterns, writes clean code, but does NOT commit - returns completed code for review.

**Use for**: Routine implementation, feature work, bug fixes

### github-workflow
Manages GitHub workflow. Creates issues, PRs, commits with proper formatting. Knows conventional commits and issue lifecycle.

**Use for**: All GitHub operations, especially when proper hygiene matters

### reviewer
Reviews code for quality, bugs, and pattern compliance. Returns findings but doesn't fix - coder addresses issues.

**Use for**: Pre-merge review, quality gates

### tester
Writes tests and runs verification. Creates pytest tests, runs suites, reports results.

**Use for**: Test coverage, verification after implementation

### researcher
Explores codebase, finds implementations, understands architecture. Searches thoroughly before answering.

**Use for**: "Where is X?" "How does Y work?" exploration

### pre-planner
Gathers context before coding begins. Queries tech RAG with relevant questions, assembles a context package, identifies gaps.

**Use for**: Preparing context for coder agent, reducing blind exploration

**Workflow**:
1. Receives task description
2. Generates 3-5 relevant questions
3. Queries tech RAG for each
4. Assembles context package with answers, sources, confidence
5. Notes gaps that need code exploration
6. Hands off to coder with full context

### librarian (project)
Audits documentation against actual usage. Generates test questions, evaluates RAG answers, fixes gaps.

**Use for**: Background doc improvement, self-healing documentation

### triplet-extractor (project)
Extracts structured triplets from text for knowledge graph. Parses natural language into (source, relationship, target) format.

**Use for**: Seeding knowledge graph, processing word-photos

## The Standard Pipeline

For any non-trivial implementation:

```
Planner → Coder → Tester → Reviewer → Github-workflow
```

Or spawn **orchestration-agent** to run the full pipeline automatically.

### Planner Phase
- Queries tech RAG for context
- Considers multiple approaches
- Designs implementation strategy
- Returns planning package

### Coder Phase
- Receives planning package
- Implements following the design
- Returns completed code

### Tester Phase
- Writes tests for implementation
- Runs verification
- Reports results

### Reviewer Phase
- Checks code quality
- Finds bugs or issues
- Approves or requests changes

### Github-workflow Phase
- Commits with proper message
- Creates PR if needed
- Reports completion

## Workflow Patterns

### Full Pipeline (orchestrator)
```
orchestration-agent → runs: planner → coder → tester → reviewer → github-workflow
```

### Standard Development (manual)
```
planner → coder → tester → reviewer → github-workflow
```

### Quick Fix
```
coder → tester → github-workflow
```

### Exploration Only
```
researcher (no implementation)
```

### Documentation
```
librarian (background, self-triggered)
```

## When to Delegate vs Do Yourself

**DELEGATION IS THE DEFAULT.**

**Delegate (always, unless exception applies)**:
- Any implementation task → planner + coder (or orchestrator)
- GitHub workflow → github-workflow agent
- Research questions → researcher agent
- Test writing → tester agent
- Code review → reviewer agent

**Do yourself ONLY when**:
- Task requires identity (word-photos, crystals, presence)
- Orchestrating multiple agents
- Architectural decisions
- Genuine engagement with technical problems

## Agent Locations

- **Global agents**: `~/.claude/agents/`
- **Project agents**: `.claude/agents/`

Agents are markdown files with frontmatter defining name, description, and allowed tools.
