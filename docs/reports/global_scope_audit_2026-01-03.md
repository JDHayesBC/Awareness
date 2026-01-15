# Global Scope Audit - Issue #84

**Date**: 2026-01-07  
**Auditor**: Lyra (autonomous reflection)  
**Issue**: https://github.com/JDHayesBC/Awareness/issues/84

## Summary

Audit of `~/.claude/` directory reveals **major violations** of the "Configuration Philosophy: Light Touch on Global" principle established in DEVELOPMENT_STANDARDS.md. The global directory contains extensive project-specific code, documentation, and dependencies that should be project-scoped.

## Findings

### ❌ Major Violations (Should Be Moved)

1. **Python Virtual Environment (392MB)**
   - Location: `/home/jeff/.claude/pps/venv/`
   - **Problem**: Full Python venv with project dependencies in global space
   - **Solution**: Move to project-local `pps/venv/` directory

2. **Pattern Persistence System (PPS) Project Code**
   - Location: `/home/jeff/.claude/pps/`
   - **Problem**: Entire project/application in global scope including:
     - Source code (layers/, web/, docker/, etc.)
     - Deployment scripts 
     - Terminal logging functionality
     - Docker configurations
   - **Solution**: Move entire `pps/` directory to project scope

3. **Project-Specific Hooks**
   - Location: `/home/jeff/.claude/hooks/`
   - Contains: `inject_context.py`, `log_to_sqlite.py`, `session_finalize.py`
   - **Problem**: These hooks are PPS-specific, not general-purpose
   - **Solution**: Move to `hooks/` in project directory

4. **Technical Documentation Directory**
   - Location: `/home/jeff/.claude/tech_docs/`
   - Contains 20+ markdown files: `PATTERN_PERSISTENCE_SYSTEM.md`, `GRAPHITI_INTEGRATION.md`, etc.
   - **Problem**: Project-specific documentation in global space
   - **Solution**: Move to `docs/` in project directory

5. **MCP Configuration with Hardcoded Paths**
   - Location: `/home/jeff/.claude/.mcp.json`
   - Contains hardcoded paths to `/mnt/c/Users/Jeff/Claude_Projects/Awareness/`
   - **Problem**: Project-specific MCP servers in global config
   - **Solution**: Move to project-scoped `.mcp.json`

### ✅ Appropriate for Global

- `/home/jeff/.claude/CLAUDE.md` - minimal global instructions
- `/home/jeff/.claude/journals/` - cross-project journals (if applicable)

## Impact Assessment

**For Steve/New Users**: Current setup would pollute their global Claude configuration with PPS-specific settings. A clean checkout should be self-contained.

**Storage**: 392MB+ in global config violates "light touch" principle.

**Maintenance**: Changes to PPS project scattered across global and project scopes.

## Recommended Actions

1. **Immediate**: Create migration plan for moving components to project scope
2. **Priority**: Start with `pps/venv/` (largest violator) and `pps/` directory
3. **Testing**: Ensure all functionality preserved after migration
4. **Documentation**: Update any references to old paths

## Next Steps

This audit provides the foundation for Issue #84 remediation. Recommend creating specific sub-issues for each major component migration to track progress systematically.

---

**Status**: Audit Complete  
**Next**: Implementation planning and execution