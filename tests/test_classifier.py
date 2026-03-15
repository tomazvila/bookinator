"""Tests for the classifier module."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from bookstuff.classifier import (
    CATEGORIES,
    ClassificationResult,
    classify_batch,
    classify_book,
    normalize_filename,
    extract_pdf_metadata,
    extract_epub_metadata,
)


class TestCategories:
    def test_categories_list(self):
        assert "programming" in CATEGORIES
        assert "uncategorized" in CATEGORIES
        assert "fiction" in CATEGORIES
        assert len(CATEGORIES) == 15


class TestNormalizeFilename:
    def test_author_title(self):
        assert normalize_filename("John Doe", "Python Guide", ".pdf") == "John Doe - Python Guide.pdf"

    def test_unknown_author(self):
        assert normalize_filename(None, "Python Guide", ".pdf") == "Python Guide.pdf"

    def test_empty_author(self):
        assert normalize_filename("", "Python Guide", ".pdf") == "Python Guide.pdf"

    def test_cleans_special_chars(self):
        result = normalize_filename("Author", "Title: A Book/Story", ".pdf")
        assert "/" not in result
        assert ":" not in result

    def test_trims_whitespace(self):
        result = normalize_filename("  Author  ", "  Title  ", ".pdf")
        assert result == "Author - Title.pdf"

    def test_no_title(self):
        result = normalize_filename("Author", None, ".pdf")
        assert result.endswith(".pdf")


class TestClassifyBook:
    @patch("bookstuff.classifier.anthropic")
    def test_classify_with_mocked_api(self, mock_anthropic):
        """Test classification with a mocked Claude API response."""
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps({
            "title": "Introduction to Algorithms",
            "author": "Thomas Cormen",
            "category": "computer-science",
        }))]
        mock_client.messages.create.return_value = mock_response

        result = classify_book(
            path=Path("/books/intro_algorithms.pdf"),
            metadata={"title": "Introduction to Algorithms"},
            content_sample="This textbook covers algorithms...",
            api_key="fake-key",
        )

        assert isinstance(result, ClassificationResult)
        assert result.category == "computer-science"
        assert result.title == "Introduction to Algorithms"
        assert result.author == "Thomas Cormen"

    @patch("bookstuff.classifier.anthropic")
    def test_classify_falls_back_to_uncategorized(self, mock_anthropic):
        """Test that invalid category falls back to uncategorized."""
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps({
            "title": "Unknown Book",
            "author": None,
            "category": "basket-weaving",
        }))]
        mock_client.messages.create.return_value = mock_response

        result = classify_book(
            path=Path("/books/unknown.pdf"),
            metadata={},
            content_sample="",
            api_key="fake-key",
        )

        assert result.category == "uncategorized"

    @patch("bookstuff.classifier.anthropic")
    def test_classify_api_error_returns_uncategorized(self, mock_anthropic):
        """Test that API errors result in uncategorized."""
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        mock_client.messages.create.side_effect = Exception("API error")

        result = classify_book(
            path=Path("/books/book.pdf"),
            metadata={},
            content_sample="some content",
            api_key="fake-key",
        )

        assert result.category == "uncategorized"

    def test_classify_no_text_returns_uncategorized(self):
        """Image-scanned PDFs with no extractable text -> uncategorized."""
        result = classify_book(
            path=Path("/books/scanned.pdf"),
            metadata={},
            content_sample="",
            api_key=None,
        )

        assert result.category == "uncategorized"


class TestClassifyBatch:
    @patch("bookstuff.classifier.anthropic")
    def test_batch_returns_results_for_each_file(self, mock_anthropic):
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps([
            {"title": "Eloquent JavaScript", "author": "Marijn Haverbeke", "category": "programming"},
            {"title": "Principles", "author": "Ray Dalio", "category": "business-and-management"},
        ]))]
        mock_client.messages.create.return_value = mock_response

        paths = [
            "/books/Eloquent_JavaScript.epub",
            "/books/RayDalioPrinciples.pdf",
        ]
        results = classify_batch(paths, "fake-key")

        assert len(results) == 2
        assert results[0]["category"] == "programming"
        assert results[0]["dest_filename"] == "Marijn Haverbeke - Eloquent JavaScript.epub"
        assert results[1]["category"] == "business-and-management"
        assert results[1]["path"] == "/books/RayDalioPrinciples.pdf"

    @patch("bookstuff.classifier.anthropic")
    def test_batch_skip_category(self, mock_anthropic):
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps([
            {"title": "README", "author": None, "category": "skip"},
        ]))]
        mock_client.messages.create.return_value = mock_response

        results = classify_batch(["/books/README.pdf"], "fake-key")

        assert len(results) == 1
        assert results[0]["category"] == "skip"
        assert results[0]["dest_filename"] is None

    @patch("bookstuff.classifier.anthropic")
    def test_batch_invalid_category_falls_back(self, mock_anthropic):
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps([
            {"title": "Book", "author": "Author", "category": "basket-weaving"},
        ]))]
        mock_client.messages.create.return_value = mock_response

        results = classify_batch(["/books/book.pdf"], "fake-key")
        assert results[0]["category"] == "uncategorized"

    @patch("bookstuff.classifier.anthropic")
    def test_batch_strips_markdown_fences(self, mock_anthropic):
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        mock_response = MagicMock()
        mock_response.content = [MagicMock(
            text='```json\n[{"title": "Test", "author": "A", "category": "fiction"}]\n```'
        )]
        mock_client.messages.create.return_value = mock_response

        results = classify_batch(["/books/test.epub"], "fake-key")
        assert len(results) == 1
        assert results[0]["category"] == "fiction"

    @patch("bookstuff.classifier.anthropic")
    def test_batch_extra_results_are_ignored(self, mock_anthropic):
        """If API returns more items than files, extras are ignored."""
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps([
            {"title": "Book1", "author": "A", "category": "fiction"},
            {"title": "Book2", "author": "B", "category": "fiction"},
            {"title": "Extra", "author": "C", "category": "fiction"},
        ]))]
        mock_client.messages.create.return_value = mock_response

        results = classify_batch(["/a.pdf", "/b.pdf"], "fake-key")
        assert len(results) == 2


class TestExtractPdfMetadata:
    @patch("bookstuff.classifier.fitz")
    def test_extract_pdf_metadata(self, mock_fitz):
        mock_doc = MagicMock()
        mock_doc.metadata = {"title": "My PDF", "author": "Author Name"}
        mock_page = MagicMock()
        mock_page.get_text.return_value = "Page 1 content here"
        mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
        mock_doc.__len__ = MagicMock(return_value=1)
        mock_fitz.open.return_value.__enter__ = MagicMock(return_value=mock_doc)
        mock_fitz.open.return_value.__exit__ = MagicMock(return_value=False)

        metadata, text = extract_pdf_metadata(Path("/books/test.pdf"))
        assert metadata["title"] == "My PDF"
        assert metadata["author"] == "Author Name"
        assert "Page 1 content" in text

    @patch("bookstuff.classifier.fitz")
    def test_extract_pdf_permission_error(self, mock_fitz):
        mock_fitz.open.side_effect = Exception("Cannot open file")
        metadata, text = extract_pdf_metadata(Path("/books/bad.pdf"))
        assert metadata == {}
        assert text == ""


class TestExtractEpubMetadata:
    @patch("bookstuff.classifier.epub")
    def test_extract_epub_metadata(self, mock_epub):
        mock_book = MagicMock()
        mock_book.get_metadata.side_effect = lambda ns, name: {
            ("DC", "title"): [("My EPUB Title",)],
            ("DC", "creator"): [("EPUB Author",)],
            ("DC", "subject"): [("Computer Science",)],
        }.get((ns, name), [])
        mock_epub.read_epub.return_value = mock_book

        metadata = extract_epub_metadata(Path("/books/test.epub"))
        assert metadata["title"] == "My EPUB Title"
        assert metadata["author"] == "EPUB Author"

    @patch("bookstuff.classifier.epub")
    def test_extract_epub_error(self, mock_epub):
        mock_epub.read_epub.side_effect = Exception("Cannot read")
        metadata = extract_epub_metadata(Path("/books/bad.epub"))
        assert metadata == {}
