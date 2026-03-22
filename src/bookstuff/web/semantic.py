"""Semantic search: text extraction, chunking, embeddings, and hybrid search."""

import hashlib
import logging
import os
import re
import sqlite3
import time
from html.parser import HTMLParser
from pathlib import Path

import fitz  # pymupdf
from ebooklib import epub

from bookstuff.web.embeddings import (
    EMBEDDING_DIMS,
    get_embedder,
    serialize_embedding,
)

logger = logging.getLogger(__name__)

CHUNK_SIZE = 2000  # characters
CHUNK_OVERLAP = 256
SUPPORTED_EXTENSIONS = {".pdf", ".epub"}
INDEX_BATCH_SIZE = 100


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

class _HTMLTextExtractor(HTMLParser):
    """Strip HTML tags and extract plain text."""

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def _strip_html(html: str) -> str:
    extractor = _HTMLTextExtractor()
    extractor.feed(html)
    return extractor.get_text()


def extract_full_text_pdf(book_path: str) -> tuple[str | None, list[int]]:
    """Extract full text from a PDF. Returns (text, page_char_offsets)."""
    try:
        with fitz.open(book_path) as doc:
            pages = []
            offsets = []
            total = 0
            for page in doc:
                text = page.get_text()
                offsets.append(total)
                pages.append(text)
                total += len(text)
            return "\n".join(pages), offsets
    except Exception as e:
        logger.warning("Could not extract PDF text from %s: %s", book_path, e)
        return None, []


def extract_full_text_epub(book_path: str) -> str | None:
    """Extract full text from an EPUB."""
    try:
        book = epub.read_epub(book_path)
        parts = []
        for item in book.get_items():
            if item.get_type() == 9:  # ITEM_DOCUMENT
                content = item.get_content()
                if isinstance(content, bytes):
                    content = content.decode("utf-8", errors="replace")
                text = _strip_html(content)
                if text.strip():
                    parts.append(text.strip())
        return "\n\n".join(parts) if parts else None
    except Exception as e:
        logger.warning("Could not extract EPUB text from %s: %s", book_path, e)
        return None


