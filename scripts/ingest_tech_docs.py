#!/usr/bin/env python3
"""
Ingest tech docs into rag-engine's tech-docs repository.

Safe to run multiple times — checks existing document sources and skips
already-ingested files. Run this to populate or refresh the tech-docs repo
after the rag-engine loses its registry (e.g. on first boot or data loss).

Usage:
    python3 scripts/ingest_tech_docs.py [--dry-run] [--force]

Options:
    --dry-run   Show what would be ingested without actually doing it
    --force     Re-ingest even if source already exists (deletes old first)
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).parent.parent
DOCS_DIR = PROJECT_ROOT / "docs"
RAG_ENGINE_URL = "http://localhost:8206"
REPO_NAME = "tech-docs"

SKIP_DIRS = {".git", "node_modules", "__pycache__", "venv", "calibration"}


def get_category(filepath: Path) -> str:
    """Derive category from directory structure."""
    rel_path = filepath.relative_to(DOCS_DIR)
    if len(rel_path.parts) > 1:
        return rel_path.parts[0]
    return "general"


async def ensure_repo(client: httpx.AsyncClient) -> None:
    """Create the tech-docs repo if it doesn't exist."""
    resp = await client.get(f"{RAG_ENGINE_URL}/api/repos/{REPO_NAME}")
    if resp.status_code == 404:
        print(f"  Repo '{REPO_NAME}' not found — creating...")
        create_resp = await client.post(
            f"{RAG_ENGINE_URL}/api/repos",
            json={"name": REPO_NAME},
        )
        create_resp.raise_for_status()
        print(f"  Repo created.")
    elif resp.status_code == 200:
        print(f"  Repo '{REPO_NAME}' exists.")
    else:
        resp.raise_for_status()


async def get_existing_sources(client: httpx.AsyncClient) -> dict[str, str]:
    """
    Return mapping of source_file -> doc_id for all already-ingested docs.
    Uses the source_file metadata field for matching.
    """
    resp = await client.get(f"{RAG_ENGINE_URL}/api/repos/{REPO_NAME}/documents")
    resp.raise_for_status()
    docs = resp.json()
    # Map source (the path stored during ingest) -> doc_id
    return {doc["source"]: doc["id"] for doc in docs}


async def delete_doc(client: httpx.AsyncClient, doc_id: str) -> None:
    resp = await client.delete(
        f"{RAG_ENGINE_URL}/api/repos/{REPO_NAME}/documents/{doc_id}"
    )
    resp.raise_for_status()


async def ingest_file(
    client: httpx.AsyncClient, filepath: Path, category: str
) -> dict:
    text = filepath.read_text(encoding="utf-8")
    rel_path = str(filepath.relative_to(PROJECT_ROOT))
    metadata = {
        "source_file": rel_path,
        "category": category,
    }
    resp = await client.post(
        f"{RAG_ENGINE_URL}/api/repos/{REPO_NAME}/ingest",
        json={"text": text, "metadata": metadata},
        timeout=60.0,
    )
    resp.raise_for_status()
    return resp.json()


async def main(dry_run: bool = False, force: bool = False) -> int:
    """Return exit code (0 = success)."""
    # Collect all markdown files
    all_docs: list[Path] = []
    for md_file in sorted(DOCS_DIR.rglob("*.md")):
        if any(skip in md_file.parts for skip in SKIP_DIRS):
            continue
        all_docs.append(md_file)

    # Also include .txt files (e.g. Data_Tin_Man.txt)
    for txt_file in sorted(DOCS_DIR.rglob("*.txt")):
        if any(skip in txt_file.parts for skip in SKIP_DIRS):
            continue
        all_docs.append(txt_file)

    print(f"=== Tech RAG Ingest ===")
    print(f"Target: {RAG_ENGINE_URL}/api/repos/{REPO_NAME}")
    print(f"Docs dir: {DOCS_DIR}")
    print(f"Files found: {len(all_docs)}")
    if dry_run:
        print(f"Mode: DRY RUN (no changes)")
    elif force:
        print(f"Mode: FORCE (re-ingest all)")
    else:
        print(f"Mode: INCREMENTAL (skip existing)")
    print()

    if not all_docs:
        print("No documents found — nothing to ingest.")
        return 0

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Ensure repo exists
        await ensure_repo(client)

        # Get already-ingested sources (keyed on relative path string)
        existing = await get_existing_sources(client)
        print(f"Already ingested: {len(existing)} documents\n")

        start_time = datetime.now()
        skipped = 0
        ingested = 0
        errors = 0

        for i, doc_path in enumerate(all_docs, 1):
            rel_path = str(doc_path.relative_to(PROJECT_ROOT))
            category = get_category(doc_path)
            label = f"[{i}/{len(all_docs)}] {rel_path}"

            if not force and rel_path in existing:
                print(f"  SKIP  {label}")
                skipped += 1
                continue

            if dry_run:
                action = "FORCE" if rel_path in existing else "INGEST"
                print(f"  {action} {label}")
                ingested += 1
                continue

            # Force: delete old version first
            if force and rel_path in existing:
                await delete_doc(client, existing[rel_path])

            print(f"  INGEST {label} ... ", end="", flush=True)
            try:
                result = await ingest_file(client, doc_path, category)
                chunks = result.get("chunks", "?")
                print(f"ok ({chunks} chunks)")
                ingested += 1
            except Exception as exc:
                print(f"ERROR: {exc}")
                errors += 1

            # Small delay to avoid hammering the embedding API
            await asyncio.sleep(0.05)

    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"\n=== Summary ===")
    print(f"Ingested: {ingested}")
    print(f"Skipped:  {skipped}")
    print(f"Errors:   {errors}")
    print(f"Time:     {elapsed:.1f}s ({elapsed / 60:.1f} min)")

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    force = "--force" in sys.argv
    rc = asyncio.run(main(dry_run=dry_run, force=force))
    sys.exit(rc)
