"""Tests for the web indexer module."""

import sqlite3
from pathlib import Path

import pytest

from bookstuff.web.index import (
    parse_filename,
    init_db,
    scan_books_dir,
    reindex,
    search,
    get_categories,
)


class TestParseFilename:
    def test_author_title_format(self):
        assert parse_filename("John Doe - Python Basics.pdf") == ("John Doe", "Python Basics")

    def test_no_separator(self):
        assert parse_filename("just_a_title.epub") == ("Unknown", "just_a_title")

    def test_multiple_separators(self):
        author, title = parse_filename("Author - Title - Subtitle.pdf")
        assert author == "Author"
        assert title == "Title - Subtitle"

    def test_whitespace_trimmed(self):
        assert parse_filename("  Author  -  Title  .pdf") == ("Author", "Title")


class TestInitDb:
    def test_creates_tables(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn = init_db(db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        names = {r[0] for r in tables}
        assert "books" in names
        assert "books_fts" in names
        conn.close()

    def test_idempotent(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn1 = init_db(db_path)
        conn1.close()
        conn2 = init_db(db_path)
        count = conn2.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        assert count == 0
        conn2.close()


class TestScanBooksDir:
    def test_finds_books_in_categories(self, tmp_path):
        cat_dir = tmp_path / "programming"
        cat_dir.mkdir()
        (cat_dir / "Author - Book.pdf").write_bytes(b"fake pdf content")
        (cat_dir / "Other - Guide.epub").write_bytes(b"fake epub")

        books = scan_books_dir(str(tmp_path))
        assert len(books) == 2
        assert books[0]["category"] == "programming"
        assert books[0]["author"] == "Author"
        assert books[0]["title"] == "Book"
        assert books[0]["extension"] == "pdf"

    def test_skips_hidden_dirs(self, tmp_path):
        hidden = tmp_path / ".hidden"
        hidden.mkdir()
        (hidden / "secret.pdf").write_bytes(b"hidden")
        assert scan_books_dir(str(tmp_path)) == []

    def test_skips_non_ebook_files(self, tmp_path):
        cat = tmp_path / "fiction"
        cat.mkdir()
        (cat / "readme.txt").write_text("not a book")
        (cat / "Real - Book.pdf").write_bytes(b"content")
        books = scan_books_dir(str(tmp_path))
        assert len(books) == 1
        assert books[0]["filename"] == "Real - Book.pdf"

    def test_nonexistent_dir(self):
        books = scan_books_dir("/nonexistent/path")
        assert books == []


class TestReindex:
    def test_indexes_books(self, tmp_path):
        cat = tmp_path / "science"
        cat.mkdir()
        (cat / "Hawking - Brief History.pdf").write_bytes(b"x" * 100)

        conn = init_db(str(tmp_path / "test.db"))
        count = reindex(conn, str(tmp_path))
        assert count == 1

        row = conn.execute("SELECT * FROM books").fetchone()
        assert row["author"] == "Hawking"
        assert row["title"] == "Brief History"
        assert row["category"] == "science"
        conn.close()

    def test_removes_deleted_books(self, tmp_path):
        cat = tmp_path / "math"
        cat.mkdir()
        book = cat / "Euler - Calculus.pdf"
        book.write_bytes(b"content")

        conn = init_db(str(tmp_path / "test.db"))
        reindex(conn, str(tmp_path))
        assert conn.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 1

        book.unlink()
        reindex(conn, str(tmp_path))
        assert conn.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 0
        conn.close()

    def test_no_duplicates_on_rerun(self, tmp_path):
        cat = tmp_path / "fiction"
        cat.mkdir()
        (cat / "Author - Title.epub").write_bytes(b"data")

        conn = init_db(str(tmp_path / "test.db"))
        reindex(conn, str(tmp_path))
        reindex(conn, str(tmp_path))
        assert conn.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 1
        conn.close()


class TestSearch:
    @pytest.fixture()
    def indexed_db(self, tmp_path):
        for cat, books in [
            ("programming", [
                ("Knuth - Art of Programming.pdf", b"x" * 500),
                ("Martin - Clean Code.epub", b"y" * 300),
            ]),
            ("mathematics", [
                ("Euler - Calculus.pdf", b"z" * 200),
            ]),
            ("fiction", [
                ("Tolkien - Lord of the Rings.epub", b"w" * 1000),
            ]),
        ]:
            d = tmp_path / cat
            d.mkdir()
            for name, content in books:
                (d / name).write_bytes(content)

        conn = init_db(str(tmp_path / "test.db"))
        reindex(conn, str(tmp_path))
        yield conn
        conn.close()

    def test_search_by_title(self, indexed_db):
        results = search(indexed_db, "Clean Code")
        assert len(results) == 1
        assert results[0]["title"] == "Clean Code"

    def test_search_by_author(self, indexed_db):
        results = search(indexed_db, "Tolkien")
        assert len(results) == 1
        assert results[0]["author"] == "Tolkien"

    def test_search_with_category_filter(self, indexed_db):
        results = search(indexed_db, "", category="programming")
        assert len(results) == 2
        assert all(r["category"] == "programming" for r in results)

    def test_empty_query_returns_all(self, indexed_db):
        results = search(indexed_db, "")
        assert len(results) == 4

    def test_search_with_limit(self, indexed_db):
        results = search(indexed_db, "", limit=2)
        assert len(results) == 2

    def test_no_results(self, indexed_db):
        results = search(indexed_db, "nonexistent book xyz")
        assert len(results) == 0


class TestGetCategories:
    def test_returns_categories_with_counts(self, tmp_path):
        for cat, count in [("fiction", 3), ("science", 1)]:
            d = tmp_path / cat
            d.mkdir()
            for i in range(count):
                (d / f"Author{i} - Book{i}.pdf").write_bytes(b"x")

        conn = init_db(str(tmp_path / "test.db"))
        reindex(conn, str(tmp_path))
        cats = get_categories(conn)
        assert len(cats) == 2
        cat_dict = {c["category"]: c["count"] for c in cats}
        assert cat_dict["fiction"] == 3
        assert cat_dict["science"] == 1
        conn.close()