def extract_full_text(book_path: str, extension: str) -> tuple[str | None, list[int]]:
    """Extract full text from a book file.

    Returns (text, page_offsets). page_offsets is only populated for PDFs.
    """
    ext = extension.lower().lstrip(".")
    if ext == "pdf":
        return extract_full_text_pdf(book_path)
    elif ext == "epub":
        text = extract_full_text_epub(book_path)
        return text, []
    else:
        return None, []


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk_text(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
    page_offsets: list[int] | None = None,
) -> list[dict]:
    """Split text into overlapping chunks, preferring paragraph boundaries.

    Returns list of {"chunk_index": int, "text": str, "page_number": int | None}.
    """
    if not text or not text.strip():
        return []

    # Split into paragraphs
    paragraphs = re.split(r"\n\s*\n", text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    chunks = []
    current_parts: list[str] = []
    current_len = 0
    current_start_offset = 0  # character offset into original text
    text_offset = 0  # track where we are in the original text

    # Map paragraph index to its offset in the original text
    para_offsets: list[int] = []
    search_from = 0
    for p in paragraphs:
        idx = text.find(p, search_from)
        if idx == -1:
            idx = search_from
        para_offsets.append(idx)
        search_from = idx + len(p)

    def _page_for_offset(offset: int) -> int | None:
        if not page_offsets:
            return None
        # Binary search for the page containing this offset
        lo, hi = 0, len(page_offsets) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if page_offsets[mid] <= offset:
                lo = mid + 1
            else:
                hi = mid - 1
        return hi + 1  # 1-indexed page number

    def _flush():
        if current_parts:
            chunk_text_str = "\n\n".join(current_parts)
            chunks.append({
                "chunk_index": len(chunks),
                "text": chunk_text_str,
                "page_number": _page_for_offset(current_start_offset),
            })

    for i, para in enumerate(paragraphs):
        para_len = len(para)

        # If single paragraph exceeds chunk size, split it by sentences/words
        if para_len > chunk_size:
            _flush()
            current_parts = []
            current_len = 0

            # Split long paragraph into sub-chunks
            words = para.split()
            sub_parts: list[str] = []
            sub_len = 0
            for word in words:
                if sub_len + len(word) + 1 > chunk_size and sub_parts:
                    chunk_text_str = " ".join(sub_parts)
                    chunks.append({
                        "chunk_index": len(chunks),
                        "text": chunk_text_str,
                        "page_number": _page_for_offset(para_offsets[i]),
                    })
                    # Keep overlap
                    overlap_words = []
                    overlap_len = 0
                    for w in reversed(sub_parts):
                        if overlap_len + len(w) + 1 > overlap:
                            break
                        overlap_words.insert(0, w)
                        overlap_len += len(w) + 1
                    sub_parts = overlap_words
                    sub_len = overlap_len
                sub_parts.append(word)
                sub_len += len(word) + 1

            if sub_parts:
                current_parts = [" ".join(sub_parts)]
                current_len = sub_len
                current_start_offset = para_offsets[i]
            continue

        # Would adding this paragraph exceed chunk size?
        if current_len + para_len + 2 > chunk_size and current_parts:
            _flush()
            # Start new chunk with overlap from end of previous
            overlap_text = "\n\n".join(current_parts)
            if len(overlap_text) > overlap:
                overlap_text = overlap_text[-overlap:]
            current_parts = [overlap_text] if overlap_text.strip() else []
            current_len = len(overlap_text) if overlap_text.strip() else 0
            current_start_offset = para_offsets[i] - current_len

        if not current_parts:
            current_start_offset = para_offsets[i]

        current_parts.append(para)
        current_len += para_len + 2

    _flush()
    return chunks


# ---------------------------------------------------------------------------
# File hashing (reuse pattern from dedup.py)
# ---------------------------------------------------------------------------

def hash_file(path: str, chunk_size: int = 8192) -> str:
    """Compute SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            sha256.update(chunk)
    return sha256.hexdigest()


# ---------------------------------------------------------------------------
# Database schema
# ---------------------------------------------------------------------------

_CURRENT_MODEL = "all-MiniLM-L6-v2"


def init_semantic_db(conn: sqlite3.Connection) -> None:
    """Create semantic search tables. Safe to call multiple times."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS book_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            page_number INTEGER,
            text TEXT NOT NULL,
            UNIQUE(book_id, chunk_index)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS embedding_status (
            book_id INTEGER PRIMARY KEY REFERENCES books(id) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'pending',
            file_hash TEXT,
            chunk_count INTEGER DEFAULT 0,
            error_message TEXT,
            indexed_at TEXT
        )
    """)
    # Track which model was used — reset embeddings if it changes
    conn.execute("""
        CREATE TABLE IF NOT EXISTS embedding_model (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            model_name TEXT NOT NULL,
            dims INTEGER NOT NULL
        )
    """)
    conn.commit()

    # Check if model changed — if so, wipe old embeddings
    row = conn.execute("SELECT model_name, dims FROM embedding_model WHERE id = 1").fetchone()
    need_reset = False
    if row is None:
        # First run with migration tracking — check if old embeddings exist
        # Use sqlite_master instead of querying the table (vec0 extension not loaded yet)
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunk_embeddings'"
        ).fetchone()
        if exists:
            need_reset = True
            logger.info("Found pre-existing chunk_embeddings without model tracking — resetting")
    elif row[0] != _CURRENT_MODEL or row[1] != EMBEDDING_DIMS:
        need_reset = True
        logger.info(
            "Embedding model changed from %s/%d to %s/%d — resetting all embeddings",
            row[0], row[1], _CURRENT_MODEL, EMBEDDING_DIMS,
        )

    # Load sqlite-vec early — needed for DROP TABLE on vec0 virtual tables
    vec_available = _load_sqlite_vec(conn)

    if need_reset:
        conn.execute("DELETE FROM book_chunks")
        conn.execute("UPDATE embedding_status SET status = 'pending', file_hash = NULL, chunk_count = 0")
        if vec_available:
            conn.execute("DROP TABLE IF EXISTS chunk_embeddings")
        conn.execute("DELETE FROM embedding_model")

    conn.execute(
        "INSERT OR REPLACE INTO embedding_model (id, model_name, dims) VALUES (1, ?, ?)",
        (_CURRENT_MODEL, EMBEDDING_DIMS),
    )
    conn.commit()

    # sqlite-vec virtual table — created only if extension is available
    if vec_available:
        conn.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS chunk_embeddings USING vec0(
                chunk_id INTEGER PRIMARY KEY,
                embedding float[{EMBEDDING_DIMS}]
            )
        """)
    conn.commit()


