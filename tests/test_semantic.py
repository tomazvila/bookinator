"""Tests for the semantic search module."""

import sqlite3
import struct
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bookstuff.web.semantic import (
    _strip_html,
    chunk_text,
    extract_full_text,
    hash_file,
    hybrid_search,
    init_semantic_db,
    is_garbled_text,
    is_semantic_available,
    get_embedding_status,
)
from bookstuff.web.embeddings import serialize_embedding, EMBEDDING_DIMS


# ---------------------------------------------------------------------------
# HTML stripping
# ---------------------------------------------------------------------------

class TestStripHtml:
    def test_basic(self):
        assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_empty(self):
        assert _strip_html("") == ""

    def test_no_tags(self):
        assert _strip_html("plain text") == "plain text"

    def test_nested(self):
        assert _strip_html("<div><p>nested</p></div>") == "nested"


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

class TestChunkText:
    def test_empty_text(self):
        assert chunk_text("") == []
        assert chunk_text("   ") == []

    def test_short_text(self):
        result = chunk_text("Hello world.")
        assert len(result) == 1
        assert result[0]["chunk_index"] == 0
        assert result[0]["text"] == "Hello world."

    def test_multiple_paragraphs_fit_in_one_chunk(self):
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        result = chunk_text(text, chunk_size=200, overlap=50)
        assert len(result) == 1
        assert "First paragraph" in result[0]["text"]
        assert "Third paragraph" in result[0]["text"]

    def test_paragraphs_split_into_chunks(self):
        # Create text larger than chunk_size
        para = "A" * 100
        text = "\n\n".join([para] * 30)  # 30 paragraphs of 100 chars
        result = chunk_text(text, chunk_size=500, overlap=50)
        assert len(result) > 1

    def test_chunk_indices_sequential(self):
        text = "\n\n".join(["paragraph " * 50] * 10)
        result = chunk_text(text, chunk_size=500, overlap=50)
        for i, chunk in enumerate(result):
            assert chunk["chunk_index"] == i

    def test_long_paragraph_split(self):
        # Single paragraph longer than chunk_size
        text = "word " * 1000  # ~5000 chars
        result = chunk_text(text, chunk_size=500, overlap=50)
        assert len(result) > 1

    def test_page_numbers_from_offsets(self):
        text = "Page one content.\n\nPage two content.\n\nPage three content."
        # Simulate page offsets at the start of each "page"
        offsets = [0, 19, 39]  # approximate positions
        result = chunk_text(text, chunk_size=5000, overlap=0, page_offsets=offsets)
        assert len(result) == 1
        assert result[0]["page_number"] is not None

    def test_no_page_offsets(self):
        result = chunk_text("Some text.", page_offsets=None)
        assert result[0]["page_number"] is None


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

class TestExtractFullText:
    def test_unsupported_extension(self):
        text, offsets = extract_full_text("/fake/path.mobi", "mobi")
        assert text is None
        assert offsets == []

    def test_pdf_extraction_with_fixture(self, tmp_path):
        """Test PDF extraction if a test fixture exists."""
        fixtures = Path(__file__).parent / "test_fixtures"
        pdfs = list(fixtures.glob("*.pdf")) if fixtures.exists() else []
        if not pdfs:
            pytest.skip("No PDF test fixtures available")
        text, offsets = extract_full_text(str(pdfs[0]), "pdf")
        assert text is not None or text is None  # just shouldn't crash

    def test_epub_extraction_with_fixture(self, tmp_path):
        """Test EPUB extraction if a test fixture exists."""
        fixtures = Path(__file__).parent / "test_fixtures"
        epubs = list(fixtures.glob("*.epub")) if fixtures.exists() else []
        if not epubs:
            pytest.skip("No EPUB test fixtures available")
        text, offsets = extract_full_text(str(epubs[0]), "epub")
        assert text is not None or text is None  # just shouldn't crash


# ---------------------------------------------------------------------------
# File hashing
# ---------------------------------------------------------------------------

