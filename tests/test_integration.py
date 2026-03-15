"""Integration tests — require SSH access to remote server.

Run with: nix develop --command python -m pytest tests/test_integration.py -v -m integration
"""

import pytest
import subprocess

REMOTE_HOST = "lilvilla@ssh.tomazvi.la"


@pytest.mark.integration
class TestRemoteConnection:
    def test_ssh_connection(self):
        """Verify SSH connectivity to remote server."""
        result = subprocess.run(
            ["ssh", REMOTE_HOST, "echo", "hello"],
            capture_output=True, text=True, timeout=15,
        )
        assert result.returncode == 0
        assert "hello" in result.stdout

    def test_remote_books_dir_exists(self):
        """Verify /mnt/ssdb/books/ exists on remote."""
        result = subprocess.run(
            ["ssh", REMOTE_HOST, "test", "-d", "/mnt/ssdb/books"],
            capture_output=True, text=True, timeout=15,
        )
        assert result.returncode == 0

    def test_can_create_remote_directory(self):
        """Verify we can create directories on remote."""
        result = subprocess.run(
            ["ssh", REMOTE_HOST, "mkdir", "-p", "/mnt/ssdb/books/test-integration"],
            capture_output=True, text=True, timeout=15,
        )
        assert result.returncode == 0

        # Cleanup
        subprocess.run(
            ["ssh", REMOTE_HOST, "rmdir", "/mnt/ssdb/books/test-integration"],
            capture_output=True, text=True, timeout=15,
        )

    def test_rsync_available(self):
        """Verify rsync is available locally."""
        result = subprocess.run(
            ["rsync", "--version"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
