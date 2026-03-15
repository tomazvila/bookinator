"""Tests for the reorganizer module."""

from pathlib import Path
from unittest.mock import patch, MagicMock

from bookstuff.reorganizer import (
    list_remote_ebooks,
    plan_move,
    execute_move,
    reorganize,
    REMOTE_SCAN_DIRS,
)


class TestListRemoteEbooks:
    @patch("bookstuff.reorganizer.subprocess.run")
    def test_lists_ebooks_over_ssh(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="book1.pdf\nbook2.epub\nnotebook.txt\nbook3.mobi\n",
            stderr="",
        )

        result = list_remote_ebooks("/mnt/ssdb/AK/")
        ebook_names = [Path(p).name for p in result]
        assert "book1.pdf" in ebook_names
        assert "book2.epub" in ebook_names
        assert "book3.mobi" in ebook_names
        assert "notebook.txt" not in ebook_names

    @patch("bookstuff.reorganizer.subprocess.run")
    def test_handles_ssh_error(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="connection refused")

        result = list_remote_ebooks("/mnt/ssdb/AK/")
        assert result == []


class TestPlanMove:
    def test_creates_move_plan(self):
        plan = plan_move(
            remote_path="/mnt/ssdb/AK/book.pdf",
            category="programming",
            dest_filename="Author - Title.pdf",
        )
        assert plan["source"] == "/mnt/ssdb/AK/book.pdf"
        assert plan["destination"] == "/mnt/ssdb/books/programming/Author - Title.pdf"
        assert plan["category"] == "programming"


class TestExecuteMove:
    @patch("bookstuff.reorganizer.subprocess.run")
    def test_moves_file_on_remote(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        plan = {
            "source": "/mnt/ssdb/AK/book.pdf",
            "destination": "/mnt/ssdb/books/programming/Author - Title.pdf",
            "category": "programming",
        }

        result = execute_move(plan)
        assert result is True
        # Should call ssh with mkdir and cp (not mv — we copy, never delete)
        assert mock_run.call_count >= 1

    @patch("bookstuff.reorganizer.subprocess.run")
    def test_dry_run_does_not_execute(self, mock_run):
        plan = {
            "source": "/mnt/ssdb/AK/book.pdf",
            "destination": "/mnt/ssdb/books/programming/Author - Title.pdf",
            "category": "programming",
        }

        result = execute_move(plan, dry_run=True)
        assert result is True
        mock_run.assert_not_called()

    @patch("bookstuff.reorganizer.subprocess.run")
    def test_handles_move_error(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")

        plan = {
            "source": "/mnt/ssdb/AK/book.pdf",
            "destination": "/mnt/ssdb/books/programming/book.pdf",
            "category": "programming",
        }

        result = execute_move(plan)
        assert result is False


class TestReorganize:
    @patch("bookstuff.reorganizer.execute_move")
    @patch("bookstuff.reorganizer.classify_remote_book")
    @patch("bookstuff.reorganizer.list_remote_ebooks")
    def test_reorganize_flow(self, mock_list, mock_classify, mock_execute):
        mock_list.return_value = ["/mnt/ssdb/AK/book.pdf"]
        mock_classify.return_value = {
            "category": "programming",
            "dest_filename": "Author - Title.pdf",
        }
        mock_execute.return_value = True

        results = reorganize(dry_run=False, api_key="fake-key")
        assert len(results) == len(REMOTE_SCAN_DIRS)

    @patch("bookstuff.reorganizer.list_remote_ebooks")
    def test_reorganize_empty_dirs(self, mock_list):
        mock_list.return_value = []

        results = reorganize(dry_run=True, api_key="fake-key")
        assert isinstance(results, list)
