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

Before merging to main:
- Run existing tests
- Manually verify core functionality
- For PPS changes: check all four layers via health endpoint
- For daemon changes: verify Discord connectivity

Critical paths that must always work:
- Identity reconstruction on startup
- Word-photo semantic search
- Terminal/Discord message capture
- Summary retrieval

## Documentation

**Update docs when you change behavior.** If a feature works differently than the docs describe, that's a bug.

Key docs to keep current:
- `README.md` - Installation and quick start
- `PATTERN_PERSISTENCE_SYSTEM.md` - Architecture overview
- `TODO.md` - Current status and priorities

## Security

- Never commit credentials (`.env` files, tokens, API keys)
- Use `.env.example` with placeholder values
- File permissions: 700 for directories, 600 for sensitive files
- Bind services to localhost only, never 0.0.0.0

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

---

*Last updated: 2026-01-02*
