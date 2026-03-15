"""Tests for book cover preview generation and API endpoint."""

import json
import os
from unittest.mock import MagicMock, patch
import zipfile

import pytest

from bookstuff.web.preview import (
    generate_epub_preview,
    generate_pdf_preview,
    generate_preview,
    get_cache_dir,
    get_preview_path,
)


class TestCacheHelpers:
    def test_get_cache_dir_creates_directory(self, tmp_path):
        cache_dir = get_cache_dir(str(tmp_path))
        assert cache_dir == os.path.join(str(tmp_path), ".bookstuff-cache", "previews")
        assert os.path.isdir(cache_dir)

    def test_get_preview_path(self, tmp_path):
        path = get_preview_path(str(tmp_path), 42)
        assert path.endswith("42.jpg")
        assert ".bookstuff-cache/previews/" in path


class TestPdfPreview:
    def test_generates_jpeg_from_pdf(self, tmp_path):
        dest = str(tmp_path / "out.jpg")
        mock_pix = MagicMock()
        mock_page = MagicMock()
        mock_page.rect.width = 600
        mock_page.get_pixmap.return_value = mock_pix
        mock_doc = MagicMock()
        mock_doc.__getitem__ = MagicMock(return_value=mock_page)

        with patch("bookstuff.web.preview.fitz") as mock_fitz:
            mock_fitz.open.return_value = mock_doc
            mock_fitz.Matrix = MagicMock(return_value="matrix")
            result = generate_pdf_preview("/fake/book.pdf", dest, width=400)

        assert result is True
        mock_fitz.open.assert_called_once_with("/fake/book.pdf")
        mock_page.get_pixmap.assert_called_once_with(matrix="matrix")
        mock_pix.save.assert_called_once_with(dest)
        mock_doc.close.assert_called_once()

    def test_returns_false_on_error(self, tmp_path):
        dest = str(tmp_path / "out.jpg")
        with patch("bookstuff.web.preview.fitz") as mock_fitz:
            mock_fitz.open.side_effect = Exception("corrupt PDF")
            result = generate_pdf_preview("/fake/book.pdf", dest)
        assert result is False


class TestEpubPreview:
    def _make_epub(self, tmp_path, files_dict, opf_content=None):
        """Helper to create a minimal EPUB zip file."""
        epub_path = str(tmp_path / "test.epub")
        with zipfile.ZipFile(epub_path, "w") as zf:
            for name, data in files_dict.items():
                zf.writestr(name, data)
            if opf_content:
                zf.writestr("OEBPS/content.opf", opf_content)
        return epub_path

    def test_extracts_cover_from_opf_metadata(self, tmp_path):
        opf = """<?xml version="1.0"?>
        <package xmlns="http://www.idpf.org/2007/opf">
          <metadata>
            <meta name="cover" content="cover-img"/>
          </metadata>
          <manifest>
            <item id="cover-img" href="images/cover.jpg" media-type="image/jpeg"/>
          </manifest>
        </package>"""
        epub_path = self._make_epub(tmp_path, {
            "OEBPS/images/cover.jpg": b"\xff\xd8fake-jpeg-data",
        }, opf_content=opf)

        dest = str(tmp_path / "out.jpg")
        result = generate_epub_preview(epub_path, dest)
        assert result is True
        assert os.path.exists(dest)
        with open(dest, "rb") as f:
            assert f.read() == b"\xff\xd8fake-jpeg-data"

    def test_extracts_cover_from_epub3_properties(self, tmp_path):
        opf = """<?xml version="1.0"?>
        <package xmlns="http://www.idpf.org/2007/opf">
          <metadata/>
          <manifest>
            <item id="cover" href="cover.png" media-type="image/png" properties="cover-image"/>
          </manifest>
        </package>"""
        epub_path = self._make_epub(tmp_path, {
            "OEBPS/cover.png": b"fake-png-data",
        }, opf_content=opf)

        dest = str(tmp_path / "out.jpg")
        result = generate_epub_preview(epub_path, dest)
        assert result is True
        with open(dest, "rb") as f:
            assert f.read() == b"fake-png-data"

    def test_falls_back_to_filename_heuristic(self, tmp_path):
        epub_path = self._make_epub(tmp_path, {
            "cover.jpg": b"cover-data",
            "chapter1.xhtml": b"<html></html>",
        })
        dest = str(tmp_path / "out.jpg")
        result = generate_epub_preview(epub_path, dest)
        assert result is True
        with open(dest, "rb") as f:
            assert f.read() == b"cover-data"

    def test_falls_back_to_first_image(self, tmp_path):
        epub_path = self._make_epub(tmp_path, {
            "images/fig1.jpg": b"first-image",
            "text/ch1.xhtml": b"<html></html>",
        })
        dest = str(tmp_path / "out.jpg")
        result = generate_epub_preview(epub_path, dest)
        assert result is True
        with open(dest, "rb") as f:
            assert f.read() == b"first-image"

    def test_returns_false_for_epub_with_no_images(self, tmp_path):
        epub_path = self._make_epub(tmp_path, {
            "text/ch1.xhtml": b"<html></html>",
        })
        dest = str(tmp_path / "out.jpg")
        result = generate_epub_preview(epub_path, dest)
        assert result is False

    def test_returns_false_for_corrupt_file(self, tmp_path):
        bad_path = str(tmp_path / "bad.epub")
        with open(bad_path, "wb") as f:
            f.write(b"not a zip file")
        dest = str(tmp_path / "out.jpg")
        result = generate_epub_preview(bad_path, dest)
        assert result is False


