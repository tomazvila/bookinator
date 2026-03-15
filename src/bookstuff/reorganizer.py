"""Reorganize existing remote book collections."""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

REMOTE_HOST = "lilvilla@ssh.tomazvi.la"
REMOTE_BASE = "/mnt/ssdb/books"
REMOTE_SCAN_DIRS = ["/mnt/ssdb/AK/", "/mnt/ssdb/financial knowloedge/"]

EBOOK_EXTENSIONS = {".pdf", ".epub", ".mobi", ".djvu", ".azw3", ".cbz"}


def list_remote_ebooks(remote_dir: str) -> list[str]:
    """List e-book files in a remote directory over SSH."""
    cmd = ["ssh", REMOTE_HOST, "find", remote_dir, "-type", "f"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error("Failed to list remote dir %s: %s", remote_dir, result.stderr)
            return []

        paths = []
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            if Path(line).suffix.lower() in EBOOK_EXTENSIONS:
                paths.append(line)
        return paths

    except Exception as e:
        logger.error("Error listing remote dir %s: %s", remote_dir, e)
        return []


def plan_move(remote_path: str, category: str, dest_filename: str) -> dict:
    """Create a move plan for a remote file."""
    return {
        "source": remote_path,
        "destination": f"{REMOTE_BASE}/{category}/{dest_filename}",
        "category": category,
    }


def execute_move(plan: dict, dry_run: bool = False) -> bool:
    """Execute a move plan on the remote server.

    Uses 'cp' instead of 'mv' to avoid deleting source files.
    """
    if dry_run:
        logger.info("[DRY RUN] Would copy %s -> %s", plan["source"], plan["destination"])
        return True

    dest_dir = str(Path(plan["destination"]).parent)

    # Create destination directory
    mkdir_cmd = ["ssh", REMOTE_HOST, "mkdir", "-p", dest_dir]
    try:
        result = subprocess.run(mkdir_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error("Failed to create dir %s: %s", dest_dir, result.stderr)
            return False
    except Exception as e:
        logger.error("Error creating dir %s: %s", dest_dir, e)
        return False

    # Copy file (never delete source)
    cp_cmd = ["ssh", REMOTE_HOST, "cp", "-n", plan["source"], plan["destination"]]
    try:
        result = subprocess.run(cp_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error("Failed to copy %s: %s", plan["source"], result.stderr)
            return False
        logger.info("Copied %s -> %s", plan["source"], plan["destination"])
        return True
    except Exception as e:
        logger.error("Error copying %s: %s", plan["source"], e)
        return False


def classify_remote_book(remote_path: str, api_key: str) -> dict:
    """Classify a remote book by downloading a content sample."""
    from bookstuff.classifier import classify_book

    # Try to get content sample via SSH
    content_sample = ""
    try:
        cmd = ["ssh", REMOTE_HOST, "head", "-c", "50000", remote_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            content_sample = result.stdout[:3000]
    except Exception as e:
        logger.warning("Could not sample remote file %s: %s", remote_path, e)

    classification = classify_book(
        path=Path(remote_path),
        metadata={"title": Path(remote_path).stem},
        content_sample=content_sample,
        api_key=api_key,
    )

    return {
        "category": classification.category,
        "dest_filename": classification.dest_filename,
    }


def reorganize(dry_run: bool = False, api_key: str | None = None) -> list[dict]:
    """Reorganize all remote scan directories."""
    all_results = []

    for remote_dir in REMOTE_SCAN_DIRS:
        dir_results = {
            "directory": remote_dir,
            "plans": [],
            "successes": 0,
            "failures": 0,
        }

        ebooks = list_remote_ebooks(remote_dir)
        logger.info("Found %d e-books in %s", len(ebooks), remote_dir)

        for ebook_path in ebooks:
            if api_key:
                classification = classify_remote_book(ebook_path, api_key)
            else:
                classification = {
                    "category": "uncategorized",
                    "dest_filename": Path(ebook_path).name,
                }

            move_plan = plan_move(
                remote_path=ebook_path,
                category=classification["category"],
                dest_filename=classification["dest_filename"],
            )
            dir_results["plans"].append(move_plan)

            if not dry_run:
                if execute_move(move_plan):
                    dir_results["successes"] += 1
                else:
                    dir_results["failures"] += 1

        all_results.append(dir_results)

    return all_results