def _load_sqlite_vec(conn: sqlite3.Connection) -> bool:
    """Try to load the sqlite-vec extension. Returns True on success."""
    try:
        conn.enable_load_extension(True)
        import sqlite_vec
        sqlite_vec.load(conn)
        return True
    except Exception as e:
        logger.warning("sqlite-vec not available, semantic search disabled: %s", e)
        return False


def is_semantic_available(conn: sqlite3.Connection) -> bool:
    """Check if the semantic search tables exist and sqlite-vec is loaded."""
    try:
        conn.execute("SELECT 1 FROM chunk_embeddings LIMIT 0")
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Text quality validation
# ---------------------------------------------------------------------------

def is_garbled_text(text: str, sample_size: int = 2000) -> bool:
    """Detect garbled/corrupted text from broken PDF font encodings.

    Checks a sample of the text for a high ratio of non-printable characters,
    control characters, or Unicode replacement characters that indicate the
    PDF text extraction produced garbage.
    """
    sample = text[:sample_size]
    if not sample:
        return True

    bad_chars = 0
    for ch in sample:
        cp = ord(ch)
        # Control characters (except newline, tab, carriage return)
        if cp < 32 and cp not in (9, 10, 13):
            bad_chars += 1
        # Unicode replacement character
        elif cp == 0xFFFD:
            bad_chars += 1
        # Private use area
        elif 0xE000 <= cp <= 0xF8FF:
            bad_chars += 1
        # Specials block (includes interlinear annotation anchors, etc.)
        elif 0xFFF0 <= cp <= 0xFFFE:
            bad_chars += 1

    ratio = bad_chars / len(sample)
    return ratio > 0.05


# ---------------------------------------------------------------------------
# Indexing pipeline
# ---------------------------------------------------------------------------

def index_book(
    conn: sqlite3.Connection,
    book_id: int,
    book_path: str,
    extension: str,
) -> bool:
    """Index a single book: extract text, chunk, embed, store.

    Returns True on success.
    """
    embedder = get_embedder()
    if embedder is None:
        logger.warning("Embedding model not available, skipping book %d", book_id)
        return False

    # Mark as processing
    conn.execute(
        "UPDATE embedding_status SET status = 'processing', error_message = NULL WHERE book_id = ?",
        (book_id,),
    )
    conn.commit()

    try:
        # Check if format is supported
        if f".{extension}" not in SUPPORTED_EXTENSIONS:
            conn.execute(
                "UPDATE embedding_status SET status = 'unsupported' WHERE book_id = ?",
                (book_id,),
            )
            conn.commit()
            return False

        # Extract text
        text, page_offsets = extract_full_text(book_path, extension)
        if not text or len(text.strip()) < 100:
            conn.execute(
                "UPDATE embedding_status SET status = 'unsupported', error_message = 'No extractable text' WHERE book_id = ?",
                (book_id,),
            )
            conn.commit()
            return False

        # Reject garbled text from broken PDF font encodings
        if is_garbled_text(text):
            conn.execute(
                "UPDATE embedding_status SET status = 'unsupported', error_message = 'Garbled text detected' WHERE book_id = ?",
                (book_id,),
            )
            conn.commit()
            logger.info("Skipping book %d: garbled text detected", book_id)
            return False

        # Chunk
        chunks = chunk_text(text, page_offsets=page_offsets)
        if not chunks:
            conn.execute(
                "UPDATE embedding_status SET status = 'unsupported', error_message = 'No chunks produced' WHERE book_id = ?",
                (book_id,),
            )
            conn.commit()
            return False

        # Generate embeddings locally
        chunk_texts = [c["text"] for c in chunks]
        embeddings = embedder.embed(chunk_texts)

        # Clear old data for this book
        old_chunk_ids = [
            row[0]
            for row in conn.execute(
                "SELECT id FROM book_chunks WHERE book_id = ?", (book_id,)
            ).fetchall()
        ]
        if old_chunk_ids:
            conn.executemany(
                "DELETE FROM chunk_embeddings WHERE chunk_id = ?",
                [(cid,) for cid in old_chunk_ids],
            )
            conn.execute("DELETE FROM book_chunks WHERE book_id = ?", (book_id,))

        # Store chunks and embeddings
        for chunk, embedding in zip(chunks, embeddings):
            cursor = conn.execute(
                "INSERT INTO book_chunks (book_id, chunk_index, page_number, text) VALUES (?, ?, ?, ?)",
                (book_id, chunk["chunk_index"], chunk["page_number"], chunk["text"]),
            )
            chunk_id = cursor.lastrowid
            conn.execute(
                "INSERT INTO chunk_embeddings (chunk_id, embedding) VALUES (?, ?)",
                (chunk_id, serialize_embedding(embedding)),
            )

        # Update status
        file_hash = hash_file(book_path)
        conn.execute(
            """UPDATE embedding_status
               SET status = 'done', file_hash = ?, chunk_count = ?, indexed_at = ?, error_message = NULL
               WHERE book_id = ?""",
            (file_hash, len(chunks), time.strftime("%Y-%m-%dT%H:%M:%S"), book_id),
        )
        conn.commit()
        logger.info("Indexed book %d: %d chunks", book_id, len(chunks))
        return True

    except Exception as e:
        conn.rollback()
        conn.execute(
            "UPDATE embedding_status SET status = 'failed', error_message = ? WHERE book_id = ?",
            (str(e)[:500], book_id),
        )
        conn.commit()
        logger.exception("Failed to index book %d: %s", book_id, e)
        return False


