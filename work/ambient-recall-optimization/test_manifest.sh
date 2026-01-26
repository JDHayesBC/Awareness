#!/bin/bash
# Test script to verify manifest tracking in ambient_recall

echo "=== Testing Ambient Recall Manifest ==="
echo ""

# Test 1: HTTP Server (JSON response)
echo "Test 1: HTTP Server ambient_recall"
echo "-----------------------------------"
curl -s -X POST http://localhost:8201/tools/ambient_recall \
  -H "Content-Type: application/json" \
  -d '{"context": "startup", "limit_per_layer": 3}' | \
  python3 -c "
import sys, json
response = json.load(sys.stdin)
if 'manifest' in response:
    print('✓ Manifest present in response')
    manifest = response['manifest']
    print(f\"  Crystals: {manifest['crystals']['chars']} chars ({manifest['crystals']['count']} items)\")
    print(f\"  Word-photos: {manifest['word_photos']['chars']} chars ({manifest['word_photos']['count']} items)\")
    print(f\"  Rich texture: {manifest['rich_texture']['chars']} chars ({manifest['rich_texture']['count']} items)\")
    print(f\"  Summaries: {manifest['summaries']['chars']} chars ({manifest['summaries']['count']} items)\")
    print(f\"  Recent turns: {manifest['recent_turns']['chars']} chars ({manifest['recent_turns']['count']} items)\")
    print(f\"  TOTAL: {manifest['total_chars']} chars\")

    # Sanity checks
    if manifest['total_chars'] > 0:
        print('✓ Total chars is positive')
    else:
        print('✗ Total chars is zero or negative')

    if manifest['total_chars'] == sum(v['chars'] for v in [manifest['crystals'], manifest['word_photos'], manifest['rich_texture'], manifest['summaries'], manifest['recent_turns']]):
        print('✓ Total matches sum of parts')
    else:
        print('✗ Total does NOT match sum of parts')
else:
    print('✗ Manifest NOT found in response')
    sys.exit(1)
"

echo ""
echo "Test complete!"
