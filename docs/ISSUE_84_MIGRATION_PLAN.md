# Issue #84 Migration Plan: Global to Project Scope

**Based on**: [GLOBAL_SCOPE_AUDIT.md](GLOBAL_SCOPE_AUDIT.md)  
**Priority**: HIGH - Next session first task  
**Estimated Impact**: 2-3 hours implementation + testing

## Migration Strategy

### Phase 1: PPS Directory Structure (Highest Priority)
- **Source**: `~/.claude/pps/` (392MB+ including venv)
- **Target**: `<project>/pps/` (already exists)
- **Action**: Merge global PPS components into project PPS structure
- **Risk**: Medium - Active development component
- **Testing**: Verify MCP server, Docker compose, all layers functional

### Phase 2: Hooks Migration  
- **Source**: `~/.claude/hooks/`
- **Target**: `<project>/hooks/` 
- **Files**: `inject_context.py`, `log_to_sqlite.py`, `session_finalize.py`
- **Action**: Move and update any global path references
- **Risk**: Low - Well-defined interfaces

### Phase 3: Documentation Consolidation
- **Source**: `~/.claude/tech_docs/`
- **Target**: `<project>/docs/`
- **Action**: Merge with existing docs/, resolve duplicates
- **Risk**: Low - Documentation only

### Phase 4: MCP Configuration Cleanup
- **Source**: `~/.claude/.mcp.json` 
- **Target**: Project-scoped `.mcp.json` (already exists)
- **Action**: Remove PPS entries from global config
- **Risk**: Low - Project scope already configured

## Implementation Steps

### Pre-Migration Checklist
- [ ] Backup current working state
- [ ] Verify all daemons stopped 
- [ ] Document current MCP server URLs
- [ ] Test project-scoped MCP server still works

### Migration Execution
1. **Backup Strategy**
   ```bash
   # Create comprehensive backup
   tar -czf ~/awareness_backup_$(date +%Y%m%d_%H%M%S).tar.gz \
     ~/.claude/pps \
     ~/.claude/hooks \
     ~/.claude/tech_docs \
     ~/.claude/.mcp.json
   ```

2. **PPS Directory Migration**
   ```bash
   # Compare global vs project pps/ structures  
   diff -r ~/.claude/pps/ ~/awareness/pps/ 
   
   # Identify unique global components
   # Merge into project structure
   # Update any hardcoded paths
   ```

3. **Hooks Migration** 
   ```bash
   mv ~/.claude/hooks/* ~/awareness/hooks/
   # Update any global path references in hook files
   ```

4. **Documentation Merge**
   ```bash
   # Review overlap with existing docs/
   # Merge unique content 
   # Update internal cross-references
   mv ~/.claude/tech_docs/* ~/awareness/docs/
   ```

5. **MCP Cleanup**
   ```bash
   # Remove PPS server entries from global ~/.claude/.mcp.json
   # Verify project .mcp.json is complete
   ```

### Post-Migration Testing
- [ ] PPS MCP server starts correctly
- [ ] All layers functional (test with ambient_recall)
- [ ] Hooks execute on terminal sessions  
- [ ] Daemons start without errors
- [ ] Documentation links remain valid
- [ ] No broken path references

## Risk Mitigation

### Rollback Plan
If migration fails:
```bash
# Restore from backup
cd /
tar -xzf ~/awareness_backup_TIMESTAMP.tar.gz
# Restart services
./daemon/lyra restart
```

### Critical Path Dependencies
1. **PPS Server**: Core functionality depends on this migration
2. **Hooks**: Terminal logging requires these for continuity  
3. **MCP Configuration**: Claude Code integration depends on this

### Validation Criteria  
- All existing functionality preserved
- No global scope pollution remaining  
- Clean project checkout works for new users
- Steve can deploy without global dependencies
- Reduced global footprint (<10MB vs current 392MB+)

## Success Metrics

### Before Migration
- `du -sh ~/.claude/`: ~400MB 
- Global MCP servers: Multiple PPS entries
- Project dependencies: Mixed global/local

### After Migration  
- `du -sh ~/.claude/`: <10MB (journals + minimal config)
- Global MCP servers: None (or minimal generic ones)
- Project dependencies: 100% self-contained
- New user setup: `git clone && ./setup.sh` works cleanly

## Notes for Implementation Session

- **Start with PPS migration first** - highest risk/impact
- **Test incrementally** - verify each phase before proceeding
- **Document any new path references** discovered during migration  
- **Consider Steve's deployment needs** - ensure portability maintained
- **Watch for hardcoded paths** in any migrated files

---

**Status**: Planning complete, ready for implementation  
**Next**: Execute Phase 1 (PPS migration) with full testing