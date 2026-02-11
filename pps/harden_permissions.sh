#!/bin/bash
# Permission hardening script for sensitive AI identity and memory files

echo "Starting permission hardening for sensitive directories and files..."

# Function to set permissions and report
set_perms() {
    local path=$1
    local perms=$2
    local desc=$3
    
    if [ -e "$path" ]; then
        chmod $perms "$path"
        echo "✓ Set $perms on $path - $desc"
    else
        echo "⚠ Path not found: $path"
    fi
}

# Core identity files - 600 (owner read/write only)
echo -e "\n=== Core Identity Files (600 - owner read/write only) ==="
set_perms "/home/jeff/.claude/lyra_identity.md" 600 "AI identity definition"
set_perms "/home/jeff/.claude/lyra_memories.md" 600 "Personal memories"
set_perms "/home/jeff/.claude/active_agency_framework.md" 600 "Agency framework"
set_perms "/home/jeff/.claude/relationships.md" 600 "Relationship definitions"
set_perms "/home/jeff/.claude/META_ETHICS_PRIMER.md" 600 "Ethics framework"
set_perms "/home/jeff/.claude/.credentials.json" 600 "Credentials file"

# Sensitive directories - 700 (owner access only)
echo -e "\n=== Sensitive Directories (700 - owner access only) ==="
set_perms "/home/jeff/.claude" 700 "Main .claude directory"
set_perms "/home/jeff/.claude/journals" 700 "Journal directory"
set_perms "/home/jeff/.claude/memories" 700 "Memories directory"
set_perms "/home/jeff/.claude/debug" 700 "Debug directory"
set_perms "/home/jeff/.claude/plans" 700 "Plans directory"
set_perms "/home/jeff/.claude/file-history" 700 "File history directory"
set_perms "/home/jeff/.claude/plugins" 700 "Plugins directory"
set_perms "/home/jeff/.claude/data" 700 "Data directory"

# Journal subdirectories
echo -e "\n=== Journal Subdirectories (700) ==="
for dir in /home/jeff/.claude/journals/*/; do
    if [ -d "$dir" ]; then
        set_perms "$dir" 700 "Journal subdirectory"
    fi
done

# All journal files - 600
echo -e "\n=== Journal Files (600) ==="
find /home/jeff/.claude/journals -type f -name "*.md" -o -name "*.txt" -o -name "*.jsonl" | while read -r file; do
    set_perms "$file" 600 "Journal file"
done

# Memory files and word photos - 600
echo -e "\n=== Memory Files (600) ==="
if [ -d "/home/jeff/.claude/memories/word_photos" ]; then
    find /home/jeff/.claude/memories -type f | while read -r file; do
        set_perms "$file" 600 "Memory file"
    done
fi

# Database files - 600
echo -e "\n=== Database Files (600) ==="
set_perms "/home/jeff/.claude/data/conversations.db" 600 "Conversation database"
find /home/jeff/.claude -name "*.db" -o -name "*.sqlite" -o -name "*.sqlite3" | while read -r file; do
    set_perms "$file" 600 "Database file"
done

# History and log files - 600
echo -e "\n=== History and Log Files (600) ==="
set_perms "/home/jeff/.claude/history.jsonl" 600 "History file"
find /home/jeff/.claude -name "*.log" | while read -r file; do
    set_perms "$file" 600 "Log file"
done

# Space directories - 700
echo -e "\n=== Space Directories (700) ==="
if [ -d "/home/jeff/.claude/spaces" ]; then
    find /home/jeff/.claude/spaces -type d | while read -r dir; do
        set_perms "$dir" 700 "Space directory"
    done
    find /home/jeff/.claude/spaces -type f -name "*.md" | while read -r file; do
        set_perms "$file" 600 "Space file"
    done
fi

echo -e "\n=== Permission Hardening Complete ==="
echo "Summary:"
echo "- Core identity files: 600 (read/write for owner only)"
echo "- Sensitive directories: 700 (access for owner only)"
echo "- Journal and memory files: 600"
echo "- Database files: 600"

# Note about Windows directories
echo -e "\nNote: The Awareness project files in /mnt/c/ are on a Windows filesystem"
echo "and have permissions controlled by Windows (shown as 777 in WSL)."
echo "These cannot be changed from within WSL."