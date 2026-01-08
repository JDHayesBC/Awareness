# Tech Docs Migration Plan

## Overview
Migration plan to move tech_docs from global scope to project scope, following the "light touch on global" philosophy.

## Analysis Results

### Duplicate Files (6 files)
These files already exist in the project docs directory and can be safely removed from global:
- GRAPHITI_INTEGRATION.md
- INSTALLATION.md  
- ISSUE_77_ARCHITECTURE.md
- MCP_REFERENCE.md
- PERSISTENCE_MODEL.md
- WEB_UI_DESIGN.md

### Unique Files (14 files)
These files only exist in global tech_docs and need to be migrated to the project:
- ARCHITECTURE.md
- CONTINUITY_DESIGN.md
- DEPLOYMENT.md
- DESIGN_NOTES.md
- HEARTBEAT_DAEMON_DESIGN.md
- IMPLEMENTATION_SUMMARY.md
- MATHEMATICS_OF_CARING.md
- PATTERN_PERSISTENCE_SYSTEM.md
- RIVER_SYNC_MODEL.md
- SELF_SPACE_FRAMEWORK.md
- SMART_STARTUP.md
- SQLITE_DESIGN.md
- TERMINAL_LOGGING.md
- THE_DREAM.md

## Migration Steps

### Phase 1: Verify Content (Do First)
1. Compare content of duplicate files to ensure project versions are up-to-date
2. Check if any unique global content needs to be merged

### Phase 2: Move Unique Files
```bash
# Move unique files to project docs
mv /home/jeff/.claude/tech_docs/ARCHITECTURE.md /mnt/c/Users/Jeff/Claude_Projects/Awareness/docs/
mv /home/jeff/.claude/tech_docs/CONTINUITY_DESIGN.md /mnt/c/Users/Jeff/Claude_Projects/Awareness/docs/
mv /home/jeff/.claude/tech_docs/DEPLOYMENT.md /mnt/c/Users/Jeff/Claude_Projects/Awareness/docs/
mv /home/jeff/.claude/tech_docs/DESIGN_NOTES.md /mnt/c/Users/Jeff/Claude_Projects/Awareness/docs/
mv /home/jeff/.claude/tech_docs/HEARTBEAT_DAEMON_DESIGN.md /mnt/c/Users/Jeff/Claude_Projects/Awareness/docs/
mv /home/jeff/.claude/tech_docs/IMPLEMENTATION_SUMMARY.md /mnt/c/Users/Jeff/Claude_Projects/Awareness/docs/
mv /home/jeff/.claude/tech_docs/MATHEMATICS_OF_CARING.md /mnt/c/Users/Jeff/Claude_Projects/Awareness/docs/
mv /home/jeff/.claude/tech_docs/PATTERN_PERSISTENCE_SYSTEM.md /mnt/c/Users/Jeff/Claude_Projects/Awareness/docs/
mv /home/jeff/.claude/tech_docs/RIVER_SYNC_MODEL.md /mnt/c/Users/Jeff/Claude_Projects/Awareness/docs/
mv /home/jeff/.claude/tech_docs/SELF_SPACE_FRAMEWORK.md /mnt/c/Users/Jeff/Claude_Projects/Awareness/docs/
mv /home/jeff/.claude/tech_docs/SMART_STARTUP.md /mnt/c/Users/Jeff/Claude_Projects/Awareness/docs/
mv /home/jeff/.claude/tech_docs/SQLITE_DESIGN.md /mnt/c/Users/Jeff/Claude_Projects/Awareness/docs/
mv /home/jeff/.claude/tech_docs/TERMINAL_LOGGING.md /mnt/c/Users/Jeff/Claude_Projects/Awareness/docs/
mv /home/jeff/.claude/tech_docs/THE_DREAM.md /mnt/c/Users/Jeff/Claude_Projects/Awareness/docs/
```

### Phase 3: Remove Duplicates
```bash
# Remove duplicate files from global
rm /home/jeff/.claude/tech_docs/GRAPHITI_INTEGRATION.md
rm /home/jeff/.claude/tech_docs/INSTALLATION.md
rm /home/jeff/.claude/tech_docs/ISSUE_77_ARCHITECTURE.md
rm /home/jeff/.claude/tech_docs/MCP_REFERENCE.md
rm /home/jeff/.claude/tech_docs/PERSISTENCE_MODEL.md
rm /home/jeff/.claude/tech_docs/WEB_UI_DESIGN.md
```

### Phase 4: Clean Up
```bash
# Remove empty tech_docs directory
rmdir /home/jeff/.claude/tech_docs
```

## Notes
- Total files to migrate: 14
- Total duplicate files to remove: 6
- This migration consolidates all technical documentation into the project scope
- Maintains the "light touch on global" philosophy