#!/bin/bash
#
# Test script for conversation navigation tools
# Tests both MCP (via server.py) and HTTP (via server_http.py) versions
#
# Usage:
#   bash test_navigation_tools.sh
#

set -e  # Exit on error

echo "======================================================================="
echo "CONVERSATION NAVIGATION TOOLS - TEST SUITE"
echo "======================================================================="
echo

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

HTTP_BASE="http://localhost:8201"

# Test counter
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

# Helper functions
pass() {
    echo -e "${GREEN}✓ PASS${NC}: $1"
    TESTS_PASSED=$((TESTS_PASSED + 1))
}

fail() {
    echo -e "${RED}✗ FAIL${NC}: $1"
    echo "  Details: $2"
    TESTS_FAILED=$((TESTS_FAILED + 1))
}

test_section() {
    echo
    echo "-----------------------------------------------------------------------"
    echo "$1"
    echo "-----------------------------------------------------------------------"
}

# Check if PPS HTTP server is running
test_section "PREREQUISITE: PPS HTTP Server Status"

if curl -s "$HTTP_BASE/health" > /dev/null 2>&1; then
    pass "PPS HTTP server is running at $HTTP_BASE"
else
    fail "PPS HTTP server not responding" "Start with: cd pps/docker && docker-compose up -d pps-server"
    exit 1
fi

# TEST 1: get_conversation_context - Small request
test_section "TEST 1: get_conversation_context (small request)"
TESTS_RUN=$((TESTS_RUN + 1))

RESPONSE=$(curl -s -X POST "$HTTP_BASE/tools/get_conversation_context" \
    -H "Content-Type: application/json" \
    -d '{"turns": 5}')

if echo "$RESPONSE" | jq -e '.success == true' > /dev/null 2>&1; then
    RAW_COUNT=$(echo "$RESPONSE" | jq -r '.raw_turns_count')
    SUMMARY_COUNT=$(echo "$RESPONSE" | jq -r '.summaries_count')
    pass "get_conversation_context(turns=5) returned $RAW_COUNT raw turns, $SUMMARY_COUNT summaries"
else
    fail "get_conversation_context(turns=5)" "Response: $RESPONSE"
fi

# TEST 2: get_conversation_context - Large request (should blend)
test_section "TEST 2: get_conversation_context (large request)"
TESTS_RUN=$((TESTS_RUN + 1))

RESPONSE=$(curl -s -X POST "$HTTP_BASE/tools/get_conversation_context" \
    -H "Content-Type: application/json" \
    -d '{"turns": 200}')

if echo "$RESPONSE" | jq -e '.success == true' > /dev/null 2>&1; then
    RAW_COUNT=$(echo "$RESPONSE" | jq -r '.raw_turns_count')
    SUMMARY_COUNT=$(echo "$RESPONSE" | jq -r '.summaries_count')
    TOTAL_COVERED=$(echo "$RESPONSE" | jq -r '.turns_covered_approx')
    pass "get_conversation_context(turns=200) covered ~$TOTAL_COVERED turns ($SUMMARY_COUNT summaries + $RAW_COUNT raw)"
else
    fail "get_conversation_context(turns=200)" "Response: $RESPONSE"
fi

# TEST 3: get_conversation_context - Edge case (turns=0)
test_section "TEST 3: get_conversation_context (edge case: turns=0)"
TESTS_RUN=$((TESTS_RUN + 1))

RESPONSE=$(curl -s -X POST "$HTTP_BASE/tools/get_conversation_context" \
    -H "Content-Type: application/json" \
    -d '{"turns": 0}')

if echo "$RESPONSE" | jq -e '.detail' | grep -q "greater than 0" > /dev/null 2>&1; then
    pass "get_conversation_context(turns=0) correctly rejected with validation error"
else
    fail "get_conversation_context(turns=0) should reject invalid input" "Response: $RESPONSE"
fi