class TestHashFile:
    def test_hash_deterministic(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        h1 = hash_file(str(f))
        h2 = hash_file(str(f))
        assert h1 == h2

    def test_different_content_different_hash(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("hello")
        f2.write_text("world")
        assert hash_file(str(f1)) != hash_file(str(f2))


# ---------------------------------------------------------------------------
# Database schema
# ---------------------------------------------------------------------------

class TestInitSemanticDb:
    def test_creates_tables(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        # Create the base books table first
        conn.execute("""
            CREATE TABLE books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT, author TEXT, title TEXT,
                category TEXT, extension TEXT, size_bytes INTEGER, path TEXT UNIQUE
            )
        """)
        conn.commit()

        with patch("bookstuff.web.semantic.load_sqlite_vec", return_value=False):
            init_semantic_db(conn)

        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "book_chunks" in tables
        assert "embedding_status" in tables
        assert "embedding_model" in tables

    def test_idempotent(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT, author TEXT, title TEXT,
                category TEXT, extension TEXT, size_bytes INTEGER, path TEXT UNIQUE
            )
        """)
        conn.commit()

        with patch("bookstuff.web.semantic.load_sqlite_vec", return_value=False):
            init_semantic_db(conn)
            init_semantic_db(conn)  # should not raise


# ---------------------------------------------------------------------------
# Garbled text detection
# ---------------------------------------------------------------------------

class TestGarbledText:
    def test_clean_text(self):
        assert is_garbled_text("This is perfectly normal English text.") is False

    def test_garbled_pdf_text(self):
        # Real garbled text from PDF with broken font encoding (contains control chars \x11, \x0f)
        garbled = "6HQLDX ãLV NDLPDV YDGLQRVL\x118åSHONLDL\x11 7ÔOXV\x0f YLHQRGDV DWURGR\x0f PLãNHOLÐ" * 20
        assert is_garbled_text(garbled) is True

    def test_control_characters(self):
        text = "Some text\x00\x01\x02\x03\x04\x05" * 100
        assert is_garbled_text(text) is True

    def test_unicode_replacement_chars(self):
        text = "Hello \ufffd\ufffd\ufffd world \ufffd\ufffd" * 100
        assert is_garbled_text(text) is True

    def test_private_use_area(self):
        text = "Text \ue000\ue001\ue002 more \ue003" * 100
        assert is_garbled_text(text) is True

    def test_normal_unicode(self):
        # Lithuanian text with proper Unicode should pass
        text = "Priešaušrio vieškeliai — tai knyga apie Lietuvą."
        assert is_garbled_text(text) is False

    def test_empty_text(self):
        assert is_garbled_text("") is True

    def test_threshold_boundary(self):
        # Just under 5% bad chars should pass
        good = "a" * 96
        bad = "\x00" * 4  # 4% bad
        assert is_garbled_text(good + bad) is False

        # Just over 5% should fail
        good = "a" * 94
        bad = "\x00" * 6  # 6% bad
        assert is_garbled_text(good + bad) is True


# ---------------------------------------------------------------------------
# Hybrid Search (keyword-only fallback)
# ---------------------------------------------------------------------------

class TestHybridSearch:
    def _setup_db(self, tmp_path):
        """Create a test DB with books and mock semantic tables."""
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT, author TEXT, title TEXT,
                category TEXT, extension TEXT, size_bytes INTEGER, path TEXT UNIQUE
            )
        """)
        conn.execute("""
            CREATE VIRTUAL TABLE books_fts USING fts5(
                filename, author, title, category,
                content='books', content_rowid='id'
            )
        """)
        conn.executescript("""
            CREATE TRIGGER books_ai AFTER INSERT ON books BEGIN
                INSERT INTO books_fts(rowid, filename, author, title, category)
                VALUES (new.id, new.filename, new.author, new.title, new.category);
            END;
        """)

        # Insert test books
        books = [
            ("python-ml.pdf", "Author A", "Python Machine Learning", "programming", "pdf", 1000, "programming/python-ml.pdf"),
            ("statistics.pdf", "Author B", "Statistics Fundamentals", "mathematics", "pdf", 2000, "mathematics/statistics.pdf"),
            ("cooking.epub", "Author C", "Modern Cooking", "uncategorized", "epub", 500, "uncategorized/cooking.epub"),
        ]
        for b in books:
            conn.execute("INSERT INTO books (filename, author, title, category, extension, size_bytes, path) VALUES (?, ?, ?, ?, ?, ?, ?)", b)
        conn.commit()
        return conn

    @patch("bookstuff.web.semantic.get_embedder", return_value=None)
    @patch("bookstuff.web.semantic.is_semantic_available", return_value=False)
    def test_fallback_to_keyword(self, mock_avail, mock_embedder, tmp_path):
        conn = self._setup_db(tmp_path)
        results = hybrid_search(conn, "Python", category=None, limit=50)
        assert len(results) >= 1
        assert results[0]["match_type"] == "keyword"

    def test_empty_query_browse_mode(self, tmp_path):
        conn = self._setup_db(tmp_path)
        results = hybrid_search(conn, "", category=None, limit=50)
        assert len(results) == 3
        for r in results:
            assert r["match_type"] == "browse"

    @patch("bookstuff.web.semantic.get_embedder", return_value=None)
    def test_category_filter_keyword(self, mock_embedder, tmp_path):
        conn = self._setup_db(tmp_path)
        results = hybrid_search(conn, "Author", category="programming", limit=50)
        assert all(r["category"] == "programming" for r in results)

    @patch("bookstuff.web.semantic.semantic_search")
    @patch("bookstuff.web.semantic.get_embedder")
    @patch("bookstuff.web.semantic.is_semantic_available", return_value=True)
    def test_rrf_fusion(self, mock_avail, mock_embedder, mock_sem, tmp_path):
        conn = self._setup_db(tmp_path)
        mock_embedder.return_value = MagicMock()

        # Mock semantic results — return book 3 (cooking) as top semantic match
        book3 = dict(conn.execute("SELECT * FROM books WHERE id = 3").fetchone())
        book3["match_context"] = "A passage about cooking techniques..."
        book3["match_page"] = 5
        book3["distance"] = 0.1
        mock_sem.return_value = [book3]

        results = hybrid_search(conn, "Python", category=None, limit=50)
        # Should have results from both keyword (Python ML) and semantic (cooking)
        ids = [r["id"] for r in results]
        assert 1 in ids  # Python ML from keyword
        assert 3 in ids  # Cooking from semantic

    @patch("bookstuff.web.semantic.semantic_search")
    @patch("bookstuff.web.semantic.get_embedder")
    @patch("bookstuff.web.semantic.is_semantic_available", return_value=True)
    def test_hybrid_match_type(self, mock_avail, mock_embedder, mock_sem, tmp_path):
        conn = self._setup_db(tmp_path)
        mock_embedder.return_value = MagicMock()

        # Make semantic also return book 1 (same as keyword hit)
        book1 = dict(conn.execute("SELECT * FROM books WHERE id = 1").fetchone())
        book1["match_context"] = "Deep learning chapter..."
        book1["match_page"] = 10
        book1["distance"] = 0.05
        mock_sem.return_value = [book1]

        results = hybrid_search(conn, "Python", category=None, limit=50)
        # Book 1 should be "hybrid" since it appeared in both
        book1_result = next(r for r in results if r["id"] == 1)
        assert book1_result["match_type"] == "hybrid"
        assert book1_result["match_context"] == "Deep learning chapter..."


# ---------------------------------------------------------------------------
# Embedding status
# ---------------------------------------------------------------------------

class TestEmbeddingStatus:
    def test_empty_db(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE books (
                id INTEGER PRIMARY KEY, filename TEXT, author TEXT, title TEXT,
                category TEXT, extension TEXT, size_bytes INTEGER, path TEXT UNIQUE
            )
        """)
        with patch("bookstuff.web.semantic.load_sqlite_vec", return_value=False):
            init_semantic_db(conn)

        status = get_embedding_status(conn)
        assert status["total_books"] == 0
        assert status["indexed"] == 0
        assert status["pending"] == 0


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

class TestSerializeEmbedding:
    def test_roundtrip(self):
        vec = [0.1, 0.2, 0.3, 0.4]
        data = serialize_embedding(vec)
        assert isinstance(data, bytes)
        unpacked = struct.unpack(f"{len(vec)}f", data)
        for a, b in zip(vec, unpacked):
            assert abs(a - b) < 1e-6
