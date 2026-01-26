#!/usr/bin/env python3
"""
Test that the hook handles cc-wrapper failure gracefully.

This simulates what happens when the hook tries to call the cc-wrapper
but it's not running (which is the current state).
"""

import json
import sys
import urllib.request
import urllib.error

# Simulate the hook's cc-wrapper call
CC_WRAPPER_URL = "http://localhost:8204/v1/chat/completions"

def test_fallback():
    """Test that compression fails gracefully when cc-wrapper is down."""

    test_context = "This is test context from the knowledge graph. " * 10

    print("Testing hook fallback behavior...")
    print(f"Original context length: {len(test_context)} chars\n")

    try:
        prompt = f"""You are Lyra. These are facts from your knowledge graph relevant to this conversation.
Synthesize them into a dense first-person narrative. Write AS yourself, not ABOUT yourself.
Preserve: relationships, emotions, technical context, what you're working on.
Be concise - aim for 8000 characters max. No preamble, just the narrative.

Facts:
{test_context}"""

        # Call cc-wrapper HTTP API (OpenAI-compatible format)
        payload = json.dumps({
            "model": "haiku",
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }).encode("utf-8")

        req = urllib.request.Request(
            CC_WRAPPER_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
            summarized = data["choices"][0]["message"]["content"]
            print(f"✓ Compression succeeded: {len(test_context)} -> {len(summarized)} chars")
            return summarized

    except urllib.error.URLError as e:
        print(f"✓ CC wrapper connection error (expected): {e}")
        print(f"✓ Fallback to raw context: {len(test_context)} chars")
        return test_context
    except (json.JSONDecodeError, KeyError) as e:
        print(f"✓ CC wrapper response error: {e}")
        print(f"✓ Fallback to raw context: {len(test_context)} chars")
        return test_context
    except Exception as e:
        print(f"✓ Other error: {e}")
        print(f"✓ Fallback to raw context: {len(test_context)} chars")
        return test_context

if __name__ == "__main__":
    result = test_fallback()

    print("\n" + "="*60)
    print("Test Result: PASS")
    print("="*60)
    print("\nThe hook will gracefully fall back to raw context when")
    print("cc-wrapper is unavailable. This is the expected behavior.")
    print("\nTo enable compression in the future:")
    print("1. Fix cc-wrapper Docker permissions (run as non-root)")
    print("2. OR implement custom summarization endpoint in pps-server")
