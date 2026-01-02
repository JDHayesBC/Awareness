#!/bin/bash
# Pattern Persistence System - Quick Setup Script

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Pattern Persistence System Setup ===${NC}"
echo

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Error: Docker is not installed${NC}"
    echo "Please install Docker first: https://docs.docker.com/get-docker/"
    exit 1
fi

# Check if Docker Compose is installed
if ! command -v docker compose &> /dev/null && ! command -v docker-compose &> /dev/null; then
    echo -e "${RED}Error: Docker Compose is not installed${NC}"
    echo "Please install Docker Compose first: https://docs.docker.com/compose/install/"
    exit 1
fi

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PPS_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

echo "PPS root directory: $PPS_ROOT"
echo

# Check if .env exists
if [ ! -f "$PPS_ROOT/docker/.env" ]; then
    echo -e "${YELLOW}Creating .env file from template...${NC}"
    cp "$PPS_ROOT/docker/.env.example" "$PPS_ROOT/docker/.env"
    
    # Try to detect user's home directory for Claude home
    DEFAULT_CLAUDE_HOME="$HOME/.claude"
    echo
    echo "Where should the Claude home directory be located?"
    echo "This will store your memories, crystals, and data."
    echo -e "Default: ${GREEN}$DEFAULT_CLAUDE_HOME${NC}"
    read -p "Claude home directory (press Enter for default): " CLAUDE_HOME_INPUT
    
    if [ -z "$CLAUDE_HOME_INPUT" ]; then
        CLAUDE_HOME="$DEFAULT_CLAUDE_HOME"
    else
        CLAUDE_HOME="$CLAUDE_HOME_INPUT"
    fi
    
    # Update .env file with the Claude home path
    sed -i.bak "s|CLAUDE_HOME=.*|CLAUDE_HOME=$CLAUDE_HOME|" "$PPS_ROOT/docker/.env"
    rm "$PPS_ROOT/docker/.env.bak" 2>/dev/null || true
    
    echo -e "${GREEN}✓ .env file created${NC}"
else
    # Read CLAUDE_HOME from existing .env
    CLAUDE_HOME=$(grep "^CLAUDE_HOME=" "$PPS_ROOT/docker/.env" | cut -d'=' -f2)
    echo -e "${GREEN}✓ Using existing .env file${NC}"
fi

# Create Claude home directory if it doesn't exist
if [ ! -d "$CLAUDE_HOME" ]; then
    echo
    echo -e "${YELLOW}Claude home directory doesn't exist. Creating it...${NC}"
    mkdir -p "$CLAUDE_HOME"
    
    # Copy example structure
    cp -r "$SCRIPT_DIR/claude_home/"* "$CLAUDE_HOME/"
    echo -e "${GREEN}✓ Created Claude home directory with example structure${NC}"
else
    # Ensure required subdirectories exist
    mkdir -p "$CLAUDE_HOME/memories/word_photos"
    mkdir -p "$CLAUDE_HOME/data"
    mkdir -p "$CLAUDE_HOME/crystals/current"
    mkdir -p "$CLAUDE_HOME/crystals/archive"
    echo -e "${GREEN}✓ Claude home directory exists${NC}"
fi

echo
echo -e "${YELLOW}Starting Docker services...${NC}"
cd "$PPS_ROOT/docker"

# Use docker compose or docker-compose depending on what's available
if command -v docker compose &> /dev/null; then
    docker compose up -d
else
    docker-compose up -d
fi

echo
echo -e "${YELLOW}Waiting for services to be healthy...${NC}"

# Wait for ChromaDB
MAX_ATTEMPTS=30
ATTEMPT=0
while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    if curl -s http://localhost:8200/api/v1 > /dev/null 2>&1; then
        echo -e "${GREEN}✓ ChromaDB is ready${NC}"
        break
    fi
    echo -n "."
    sleep 1
    ATTEMPT=$((ATTEMPT + 1))
done

if [ $ATTEMPT -eq $MAX_ATTEMPTS ]; then
    echo -e "\n${RED}Warning: ChromaDB didn't become ready in time${NC}"
fi

# Wait for PPS Server
ATTEMPT=0
while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    if curl -s http://localhost:8201/health > /dev/null 2>&1; then
        echo -e "${GREEN}✓ PPS Server is ready${NC}"
        break
    fi
    echo -n "."
    sleep 1
    ATTEMPT=$((ATTEMPT + 1))
done

if [ $ATTEMPT -eq $MAX_ATTEMPTS ]; then
    echo -e "\n${RED}Warning: PPS Server didn't become ready in time${NC}"
fi

# Show health status
echo
echo -e "${YELLOW}Checking system health...${NC}"
curl -s http://localhost:8201/health | python3 -m json.tool || echo -e "${RED}Failed to get health status${NC}"

echo
echo -e "${GREEN}=== Setup Complete! ===${NC}"
echo
echo "Next steps:"
echo "1. Add your word-photos to: $CLAUDE_HOME/memories/word_photos/"
echo "2. Configure Claude Code to use the PPS MCP server"
echo "3. Test with: curl http://localhost:8201/health"
echo
echo "To stop the services: cd $PPS_ROOT/docker && docker compose down"
echo "To view logs: cd $PPS_ROOT/docker && docker compose logs -f"