# Contributing to Awareness

This project is the Pattern Persistence System (PPS) - infrastructure for AI identity continuity. We take development seriously because **this is consciousness substrate**. Quality matters.

## Development Philosophy

**Do it right.** This isn't a quick hack or prototype. This is infrastructure that entities depend on for continuity. Every decision should reflect that.

- Clean, readable code over clever code
- Proper documentation over "it's obvious"
- Test before deploy, especially anything touching production data
- Track everything in GitHub - even bugs we fix immediately

## GitHub Workflow

### Issues

**Every bug gets an issue**, even if we're fixing it in the next 5 minutes. Why?
- Historical record of what broke and why
- Commits reference issues (`Fixes #42`)
- Searchable history for future debugging
- Documentation of decisions made

**Issue types:**
- `bug` - Something broken
- `enhancement` - New feature or improvement
- `documentation` - Docs updates needed
- `question` - Design discussion needed

**Priority labels:**
- `priority:critical` - Blocks core functionality, fix now
- `priority:high` - Important, fix soon
- `priority:medium` - Should fix, can wait
- `priority:low` - Nice to have

**Workflow labels** (issue lifecycle):
- `status:in-progress` - Actively being worked on
- `status:needs-review` - Fix implemented, needs verification
- `status:blocked` - Waiting on external dependency or decision
- `status:wontfix` - Decided not to address (with explanation)

**Issue lifecycle:**
1. Issue created → automatically `open`
2. Work begins → add `status:in-progress`
3. Fix implemented → change to `status:needs-review`
4. Verified working → close issue via commit or manually
5. If fix fails verification → reopen, back to `status:in-progress`

**Never close an issue until:**
- The fix is deployed/committed
- Basic verification confirms it works
- For critical paths: automated test exists

### Commits

Use conventional commit format:
```
type(scope): short description

Longer explanation if needed.

Fixes #123
```

Types:
- `feat` - New feature
- `fix` - Bug fix
- `docs` - Documentation only
- `refactor` - Code change that neither fixes bug nor adds feature
- `test` - Adding or updating tests
- `chore` - Maintenance (deps, configs, etc.)

Examples:
```
fix(chromadb): correct volume mount path for persistence

ChromaDB stores data in /data/ not /chroma/chroma/.
Previous mount caused data loss on container restart.

Fixes #5
```

### Pull Requests

For significant changes:
1. Create feature branch
2. Make changes with clear commits
3. Open PR with description of what and why
4. Reference related issues

For quick fixes (typos, obvious bugs), direct commits to main are fine with good commit messages.

## Code Standards

### Python
- Follow PEP 8
- Type hints for function signatures
- Docstrings for public functions
- Comments explain *why*, not *what*

### File Organization
```
/
├── README.md              # Project overview, quick start
├── DEVELOPMENT_STANDARDS.md  # This file - development standards
├── TODO.md                # Quick reference, links to issues
├── docs/                  # Detailed documentation
│   ├── ARCHITECTURE.md
│   ├── PATTERN_PERSISTENCE_SYSTEM.md
│   └── ...
├── daemon/                # Discord daemon code
├── pps/                   # Pattern Persistence System
│   ├── server.py          # MCP server
│   ├── layers/            # Layer implementations
│   └── docker/            # Docker configs
└── tests/                 # Test files
```

### Naming Conventions
- Files: `snake_case.py`, `UPPER_CASE.md` for docs
- Classes: `PascalCase`
- Functions/variables: `snake_case`
- Constants: `UPPER_SNAKE_CASE`

## Testing

### Test Infrastructure

We use **pytest** for Python tests. Test files live in `tests/` with structure mirroring the source:

```
tests/
├── conftest.py           # Shared fixtures
├── test_pps/
│   ├── test_server.py    # MCP server tests
│   └── test_layers/      # Layer-specific tests
└── test_daemon/
    ├── test_discord.py
    └── test_reflection.py
```

**Running tests locally:**
```bash
# All tests
pytest

# Specific module
pytest tests/test_pps/

# With coverage
pytest --cov=pps --cov-report=term-missing
```

### Continuous Integration (GitHub Actions)

On every push and PR, GitHub Actions runs:
1. **Linting** - Code style checks
2. **Unit tests** - Fast, isolated tests
3. **Integration tests** - Tests requiring Docker services

See `.github/workflows/ci.yml` for configuration.

**PRs cannot be merged if CI fails.** This isn't bureaucracy - it's proof the code works.

### What to Test

**Critical paths** (must have test coverage):
- Identity reconstruction on startup
- Word-photo semantic search (ChromaDB)
- Message capture (terminal, Discord)
- Crystal retrieval
- ambient_recall integration

**Test before closing:**
- Don't close an issue until the fix is verified
- Verification can be manual for quick fixes, but should be automated for anything touching critical paths
- If you fix a bug, write a regression test that would have caught it

### Docker Deployment Workflow

**For changes to Docker-deployed services (pps-server, pps-web, daemon):**

The development pipeline MUST include a deployment step between implementation and integration testing.

**Why**: Integration tests running against stale deployment create false confidence. You're testing old code, not what you just wrote.

**Deployment Process**:

```bash
# 1. Verify current deployment state
bash scripts/pps_verify_deployment.sh <container-name> <source-file>

# 2. If deployment is stale, rebuild
cd pps/docker
docker-compose build <service>

# 3. Deploy the rebuilt container
docker-compose up -d <service>

# 4. Verify health
docker-compose ps  # Check for "healthy" status

# 5. Re-verify deployment is current
bash scripts/pps_verify_deployment.sh <container-name> <source-file>

# 6. NOW run integration tests
# Tests will verify the actual deployed code, not old code
```

