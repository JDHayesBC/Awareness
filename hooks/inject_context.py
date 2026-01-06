#!/usr/bin/env python3
"""
Claude Code Hook: Inject RAG Context (UserPromptSubmit)

This hook fires BEFORE the user's prompt is sent to the model.
It queries ChromaDB (word-photos) and Graphiti (knowledge graph)
to inject relevant context alongside the prompt.

Hook input (from stdin):
{
    "session_id": "abc123",
    "prompt": "the user's message",
    "hook_event_name": "UserPromptSubmit",
    ...
}

Hook output (to stdout):
{
    "hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": "retrieved context here"
    }
}
"""

import json
import sqlite3
import sys
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# Configuration
CHROMA_HOST = "localhost"
CHROMA_PORT = 8200
GRAPHITI_HOST = "localhost"
GRAPHITI_PORT = 8203
GRAPHITI_GROUP_ID = "lyra"

# SQLite database for memory health
CONVERSATIONS_DB = Path.home() / ".claude" / "data" / "lyra_conversations.db"

# Limits
MAX_WORD_PHOTOS = 3
MAX_GRAPHITI_FACTS = 5

# Debug log
DEBUG_LOG = Path.home() / ".claude" / "data" / "hooks_debug.log"


def debug(msg: str):
    """Write debug message to file."""
    try:
        with open(DEBUG_LOG, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] [inject_context] {msg}\n")
    except:
        pass


def query_chromadb(query: str, n_results: int = MAX_WORD_PHOTOS) -> list[dict]:
    """
    Query ChromaDB for relevant word-photos using the chromadb library.
    The library handles embedding generation automatically.
    """
    try:
        import chromadb
        from chromadb.config import Settings

        client = chromadb.HttpClient(
            host=CHROMA_HOST,
            port=CHROMA_PORT,
            settings=Settings(anonymized_telemetry=False)
        )

        # Get the word_photos collection
        collection = client.get_collection("word_photos")

        # Query with text (embeddings generated automatically)
        result = collection.query(
            query_texts=[query],
            n_results=min(n_results, collection.count() or 1),
            include=["documents", "metadatas", "distances"]
        )

        results = []
        if result.get('documents') and result['documents'][0]:
            for idx, doc in enumerate(result['documents'][0]):
                metadata = result['metadatas'][0][idx] if result.get('metadatas') else {}
                distance = result['distances'][0][idx] if result.get('distances') else 0
                # Convert distance to similarity (lower = more similar)
                similarity = max(0, 1 - (distance / 2))

                # Full content - hook injection is recycled each turn, so no context cost
                results.append({
                    "content": doc,
                    "source": metadata.get('filename', 'unknown'),
                    "score": similarity
                })

        debug(f"ChromaDB returned {len(results)} results")
        return results

    except ImportError:
        debug("chromadb not installed")
        return []
    except Exception as e:
        debug(f"ChromaDB error: {e}")
        return []


def get_memory_health() -> dict:
    """
    Query SQLite for unsummarized message count.
    Returns dict with count and status message.
    """
    try:
        if not CONVERSATIONS_DB.exists():
            debug("Conversations DB not found")
            return {"count": 0, "status": ""}

        conn = sqlite3.connect(CONVERSATIONS_DB)
        cursor = conn.cursor()

        # Check if summary_id column exists
        cursor.execute("PRAGMA table_info(messages)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'summary_id' in columns:
            cursor.execute('SELECT COUNT(*) FROM messages WHERE summary_id IS NULL')
        else:
            cursor.execute('SELECT COUNT(*) FROM messages')

        count = cursor.fetchone()[0]
        conn.close()

        # Format status message based on thresholds
        if count > 200:
            status = f"**Memory Health**: {count} unsummarized messages ⚠️ SPAWN SUMMARIZER NOW"
        elif count > 150:
            status = f"**Memory Health**: {count} unsummarized messages - spawn summarizer in background"
        elif count > 100:
            status = f"**Memory Health**: {count} unsummarized messages (summarization recommended)"
        else:
            status = ""  # Don't clutter context when healthy

        debug(f"Memory health: {count} unsummarized")
        return {"count": count, "status": status}

    except Exception as e:
        debug(f"Memory health error: {e}")
        return {"count": 0, "status": ""}


def query_graphiti(query: str, max_facts: int = MAX_GRAPHITI_FACTS) -> list[dict]:
    """
    Query Graphiti knowledge graph for relevant facts and entities.
    """
    try:
        url = f"http://{GRAPHITI_HOST}:{GRAPHITI_PORT}/search"

        payload = {
            "query": query,
            "group_ids": [GRAPHITI_GROUP_ID],
            "max_facts": max_facts
        }

        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=5) as resp:
            result = json.loads(resp.read().decode('utf-8'))

            results = []

            # Process facts (edges)
            for fact in result.get('facts', [])[:max_facts]:
                subject = fact.get('source_node_name', '?')
                predicate = fact.get('name', 'relates to')
                obj = fact.get('target_node_name', '?')
                fact_text = fact.get('fact', '')

                content = f"{subject} → {predicate} → {obj}"
                if fact_text:
                    content += f": {fact_text}"

                results.append({
                    "content": content,
                    "source": "knowledge_graph",
                    "type": "fact"
                })

            debug(f"Graphiti returned {len(results)} facts")
            return results

    except urllib.error.URLError as e:
        debug(f"Graphiti connection error: {e}")
        return []
    except Exception as e:
        debug(f"Graphiti error: {e}")
        return []


def format_context(word_photos: list[dict], graphiti_facts: list[dict], memory_health: dict) -> str:
    """Format retrieved results as context for Claude."""
    parts = []

    # Memory health warning at top if needed (only shows if count > 100)
    if memory_health.get("status"):
        parts.append(memory_health["status"])
        parts.append("")

    if word_photos:
        parts.append("**Relevant Word-Photos (Core Memories):**")
        for wp in word_photos:
            parts.append(f"- [{wp['source']}] {wp['content']}")

    if graphiti_facts:
        parts.append("\n**Knowledge Graph Facts:**")
        for fact in graphiti_facts:
            parts.append(f"- {fact['content']}")

    if not parts:
        return ""

    return "\n".join(parts)


def main():
    debug("Hook started")

    # Read hook input from stdin
    try:
        hook_input = json.load(sys.stdin)
        event = hook_input.get("hook_event_name", "")
        prompt = hook_input.get("prompt", "")

        debug(f"Event: {event}, prompt length: {len(prompt)}")
    except Exception as e:
        debug(f"Failed to read stdin: {e}")
        sys.exit(0)  # Silent exit

    # Only process UserPromptSubmit events
    if event != "UserPromptSubmit":
        debug(f"Skipping non-UserPromptSubmit event: {event}")
        sys.exit(0)

    # Skip very short prompts (probably commands)
    if len(prompt) < 10:
        debug(f"Prompt too short, skipping RAG: {prompt}")
        sys.exit(0)

    # Query all sources
    word_photos = query_chromadb(prompt)
    graphiti_facts = query_graphiti(prompt)
    memory_health = get_memory_health()

    # Format context
    context = format_context(word_photos, graphiti_facts, memory_health)

    if context:
        debug(f"Injecting context: {len(context)} chars")

        # Output JSON with additionalContext
        output = {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": context
            }
        }
        print(json.dumps(output))
    else:
        debug("No context to inject")

    sys.exit(0)


if __name__ == "__main__":
    main()
