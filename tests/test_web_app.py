"""Tests for the Flask web application."""

import json

import pytest

from bookstuff.web.app import create_app


@pytest.fixture()
def books_dir(tmp_path):
    """Create a temporary books directory with sample books."""
    for cat, books in [
        ("programming", [
            ("Knuth - Art of Programming.pdf", b"x" * 500),
            ("Martin - Clean Code.epub", b"y" * 300),
        ]),
        ("fiction", [
            ("Tolkien - The Hobbit.epub", b"w" * 1000),
        ]),
    ]:
        d = tmp_path / cat
        d.mkdir()
        for name, content in books:
            (d / name).write_bytes(content)
    return tmp_path


@pytest.fixture()
def client(books_dir):
    app = create_app(books_dir=str(books_dir), reindex_on_start=True)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class TestIndexPage:
    def test_returns_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"books.tomazvi.la" in resp.data


class TestSearchApi:
    def test_empty_query_returns_all(self, client):
        resp = client.get("/api/search?q=")
        data = json.loads(resp.data)
        assert data["count"] == 3

    def test_search_by_title(self, client):
        resp = client.get("/api/search?q=Clean+Code")
        data = json.loads(resp.data)
        assert data["count"] == 1
        assert data["results"][0]["title"] == "Clean Code"

    def test_filter_by_category(self, client):
        resp = client.get("/api/search?q=&category=fiction")
        data = json.loads(resp.data)
        assert data["count"] == 1
        assert data["results"][0]["category"] == "fiction"

    def test_search_with_category(self, client):
        resp = client.get("/api/search?q=Knuth&category=programming")
        data = json.loads(resp.data)
        assert data["count"] == 1

    def test_limit_parameter(self, client):
        resp = client.get("/api/search?q=&limit=1")
        data = json.loads(resp.data)
        assert data["count"] == 1

    def test_no_results(self, client):
        resp = client.get("/api/search?q=nonexistent+xyz")
        data = json.loads(resp.data)
        assert data["count"] == 0


class TestCategoriesApi:
    def test_returns_categories(self, client):
        resp = client.get("/api/categories")
        data = json.loads(resp.data)
        cats = {c["category"]: c["count"] for c in data["categories"]}
        assert cats["programming"] == 2
        assert cats["fiction"] == 1


class TestHealthApi:
    def test_health_check(self, client):
        resp = client.get("/api/health")
        data = json.loads(resp.data)
        assert data["status"] == "ok"
        assert data["books"] == 3


class TestDownload:
    def test_download_file(self, client):
        resp = client.get("/download/fiction/Tolkien%20-%20The%20Hobbit.epub")
        assert resp.status_code == 200
        assert resp.data == b"w" * 1000

    def test_download_nonexistent_category(self, client):
        resp = client.get("/download/nonexistent/file.pdf")
        assert resp.status_code == 404

    def test_download_nonexistent_file(self, client):
        resp = client.get("/download/fiction/nonexistent.pdf")
        assert resp.status_code == 404