def index_pending_books(
    conn: sqlite3.Connection,
    books_dir: str,
    batch_size: int = INDEX_BATCH_SIZE,
) -> int:
    """Index books that need embedding. Returns count of newly indexed books."""
    if get_embedder() is None:
        return 0

    if not is_semantic_available(conn):
        return 0

    # Recover books stuck in 'processing' from a previous crash/OOM kill
    stuck = conn.execute(
        "UPDATE embedding_status SET status = 'pending' WHERE status = 'processing'"
    ).rowcount
    if stuck:
        logger.info("Reset %d books stuck in 'processing' back to 'pending'", stuck)

    # Clean orphaned embeddings left by incomplete indexing runs
    orphaned = conn.execute(
        "DELETE FROM chunk_embeddings WHERE chunk_id NOT IN (SELECT id FROM book_chunks)"
    ).rowcount
    if orphaned:
        logger.info("Cleaned %d orphaned chunk embeddings", orphaned)

    conn.commit()

    # Ensure all books have an embedding_status row
    conn.execute("""
        INSERT OR IGNORE INTO embedding_status (book_id, status)
        SELECT id, 'pending' FROM books
        WHERE id NOT IN (SELECT book_id FROM embedding_status)
    """)
    conn.commit()

    # Find books to index: pending, failed, or done-but-hash-changed
    rows = conn.execute("""
        SELECT es.book_id, b.path, b.extension, es.status, es.file_hash
        FROM embedding_status es
        JOIN books b ON b.id = es.book_id
        WHERE es.status IN ('pending', 'failed')
        LIMIT ?
    """, (batch_size,)).fetchall()

    # Also check for hash changes on done books (smaller batch)
    if len(rows) < batch_size:
        done_rows = conn.execute("""
            SELECT es.book_id, b.path, b.extension, es.status, es.file_hash
            FROM embedding_status es
            JOIN books b ON b.id = es.book_id
            WHERE es.status = 'done'
            LIMIT ?
        """, (batch_size - len(rows),)).fetchall()

        for row in done_rows:
            book_path = os.path.join(books_dir, row[1])
            if os.path.exists(book_path):
                current_hash = hash_file(book_path)
                if current_hash != row[4]:
                    rows.append(row)

    indexed = 0
    for row in rows:
        book_id, rel_path, extension, status, _ = row
        book_path = os.path.join(books_dir, rel_path)
        if not os.path.exists(book_path):
            continue
        if index_book(conn, book_id, book_path, extension):
            indexed += 1

    if indexed:
        logger.info("Indexed %d books in this batch", indexed)
    return indexed


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def semantic_search(
    conn: sqlite3.Connection,
    query: str,
    category: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Search books by semantic similarity using local embeddings."""
    if not query.strip():
        return []

    embedder = get_embedder()
    if embedder is None or not is_semantic_available(conn):
        return []

    query_embedding = embedder.embed_query(query)
    query_bytes = serialize_embedding(query_embedding)

    # Vector search: get top chunks
    search_limit = limit * 3  # over-fetch since we dedupe by book
    rows = conn.execute("""
        SELECT ce.chunk_id, ce.distance,
               bc.book_id, bc.text, bc.page_number
        FROM chunk_embeddings ce
        JOIN book_chunks bc ON bc.id = ce.chunk_id
        WHERE ce.embedding MATCH ? AND k = ?
        ORDER BY ce.distance
    """, (query_bytes, search_limit)).fetchall()

    # Deduplicate by book_id (keep best match per book)
    seen_books: dict[int, dict] = {}
    for row in rows:
        chunk_id, distance, book_id, chunk_text, page_number = row
        if book_id in seen_books:
            continue

        # Get book metadata
        book_row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        if not book_row:
            continue

        book = dict(book_row)

        # Apply category filter
        if category and book["category"] != category:
            continue

        # Truncate match context
        context = chunk_text[:200] + "..." if len(chunk_text) > 200 else chunk_text

        book["match_context"] = context
        book["match_page"] = page_number
        book["distance"] = distance
        seen_books[book_id] = book

        if len(seen_books) >= limit:
            break

    return list(seen_books.values())


def hybrid_search(
    conn: sqlite3.Connection,
    query: str,
    category: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Combine FTS5 keyword search and semantic vector search using RRF.

    Falls back to FTS5-only if semantic search is unavailable.
    """
    from bookstuff.web.index import search as fts_search

    # If no query, just use browse mode from FTS
    if not query.strip():
        results = fts_search(conn, query, category=category, limit=limit, offset=offset)
        for r in results:
            r["match_type"] = "browse"
            r["match_context"] = None
            r["match_page"] = None
            r["score"] = 0
        return results

    # Run FTS5 search
    fts_results = fts_search(conn, query, category=category, limit=limit * 2, offset=0)

    # Run semantic search (local — no API call)
    sem_results = []
    if is_semantic_available(conn) and get_embedder() is not None:
        try:
            sem_results = semantic_search(conn, query, category=category, limit=limit * 2)
        except Exception as e:
            logger.warning("Semantic search failed, using keyword only: %s", e)

    # If no semantic results, return FTS with metadata
    if not sem_results:
        for r in fts_results:
            r["match_type"] = "keyword"
            r["match_context"] = None
            r["match_page"] = None
            r["score"] = 0
        return fts_results[offset : offset + limit]

    # RRF fusion (k=60)
    k = 60
    scores: dict[int, float] = {}
    match_info: dict[int, dict] = {}  # book_id -> {match_type, context, page, book_data}

    # Score FTS results by rank
    for rank, book in enumerate(fts_results):
        book_id = book["id"]
        scores[book_id] = scores.get(book_id, 0) + 1.0 / (k + rank + 1)
        match_info[book_id] = {
            "match_type": "keyword",
            "match_context": None,
            "match_page": None,
            "data": book,
        }

    # Score semantic results by rank
    for rank, book in enumerate(sem_results):
        book_id = book["id"]
        scores[book_id] = scores.get(book_id, 0) + 1.0 / (k + rank + 1)
        existing = match_info.get(book_id)
        if existing:
            # Appeared in both — hybrid match
            match_info[book_id]["match_type"] = "hybrid"
            match_info[book_id]["match_context"] = book.get("match_context")
            match_info[book_id]["match_page"] = book.get("match_page")
        else:
            match_info[book_id] = {
                "match_type": "semantic",
                "match_context": book.get("match_context"),
                "match_page": book.get("match_page"),
                "data": book,
            }

    # Sort by RRF score descending
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    results = []
    for book_id, score in ranked[offset : offset + limit]:
        info = match_info[book_id]
        book = dict(info["data"])
        # Remove internal fields
        book.pop("distance", None)
        book["match_type"] = info["match_type"]
        book["match_context"] = info["match_context"]
        book["match_page"] = info["match_page"]
        book["score"] = round(score, 6)
        results.append(book)

    return results


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def get_embedding_status(conn: sqlite3.Connection) -> dict:
    """Get summary of embedding indexing progress."""
    total = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]

    status_counts = {}
    rows = conn.execute(
        "SELECT status, COUNT(*) FROM embedding_status GROUP BY status"
    ).fetchall()
    for row in rows:
        status_counts[row[0]] = row[1]

    return {
        "total_books": total,
        "indexed": status_counts.get("done", 0),
        "pending": status_counts.get("pending", 0),
        "processing": status_counts.get("processing", 0),
        "failed": status_counts.get("failed", 0),
        "unsupported": status_counts.get("unsupported", 0),
        "semantic_available": total > 0,  # will be corrected by caller
    }
