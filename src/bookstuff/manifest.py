"""JSON manifest tracking uploaded files."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class Manifest:
    """Manages a JSON manifest of scanned/uploaded books.

    Format: {hash: {path, category, dest_filename, uploaded_at, remote_path}}
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.entries: dict[str, dict] = {}

    def load(self):
        """Load manifest from disk. No-op if file doesn't exist."""
        if self.path.exists():
            with open(self.path) as f:
                self.entries = json.load(f)
            logger.info("Loaded manifest with %d entries from %s", len(self.entries), self.path)
        else:
            logger.debug("Manifest file does not exist: %s", self.path)
            self.entries = {}

    def save(self):
        """Save manifest to disk."""
        with open(self.path, "w") as f:
            json.dump(self.entries, f, indent=2)
        logger.info("Saved manifest with %d entries to %s", len(self.entries), self.path)

    def add_entry(self, file_hash: str, path: str, category: str, dest_filename: str):
        """Add or update a manifest entry."""
        self.entries[file_hash] = {
            "path": path,
            "category": category,
            "dest_filename": dest_filename,
            "uploaded_at": None,
            "remote_path": None,
        }

    def has_hash(self, file_hash: str) -> bool:
        """Check if a hash already exists in the manifest."""
        return file_hash in self.entries

    def mark_uploaded(self, file_hash: str, remote_path: str):
        """Mark a file as uploaded with timestamp and remote path."""
        if file_hash in self.entries:
            self.entries[file_hash]["uploaded_at"] = datetime.now(timezone.utc).isoformat()
            self.entries[file_hash]["remote_path"] = remote_path

    def get_pending(self) -> dict[str, dict]:
        """Get entries that haven't been uploaded yet."""
        return {h: e for h, e in self.entries.items() if e.get("uploaded_at") is None}

    def get_uploaded(self) -> dict[str, dict]:
        """Get entries that have been uploaded."""
        return {h: e for h, e in self.entries.items() if e.get("uploaded_at") is not None}

    def get_stats(self) -> dict[str, int]:
        """Get summary statistics."""
        uploaded = len(self.get_uploaded())
        pending = len(self.get_pending())
        return {
            "total": len(self.entries),
            "uploaded": uploaded,
            "pending": pending,
        }
