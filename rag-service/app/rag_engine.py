import os
import httpx
import chromadb
from pathlib import Path


class RAGEngine:
    def __init__(self, chroma_path: str = '/app/data/chromadb'):
        Path(chroma_path).mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=chroma_path)

    def chunk_text(self, text: str, chunk_size: int, chunk_overlap: int, source: str = '') -> list[dict]:
        """Recursive text splitter with overlap."""
        chunks = []
        separators = ['\n\n', '\n', '. ', ' ']

        def split_recursive(text: str, seps: list[str]) -> list[str]:
            if not seps or len(text) <= chunk_size:
                # Base case: split by character
                result = []
                for i in range(0, len(text), chunk_size - chunk_overlap):
                    result.append(text[i:i + chunk_size])
                return result

            sep = seps[0]
            parts = text.split(sep)
            result = []
            current = ""

            for part in parts:
                if len(current) + len(sep) + len(part) <= chunk_size:
                    current += (sep if current else "") + part
                else:
                    if current:
                        result.append(current)
                    if len(part) > chunk_size:
                        # Part too large, recurse with next separator
                        result.extend(split_recursive(part, seps[1:]))
                        current = ""
                    else:
                        current = part

            if current:
                result.append(current)

            return result

        raw_chunks = split_recursive(text, separators)

        # Add overlap
        for i, chunk in enumerate(raw_chunks):
            chunk_with_overlap = chunk
            if i > 0 and chunk_overlap > 0:
                # Prepend tail of previous chunk
                prev_tail = raw_chunks[i-1][-chunk_overlap:]
                chunk_with_overlap = prev_tail + chunk

            chunks.append({
                'text': chunk_with_overlap,
                'index': i,
                'source': source
            })

        return chunks

    async def embed_texts(self, texts: list[str], model: str) -> list[list[float]]:
        """Call Jina AI API to embed texts."""
        api_key = os.getenv('JINA_API_KEY')
        if not api_key:
            raise ValueError('JINA_API_KEY environment variable not set')

        embeddings = []
        batch_size = 100

        async with httpx.AsyncClient() as client:
            for i in range(0, len(texts), batch_size):
                batch = texts[i:i + batch_size]
                response = await client.post(
                    'https://api.jina.ai/v1/embeddings',
                    headers={'Authorization': f'Bearer {api_key}'},
                    json={'input': batch, 'model': model},
                    timeout=30.0
                )
                response.raise_for_status()
                data = response.json()
                embeddings.extend([item['embedding'] for item in data['data']])

        return embeddings

    def add_chunks(self, repo_name: str, chunks: list[dict], embeddings: list[list[float]], doc_id: str, metadata: dict):
        """Store chunks with embeddings in ChromaDB."""
        collection = self.client.get_or_create_collection(name=repo_name)

        ids = [f"{doc_id}_{i}" for i in range(len(chunks))]
        documents = [c['text'] for c in chunks]
        metadatas = [
            {
                'doc_id': doc_id,
                'source': chunks[i]['source'],
                'index': chunks[i]['index'],
                **metadata
            }
            for i in range(len(chunks))
        ]

        collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas
        )

    async def search_vector(self, repo_name: str, query_embedding: list[float], limit: int) -> list[dict]:
        """Search ChromaDB collection."""
        try:
            collection = self.client.get_collection(name=repo_name)
        except:
            return []

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=limit
        )

        output = []
        if results['documents'] and results['documents'][0]:
            for i in range(len(results['documents'][0])):
                distance = results['distances'][0][i]
                score = max(0.0, 1.0 - distance)
                output.append({
                    'text': results['documents'][0][i],
                    'source': results['metadatas'][0][i].get('source', ''),
                    'score': score,
                    'metadata': results['metadatas'][0][i]
                })

        return output

    def delete_collection(self, repo_name: str):
        """Delete ChromaDB collection."""
        try:
            self.client.delete_collection(name=repo_name)
        except:
            pass

    def delete_by_doc_id(self, repo_name: str, doc_id: str):
        """Delete all chunks for a document."""
        try:
            collection = self.client.get_collection(name=repo_name)
            collection.delete(where={'doc_id': doc_id})
        except:
            pass

    def get_collection_count(self, repo_name: str) -> int:
        """Get count of chunks in collection."""
        try:
            collection = self.client.get_collection(name=repo_name)
            return collection.count()
        except:
            return 0

    async def ingest_text(self, repo_name: str, text: str, source: str, metadata: dict, config: dict) -> dict:
        """Chunk, embed, and store text."""
        chunks = self.chunk_text(
            text,
            config['chunk_size'],
            config['chunk_overlap'],
            source
        )

        texts = [c['text'] for c in chunks]
        embeddings = await self.embed_texts(texts, config['embedding_model'])

        # Generate doc_id (will be passed from main.py after storing in SQLite)
        return {'chunks': len(chunks), 'embeddings': embeddings, 'chunk_data': chunks}

    async def rerank(self, query: str, documents: list[str], top_n: int | None = None, model: str = 'jina-reranker-v2-base-multilingual') -> list[dict]:
        """Rerank documents against a query using JINA Reranker API."""
        api_key = os.getenv('JINA_API_KEY')
        if not api_key:
            raise ValueError('JINA_API_KEY environment variable not set')

        async with httpx.AsyncClient() as client:
            payload = {
                'model': model,
                'query': query,
                'documents': documents,
            }
            if top_n is not None:
                payload['top_n'] = top_n

            response = await client.post(
                'https://api.jina.ai/v1/rerank',
                headers={'Authorization': f'Bearer {api_key}'},
                json=payload,
                timeout=30.0
            )
            response.raise_for_status()
            data = response.json()

        results = []
        for item in data.get('results', []):
            results.append({
                'index': item['index'],
                'text': documents[item['index']],
                'score': item['relevance_score'],
            })

        return sorted(results, key=lambda x: x['score'], reverse=True)

    async def search(self, repo_name: str, query: str, config: dict, limit: int | None) -> list[dict]:
        """Search repository."""
        query_embedding = (await self.embed_texts([query], config['embedding_model']))[0]
        search_limit = limit or config['max_results']
        return await self.search_vector(repo_name, query_embedding, search_limit)
