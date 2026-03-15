"""Tests for the uploader module."""

from pathlib import Path
from unittest.mock import patch, MagicMock, call

from bookstuff.uploader import (
    build_rsync_command,
    upload_file,
    upload_files,
    REMOTE_HOST,
    REMOTE_BASE,
)


class TestBuildRsyncCommand:
    def test_basic_command(self):
        cmd = build_rsync_command(
            local_path=Path("/tmp/book.pdf"),
            category="programming",
            dest_filename="Author - Title.pdf",
        )
        assert "rsync" in cmd[0]
        assert "-avz" in cmd
        assert "-e" in cmd
        assert "ssh" in cmd
        assert str(Path("/tmp/book.pdf")) in cmd
        assert f"{REMOTE_HOST}:{REMOTE_BASE}/programming/Author - Title.pdf" in cmd

    def test_command_structure(self):
        cmd = build_rsync_command(
            local_path=Path("/home/user/test.epub"),
            category="fiction",
            dest_filename="Tolkien - The Hobbit.epub",
        )
        # Should be: rsync -avz -e ssh <local> <remote>
        assert cmd[0] == "rsync"
        assert "-avz" in cmd
        assert cmd[cmd.index("-e") + 1] == "ssh"


class TestUploadFile:
    @patch("bookstuff.uploader.subprocess.run")
    def test_upload_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        result = upload_file(
            local_path=Path("/tmp/book.pdf"),
            category="programming",
            dest_filename="Author - Title.pdf",
        )

        assert result is True
        assert mock_run.call_count == 2  # mkdir + rsync

    @patch("bookstuff.uploader.subprocess.run")
    def test_upload_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")

        result = upload_file(
            local_path=Path("/tmp/book.pdf"),
            category="programming",
            dest_filename="Author - Title.pdf",
        )

        assert result is False

    @patch("bookstuff.uploader.subprocess.run")
    def test_dry_run_does_not_transfer(self, mock_run):
        result = upload_file(
            local_path=Path("/tmp/book.pdf"),
            category="programming",
            dest_filename="Author - Title.pdf",
            dry_run=True,
        )

        assert result is True
        mock_run.assert_not_called()

    @patch("bookstuff.uploader.subprocess.run")
    def test_creates_remote_directory(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        upload_file(
            local_path=Path("/tmp/book.pdf"),
            category="new-category",
            dest_filename="book.pdf",
        )

        # Should have two calls: mkdir + rsync
        assert mock_run.call_count == 2
        mkdir_call = mock_run.call_args_list[0]
        assert "mkdir" in str(mkdir_call)


class TestUploadFiles:
    @patch("bookstuff.uploader.upload_file")
    def test_upload_multiple_files(self, mock_upload):
        mock_upload.return_value = True

        files = [
            {"local_path": Path("/a.pdf"), "category": "math", "dest_filename": "a.pdf"},
            {"local_path": Path("/b.epub"), "category": "cs", "dest_filename": "b.epub"},
        ]

        results = upload_files(files)
        assert all(results)
        assert mock_upload.call_count == 2

    @patch("bookstuff.uploader.upload_file")
    def test_upload_empty_list(self, mock_upload):
        results = upload_files([])
        assert results == []
        mock_upload.assert_not_called()
