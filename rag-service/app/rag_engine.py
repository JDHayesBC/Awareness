import os
import logging
import httpx
import chromadb
from pathlib import Path

logger = logging.getLogger(__name__)


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

    # How many candidates to pull from the vector index before reranking.
    #
    # Measured 2026-09-17 (Lyra, at Caia's insistence — the first number here was
    # itself instrument-shaped). The rescued document for "I fixed it in the command
    # line tool but every library caller is still broken" was first recorded at
    # "dense rank 25 of 25". That was a CEILING, not a rank: 25 was the fetch limit
    # and the document was merely last. Its true dense rank is 33.
    #
    # Candidate depth vs. reranked rank of that document (corpus: 2979 chunks):
    #
    #     depth  30  ->  MISS
    #     depth  33  ->  rank 1     <- the cliff sits exactly at its own dense rank
    #     depth  40  ->  rank 1     (the old value: 7 chunks of headroom, in 2979)
    #     depth 200  ->  rank 1     (deeper never degraded any case measured)
    #
    # The failure is silent: below the cliff the document simply does not exist, with
    # no error and no log line. 40 was not chosen against a measurement — it was
    # chosen against a number that was an artifact of how far I happened to look.
    #
    # Cost is roughly linear and small: median rerank latency 437 ms at depth 40,
    # 583 ms at 100, 969 ms at 200. 100 buys 67 chunks of headroom for ~150 ms.
    #
    # This is a corpus-relative constant. If tech-docs grows substantially, re-run the
    # sweep rather than assuming the margin held — a correct document drifting past
    # this line disappears without complaining.
    RERANK_CANDIDATES = 100

    async def search(self, repo_name: str, query: str, config: dict, limit: int | None) -> list[dict]:
        """Search repository: dense retrieve, then cross-encoder rerank.

        WHY THE RERANK STAGE EXISTS (2026-09-17). Dense-only retrieval here BURIES
        conversational, first-person queries — the exact shape a real recall moment
        takes. Not blind: the correct document is in the candidate set, at dense rank
        33 of 2979. The signal is there and the ranking cannot surface it, which is a
        drowning problem, not a blindness one — and that distinction is why the fix is
        over-fetch plus rerank rather than a different embedding. Same document, same
        content, four query shapes:

            declarative statement ........................ 0.5930  rank 1
            keyword-ish .................................. 0.3237  rank 1
            prose description of the situation ........... 0.1155  rank 1
            "I fixed it in the CLI but every library
             caller is still broken" .................... <0.1837  ABSENT from
                                                                   the top 10
                                                                   (dense rank 33)

        A bi-encoder embeds query and passage independently, so a short narrative
        query and a 1000-char passage barely meet. The cross-encoder reads both
        together and does. The reranker was already built, deployed and exposed at
        /api/rerank — it simply was not wired into this path.

        FAILURE POLICY: reranking is an IMPROVEMENT, never a dependency. Any failure
        (no JINA_API_KEY, API error, timeout, malformed response) falls back to the
        dense ordering. A search that returns worse results is a bad day; a search
        that raises is a broken sense.
        """
        query_embedding = (await self.embed_texts([query], config['embedding_model']))[0]
        search_limit = limit or config['max_results']

        if not config.get('rerank', True):
            return await self.search_vector(repo_name, query_embedding, search_limit)

        candidates = await self.search_vector(
            repo_name, query_embedding,
            max(search_limit, self.RERANK_CANDIDATES),
        )
        if len(candidates) <= 1:
            return candidates[:search_limit]

        try:
            ranked = await self.rerank(
                query,
                [c['text'] for c in candidates],
                top_n=search_limit,
                model=config.get('rerank_model', 'jina-reranker-v2-base-multilingual'),
            )
        except Exception as exc:
            # Loud in the log, silent to the caller — they still get real results.
            logger.warning(
                'rerank failed for repo %r (%s: %s) — returning dense ordering',
                repo_name, type(exc).__name__, exc,
            )
            return candidates[:search_limit]

        out = []
        for hit in ranked:
            # rerank() returns index/text/score only; carry the ORIGINAL row so
            # source and metadata survive. Dropping them would make the reranked
            # result unciteable, which is worse than not reranking.
            original = candidates[hit['index']]
            out.append({**original, 'score': hit['score'],
                        'dense_score': original.get('score')})
        return out[:search_limit]
