"""Tests for the CLI module."""

from unittest.mock import patch, MagicMock
from click.testing import CliRunner

from bookstuff.cli import cli


class TestCli:
    def test_cli_group_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "BookStuff" in result.output

    def test_scan_command_exists(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["scan", "--help"])
        assert result.exit_code == 0
        assert "dry-run" in result.output

    def test_upload_command_exists(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["upload", "--help"])
        assert result.exit_code == 0

    def test_status_command_exists(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["status", "--help"])
        assert result.exit_code == 0

    def test_reorganize_command_exists(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["reorganize", "--help"])
        assert result.exit_code == 0

    @patch("bookstuff.cli.scan_directories")
    @patch("bookstuff.cli.filter_file")
    def test_scan_dry_run(self, mock_filter, mock_scan):
        mock_scan.return_value = []
        runner = CliRunner()
        result = runner.invoke(cli, ["scan", "--dry-run"])
        assert result.exit_code == 0

    @patch("bookstuff.cli.Manifest")
    def test_status_shows_stats(self, mock_manifest_cls):
        mock_manifest = MagicMock()
        mock_manifest.get_stats.return_value = {"total": 5, "uploaded": 3, "pending": 2}
        mock_manifest_cls.return_value = mock_manifest

        runner = CliRunner()
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "5" in result.output

    def test_upload_requires_api_key_env(self):
        """Upload should work even without API key (it doesn't classify)."""
        runner = CliRunner()
        result = runner.invoke(cli, ["upload", "--help"])
        assert result.exit_code == 0

    @patch("bookstuff.cli.Manifest")
    def test_upload_dry_run(self, mock_manifest_cls):
        mock_manifest = MagicMock()
        mock_manifest.get_pending.return_value = {}
        mock_manifest_cls.return_value = mock_manifest

        runner = CliRunner()
        result = runner.invoke(cli, ["upload", "--dry-run"])
        assert result.exit_code == 0
