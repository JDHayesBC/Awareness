#!/bin/bash
# Read Recent Discord Journals
# Display recent Discord journal entries for startup context
#
# Usage: ./read_discord_journal.sh [N]
#   N    Number of recent days to read (default: 3)
#
# Reads Discord JSONL journal entries and formats for reading

set -e

# Configuration
JOURNAL_PATH="${JOURNAL_PATH:-/home/jeff/.claude/journals/discord}"
NUM_DAYS="${1:-3}"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
PURPLE='\033[0;35m'
NC='\033[0m'

echo "==================================="
echo "Discord Journal Entries"
echo "==================================="
echo -e "${BLUE}Path:${NC} $JOURNAL_PATH"
echo -e "${BLUE}Reading:${NC} Last $NUM_DAYS days"
echo "==================================="
echo

# Check if journal directory exists
if [ ! -d "$JOURNAL_PATH" ]; then
    echo -e "${YELLOW}No Discord journal directory found${NC}"
    echo "The daemon hasn't created any journal entries yet."
    exit 0
fi

# Find all journal files and sort by date (newest first)
JOURNALS=($(ls -1 "$JOURNAL_PATH"/*.jsonl 2>/dev/null | sort -r))
FOUND=${#JOURNALS[@]}

if [ $FOUND -eq 0 ]; then
    echo -e "${YELLOW}No Discord journal entries found${NC}"
    echo
    echo "The daemon hasn't created any journal entries yet."
    echo "Run the daemon and interact to create entries."
    echo
    exit 0
fi

# Limit to requested number
if [ $FOUND -lt $NUM_DAYS ]; then
    echo -e "${CYAN}Found $FOUND day(s) of journals (requested $NUM_DAYS)${NC}"
    echo
    NUM_TO_READ=$FOUND
else
    NUM_TO_READ=$NUM_DAYS
fi

# Read and display journals
for i in $(seq 0 $((NUM_TO_READ - 1))); do
    JOURNAL="${JOURNALS[$i]}"
    BASENAME=$(basename "$JOURNAL" .jsonl)

    echo
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}📱 Discord Journal: $BASENAME${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo

    # Parse and display each JSONL entry
    while IFS= read -r line; do
        if [ -n "$line" ]; then
            # Extract fields using jq if available, otherwise show raw
            if command -v jq &> /dev/null; then
                TYPE=$(echo "$line" | jq -r '.type // "unknown"')
                TIMESTAMP=$(echo "$line" | jq -r '.timestamp // ""' | cut -d'T' -f2 | cut -d'+' -f1 | cut -d'.' -f1)
                CONTEXT=$(echo "$line" | jq -r '.context // ""')
                RESPONSE=$(echo "$line" | jq -r '.response // ""')
                HEARTBEAT=$(echo "$line" | jq -r '.heartbeat_count // 0')

                # Color-code by type
                case $TYPE in
                    mention_response)
                        echo -e "${BLUE}[$TIMESTAMP]${NC} ${PURPLE}[Mention #$HEARTBEAT]${NC}"
                        ;;
                    heartbeat_response)
                        echo -e "${BLUE}[$TIMESTAMP]${NC} ${CYAN}[Heartbeat #$HEARTBEAT - Responded]${NC}"
                        ;;
                    heartbeat_quiet)
                        echo -e "${BLUE}[$TIMESTAMP]${NC} ${YELLOW}[Heartbeat #$HEARTBEAT - Quiet]${NC}"
                        ;;
                    *)
                        echo -e "${BLUE}[$TIMESTAMP]${NC} [$TYPE #$HEARTBEAT]"
                        ;;
                esac

                if [ -n "$CONTEXT" ]; then
                    echo -e "  ${CYAN}Context:${NC} $CONTEXT"
                fi
                if [ -n "$RESPONSE" ]; then
                    echo -e "  ${GREEN}Response:${NC} $RESPONSE"
                fi
                echo
            else
                # No jq, show raw JSON
                echo "$line"
                echo
            fi
        fi
    done < "$JOURNAL"
done

echo
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}Displayed $NUM_TO_READ of $FOUND total journal days${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo
