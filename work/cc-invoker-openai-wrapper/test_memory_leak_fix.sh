#!/bin/bash
# Test script for memory leak fix
#
# This script stress-tests the wrapper by forcing multiple restarts
# and monitoring memory usage. If the fix works, memory should stay
# stable even after 50+ restarts.
#
# Usage:
#   ./test_memory_leak_fix.sh

set -e

WRAPPER_URL="${WRAPPER_URL:-http://localhost:8204}"
RESTARTS_TO_TEST=20
REQUESTS_PER_RESTART=12  # Slightly over max_turns=10 to trigger restart

echo "==================================="
echo "Memory Leak Fix Test"
echo "==================================="
echo "Wrapper URL: $WRAPPER_URL"
echo "Target restarts: $RESTARTS_TO_TEST"
echo "Requests per restart: $REQUESTS_PER_RESTART"
echo ""

# Check if wrapper is running
if ! curl -sf "$WRAPPER_URL/health" > /dev/null; then
    echo "ERROR: Wrapper not responding at $WRAPPER_URL"
    echo "Start with: docker compose up pps-haiku-wrapper"
    exit 1
fi

echo "Wrapper is running. Starting test..."
echo ""

# Function to get current memory
get_memory() {
    curl -s "$WRAPPER_URL/health" | jq -r '.memory.rss_mb // "N/A"'
}

# Function to get restart count
get_restart_count() {
    curl -s "$WRAPPER_URL/health" | jq -r '.stats.restart_count // 0'
}

# Get baseline
baseline_memory=$(get_memory)
baseline_restarts=$(get_restart_count)

echo "Baseline:"
echo "  Memory: ${baseline_memory} MB"
echo "  Restarts: ${baseline_restarts}"
echo ""

# Track memory samples
declare -a memory_samples
declare -a restart_counts

# Run test
echo "Running stress test (this will take a few minutes)..."
echo ""

for restart_num in $(seq 1 $RESTARTS_TO_TEST); do
    echo -n "Restart cycle $restart_num/$RESTARTS_TO_TEST: "

    # Send enough requests to trigger a restart
    for req in $(seq 1 $REQUESTS_PER_RESTART); do
        curl -s "$WRAPPER_URL/v1/chat/completions" \
            -H "Content-Type: application/json" \
            -d '{
                "model": "haiku",
                "messages": [
                    {"role": "system", "content": "You are a test assistant."},
                    {"role": "user", "content": "Respond with just OK"}
                ]
            }' > /dev/null 2>&1 || true

        # Small delay to avoid overwhelming the wrapper
        sleep 0.1
    done

    # Wait for restart to complete
    sleep 2

    # Sample memory and restart count
    current_memory=$(get_memory)
    current_restarts=$(get_restart_count)

    memory_samples+=("$current_memory")
    restart_counts+=("$current_restarts")

    echo "Memory: ${current_memory} MB, Restarts: ${current_restarts}"
done

echo ""
echo "==================================="
echo "Test Complete"
echo "==================================="
echo ""

# Calculate statistics
total_restarts=$(($(get_restart_count) - baseline_restarts))
final_memory=$(get_memory)

echo "Results:"
echo "  Total restarts triggered: ${total_restarts}"
echo "  Baseline memory: ${baseline_memory} MB"
echo "  Final memory: ${final_memory} MB"

if [[ "$baseline_memory" != "N/A" && "$final_memory" != "N/A" ]]; then
    delta=$(awk "BEGIN {print $final_memory - $baseline_memory}")
    echo "  Memory delta: ${delta} MB"
    echo ""

    # Check if memory grew significantly
    if (( $(awk "BEGIN {print ($delta > 200)}") )); then
        echo "❌ FAIL: Memory grew by ${delta} MB (threshold: 200 MB)"
        echo "   This suggests the leak is NOT fixed."
        echo ""
        echo "Memory progression:"
        for i in "${!memory_samples[@]}"; do
            echo "  Restart $((i+1)): ${memory_samples[$i]} MB"
        done
        exit 1
    elif (( $(awk "BEGIN {print ($delta > 50)}") )); then
        echo "⚠️  WARNING: Memory grew by ${delta} MB (threshold: 50 MB)"
        echo "   This is borderline. Monitor production closely."
        echo ""
        echo "Memory progression:"
        for i in "${!memory_samples[@]}"; do
            echo "  Restart $((i+1)): ${memory_samples[$i]} MB"
        done
        exit 0
    else
        echo "✅ PASS: Memory delta ${delta} MB is within expected range"
        echo "   The leak appears to be fixed!"
        echo ""
        echo "Memory progression (showing stability):"
        for i in "${!memory_samples[@]}"; do
            echo "  Restart $((i+1)): ${memory_samples[$i]} MB"
        done
        exit 0
    fi
else
    echo "⚠️  Cannot calculate delta (psutil not available)"
    echo "   Install psutil in wrapper container to enable memory monitoring"
    exit 0
fi
