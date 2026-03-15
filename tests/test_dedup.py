"""Tests for the dedup module."""

from pathlib import Path

from bookstuff.dedup import hash_file, find_duplicates


class TestHashFile:
    def test_hash_known_content(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_bytes(b"hello world")
        h = hash_file(f)
        # SHA-256 of "hello world"
        assert h == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"

    def test_hash_empty_file(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_bytes(b"")
        h = hash_file(f)
        # SHA-256 of empty string
        assert h == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    def test_same_content_same_hash(self, tmp_path):
        f1 = tmp_path / "a.pdf"
        f2 = tmp_path / "b.pdf"
        content = b"same content here"
        f1.write_bytes(content)
        f2.write_bytes(content)
        assert hash_file(f1) == hash_file(f2)

    def test_different_content_different_hash(self, tmp_path):
        f1 = tmp_path / "a.pdf"
        f2 = tmp_path / "b.pdf"
        f1.write_bytes(b"content A")
        f2.write_bytes(b"content B")
        assert hash_file(f1) != hash_file(f2)


class TestFindDuplicates:
    def test_no_duplicates(self, tmp_path):
        f1 = tmp_path / "a.pdf"
        f2 = tmp_path / "b.pdf"
        f1.write_bytes(b"unique 1")
        f2.write_bytes(b"unique 2")
        dupes = find_duplicates([f1, f2])
        assert len(dupes) == 0

    def test_finds_duplicates(self, tmp_path):
        f1 = tmp_path / "a.pdf"
        f2 = tmp_path / "b.pdf"
        f3 = tmp_path / "c.pdf"
        f1.write_bytes(b"same")
        f2.write_bytes(b"same")
        f3.write_bytes(b"different")

        dupes = find_duplicates([f1, f2, f3])
        # dupes should map hash -> list of paths, with at least one group having 2 paths
        assert len(dupes) == 1
        dupe_group = list(dupes.values())[0]
        assert len(dupe_group) == 2

    def test_empty_list(self):
        dupes = find_duplicates([])
        assert len(dupes) == 0

    def test_multiple_duplicate_groups(self, tmp_path):
        f1 = tmp_path / "a.pdf"
        f2 = tmp_path / "a_copy.pdf"
        f3 = tmp_path / "b.epub"
        f4 = tmp_path / "b_copy.epub"
        f1.write_bytes(b"group1")
        f2.write_bytes(b"group1")
        f3.write_bytes(b"group2")
        f4.write_bytes(b"group2")

        dupes = find_duplicates([f1, f2, f3, f4])
        assert len(dupes) == 2
