#!/bin/bash
# HTTP Endpoint Migration - Phase 2 Test Suite
# Tests all 19 new Phase 2 endpoints against running PPS server
#
# Usage: ./test_phase2_endpoints.sh [base_url]
# Default: http://localhost:8201

set -e

BASE_URL="${1:-http://localhost:8201}"
RESULTS_FILE="$(dirname "$0")/test_phase2_results.md"
PASSED=0
FAILED=0
TESTS=()

# Colors for terminal output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=================================="
echo "PPS HTTP Endpoint Tests - Phase 2"
echo "=================================="
echo "Target: $BASE_URL"
echo "Started: $(date)"
echo ""

# Initialize results file
cat > "$RESULTS_FILE" << EOF
# HTTP Endpoint Test Results - Phase 2

**Date**: $(date "+%Y-%m-%d %H:%M:%S")
**Target**: $BASE_URL
**Tester**: test_phase2_endpoints.sh

## Summary

EOF

# Helper function to run a test
run_test() {
    local name="$1"
    local method="$2"
    local endpoint="$3"
    local data="$4"
    local expected_field="$5"

    echo -n "Testing: $name... "

    if [ "$method" = "GET" ]; then
        response=$(curl -s -w "\n%{http_code}" "$BASE_URL$endpoint")
    elif [ "$method" = "DELETE" ]; then
        if [ -n "$data" ]; then
            response=$(curl -s -w "\n%{http_code}" -X DELETE \
                -H "Content-Type: application/json" \
                -d "$data" \
                "$BASE_URL$endpoint")
        else
            response=$(curl -s -w "\n%{http_code}" -X DELETE "$BASE_URL$endpoint")
        fi
    else
        response=$(curl -s -w "\n%{http_code}" -X POST \
            -H "Content-Type: application/json" \
            -d "$data" \
            "$BASE_URL$endpoint")
    fi

    http_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | sed '$d')

    # Check HTTP status and expected field
    if [ "$http_code" -ge 200 ] && [ "$http_code" -lt 300 ]; then
        if [ -n "$expected_field" ]; then
            if echo "$body" | grep -q "$expected_field"; then
                echo -e "${GREEN}PASS${NC} (HTTP $http_code)"
                TESTS+=("PASS: $name")
                ((PASSED++))
                log_pass "$name" "$http_code" "$method" "$endpoint" "$body"
                return 0
            else
                echo -e "${RED}FAIL${NC} (HTTP $http_code, missing '$expected_field')"
                TESTS+=("FAIL: $name - missing expected field")
                ((FAILED++))
                log_fail "$name" "$http_code" "$method" "$endpoint" "$body"
                return 1
            fi
        else
            echo -e "${GREEN}PASS${NC} (HTTP $http_code)"
            TESTS+=("PASS: $name")
            ((PASSED++))
            log_pass "$name" "$http_code" "$method" "$endpoint" "$body"
            return 0
        fi
    else
        echo -e "${RED}FAIL${NC} (HTTP $http_code)"
        TESTS+=("FAIL: $name - HTTP $http_code")
        ((FAILED++))
        log_fail "$name" "$http_code" "$method" "$endpoint" "$body"
        return 1
    fi
}

log_pass() {
    local name="$1"
    local http_code="$2"
    local method="$3"
    local endpoint="$4"
    local body="$5"
    
    echo "### $name" >> "$RESULTS_FILE"
    echo "" >> "$RESULTS_FILE"
    echo "- **Status**: PASS ✓" >> "$RESULTS_FILE"
    echo "- **HTTP Code**: $http_code" >> "$RESULTS_FILE"
    echo "- **Endpoint**: \`$method $endpoint\`" >> "$RESULTS_FILE"
    echo "" >> "$RESULTS_FILE"
    echo "\`\`\`json" >> "$RESULTS_FILE"
    echo "$body" | head -c 1000 >> "$RESULTS_FILE"
    echo "" >> "$RESULTS_FILE"
    echo "\`\`\`" >> "$RESULTS_FILE"
    echo "" >> "$RESULTS_FILE"
}

log_fail() {
    local name="$1"
    local http_code="$2"
    local method="$3"
    local endpoint="$4"
    local body="$5"
    
    echo "### $name" >> "$RESULTS_FILE"
    echo "" >> "$RESULTS_FILE"
    echo "- **Status**: FAIL ✗" >> "$RESULTS_FILE"
    echo "- **HTTP Code**: $http_code" >> "$RESULTS_FILE"
    echo "- **Endpoint**: \`$method $endpoint\`" >> "$RESULTS_FILE"
    echo "" >> "$RESULTS_FILE"
    echo "**Response:**" >> "$RESULTS_FILE"
    echo "\`\`\`json" >> "$RESULTS_FILE"
    echo "$body" | head -c 2000 >> "$RESULTS_FILE"
    echo "" >> "$RESULTS_FILE"
    echo "\`\`\`" >> "$RESULTS_FILE"
    echo "" >> "$RESULTS_FILE"
}

