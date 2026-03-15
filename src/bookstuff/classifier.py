"""Extract metadata and classify books using Claude API."""

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import anthropic
from ebooklib import epub
import fitz  # pymupdf

logger = logging.getLogger(__name__)

CATEGORIES = [
    "programming",
    "computer-science",
    "mathematics",
    "physics",
    "finance-and-investing",
    "business-and-management",
    "philosophy",
    "psychology",
    "self-help",
    "history",
    "science",
    "fiction",
    "reference",
    "art-and-design",
    "uncategorized",
]

MODEL = "claude-haiku-4-5-20251001"


@dataclass
class ClassificationResult:
    path: Path
    title: str | None
    author: str | None
    category: str
    dest_filename: str


def normalize_filename(author: str | None, title: str | None, extension: str) -> str:
    """Normalize a filename to 'Author - Title.ext' format."""
    def clean(s: str) -> str:
        s = s.strip()
        s = re.sub(r'[/:*?"<>|]', "", s)
        s = re.sub(r"\s+", " ", s)
        return s.strip()

    if title:
        title = clean(title)
    if author:
        author = clean(author)

    if author and title:
        return f"{author} - {title}{extension}"
    elif title:
        return f"{title}{extension}"
    elif author:
        return f"{author} - Unknown Title{extension}"
    else:
        return f"Unknown{extension}"


def extract_pdf_metadata(path: Path) -> tuple[dict, str]:
    """Extract metadata and text sample from a PDF."""
    metadata = {}
    text = ""
    try:
        with fitz.open(path) as doc:
            metadata = dict(doc.metadata) if doc.metadata else {}
            pages = []
            for i, page in enumerate(doc):
                if i >= 5:
                    break
                pages.append(page.get_text())
            text = "\n".join(pages)
    except Exception as e:
        logger.warning("Could not extract PDF metadata from %s: %s", path, e)
    return metadata, text


def extract_epub_metadata(path: Path) -> dict:
    """Extract metadata from an EPUB file."""
    metadata = {}
    try:
        book = epub.read_epub(path)
        title_meta = book.get_metadata("DC", "title")
        if title_meta:
            metadata["title"] = title_meta[0][0]
        author_meta = book.get_metadata("DC", "creator")
        if author_meta:
            metadata["author"] = author_meta[0][0]
        subject_meta = book.get_metadata("DC", "subject")
        if subject_meta:
            metadata["subject"] = subject_meta[0][0]
    except Exception as e:
        logger.warning("Could not extract EPUB metadata from %s: %s", path, e)
    return metadata


def classify_book(
    path: Path,
    metadata: dict,
    content_sample: str,
    api_key: str | None,
) -> ClassificationResult:
    """Classify a book using Claude API.

    If no API key or no content, returns uncategorized.
    """
    title = metadata.get("title") or path.stem
    author = metadata.get("author")

    if not api_key:
        return ClassificationResult(
            path=path,
            title=title,
            author=author,
            category="uncategorized",
            dest_filename=normalize_filename(author, title, path.suffix),
        )

    try:
        client = anthropic.Anthropic(api_key=api_key)

        prompt_parts = [f"Filename: {path.name}", f"File path: {path}"]
        if metadata:
            prompt_parts.append(f"Metadata: {json.dumps(metadata)}")
        if content_sample:
            prompt_parts.append(f"Content sample (first pages):\n{content_sample[:3000]}")

        categories_str = ", ".join(CATEGORIES)

        response = client.messages.create(
            model=MODEL,
            max_tokens=256,
            messages=[{
                "role": "user",
                "content": (
                    f"Classify this e-book. Return JSON with: title, author, category.\n"
                    f"Categories: {categories_str}\n"
                    f"Pick the single best category. If unsure, use 'uncategorized'.\n\n"
                    f"{''.join(prompt_parts)}\n\n"
                    f"Return ONLY valid JSON: {{\"title\": \"...\", \"author\": \"...\", \"category\": \"...\"}}"
                ),
            }],
        )

        raw = response.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)

        classified_title = data.get("title") or title
        classified_author = data.get("author") or author
        classified_category = data.get("category", "uncategorized")

        if classified_category not in CATEGORIES:
            logger.warning("Invalid category '%s', falling back to uncategorized", classified_category)
            classified_category = "uncategorized"

        return ClassificationResult(
            path=path,
            title=classified_title,
            author=classified_author,
            category=classified_category,
            dest_filename=normalize_filename(classified_author, classified_title, path.suffix),
        )

    except Exception as e:
        logger.warning("Classification failed for %s: %s", path, e)
        return ClassificationResult(
            path=path,
            title=title,
            author=author,
            category="uncategorized",
            dest_filename=normalize_filename(author, title, path.suffix),
        )


def classify_batch(paths: list[str], api_key: str) -> list[dict]:
    """Classify a batch of files in a single API call.

    Returns list of dicts with keys: path, title, author, category, dest_filename.
    """
    categories_str = ", ".join(CATEGORIES)

    file_list = "\n".join(
        f"{i+1}. {p}" for i, p in enumerate(paths)
    )

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": (
                f"Classify each e-book file below. For each, determine the title, author, and category.\n"
                f"Categories: {categories_str}\n"
                f"Pick the single best category for each. If unsure, use 'uncategorized'.\n"
                f"Files that are clearly NOT books (READMEs, CVs, tickets, menus, invoices, "
                f"app resources, cheat sheets, course syllabi, ERD diagrams, installation guides) "
                f"should get category 'skip'.\n\n"
                f"Files:\n{file_list}\n\n"
                f"Return ONLY a valid JSON array, one object per file in order:\n"
                f"[{{\"title\": \"...\", \"author\": \"...\", \"category\": \"...\"}}, ...]"
            ),
        }],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    items = json.loads(raw)

    results = []
    for i, item in enumerate(items):
        if i >= len(paths):
            break
        p = paths[i]
        ext = Path(p).suffix
        title = item.get("title") or Path(p).stem
        author = item.get("author")
        category = item.get("category", "uncategorized")

        if category not in CATEGORIES and category != "skip":
            category = "uncategorized"

        dest_filename = normalize_filename(author, title, ext) if category != "skip" else None

        results.append({
            "path": p,
            "title": title,
            "author": author,
            "category": category,
            "dest_filename": dest_filename,
        })

    return results
