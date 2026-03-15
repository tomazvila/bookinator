"""SHA-256 hashing for duplicate detection."""

import hashlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def hash_file(path: Path, chunk_size: int = 8192) -> str:
    """Compute SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            sha256.update(chunk)
    return sha256.hexdigest()


def find_duplicates(paths: list[Path]) -> dict[str, list[Path]]:
    """Find duplicate files by content hash.

    Returns a dict mapping hash -> list of paths for groups with 2+ files.
    """
    hash_map: dict[str, list[Path]] = {}

    for path in paths:
        try:
            h = hash_file(path)
            hash_map.setdefault(h, []).append(path)
        except (OSError, PermissionError) as e:
            logger.warning("Could not hash %s: %s", path, e)

    return {h: paths for h, paths in hash_map.items() if len(paths) > 1}
