# ScienceMadeReadable — Search API for AI Agents

> Free, no-auth semantic search over ~200 million scholarly papers. Built for AI agents.

**Base URL**: `https://api.sciencemadereadable.com/api/data`

**Coverage**: ~125M papers for semantic search, ~200M for keyword/lookup. Updated daily from OpenAlex.

**Rate limit**: 30 requests/minute. HTTP 429 with `Retry-After` header when exceeded.

---

## Quick Start

```sh
B=https://api.sciencemadereadable.com/api/data

# Semantic search (plain language)
curl -G "$B/search" --data-urlencode "q=does intermittent fasting help weight loss" -d k=5 -d abstracts=false

# Keyword search (boolean syntax)
curl -G "$B/search" --data-urlencode 'q="gut microbiome" AND (autism OR ASD) NOT mice' -d k=5

# Lookup by DOI
curl "$B/works/10.1126/science.aan8048"

# Similar papers
curl "$B/similar/W2782456798?k=5&abstracts=false"

# Citation walk (what to read next)
curl "$B/walk?id=10.1126/science.aan8048&k=30"
```

No-code URL: `https://api.sciencemadereadable.com/api/data/search/your+question+here?k=10`

---

## MCP Server (for Claude Code etc.)

```sh
claude mcp add --transport http --scope user science https://api.sciencemadereadable.com/mcp
```

Tools: `search_papers`, `get_papers`, `find_similar_papers`, `citation_walk`

---

## Key Endpoints

### GET /search?q=...

- `q`: plain language or boolean (auto-detects mode)
- `mode`: `auto` | `semantic` | `keyword`
- `k`: 1–100 results (default 10, no paging — ask for all at once)
- `abstracts=false`: ~10x smaller response, use for screening
- Filters: `year_from`, `year_to`, `type`, `open_access=true`, `pmc_open_access=true`
- `collection=smr`: only papers ScienceMadeReadable can open/rewrite (~3.9M papers)

### GET /works/{ref}

Look up one paper by W-number, DOI, PMCID, or URL. Full record.

### GET /similar/{ref}

Papers closest in meaning to a given paper. Same filters as /search.

### GET /walk?id=...

Citation walk: finds papers that cite the same references — effectively "what should this paper have also cited" / what to read next.

---

## Using It Well (Agent Tips)

- **Plain questions → semantic; precise terms → keyword.** "effects of screen time on sleep" → semantic. Named gene/drug/author's phrase → keyword with quotes.
- **Phrase like a paper, not a search box.** "effectiveness of dietary interventions for weight loss in adults" beats "how to lose weight". Biggest quality gain available.
- **Snowball**: best 2–3 results → `/similar/{id}` for more like them → `/walk?id=` for their citation neighborhood. Deduplicate by `id`.
- **Save tokens**: `abstracts=false` for screening, then `/works/{id}` only for papers you keep.
- **Cite** with DOI when present, else the `openalex` URL.
- **One big call > many small ones**: `k=100` rather than several `k=10` searches.

---

## Result Fields (Key)

| field | meaning |
|---|---|
| `id` | OpenAlex W-number — use for /works, /similar, /walk |
| `doi`, `pmcid` | identifiers |
| `title`, `abstract` | as OpenAlex has them |
| `year`, `date` | publication date |
| `type` | article, review, preprint, book-chapter, ... |
| `citations` | times cited (at snapshot date) |
| `is_oa`, `url`, `pdf_url` | open access and links |
| `smr` | 1 = ScienceMadeReadable can open/rewrite it |
| `junk` | 0–1 spam/non-scholarship score |
| `score` | semantic: cosine similarity; keyword: BM25 |

---

## Limits

- English titles+abstracts only (no full texts)
- Very recent papers arrive later (daily update from OpenAlex)
- `topic`/`field` labels are often wrong — use the text for classification
- `junk` score is a model, not a quality judge (crank papers can score clean)
- Retracted papers excluded from search results

---

## Sources

Paper records: OpenAlex (CC0). Embeddings: DenseOn. Operated for ScienceMadeReadable.

Full docs: `https://api.sciencemadereadable.com/api/data/docs`
LLM guide: `https://api.sciencemadereadable.com/api/data/llms.txt`