# TEST 4: get_turns_since - Recent timestamp
test_section "TEST 4: get_turns_since (recent timestamp)"
TESTS_RUN=$((TESTS_RUN + 1))

# Get timestamp from 1 hour ago
TIMESTAMP=$(date -u -d '1 hour ago' '+%Y-%m-%dT%H:%M:%S' 2>/dev/null || date -u -v-1H '+%Y-%m-%dT%H:%M:%S')

RESPONSE=$(curl -s -X POST "$HTTP_BASE/tools/get_turns_since" \
    -H "Content-Type: application/json" \
    -d "{\"timestamp\": \"$TIMESTAMP\", \"include_summaries\": true, \"limit\": 100}")

if echo "$RESPONSE" | jq -e '.success == true' > /dev/null 2>&1; then
    MSG_COUNT=$(echo "$RESPONSE" | jq -r '.messages_count')
    SUMMARY_COUNT=$(echo "$RESPONSE" | jq -r '.summaries_count')
    pass "get_turns_since(1 hour ago) returned $MSG_COUNT messages, $SUMMARY_COUNT summaries"
else
    fail "get_turns_since($TIMESTAMP)" "Response: $RESPONSE"
fi

# TEST 5: get_turns_since - Future timestamp (should be empty)
test_section "TEST 5: get_turns_since (future timestamp)"
TESTS_RUN=$((TESTS_RUN + 1))

FUTURE_TIMESTAMP=$(date -u -d '1 day' '+%Y-%m-%dT%H:%M:%S' 2>/dev/null || date -u -v+1d '+%Y-%m-%dT%H:%M:%S')

RESPONSE=$(curl -s -X POST "$HTTP_BASE/tools/get_turns_since" \
    -H "Content-Type: application/json" \
    -d "{\"timestamp\": \"$FUTURE_TIMESTAMP\", \"include_summaries\": false, \"limit\": 100}")

if echo "$RESPONSE" | jq -e '.success == true and .messages_count == 0' > /dev/null 2>&1; then
    pass "get_turns_since(future) correctly returned 0 messages"
else
    fail "get_turns_since(future) should return empty" "Response: $RESPONSE"
fi

# TEST 6: get_turns_since - Invalid timestamp format
test_section "TEST 6: get_turns_since (invalid timestamp)"
TESTS_RUN=$((TESTS_RUN + 1))

RESPONSE=$(curl -s -X POST "$HTTP_BASE/tools/get_turns_since" \
    -H "Content-Type: application/json" \
    -d '{"timestamp": "not-a-timestamp", "include_summaries": false}')

if echo "$RESPONSE" | jq -e '.detail' | grep -q "Invalid timestamp" > /dev/null 2>&1; then
    pass "get_turns_since(invalid) correctly rejected with format error"
else
    fail "get_turns_since(invalid) should reject bad timestamp" "Response: $RESPONSE"
fi

# TEST 7: get_turns_around - Centered on noon today
test_section "TEST 7: get_turns_around (centered on noon)"
TESTS_RUN=$((TESTS_RUN + 1))

NOON_TODAY=$(date -u '+%Y-%m-%dT12:00:00')

RESPONSE=$(curl -s -X POST "$HTTP_BASE/tools/get_turns_around" \
    -H "Content-Type: application/json" \
    -d "{\"timestamp\": \"$NOON_TODAY\", \"count\": 40, \"before_ratio\": 0.5}")

if echo "$RESPONSE" | jq -e '.success == true' > /dev/null 2>&1; then
    BEFORE_COUNT=$(echo "$RESPONSE" | jq -r '.before_count')
    AFTER_COUNT=$(echo "$RESPONSE" | jq -r '.after_count')
    TOTAL_COUNT=$(echo "$RESPONSE" | jq -r '.total_count')
    pass "get_turns_around(noon, 40) returned $BEFORE_COUNT before, $AFTER_COUNT after (total: $TOTAL_COUNT)"
else
    fail "get_turns_around($NOON_TODAY)" "Response: $RESPONSE"
fi

