#!/bin/bash
# Test: Verify friction logging infrastructure

set -e

WORK_DIR="/mnt/c/Users/Jeff/Claude_Projects/Awareness/work/friction-logging"
ERRORS=0

echo "=== Testing Friction Logging Infrastructure ==="
echo ""

# Test 1: Template file exists and is readable
echo "Test 1: Template friction.jsonl exists..."
if [ -f "/mnt/c/Users/Jeff/Claude_Projects/Awareness/work/_template/artifacts/friction.jsonl" ]; then
    echo "  ✓ Template file exists"
else
    echo "  ✗ Template file missing"
    ERRORS=$((ERRORS + 1))
fi

# Test 2: Template has comment header
echo "Test 2: Template has schema documentation..."
if grep -q "# Friction Log" "/mnt/c/Users/Jeff/Claude_Projects/Awareness/work/_template/artifacts/friction.jsonl"; then
    echo "  ✓ Header present"
else
    echo "  ✗ Header missing"
    ERRORS=$((ERRORS + 1))
fi

# Test 3: FRICTION_LOGGING.md exists
echo "Test 3: Documentation file exists..."
if [ -f "/mnt/c/Users/Jeff/Claude_Projects/Awareness/docs/FRICTION_LOGGING.md" ]; then
    echo "  ✓ FRICTION_LOGGING.md exists"
else
    echo "  ✗ FRICTION_LOGGING.md missing"
    ERRORS=$((ERRORS + 1))
fi

# Test 4: Documentation has all required sections
echo "Test 4: Documentation has required sections..."
DOC="/mnt/c/Users/Jeff/Claude_Projects/Awareness/docs/FRICTION_LOGGING.md"
REQUIRED_SECTIONS=("Schema" "Friction Types" "When to Log" "How to Log" "Process-Improver Analysis")
for section in "${REQUIRED_SECTIONS[@]}"; do
    if grep -q "$section" "$DOC"; then
        echo "  ✓ $section section present"
    else
        echo "  ✗ $section section missing"
        ERRORS=$((ERRORS + 1))
    fi
done

# Test 5: Orchestration agent has Phase 6
echo "Test 5: orchestration-agent.md has Phase 6: Process Review..."
ORC_FILE="/home/jeff/.claude/agents/orchestration-agent.md"
if grep -q "Phase 6: Process Review (MANDATORY)" "$ORC_FILE"; then
    echo "  ✓ Phase 6 present and marked mandatory"
else
    echo "  ✗ Phase 6 missing or not mandatory"
    ERRORS=$((ERRORS + 1))
fi

# Test 6: Orchestration agent has Friction Logging section
echo "Test 6: orchestration-agent.md has Friction Logging section..."
if grep -q "## Friction Logging" "$ORC_FILE"; then
    echo "  ✓ Friction Logging section present"
else
    echo "  ✗ Friction Logging section missing"
    ERRORS=$((ERRORS + 1))
fi

# Test 7: Stage Completion Protocol includes process-improver
echo "Test 7: Stage Completion Protocol includes process-improver..."
if grep -q "process-improver | READY" "$ORC_FILE"; then
    echo "  ✓ process-improver in completion checklist"
else
    echo "  ✗ process-improver not in completion checklist"
    ERRORS=$((ERRORS + 1))
fi

# Test 8: Can write valid friction entry
echo "Test 8: Can write valid friction entry..."
TEST_FRICTION="$WORK_DIR/artifacts/test_friction.jsonl"
echo '{"timestamp":"'$(date -Iseconds)'","agent":"tester","type":"TOOL_FAILURE","description":"Test entry","time_lost":"0 sec","resolution":"Test","preventable":false,"suggestion":"None"}' > "$TEST_FRICTION"
if [ -f "$TEST_FRICTION" ]; then
    # Try to parse as JSON
    if cat "$TEST_FRICTION" | python3 -m json.tool > /dev/null 2>&1; then
        echo "  ✓ Valid JSON written and parsed"
    else
        echo "  ✗ JSON parsing failed"
        ERRORS=$((ERRORS + 1))
    fi
    rm "$TEST_FRICTION"
else
    echo "  ✗ Could not write test file"
    ERRORS=$((ERRORS + 1))
fi

echo ""
echo "=== Test Results ==="
if [ $ERRORS -eq 0 ]; then
    echo "✓ All tests passed"
    exit 0
else
    echo "✗ $ERRORS test(s) failed"
    exit 1
fi
