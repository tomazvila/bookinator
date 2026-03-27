"""SQLite FTS5 indexer for the book collection."""

import logging
import os
import sqlite3
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

EBOOK_EXTENSIONS = {".pdf", ".epub", ".mobi", ".djvu", ".azw3", ".cbz"}
REINDEX_INTERVAL = 300  # 5 minutes


def parse_filename(filename: str) -> tuple[str, str]:
    """Parse 'Author - Title.ext' into (author, title).

    Falls back to ("Unknown", stem) if no separator found.
    """
    stem = Path(filename).stem
    if " - " in stem:
        author, title = stem.split(" - ", 1)
        return author.strip(), title.strip()
    return "Unknown", stem.strip()


def get_db_path(books_dir: str) -> str:
    return os.path.join(books_dir, ".bookstuff.db")


def init_db(db_path: str) -> sqlite3.Connection:
    """Create the database schema with FTS5 virtual table."""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            author TEXT NOT NULL,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            extension TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            path TEXT NOT NULL UNIQUE
        )
    """)
    # FTS5 virtual table for full-text search
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS books_fts USING fts5(
            filename, author, title, category,
            content='books',
            content_rowid='id'
        )
    """)
    # Triggers to keep FTS in sync
    conn.executescript("""
        CREATE TRIGGER IF NOT EXISTS books_ai AFTER INSERT ON books BEGIN
            INSERT INTO books_fts(rowid, filename, author, title, category)
            VALUES (new.id, new.filename, new.author, new.title, new.category);
        END;
        CREATE TRIGGER IF NOT EXISTS books_ad AFTER DELETE ON books BEGIN
            INSERT INTO books_fts(books_fts, rowid, filename, author, title, category)
            VALUES ('delete', old.id, old.filename, old.author, old.title, old.category);
        END;
        CREATE TRIGGER IF NOT EXISTS books_au AFTER UPDATE ON books BEGIN
            INSERT INTO books_fts(books_fts, rowid, filename, author, title, category)
            VALUES ('delete', old.id, old.filename, old.author, old.title, old.category);
            INSERT INTO books_fts(rowid, filename, author, title, category)
            VALUES (new.id, new.filename, new.author, new.title, new.category);
        END;
    """)
    conn.commit()

    # Initialize semantic search tables
    from bookstuff.web.semantic import init_semantic_db
    init_semantic_db(conn)

    return conn


def scan_books_dir(books_dir: str) -> list[dict]:
    """Scan the books directory for ebook files organized by category."""
    books = []
    base = Path(books_dir)
    if not base.exists():
        logger.warning("Books directory does not exist: %s", books_dir)
        return books

    for category_dir in sorted(base.iterdir()):
        if not category_dir.is_dir() or category_dir.name.startswith("."):
            continue
        category = category_dir.name
        try:
            for entry in sorted(category_dir.iterdir()):
                if not entry.is_file():
                    continue
                if entry.suffix.lower() not in EBOOK_EXTENSIONS:
                    continue
                author, title = parse_filename(entry.name)
                books.append({
                    "filename": entry.name,
                    "author": author,
                    "title": title,
                    "category": category,
                    "extension": entry.suffix.lower().lstrip("."),
                    "size_bytes": entry.stat().st_size,
                    "path": str(entry.relative_to(base)),
                })
        except PermissionError:
            logger.warning("Permission denied: %s", category_dir)

    return books


def reindex(conn: sqlite3.Connection, books_dir: str) -> int:
    """Full reindex: scan filesystem and sync to database.

    Returns the number of books indexed.
    """
    books = scan_books_dir(books_dir)
    existing = {row["path"] for row in conn.execute("SELECT path FROM books").fetchall()}
    new_paths = {b["path"] for b in books}

    # Remove books no longer on disk
    removed = existing - new_paths
    if removed:
        conn.executemany(
            "DELETE FROM books WHERE path = ?",
            [(p,) for p in removed],
        )

    # Upsert books
    for book in books:
        if book["path"] in existing:
            continue
        conn.execute(
            """INSERT OR IGNORE INTO books
               (filename, author, title, category, extension, size_bytes, path)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                book["filename"],
                book["author"],
                book["title"],
                book["category"],
                book["extension"],
                book["size_bytes"],
                book["path"],
            ),
        )

    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
    logger.info("Indexed %d books (%d new, %d removed)", count, len(new_paths - existing), len(removed))
    return count


def search(conn: sqlite3.Connection, query: str, category: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
    """Search books using FTS5."""
    if not query.strip():
        # Browse mode: return all books, optionally filtered by category
        if category:
            rows = conn.execute(
                "SELECT * FROM books WHERE category = ? ORDER BY author, title LIMIT ? OFFSET ?",
                (category, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM books ORDER BY author, title LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [dict(r) for r in rows]

    # FTS5 search — quote the query to handle special chars
    fts_query = " OR ".join(f'"{term}"' for term in query.split() if term)
    if category:
        rows = conn.execute(
            """SELECT b.* FROM books b
               JOIN books_fts ON books_fts.rowid = b.id
               WHERE books_fts MATCH ? AND b.category = ?
               ORDER BY rank LIMIT ? OFFSET ?""",
            (fts_query, category, limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT b.* FROM books b
               JOIN books_fts ON books_fts.rowid = b.id
               WHERE books_fts MATCH ?
               ORDER BY rank LIMIT ? OFFSET ?""",
            (fts_query, limit, offset),
        ).fetchall()

    return [dict(r) for r in rows]


def get_categories(conn: sqlite3.Connection) -> list[dict]:
    """Get all categories with their book counts."""
    rows = conn.execute(
        "SELECT category, COUNT(*) as count FROM books GROUP BY category ORDER BY category"
    ).fetchall()
    return [dict(r) for r in rows]


def start_reindex_thread(
    conn: sqlite3.Connection,
    books_dir: str,
    interval: int = REINDEX_INTERVAL,
) -> threading.Thread:
    """Start a background thread that re-indexes periodically."""
    def _loop():
        while True:
            time.sleep(interval)
            try:
                reindex(conn, books_dir)
            except Exception:
                logger.exception("Reindex failed")

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    return t
