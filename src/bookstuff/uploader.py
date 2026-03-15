"""Transfer files via rsync to remote server."""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

REMOTE_HOST = "lilvilla@ssh.tomazvi.la"
REMOTE_BASE = "/mnt/ssdb/books"


def build_rsync_command(local_path: Path, category: str, dest_filename: str) -> list[str]:
    """Build the rsync command to upload a file."""
    remote_dest = f"{REMOTE_HOST}:{REMOTE_BASE}/{category}/{dest_filename}"
    return ["rsync", "-avz", "-e", "ssh", str(local_path), remote_dest]


def upload_file(
    local_path: Path,
    category: str,
    dest_filename: str,
    dry_run: bool = False,
) -> bool:
    """Upload a single file to the remote server.

    Returns True on success, False on failure.
    """
    if dry_run:
        logger.info("[DRY RUN] Would upload %s -> %s/%s/%s", local_path, REMOTE_BASE, category, dest_filename)
        return True

    # Create remote directory first
    result = subprocess.run(
        ["ssh", REMOTE_HOST, "mkdir", "-p", f"{REMOTE_BASE}/{category}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        logger.error("Failed to create remote dir: %s", result.stderr)
        return False

    # rsync the file
    cmd = build_rsync_command(local_path, category, dest_filename)
    logger.info("Uploading %s -> %s/%s/%s", local_path, REMOTE_BASE, category, dest_filename)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error("rsync failed for %s: %s", local_path, result.stderr)
            return False
        return True
    except Exception as e:
        logger.error("Upload error for %s: %s", local_path, e)
        return False


def upload_files(files: list[dict], dry_run: bool = False) -> list[bool]:
    """Upload multiple files. Each dict should have local_path, category, dest_filename."""
    results = []
    for f in files:
        ok = upload_file(
            local_path=f["local_path"],
            category=f["category"],
            dest_filename=f["dest_filename"],
            dry_run=dry_run,
        )
        results.append(ok)
    return results
