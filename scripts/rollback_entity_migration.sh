#!/bin/bash
# Rollback script for entity migration
# Run this if Claude Code restart breaks PPS or identity loading

echo "=== Entity Migration Rollback ==="
echo ""

# Step 1: Remove ENTITY_PATH from MCP config
echo "Step 1: Reverting MCP config..."
python3 -c "
import json
with open('/home/jeff/.claude.json', 'r') as f:
    config = json.load(f)
if 'ENTITY_PATH' in config.get('projects', {}).get('/home/jeff/.claude', {}).get('mcpServers', {}).get('pps', {}).get('env', {}):
    del config['projects']['/home/jeff/.claude']['mcpServers']['pps']['env']['ENTITY_PATH']
    with open('/home/jeff/.claude.json', 'w') as f:
        json.dump(config, f, indent=2)
    print('  ✓ Removed ENTITY_PATH from MCP config')
else:
    print('  - ENTITY_PATH not found (already clean)')
"

# Step 2: Revert global CLAUDE.md to use ~/.claude paths
echo ""
echo "Step 2: Reverting CLAUDE.md paths..."
sed -i 's|/mnt/c/Users/Jeff/Claude_Projects/Awareness/entities/lyra|/home/jeff/.claude|g' /home/jeff/.claude/CLAUDE.md
echo "  ✓ Reverted paths in ~/.claude/CLAUDE.md"

echo ""
echo "=== Rollback Complete ==="
echo ""
echo "Now restart Claude Code again."
echo "PPS will use ~/.claude (the old location where files still exist)."
