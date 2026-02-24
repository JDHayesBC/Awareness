#!/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/venv/bin/python
"""
Populate Tech RAG - Batch ingest documentation

Ingests all markdown files from docs/ into the tech-docs RAG repository.
Uses the PPS tech_ingest tool which handles chunking and embedding via RAG engine.

Run during reflection or maintenance windows - embedding 172 docs takes ~10-20 minutes.
"""

import sys
import httpx
import asyncio
from pathlib import Path
from datetime import datetime

# Project root
PROJECT_ROOT = Path(__file__).parent.parent
DOCS_DIR = PROJECT_ROOT / "docs"
RAG_ENGINE_URL = "http://localhost:8206"

async def ingest_file(client: httpx.AsyncClient, filepath: Path, category: str = None) -> dict:
    """Ingest a single file directly via RAG engine."""
    try:
        text = filepath.read_text(encoding="utf-8")
        metadata = {"source_file": str(filepath.relative_to(PROJECT_ROOT))}
        if category:
            metadata["category"] = category

        resp = await client.post(
            f"{RAG_ENGINE_URL}/api/repos/tech-docs/ingest",
            json={"text": text, "metadata": metadata},
            timeout=60.0
        )
        resp.raise_for_status()
        data = resp.json()
        return {"chunks_created": data.get("chunks", 0)}
    except Exception as e:
        return {"error": str(e), "filepath": str(filepath)}


async def main():
    """Ingest all markdown docs from docs/"""

    # Find all markdown files (exclude some directories)
    all_docs = []
    skip_dirs = {".git", "node_modules", "__pycache__", "venv"}

    for md_file in DOCS_DIR.rglob("*.md"):
        # Skip if in excluded directory
        if any(skip in md_file.parts for skip in skip_dirs):
            continue
        all_docs.append(md_file)

    print(f"=== Tech RAG Population ===")
    print(f"Found {len(all_docs)} markdown files in {DOCS_DIR}\n")

    if not all_docs:
        print("No documents to ingest.")
        return

    # Categorize by directory
    def get_category(filepath: Path) -> str:
        """Derive category from directory structure."""
        rel_path = filepath.relative_to(DOCS_DIR)
        if len(rel_path.parts) > 1:
            return rel_path.parts[0]  # First directory level
        return "general"

    start_time = datetime.now()
    success_count = 0
    error_count = 0

    async with httpx.AsyncClient() as client:
        for i, doc_path in enumerate(all_docs, 1):
            category = get_category(doc_path)
            rel_path = doc_path.relative_to(PROJECT_ROOT)

            print(f"[{i}/{len(all_docs)}] {rel_path} ({category})... ", end="", flush=True)

            result = await ingest_file(client, doc_path, category)

            if "error" in result:
                print(f"ERROR: {result['error']}")
                error_count += 1
            else:
                chunks = result.get("chunks_created", "?")
                print(f"✓ ({chunks} chunks)")
                success_count += 1

            # Small delay to avoid hammering the API
            if i < len(all_docs):
                await asyncio.sleep(0.1)

    elapsed = (datetime.now() - start_time).total_seconds()

    print(f"\n=== Summary ===")
    print(f"Success: {success_count}")
    print(f"Errors:  {error_count}")
    print(f"Total:   {len(all_docs)}")
    print(f"Time:    {elapsed:.1f}s ({elapsed/60:.1f} minutes)")

    return error_count == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
