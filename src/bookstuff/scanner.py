"""Recursively find e-book files in directories."""

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

EBOOK_EXTENSIONS = {".pdf", ".epub", ".mobi", ".djvu", ".azw3", ".cbz"}
SKIP_DIRS = {"src", "tests", "test_fixtures"}


@dataclass
class BookFile:
    path: Path
    extension: str
    size: int
    mtime: float

    def __str__(self):
        return f"BookFile({self.path.name}, {self.extension}, {self.size}B)"


def scan_directory(directory: Path) -> list[BookFile]:
    """Recursively scan a directory for e-book files.

    Skips hidden directories, src/, tests/, test_fixtures/.
    Handles permission errors gracefully.
    """
    results = []
    directory = Path(directory)

    if not directory.exists():
        logger.warning("Directory does not exist: %s", directory)
        return results

    try:
        for entry in sorted(directory.iterdir()):
            if entry.is_dir():
                if entry.name.startswith("."):
                    logger.debug("Skipping hidden directory: %s", entry)
                    continue
                if entry.name in SKIP_DIRS:
                    logger.debug("Skipping excluded directory: %s", entry)
                    continue
                results.extend(scan_directory(entry))
            elif entry.is_file():
                if entry.suffix.lower() in EBOOK_EXTENSIONS:
                    stat = entry.stat()
                    results.append(BookFile(
                        path=entry,
                        extension=entry.suffix.lower(),
                        size=stat.st_size,
                        mtime=stat.st_mtime,
                    ))
    except PermissionError:
        logger.warning("Permission denied: %s", directory)

    return results


def scan_directories(directories: list[Path]) -> list[BookFile]:
    """Scan multiple directories for e-book files, deduplicating by path."""
    seen_paths = set()
    results = []

    for d in directories:
        d = Path(d)
        if not d.exists():
            logger.warning("Skipping nonexistent directory: %s", d)
            continue
        for bf in scan_directory(d):
            if bf.path not in seen_paths:
                seen_paths.add(bf.path)
                results.append(bf)

    return results
