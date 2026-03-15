"""Tests for the manifest module."""

import json
from pathlib import Path

from bookstuff.manifest import Manifest


class TestManifest:
    def test_create_empty_manifest(self, tmp_path):
        path = tmp_path / "manifest.json"
        m = Manifest(path)
        assert m.entries == {}

    def test_add_entry(self, tmp_path):
        path = tmp_path / "manifest.json"
        m = Manifest(path)
        m.add_entry(
            file_hash="abc123",
            path="/books/test.pdf",
            category="programming",
            dest_filename="Author - Title.pdf",
        )
        assert "abc123" in m.entries
        assert m.entries["abc123"]["path"] == "/books/test.pdf"
        assert m.entries["abc123"]["category"] == "programming"
        assert m.entries["abc123"]["dest_filename"] == "Author - Title.pdf"

    def test_save_and_load(self, tmp_path):
        path = tmp_path / "manifest.json"
        m = Manifest(path)
        m.add_entry(
            file_hash="abc123",
            path="/books/test.pdf",
            category="programming",
            dest_filename="Author - Title.pdf",
        )
        m.save()

        m2 = Manifest(path)
        m2.load()
        assert "abc123" in m2.entries
        assert m2.entries["abc123"]["path"] == "/books/test.pdf"

    def test_has_hash(self, tmp_path):
        path = tmp_path / "manifest.json"
        m = Manifest(path)
        m.add_entry(file_hash="abc", path="/a.pdf", category="math", dest_filename="a.pdf")
        assert m.has_hash("abc") is True
        assert m.has_hash("xyz") is False

    def test_mark_uploaded(self, tmp_path):
        path = tmp_path / "manifest.json"
        m = Manifest(path)
        m.add_entry(file_hash="abc", path="/a.pdf", category="math", dest_filename="a.pdf")
        m.mark_uploaded("abc", remote_path="/mnt/ssdb/books/math/a.pdf")
        assert m.entries["abc"]["uploaded_at"] is not None
        assert m.entries["abc"]["remote_path"] == "/mnt/ssdb/books/math/a.pdf"

    def test_get_pending(self, tmp_path):
        path = tmp_path / "manifest.json"
        m = Manifest(path)
        m.add_entry(file_hash="a", path="/a.pdf", category="math", dest_filename="a.pdf")
        m.add_entry(file_hash="b", path="/b.pdf", category="cs", dest_filename="b.pdf")
        m.mark_uploaded("a", remote_path="/mnt/ssdb/books/math/a.pdf")

        pending = m.get_pending()
        assert len(pending) == 1
        assert "b" in pending

    def test_get_uploaded(self, tmp_path):
        path = tmp_path / "manifest.json"
        m = Manifest(path)
        m.add_entry(file_hash="a", path="/a.pdf", category="math", dest_filename="a.pdf")
        m.add_entry(file_hash="b", path="/b.pdf", category="cs", dest_filename="b.pdf")
        m.mark_uploaded("a", remote_path="/mnt/ssdb/books/math/a.pdf")

        uploaded = m.get_uploaded()
        assert len(uploaded) == 1
        assert "a" in uploaded

    def test_load_nonexistent_file(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        m = Manifest(path)
        m.load()  # Should not raise
        assert m.entries == {}

    def test_save_creates_file(self, tmp_path):
        path = tmp_path / "manifest.json"
        m = Manifest(path)
        m.add_entry(file_hash="x", path="/x.pdf", category="fiction", dest_filename="x.pdf")
        m.save()
        assert path.exists()
        data = json.loads(path.read_text())
        assert "x" in data

    def test_get_stats(self, tmp_path):
        path = tmp_path / "manifest.json"
        m = Manifest(path)
        m.add_entry(file_hash="a", path="/a.pdf", category="math", dest_filename="a.pdf")
        m.add_entry(file_hash="b", path="/b.pdf", category="cs", dest_filename="b.pdf")
        m.mark_uploaded("a", remote_path="/mnt/ssdb/books/math/a.pdf")

        stats = m.get_stats()
        assert stats["total"] == 2
        assert stats["uploaded"] == 1
        assert stats["pending"] == 1
