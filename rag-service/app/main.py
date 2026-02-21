import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager
from pathlib import Path
import json

# Allow data dir override via environment variable (for local dev/testing)
DATA_DIR = Path(os.environ.get('RAG_DATA_DIR', '/app/data'))

from .models import (
    RepoCreate, RepoUpdate, RepoResponse, IngestRequest,
    SearchRequest, SearchResponse, SearchResult, DocumentInfo,
    RerankRequest, RerankResult, RerankResponse
)
from .storage import Storage
from .rag_engine import RAGEngine


storage: Storage | None = None
rag_engine: RAGEngine | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global storage, rag_engine

    # Ensure data directory exists
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    storage = Storage(str(DATA_DIR / 'rag.db'))
    await storage.init()

    rag_engine = RAGEngine(chroma_path=str(DATA_DIR / 'chromadb'))

    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "rag-engine"}


@app.post("/api/repos", status_code=201)
async def create_repo(repo: RepoCreate):
    existing = await storage.get_repo(repo.name)
    if existing:
        raise HTTPException(status_code=409, detail="Repository already exists")

    config = repo.model_dump()
    await storage.create_repo(repo.name, config)

    doc_count = await storage.get_document_count(repo.name)
    repo_data = await storage.get_repo(repo.name)
    return RepoResponse(**config, document_count=doc_count, created_at=repo_data['created_at'])


@app.get("/api/repos")
async def list_repos():
    repos = await storage.list_repos()

    result = []
    for repo in repos:
        config = repo['config']
        doc_count = await storage.get_document_count(repo['name'])
        result.append(
            RepoResponse(
                **config,
                document_count=doc_count,
                created_at=repo['created_at']
            )
        )

    return result


@app.get("/api/repos/{name}")
async def get_repo(name: str):
    repo = await storage.get_repo(name)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    doc_count = await storage.get_document_count(name)
    return RepoResponse(
        **repo['config'],
        document_count=doc_count,
        created_at=repo['created_at']
    )


@app.put("/api/repos/{name}")
async def update_repo(name: str, updates: RepoUpdate):
    repo = await storage.get_repo(name)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    config = repo['config']
    update_data = updates.model_dump(exclude_unset=True)
    config.update(update_data)

    await storage.update_repo(name, config)

    doc_count = await storage.get_document_count(name)
    return RepoResponse(**config, document_count=doc_count, created_at=repo['created_at'])


@app.delete("/api/repos/{name}")
async def delete_repo(name: str):
    repo = await storage.get_repo(name)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    # Delete documents from SQLite (and repo record)
    await storage.delete_repo(name)

    # Delete ChromaDB collection
    rag_engine.delete_collection(name)

    return {"deleted": name}


async def _ingest_single(repo_name: str, text: str, source: str, metadata: dict, config: dict) -> dict:
    """Chunk, embed, store in ChromaDB and SQLite. Returns doc info."""
    result = await rag_engine.ingest_text(repo_name, text, source, metadata, config)
    chunks = result['chunks']
    embeddings = result['embeddings']
    chunk_data = result['chunk_data']

    # Store original in SQLite first to get doc_id
    doc_id = await storage.store_document(repo_name, source, text, metadata, chunks)

    # Add to ChromaDB with doc_id
    rag_engine.add_chunks(repo_name, chunk_data, embeddings, doc_id, metadata)

    return {'doc_id': doc_id, 'chunks': chunks, 'source': source}


@app.post("/api/repos/{name}/ingest")
async def ingest(name: str, request: IngestRequest):
    repo = await storage.get_repo(name)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    config = repo['config']
    metadata = request.metadata or {}
    total_chunks = 0
    ingested_count = 0

    try:
        if request.text:
            # Text mode
            source = metadata.get('source_file', 'direct_input')
            info = await _ingest_single(name, request.text, source, metadata, config)
            ingested_count = 1
            total_chunks = info['chunks']

        elif request.file_path:
            # File mode
            file_path = Path(request.file_path)
            if not file_path.exists():
                raise HTTPException(status_code=400, detail=f"File not found: {request.file_path}")

            text = file_path.read_text(encoding='utf-8')
            info = await _ingest_single(name, text, str(file_path), metadata, config)
            ingested_count = 1
            total_chunks = info['chunks']

        elif request.directory_path:
            # Directory mode
            dir_path = Path(request.directory_path)
            if not dir_path.exists():
                raise HTTPException(status_code=400, detail=f"Directory not found: {request.directory_path}")

            glob_pattern = request.glob_pattern or '*.md'
            files = list(dir_path.glob(glob_pattern))

            for file_path in files:
                try:
                    text = file_path.read_text(encoding='utf-8')
                    file_meta = {**metadata, 'source_file': str(file_path)}
                    info = await _ingest_single(name, text, str(file_path), file_meta, config)
                    ingested_count += 1
                    total_chunks += info['chunks']
                except Exception:
                    continue  # Skip unreadable files

        else:
            raise HTTPException(status_code=400, detail="Provide text, file_path, or directory_path")

    except ValueError as e:
        if 'JINA_API_KEY' in str(e):
            raise HTTPException(status_code=503, detail=str(e))
        raise

    return {"ingested": ingested_count, "chunks": total_chunks}


@app.get("/api/repos/{name}/documents")
async def get_documents(name: str):
    repo = await storage.get_repo(name)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    docs = await storage.get_documents(name)
    return [DocumentInfo(**doc) for doc in docs]


@app.delete("/api/repos/{name}/documents/{doc_id}")
async def delete_document(name: str, doc_id: str):
    doc = await storage.get_document(doc_id)
    if not doc or doc['repo_name'] != name:
        raise HTTPException(status_code=404, detail="Document not found")

    # Delete from SQLite
    await storage.delete_document(doc_id)

    # Delete chunks from ChromaDB
    rag_engine.delete_by_doc_id(name, doc_id)

    return {"deleted": doc_id}


@app.post("/api/repos/{name}/search")
async def search(name: str, request: SearchRequest):
    repo = await storage.get_repo(name)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    try:
        results = await rag_engine.search(
            name, request.query, repo['config'], request.limit
        )

        return SearchResponse(
            query=request.query,
            repo_name=name,
            results=[
                SearchResult(
                    chunk_text=r['text'],
                    source=r['source'],
                    score=r['score'],
                    metadata=r['metadata']
                )
                for r in results
            ]
        )
    except ValueError as e:
        if 'JINA_API_KEY' in str(e):
            raise HTTPException(status_code=503, detail=str(e))
        raise


@app.post("/api/rerank")
async def rerank(request: RerankRequest):
    """Rerank documents against a query using JINA Reranker."""
    try:
        results = await rag_engine.rerank(
            query=request.query,
            documents=request.documents,
            top_n=request.top_n,
            model=request.model,
        )
        return RerankResponse(
            query=request.query,
            results=[RerankResult(**r) for r in results]
        )
    except ValueError as e:
        if 'JINA_API_KEY' in str(e):
            raise HTTPException(status_code=503, detail=str(e))
        raise


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = Path(__file__).parent / 'templates' / 'index.html'
    return HTMLResponse(content=html_path.read_text())
