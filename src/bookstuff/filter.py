"""Distinguish real books from invoices/CVs/tax docs."""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Patterns that indicate a file is NOT a book
REJECTION_PATTERNS = [
    r"invoice",
    r"receipt",
    r"(?:^|[\s_-])cv(?:$|[\s_-])",
    # Match personal resumes (name_resume, resume_2024) but not book titles about resumes
    r"(?:my|personal)[\s_-]?resume|resume[\s_-]?\d",
    r"curriculum[\s_-]?vitae",
    r"(?:^|[\s_-])tax(?:$|[\s_-])",
    r"bank[\s_-]?statement",
    r"cover[\s_-]?letter",
    r"payslip",
    r"pay[\s_-]?stub",
    r"utility[\s_-]?bill",
    r"electricity[\s_-]?bill",
    r"water[\s_-]?bill",
    # Non-book documents
    r"(?:^|[\s_-])ticket(?:$|[\s_-])",
    r"booking[\s_-]?confirmation",
    r"(?:^|[\s_-])coupon(?:$|[\s_-])",
    r"camscanner",
    r"(?:^|[\s_-])voucher(?:$|[\s_-])",
    r"kuponas",
    r"user[\s_-]?manual",
    r"form[\s_-]?fr\d",
]

# Compile patterns for efficiency
_COMPILED_PATTERNS = [(re.compile(p, re.IGNORECASE), p) for p in REJECTION_PATTERNS]


@dataclass
class FilterResult:
    path: Path
    is_book: bool
    reason: str


def filter_file(path: Path) -> FilterResult:
    """Determine if a file is likely a real book based on filename heuristics."""
    filename = path.stem  # filename without extension

    for pattern, raw in _COMPILED_PATTERNS:
        if pattern.search(filename):
            reason = f"filename matches rejection pattern: {raw}"
            logger.debug("Rejecting %s: %s", path, reason)
            return FilterResult(path=path, is_book=False, reason=reason)

    return FilterResult(path=path, is_book=True, reason="no rejection patterns matched")


def filter_files(paths: list[Path]) -> list[FilterResult]:
    """Filter a list of file paths, returning FilterResult for each."""
    return [filter_file(p) for p in paths]