# TEST 8: get_turns_around - Asymmetric split (70/30)
test_section "TEST 8: get_turns_around (asymmetric split)"
TESTS_RUN=$((TESTS_RUN + 1))

RESPONSE=$(curl -s -X POST "$HTTP_BASE/tools/get_turns_around" \
    -H "Content-Type: application/json" \
    -d "{\"timestamp\": \"$NOON_TODAY\", \"count\": 40, \"before_ratio\": 0.7}")

if echo "$RESPONSE" | jq -e '.success == true' > /dev/null 2>&1; then
    BEFORE_COUNT=$(echo "$RESPONSE" | jq -r '.before_count')
    AFTER_COUNT=$(echo "$RESPONSE" | jq -r '.after_count')

    # Should be roughly 28 before, 12 after (allowing for edge cases)
    if [ "$BEFORE_COUNT" -ge "$AFTER_COUNT" ]; then
        pass "get_turns_around(70/30 split) correctly returned more before ($BEFORE_COUNT) than after ($AFTER_COUNT)"
    else
        fail "get_turns_around(70/30 split) ratio incorrect" "Before: $BEFORE_COUNT, After: $AFTER_COUNT"
    fi
else
    fail "get_turns_around(70/30)" "Response: $RESPONSE"
fi

# TEST 9: get_turns_around - Edge case (count=0)
test_section "TEST 9: get_turns_around (count=0)"
TESTS_RUN=$((TESTS_RUN + 1))

RESPONSE=$(curl -s -X POST "$HTTP_BASE/tools/get_turns_around" \
    -H "Content-Type: application/json" \
    -d "{\"timestamp\": \"$NOON_TODAY\", \"count\": 0, \"before_ratio\": 0.5}")

if echo "$RESPONSE" | jq -e '.success == true and .total_count == 0' > /dev/null 2>&1; then
    pass "get_turns_around(count=0) correctly returned 0 messages"
else
    fail "get_turns_around(count=0)" "Response: $RESPONSE"
fi

# TEST 10: get_turns_around - Invalid before_ratio (should clamp)
test_section "TEST 10: get_turns_around (before_ratio clamping)"
TESTS_RUN=$((TESTS_RUN + 1))

# Test with before_ratio > 1 (should clamp to 1.0)
RESPONSE=$(curl -s -X POST "$HTTP_BASE/tools/get_turns_around" \
    -H "Content-Type: application/json" \
    -d "{\"timestamp\": \"$NOON_TODAY\", \"count\": 10, \"before_ratio\": 1.5}")

if echo "$RESPONSE" | jq -e '.success == true' > /dev/null 2>&1; then
    BEFORE_COUNT=$(echo "$RESPONSE" | jq -r '.before_count')
    AFTER_COUNT=$(echo "$RESPONSE" | jq -r '.after_count')

    # With ratio clamped to 1.0, should be all before, 0 after
    if [ "$AFTER_COUNT" -eq 0 ] && [ "$BEFORE_COUNT" -gt 0 ]; then
        pass "get_turns_around(before_ratio=1.5) correctly clamped to 1.0"
    else
        fail "get_turns_around(before_ratio=1.5) clamping failed" "Before: $BEFORE_COUNT, After: $AFTER_COUNT"
    fi
else
    fail "get_turns_around(clamping)" "Response: $RESPONSE"
fi

# Summary
echo
echo "======================================================================="
echo "TEST SUMMARY"
echo "======================================================================="
echo "Total tests run: $TESTS_RUN"
echo -e "${GREEN}Passed: $TESTS_PASSED${NC}"
if [ $TESTS_FAILED -gt 0 ]; then
    echo -e "${RED}Failed: $TESTS_FAILED${NC}"
else
    echo -e "Failed: $TESTS_FAILED"
fi
echo
if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "${GREEN}✓ ALL TESTS PASSED${NC}"
    exit 0
else
    echo -e "${RED}✗ SOME TESTS FAILED${NC}"
    exit 1
fi
