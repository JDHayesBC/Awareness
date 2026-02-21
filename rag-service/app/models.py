from pydantic import BaseModel, Field


class RepoConfig(BaseModel):
    name: str
    description: str = ''
    chunk_size: int = 1000
    chunk_overlap: int = 200
    embedding_model: str = 'jina-embeddings-v3'
    max_results: int = 10
    metadata_fields: list[str] = Field(default_factory=lambda: ['source_file', 'title'])


class RepoCreate(RepoConfig):
    pass


class RepoUpdate(BaseModel):
    description: str | None = None
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    embedding_model: str | None = None
    max_results: int | None = None
    metadata_fields: list[str] | None = None


class RepoResponse(RepoConfig):
    document_count: int = 0
    created_at: str = ''


class IngestRequest(BaseModel):
    text: str | None = None
    file_path: str | None = None
    directory_path: str | None = None
    glob_pattern: str = '*.md'
    metadata: dict | None = None


class SearchRequest(BaseModel):
    query: str
    limit: int | None = None


class SearchResult(BaseModel):
    chunk_text: str
    source: str
    score: float
    metadata: dict = Field(default_factory=dict)


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    repo_name: str


class DocumentInfo(BaseModel):
    id: str
    source: str
    chunk_count: int = 0
    created_at: str
    metadata: dict = Field(default_factory=dict)


class RerankRequest(BaseModel):
    query: str
    documents: list[str]
    top_n: int | None = None
    model: str = 'jina-reranker-v2-base-multilingual'


class RerankResult(BaseModel):
    index: int
    text: str
    score: float


class RerankResponse(BaseModel):
    query: str
    results: list[RerankResult]
