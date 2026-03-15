"""Tests for the batch_organize module."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import batch_organize


class TestLoadFileList:
    def test_loads_lines(self, tmp_path):
        f = tmp_path / "files.txt"
        f.write_text("/mnt/ssdb/a.pdf\n/mnt/ssdb/b.epub\n\n/mnt/ssdb/c.mobi\n")

        with patch.object(batch_organize, "FILE_LIST", f):
            result = batch_organize.load_file_list()

        assert result == ["/mnt/ssdb/a.pdf", "/mnt/ssdb/b.epub", "/mnt/ssdb/c.mobi"]

    def test_strips_whitespace(self, tmp_path):
        f = tmp_path / "files.txt"
        f.write_text("  /mnt/ssdb/a.pdf  \n")

        with patch.object(batch_organize, "FILE_LIST", f):
            result = batch_organize.load_file_list()

        assert result == ["/mnt/ssdb/a.pdf"]


class TestLoadSavePlan:
    def test_load_empty_plan(self, tmp_path):
        with patch.object(batch_organize, "PLAN_FILE", tmp_path / "nonexistent.json"):
            plan = batch_organize.load_plan()

        assert plan == {"classified": {}, "skipped": [], "errors": []}

    def test_load_existing_plan(self, tmp_path):
        f = tmp_path / "plan.json"
        data = {
            "classified": {"/a.pdf": {"title": "A", "author": "B", "category": "fiction", "dest_filename": "B - A.pdf"}},
            "skipped": ["/readme.pdf"],
            "errors": [],
        }
        f.write_text(json.dumps(data))

        with patch.object(batch_organize, "PLAN_FILE", f):
            plan = batch_organize.load_plan()

        assert len(plan["classified"]) == 1
        assert plan["classified"]["/a.pdf"]["category"] == "fiction"

    def test_save_and_reload(self, tmp_path):
        f = tmp_path / "plan.json"
        plan = {
            "classified": {"/a.pdf": {"title": "Test", "author": None, "category": "science", "dest_filename": "Test.pdf"}},
            "skipped": [],
            "errors": [],
        }

        with patch.object(batch_organize, "PLAN_FILE", f):
            batch_organize.save_plan(plan)
            loaded = batch_organize.load_plan()

        assert loaded == plan

    def test_save_preserves_unicode(self, tmp_path):
        f = tmp_path / "plan.json"
        plan = {
            "classified": {"/a.epub": {"title": "Balta drobulė", "author": "Škėma", "category": "fiction", "dest_filename": "Škėma - Balta drobulė.epub"}},
            "skipped": [],
            "errors": [],
        }

        with patch.object(batch_organize, "PLAN_FILE", f):
            batch_organize.save_plan(plan)

        raw = f.read_text()
        assert "Škėma" in raw
        assert "\\u" not in raw  # ensure_ascii=False


class TestClassifyAll:
    @patch.object(batch_organize, "save_plan")
    @patch("batch_organize.classify_batch")
    @patch.object(batch_organize, "load_plan", return_value={"classified": {}, "skipped": [], "errors": []})
    @patch.object(batch_organize, "load_file_list", return_value=["/a.pdf", "/b.epub", "/c.pdf"])
    @patch("batch_organize.time")
    @patch("batch_organize.os")
    def test_classify_all_processes_batches(self, mock_os, mock_time, mock_load_files, mock_load_plan, mock_classify, mock_save):
        mock_os.environ.get.return_value = "fake-key"
        mock_classify.return_value = [
            {"path": "/a.pdf", "title": "A", "author": "X", "category": "fiction", "dest_filename": "X - A.pdf"},
            {"path": "/b.epub", "title": "B", "author": "Y", "category": "skip", "dest_filename": None},
            {"path": "/c.pdf", "title": "C", "author": "Z", "category": "science", "dest_filename": "Z - C.pdf"},
        ]

        batch_organize.classify_all()

        mock_classify.assert_called_once()
        assert mock_save.call_count >= 1
        saved_plan = mock_save.call_args[0][0]
        assert len(saved_plan["classified"]) == 2
        assert "/b.epub" in saved_plan["skipped"]

    @patch.object(batch_organize, "save_plan")
    @patch("batch_organize.classify_batch")
    @patch.object(batch_organize, "load_plan", return_value={
        "classified": {"/a.pdf": {"title": "A", "author": "X", "category": "fiction", "dest_filename": "X - A.pdf"}},
        "skipped": [],
        "errors": [],
    })
    @patch.object(batch_organize, "load_file_list", return_value=["/a.pdf", "/b.epub"])
    @patch("batch_organize.time")
    @patch("batch_organize.os")
    def test_classify_all_skips_already_done(self, mock_os, mock_time, mock_load_files, mock_load_plan, mock_classify, mock_save):
        mock_os.environ.get.return_value = "fake-key"
        mock_classify.return_value = [
            {"path": "/b.epub", "title": "B", "author": "Y", "category": "programming", "dest_filename": "Y - B.epub"},
        ]

        batch_organize.classify_all()

        # Should only classify /b.epub, not /a.pdf again
        args = mock_classify.call_args[0][0]
        assert "/a.pdf" not in args
        assert "/b.epub" in args

    @patch.object(batch_organize, "save_plan")
    @patch("batch_organize.classify_batch", side_effect=Exception("API down"))
    @patch.object(batch_organize, "load_plan", return_value={"classified": {}, "skipped": [], "errors": []})
    @patch.object(batch_organize, "load_file_list", return_value=["/a.pdf"])
    @patch("batch_organize.time")
    @patch("batch_organize.os")
    def test_classify_all_handles_errors(self, mock_os, mock_time, mock_load_files, mock_load_plan, mock_classify, mock_save):
        mock_os.environ.get.return_value = "fake-key"

        batch_organize.classify_all()

        saved_plan = mock_save.call_args[0][0]
        assert "/a.pdf" in saved_plan["errors"]


class TestShowPlan:
    @patch.object(batch_organize, "load_plan", return_value={"classified": {}, "skipped": [], "errors": []})
    def test_show_empty_plan(self, mock_load, capsys):
        batch_organize.show_plan()
        assert "No plan yet" in capsys.readouterr().out

    @patch.object(batch_organize, "load_plan", return_value={
        "classified": {
            "/a.pdf": {"title": "A", "author": "X", "category": "fiction", "dest_filename": "X - A.pdf"},
            "/b.pdf": {"title": "B", "author": "Y", "category": "fiction", "dest_filename": "Y - B.pdf"},
            "/c.pdf": {"title": "C", "author": "Z", "category": "programming", "dest_filename": "Z - C.pdf"},
        },
        "skipped": ["/readme.pdf"],
        "errors": [],
    })
    def test_show_plan_summary(self, mock_load, capsys):
        batch_organize.show_plan()
        output = capsys.readouterr().out
        assert "Total books to organize: 3" in output
        assert "Skipped (not books):     1" in output
        assert "fiction" in output
        assert "programming" in output


class TestExecutePlan:
    @patch.object(batch_organize, "load_plan", return_value={"classified": {}, "skipped": [], "errors": []})
    def test_execute_empty_plan(self, mock_load, capsys):
        batch_organize.execute_plan()
        assert "No plan" in capsys.readouterr().out

    @patch("batch_organize.subprocess")
    @patch("batch_organize.Path")
    @patch.object(batch_organize, "load_plan", return_value={
        "classified": {
            "/mnt/ssdb/old/book.pdf": {
                "title": "Book",
                "author": "Author",
                "category": "fiction",
                "dest_filename": "Author - Book.pdf",
            },
        },
        "skipped": [],
        "errors": [],
    })
    def test_execute_generates_script_and_runs(self, mock_load, mock_path_cls, mock_subprocess):
        mock_script_path = MagicMock()
        mock_path_cls.return_value = mock_script_path

        mock_proc = MagicMock()
        mock_proc.stdout = ['  RESULT: 1 copied, 0 already existed, 0 failed\n']
        mock_proc.wait.return_value = 0
        mock_subprocess.Popen.return_value = mock_proc

        batch_organize.execute_plan()

        # Should write script content
        mock_script_path.write_text.assert_called_once()
        script_content = mock_script_path.write_text.call_args[0][0]

        # Script should contain mkdir, cp, and RESULT echo
        assert 'mkdir -p' in script_content
        assert 'fiction' in script_content
        assert 'cp ' in script_content
        assert 'Author - Book.pdf' in script_content
        assert 'RESULT' in script_content

        # Should scp the script to remote
        scp_call = mock_subprocess.run.call_args_list[0]
        assert "scp" in str(scp_call)

        # Should ssh to execute it
        assert mock_subprocess.Popen.called

    @patch("batch_organize.subprocess")
    @patch("batch_organize.Path")
    @patch.object(batch_organize, "load_plan", return_value={
        "classified": {
            "/mnt/ssdb/old/Kant's Book.pdf": {
                "title": "Kant's Critique",
                "author": "Author",
                "category": "philosophy",
                "dest_filename": "Author - Kant's Critique.pdf",
            },
        },
        "skipped": [],
        "errors": [],
    })
    def test_execute_escapes_special_chars(self, mock_load, mock_path_cls, mock_subprocess):
        mock_script_path = MagicMock()
        mock_path_cls.return_value = mock_script_path

        mock_proc = MagicMock()
        mock_proc.stdout = ['  RESULT: 1 copied, 0 already existed, 0 failed\n']
        mock_proc.wait.return_value = 0
        mock_subprocess.Popen.return_value = mock_proc

        batch_organize.execute_plan()

        script_content = mock_script_path.write_text.call_args[0][0]
        # Apostrophes should be escaped for double-quoted strings
        assert "Kant\\'s" not in script_content  # not single-quote escaped
        assert "Kant's" in script_content  # apostrophes are fine inside double quotes