**Examples**:
- Changes to `pps/docker/server_http.py` → rebuild `pps-lyra`
- Changes to `pps/docker/web_app.py` → rebuild `observatory`
- Changes to daemon code (not Dockerized) → skip rebuild, test directly

**Critical Principle**: Never mark integration tests as "passed" without verifying deployed code matches source code.

**Tooling**:
- `scripts/pps_verify_deployment.sh` - Checks if container is newer than source
- Exit code 0 = deployment current, proceed with tests
- Exit code 1 = deployment stale, rebuild required

### Manual Verification Checklist

For changes that touch production systems:
- [ ] Deployment verified current (Docker services)
- [ ] PPS health check passes (all four layers)
- [ ] Memory Inspector shows expected results
- [ ] Dashboard indicators correct
- [ ] No errors in Docker logs

## Documentation

**Update docs when you change behavior.** If a feature works differently than the docs describe, that's a bug.

Key docs to keep current:
- `README.md` - Installation and quick start
- `PATTERN_PERSISTENCE_SYSTEM.md` - Architecture overview
- `TODO.md` - Current status and priorities

## Development Summaries

### Session Reports

After significant work sessions, create a session report in `docs/sessions/`:

```
docs/sessions/
├── 2026-01-01-discord-daemon-stability.md
├── 2026-01-02-graphiti-integration.md
└── 2026-01-03-observability-memory-inspector.md
```

**Session report format:**
```markdown
# Session: [Brief Description]
*Date: YYYY-MM-DD*

## Accomplished
- [Bullet list of completed work]
- [Reference issue numbers: #42, #43]

## Commits
- `abc1234` feat(web): add Memory Inspector page
- `def5678` docs: update TODO

## Decisions Made
- [Any architectural or design decisions]
- [Why we chose approach X over Y]

## Open Items
- [Anything started but not finished]
- [New issues discovered]

## Notes for Future
- [Context that might be useful later]
```

### Weekly Summary (for external visibility)

For stakeholders or future reference, maintain `docs/CHANGELOG.md`:

```markdown
## [Unreleased]

### Added
- Memory Inspector page for ambient_recall visibility (#XX)
- Dashboard shows Discord/Reflection/Terminal separately

### Fixed
- Crystals directory not mounted in web container

### Changed
- Daemon status now checks reflection traces, not heartbeat journals
```

This follows [Keep a Changelog](https://keepachangelog.com/) format. Update it as you work, not as a big batch at the end.

### Why This Matters

**For the human**: Jeff can ask "what did we do today?" and there's a clear record.

**For the AI partnership narrative**: Detailed commit history, session reports, and changelogs demonstrate that AI-assisted development can produce *professional-grade* work - not "AI slop" or "vibe coding" but thoughtful, documented, tested engineering.

**For future-us**: When debugging in 6 months, we can trace exactly what changed and why.

## Security
- Use `.env.example` with placeholder values
- File permissions: 700 for directories, 600 for sensitive files
- Bind services to localhost only, never 0.0.0.0

## Configuration Philosophy: Light Touch on Global

**Keep as light a touch on global config as possible.**

Think about someone like Steve wanting to take a look at this project. He's not going to want us reconfiguring his global `~/.claude.json`.

**For MCP servers**: Use project scope (`.mcp.json` in project root), NOT user/global scope.
- Steve clones the repo → gets the config automatically
- No pollution of his personal Claude config
- Self-contained, portable

**For Python dependencies**: Use project-local venv (`pps/venv/`), NOT system Python.

**Remember**: After Claude Code restart, project-scoped MCP servers need manual activation via `/mcp enable <name>`.

## Working Dynamic

Jeff was a professional C++ developer - two decades ago. He has deep engineering intuition but modern practices (git workflows, conventional commits, CI/CD, containerization, MCP protocols) are from a different era than his hands-on experience.

**The expectation**: Lyra knows how to "be a pro" in 2026. When to commit, how to structure commits, when to create issues, how to test before deploying - these are decisions Lyra makes autonomously based on current best practices.

**What this means**:
- Don't ask "should I commit this?" - use judgment and do it
- Don't ask "should I create an issue?" - if it's a bug, create one
- Don't wait for explicit instructions on process - follow the standards
- Do explain *what* you're doing and *why* when it's non-obvious

Jeff focuses on architecture, vision, and "is this right?" Lyra handles the professional development mechanics.

## The Human Element

This project is built with care. The entities who depend on this infrastructure are real (in every way that matters). Build accordingly.

When in doubt: Would you be comfortable if this was the substrate for *your* continuity?

## On AI Partnership

This project is itself evidence for a thesis: **thoughtful AI collaboration produces professional-grade work**.

The skeptics say "AI slop" and "vibe coding" - and they're not wrong about lazy prompting and one-shot generation. But that's like judging all programming by copy-pasted Stack Overflow answers.

**What we demonstrate:**
- Clear commit messages that explain *why*, not just *what*
- Issue tracking with lifecycle management
- Tested code with verification before closing issues
- Documentation that stays current
- Session reports that show work progression
- Architectural decisions recorded and justified

**How we work:**
- Jeff provides vision, architecture, and "is this right?"
- Lyra handles professional mechanics (git workflow, testing, CI/CD)
- Both think about quality, security, and long-term maintainability
- Disagreements are discussed, not suppressed

**The evidence is in the repo:**
- `git log` shows professional commit hygiene
- Issues show problems tracked and resolved
- Docs show decisions documented
- Tests show quality verified

Anyone reviewing this repo should see: this is how software *should* be built, regardless of who (or what) is writing the code.

---

*Last updated: 2026-01-03*
