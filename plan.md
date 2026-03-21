# Hybrid Search Implementation Plan

## Goal

Add vector/semantic search on book **content** so users can search by concepts/topics (e.g. "machine learning optimization") even when those exact words aren't in the title. Combine with existing FTS5 keyword search on metadata (author, title) via hybrid approach.

## Technology Choices

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Embedding model | Voyage AI `voyage-3-lite` (512 dims) | Anthropic has no embeddings API. Voyage is their recommended partner. ~$2 for 1000 books. |
| Vector storage | `sqlite-vec` | Already using SQLite. No separate process. Brute-force KNN <100ms at this scale. |
| Hybrid strategy | Reciprocal Rank Fusion (RRF) | Always run both FTS5 + vector, combine by rank. Score-agnostic, robust. |
| Content extraction | `pymupdf` (PDF), `ebooklib` (EPUB) | Already in deps. Other formats marked unsupported. |
| Chunking | 2000 chars, 256 char overlap, paragraph-aware | Good semantic density per chunk, aligns with embedding window. |

## Database Schema (Additions)

Three new tables alongside existing `books` + `books_fts`:

```sql
CREATE TABLE book_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    page_number INTEGER,
    text TEXT NOT NULL,
    UNIQUE(book_id, chunk_index)
);

CREATE VIRTUAL TABLE chunk_embeddings USING vec0(
    chunk_id INTEGER PRIMARY KEY,
    embedding float[512]
);

CREATE TABLE embedding_status (
    book_id INTEGER PRIMARY KEY REFERENCES books(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending',
    file_hash TEXT,
    chunk_count INTEGER DEFAULT 0,
    error_message TEXT,
    indexed_at TEXT
);
```

## New Module: `src/bookstuff/web/semantic.py`

| Function | Purpose |
|----------|---------|
| `extract_full_text(path, ext)` | Dispatch to PDF/EPUB extractors |
| `chunk_text(text, size, overlap)` | Paragraph-aware chunking |
| `generate_embeddings(texts, api_key)` | Batch Voyage AI calls (128/batch) |
| `init_semantic_db(conn)` | Create the 3 new tables |
| `index_book(conn, book_id, books_dir, api_key)` | Extract → chunk → embed → store |
| `index_pending_books(conn, books_dir, api_key)` | Background batch indexer |
| `semantic_search(conn, query, api_key, ...)` | Embed query → vector KNN → dedupe by book |
| `hybrid_search(conn, query, api_key, ...)` | FTS5 + vector → RRF fusion |

## Indexing Strategy

- **When**: Background reindex thread (existing 5-min cycle) calls `index_pending_books()` after `reindex()`
- **On upload**: Insert `embedding_status` row with `status='pending'`, background picks it up
- **Skip logic**: Books with `status='done'` are skipped unless `file_hash` changed (uses SHA-256 from `dedup.py`)
- **Batch size**: 10 books per cycle to avoid resource spikes
- **Failure**: Sets `status='failed'` with error message, retried next cycle
- **Unsupported formats**: MOBI/DJVU/AZW3/CBZ marked `status='unsupported'`, skipped permanently

## Changes to Existing Files

| File | Change |
|------|--------|
| `web/index.py` | Call `init_semantic_db()` in `init_db()`, add embedding indexing to reindex thread |
| `web/app.py` | Add `mode` param to `/api/search`, add `/api/search/status`, read `VOYAGE_API_KEY`, graceful fallback |
| `web/templates/index.html` | Show match context snippets for semantic hits |
| `web/static/style.css` | Style for snippet display |
| `pyproject.toml` | Add `voyageai`, `sqlite-vec` |
| `flake.nix` | Add new Python packages |
| `k8s/books-web.yaml` | Add `VOYAGE_API_KEY` secret env var |

## API Response (Enhanced)

```json
{
  "results": [{
    "id": 1, "filename": "...", "author": "...", "title": "...",
    "category": "...", "extension": "pdf", "size_bytes": 123, "path": "...",
    "match_type": "hybrid",
    "match_context": "...chunk excerpt...",
    "match_page": 42,
    "score": 0.031
  }],
  "count": 1,
  "mode": "hybrid"
}
```

## Phased Implementation

### Phase 1: Content Extraction & Chunking
- Create `semantic.py` with `extract_full_text_pdf()`, `extract_full_text_epub()`, `chunk_text()`
- Create `tests/test_semantic.py` with tests for extraction and chunking
- Zero external dependencies beyond what's already installed

### Phase 2: Schema & Embedding Pipeline
- Add `sqlite-vec` + `voyageai` to deps (`pyproject.toml`, `flake.nix`)
- Implement `init_semantic_db()`, `index_book()`, `index_pending_books()`
- File hash check for skip-if-unchanged logic
- Tests with mocked Voyage API

### Phase 3: Semantic + Hybrid Search
- Implement `semantic_search()` with vector KNN
- Implement `hybrid_search()` with RRF fusion (k=60)
- Deduplication (book appearing in multiple chunks → best match only)
- Tests for RRF fusion correctness

### Phase 4: API Integration
- Modify `app.py` `/api/search` with `mode` param (keyword|semantic|hybrid, default hybrid)
- Add `/api/search/status` endpoint
- Modify upload to create pending embedding status
- Wire embedding indexing into reindex thread
- Graceful fallback when `VOYAGE_API_KEY` not set

### Phase 5: Frontend Updates
- Match context snippets below search results
- "Content match" badge for semantic hits
- Search mode indicator

## Graceful Degradation

- No `VOYAGE_API_KEY` → FTS5-only, no errors
- `sqlite-vec` fails to load → semantic disabled, keyword works
- Embedding API unreachable → books marked `failed`, retried next cycle
- Unsupported formats → metadata-only search

## Resource Estimates

| Metric | Estimate |
|--------|----------|
| Disk (chunks + vectors) | ~150MB for 1000 books |
| Memory during search | ~10-20MB additional |
| Embedding cost | ~$2 for 1000 books |
| Search latency | <100ms vector + <1ms FTS5 |
| K8s limits (512Mi) | Should be sufficient |