class TestGeneratePreview:
    def test_returns_cached_preview(self, tmp_path):
        books_dir = str(tmp_path)
        cache_dir = os.path.join(books_dir, ".bookstuff-cache", "previews")
        os.makedirs(cache_dir)
        cached = os.path.join(cache_dir, "7.jpg")
        with open(cached, "wb") as f:
            f.write(b"cached")

        result = generate_preview(books_dir, 7, "/any/path.pdf", "pdf")
        assert result == cached

    def test_calls_pdf_generator(self, tmp_path):
        books_dir = str(tmp_path)
        with patch("bookstuff.web.preview.generate_pdf_preview", return_value=True) as mock_gen:
            result = generate_preview(books_dir, 1, "/book.pdf", "pdf")
        assert result is not None
        assert result.endswith("1.jpg")
        mock_gen.assert_called_once()

    def test_calls_epub_generator(self, tmp_path):
        books_dir = str(tmp_path)
        with patch("bookstuff.web.preview.generate_epub_preview", return_value=True) as mock_gen:
            result = generate_preview(books_dir, 2, "/book.epub", "epub")
        assert result is not None
        mock_gen.assert_called_once()

    def test_returns_none_for_unsupported_format(self, tmp_path):
        books_dir = str(tmp_path)
        result = generate_preview(books_dir, 3, "/book.mobi", "mobi")
        assert result is None

    def test_returns_none_for_djvu(self, tmp_path):
        result = generate_preview(str(tmp_path), 4, "/book.djvu", "djvu")
        assert result is None

    def test_cleans_up_on_failure(self, tmp_path):
        books_dir = str(tmp_path)
        # Create a partial file that would exist after failed generation
        cache_dir = os.path.join(books_dir, ".bookstuff-cache", "previews")
        os.makedirs(cache_dir)

        def fake_fail(book_path, dest, **kwargs):
            # Simulate partial write then failure
            with open(dest, "wb") as f:
                f.write(b"partial")
            return False

        with patch("bookstuff.web.preview.generate_pdf_preview", side_effect=fake_fail):
            result = generate_preview(books_dir, 5, "/book.pdf", "pdf")

        assert result is None
        assert not os.path.exists(os.path.join(cache_dir, "5.jpg"))


class TestWebEndpoints:
    """Tests for the /api/preview/<book_id> and /book/<book_id> routes."""

    @pytest.fixture()
    def books_dir(self, tmp_path):
        d = tmp_path / "programming"
        d.mkdir()
        (d / "Knuth - Art of Programming.pdf").write_bytes(b"x" * 500)
        d2 = tmp_path / "fiction"
        d2.mkdir()
        (d2 / "Tolkien - The Hobbit.epub").write_bytes(b"y" * 300)
        return tmp_path

    @pytest.fixture()
    def client(self, books_dir):
        from bookstuff.web.app import create_app
        app = create_app(books_dir=str(books_dir), reindex_on_start=True)
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c

    def _get_book_id(self, client, title_fragment):
        resp = client.get(f"/api/search?q={title_fragment}")
        data = json.loads(resp.data)
        return data["results"][0]["id"]

    def test_preview_returns_jpeg(self, client, books_dir):
        book_id = self._get_book_id(client, "Knuth")
        cache_dir = os.path.join(str(books_dir), ".bookstuff-cache", "previews")
        os.makedirs(cache_dir, exist_ok=True)
        preview_file = os.path.join(cache_dir, f"{book_id}.jpg")
        with open(preview_file, "wb") as f:
            f.write(b"\xff\xd8fake-jpeg")

        resp = client.get(f"/api/preview/{book_id}")
        assert resp.status_code == 200
        assert resp.content_type == "image/jpeg"
        assert resp.data == b"\xff\xd8fake-jpeg"

    def test_preview_returns_404_for_nonexistent_book(self, client):
        resp = client.get("/api/preview/99999")
        assert resp.status_code == 404

    def test_preview_returns_404_for_unsupported_format(self, client, books_dir):
        d = books_dir / "fiction"
        (d / "Test - Book.mobi").write_bytes(b"mobi-content")
        from bookstuff.web.app import create_app
        app = create_app(books_dir=str(books_dir), reindex_on_start=True)
        app.config["TESTING"] = True
        with app.test_client() as c:
            book_id = self._get_book_id(c, "Test")
            resp = c.get(f"/api/preview/{book_id}")
            assert resp.status_code == 404

    def test_book_detail_page(self, client):
        book_id = self._get_book_id(client, "Knuth")
        resp = client.get(f"/book/{book_id}")
        assert resp.status_code == 200
        assert b"Art of Programming" in resp.data
        assert b"Knuth" in resp.data
        assert b"programming" in resp.data

    def test_book_detail_404_for_nonexistent(self, client):
        resp = client.get("/book/99999")
        assert resp.status_code == 404
