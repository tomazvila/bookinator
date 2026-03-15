"""Tests for the scanner module."""

import os
from pathlib import Path
from unittest.mock import patch

from bookstuff.scanner import BookFile, scan_directories, scan_directory


class TestBookFile:
    def test_bookfile_attributes(self, tmp_path):
        p = tmp_path / "test.pdf"
        p.write_bytes(b"fake pdf content")
        bf = BookFile(path=p, extension=".pdf", size=p.stat().st_size, mtime=p.stat().st_mtime)
        assert bf.path == p
        assert bf.extension == ".pdf"
        assert bf.size > 0
        assert bf.mtime > 0

    def test_bookfile_str(self, tmp_path):
        p = tmp_path / "test.epub"
        p.write_bytes(b"fake epub")
        bf = BookFile(path=p, extension=".epub", size=10, mtime=1.0)
        assert "test.epub" in str(bf)


class TestScanDirectory:
    def test_finds_ebook_files(self, tmp_path):
        (tmp_path / "book.pdf").write_bytes(b"pdf")
        (tmp_path / "book.epub").write_bytes(b"epub")
        (tmp_path / "book.mobi").write_bytes(b"mobi")
        (tmp_path / "book.djvu").write_bytes(b"djvu")
        (tmp_path / "book.azw3").write_bytes(b"azw3")
        (tmp_path / "book.cbz").write_bytes(b"cbz")

        results = scan_directory(tmp_path)
        extensions = {bf.extension for bf in results}
        assert extensions == {".pdf", ".epub", ".mobi", ".djvu", ".azw3", ".cbz"}

    def test_ignores_non_ebook_files(self, tmp_path):
        (tmp_path / "readme.txt").write_text("hello")
        (tmp_path / "image.png").write_bytes(b"png")
        (tmp_path / "code.py").write_text("print('hi')")

        results = scan_directory(tmp_path)
        assert len(results) == 0

    def test_scans_subdirectories(self, tmp_path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "nested.pdf").write_bytes(b"pdf")

        results = scan_directory(tmp_path)
        assert len(results) == 1
        assert results[0].path == sub / "nested.pdf"

    def test_skips_hidden_directories(self, tmp_path):
        hidden = tmp_path / ".hidden"
        hidden.mkdir()
        (hidden / "secret.pdf").write_bytes(b"pdf")

        results = scan_directory(tmp_path)
        assert len(results) == 0

    def test_skips_src_tests_test_fixtures(self, tmp_path):
        for dirname in ["src", "tests", "test_fixtures"]:
            d = tmp_path / dirname
            d.mkdir()
            (d / "file.pdf").write_bytes(b"pdf")

        results = scan_directory(tmp_path)
        assert len(results) == 0

    def test_handles_permission_error(self, tmp_path):
        restricted = tmp_path / "restricted"
        restricted.mkdir()
        (restricted / "book.pdf").write_bytes(b"pdf")
        restricted.chmod(0o000)

        try:
            results = scan_directory(tmp_path)
            # Should not crash, just skip the inaccessible directory
            assert len(results) == 0
        finally:
            restricted.chmod(0o755)

    def test_case_insensitive_extensions(self, tmp_path):
        (tmp_path / "book.PDF").write_bytes(b"pdf")
        (tmp_path / "book.Epub").write_bytes(b"epub")

        results = scan_directory(tmp_path)
        assert len(results) == 2

    def test_empty_directory(self, tmp_path):
        results = scan_directory(tmp_path)
        assert results == []


class TestScanDirectories:
    def test_scans_multiple_directories(self, tmp_path):
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()
        (dir1 / "a.pdf").write_bytes(b"pdf1")
        (dir2 / "b.epub").write_bytes(b"epub1")

        results = scan_directories([dir1, dir2])
        assert len(results) == 2

    def test_skips_nonexistent_directory(self, tmp_path):
        existing = tmp_path / "exists"
        existing.mkdir()
        (existing / "book.pdf").write_bytes(b"pdf")
        nonexistent = tmp_path / "nope"

        results = scan_directories([existing, nonexistent])
        assert len(results) == 1

    def test_deduplicates_across_directories(self, tmp_path):
        """If same path appears in multiple scan dirs, don't duplicate."""
        d = tmp_path / "shared"
        d.mkdir()
        (d / "book.pdf").write_bytes(b"pdf")

        results = scan_directories([d, d])
        assert len(results) == 1