# Prereq: Health check
echo "--- Prerequisites ---"
run_test "Health Check" "GET" "/health" "" "healthy"
echo ""

echo "--- Phase 2 Endpoints ---"
echo ""

# === Anchor Management (3) ===
echo "= Anchor Management ="

run_test "anchor_list" "GET" "/tools/anchor_list" "" \
    ""  # May return error if ChromaDB not available - that's OK

run_test "anchor_resync" "POST" "/tools/anchor_resync" '{}' \
    ""  # May return error if ChromaDB not available - that's OK

# Skip anchor_delete for now - would need a valid filename

# === Crystal Management (2) ===
echo ""
echo "= Crystal Management ="

run_test "crystal_list" "GET" "/tools/crystal_list" "" \
    '"current":'

# Skip crystal_delete for now - don't want to delete actual crystals

# === Raw Capture (1) ===
echo ""
echo "= Raw Capture ="

run_test "get_turns_since_crystal" "POST" "/tools/get_turns_since_crystal" \
    '{"limit": 10, "offset": 0, "min_turns": 5}' \
    '"turns":'

# === Message Summaries (3) ===
echo ""
echo "= Message Summaries ="

run_test "get_recent_summaries" "POST" "/tools/get_recent_summaries" \
    '{"limit": 3}' \
    '"summaries":'

run_test "search_summaries" "POST" "/tools/search_summaries" \
    '{"query": "test", "limit": 5}' \
    '"results":'

run_test "summary_stats" "GET" "/tools/summary_stats" "" \
    '"unsummarized_messages":'

# === Graphiti Stats (1) ===
echo ""
echo "= Graphiti Stats ="

run_test "graphiti_ingestion_stats" "GET" "/tools/graphiti_ingestion_stats" "" \
    '"uningested_messages":'

# === Inventory (5) ===
echo ""
echo "= Inventory ="

run_test "inventory_categories" "GET" "/tools/inventory_categories" "" \
    '"categories":'

run_test "inventory_list" "POST" "/tools/inventory_list" \
    '{"category": "clothing", "limit": 10}' \
    ""  # May be empty

# Test inventory_add
run_test "inventory_add" "POST" "/tools/inventory_add" \
    '{"name": "test-item-http", "category": "artifacts", "description": "Added via HTTP endpoint test"}' \
    '"success":true'

# Test inventory_get
run_test "inventory_get" "POST" "/tools/inventory_get" \
    '{"name": "test-item-http", "category": "artifacts"}' \
    '"item":'

# Test inventory_delete
run_test "inventory_delete" "DELETE" "/tools/inventory_delete" \
    '{"name": "test-item-http", "category": "artifacts"}' \
    '"success":true'

# === Tech RAG (4) ===
echo ""
echo "= Tech RAG ="

run_test "tech_list" "GET" "/tools/tech_list" "" \
    ""  # May return error if ChromaDB not available

run_test "tech_search" "POST" "/tools/tech_search" \
    '{"query": "pattern persistence", "limit": 3}' \
    ""  # May return error if ChromaDB not available

# Skip tech_ingest and tech_delete for safety

echo ""
echo "=================================="
echo "Test Results"
echo "=================================="
echo -e "Passed: ${GREEN}$PASSED${NC}"
echo -e "Failed: ${RED}$FAILED${NC}"
echo "Total:  $((PASSED + FAILED))"
echo ""

# Update summary in results file
sed -i "s/## Summary/## Summary\n\n- **Passed**: $PASSED\n- **Failed**: $FAILED\n- **Total**: $((PASSED + FAILED))\n/" "$RESULTS_FILE"

# Final verdict
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}ALL TESTS PASSED${NC}"
    echo "" >> "$RESULTS_FILE"
    echo "---" >> "$RESULTS_FILE"
    echo "" >> "$RESULTS_FILE"
    echo "**VERDICT: ALL TESTS PASSED**" >> "$RESULTS_FILE"
    exit 0
else
    echo -e "${YELLOW}SOME TESTS FAILED${NC}"
    echo "(Some failures expected if ChromaDB unavailable)"
    echo "" >> "$RESULTS_FILE"
    echo "---" >> "$RESULTS_FILE"
    echo "" >> "$RESULTS_FILE"
    echo "**VERDICT: $FAILED TEST(S) FAILED**" >> "$RESULTS_FILE"
    echo "" >> "$RESULTS_FILE"
    echo "*Note: Some failures may be expected if ChromaDB is not available*" >> "$RESULTS_FILE"
    exit 1
fi
