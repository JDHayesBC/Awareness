#!/bin/bash
# Observatory Health Check Script
# Verifies all PPS services are running and accessible
#
# Usage: ./verify_observatory.sh

set -e

BOLD='\033[1m'
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BOLD}=== Observatory Health Check ===${NC}\n"

# Check ChromaDB (Port 8200)
echo -n "ChromaDB (port 8200)........... "
if curl -s http://localhost:8200/api/v1/heartbeat 2>&1 | grep -q "nanosecond heartbeat"; then
    echo -e "${GREEN}✓ Running${NC}"
elif curl -s http://localhost:8200/api/v2/heartbeat 2>&1 | grep -q "nanosecond heartbeat"; then
    echo -e "${GREEN}✓ Running (v2 API)${NC}"
else
    echo -e "${RED}✗ Not responding${NC}"
    exit 1
fi

# Check MCP Server (Port 8201)
echo -n "PPS MCP Server (port 8201)..... "
if curl -s http://localhost:8201/health | grep -q '"status":"healthy"'; then
    echo -e "${GREEN}✓ Healthy${NC}"
else
    echo -e "${RED}✗ Unhealthy${NC}"
    exit 1
fi

# Check Web Dashboard (Port 8202)
echo -n "Web Dashboard (port 8202)....... "
if curl -s -o /dev/null -w "%{http_code}" http://localhost:8202/ | grep -q "200"; then
    echo -e "${GREEN}✓ Accessible${NC}"
else
    echo -e "${RED}✗ Not accessible${NC}"
    exit 1
fi

# Check Graphiti (Port 8203)
echo -n "Graphiti API (port 8203)....... "
if curl -s -o /dev/null -w "%{http_code}" http://localhost:8203/healthcheck | grep -q "200"; then
    echo -e "${GREEN}✓ Running${NC}"
else
    echo -e "${RED}✗ Not responding${NC}"
    exit 1
fi

echo -e "\n${GREEN}${BOLD}All services healthy!${NC}"
echo -e "\nAccess points:"
echo -e "  ${BOLD}Web Dashboard:${NC} http://localhost:8202"
echo -e "  ${BOLD}MCP API:${NC}       http://localhost:8201/health"
echo -e "  ${BOLD}ChromaDB:${NC}      http://localhost:8200"
echo -e "  ${BOLD}Graphiti:${NC}      http://localhost:8203"
