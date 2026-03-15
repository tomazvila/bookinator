"""Book cover preview generation with caching."""

import os
import zipfile
import xml.etree.ElementTree as ET

import fitz  # pymupdf


def get_cache_dir(books_dir: str) -> str:
    """Return the preview cache directory, creating it if needed."""
    cache_dir = os.path.join(books_dir, ".bookstuff-cache", "previews")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def get_preview_path(books_dir: str, book_id: int) -> str:
    """Return the cached preview file path for a given book ID."""
    return os.path.join(get_cache_dir(books_dir), f"{book_id}.jpg")


def generate_pdf_preview(book_path: str, dest: str, width: int = 400) -> bool:
    """Render the first page of a PDF as a JPEG thumbnail.

    Returns True on success, False on failure.
    """
    try:
        doc = fitz.open(book_path)
        page = doc[0]
        # Scale to target width
        zoom = width / page.rect.width
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        pix.save(dest)
        doc.close()
        return True
    except Exception:
        return False


def generate_epub_preview(book_path: str, dest: str) -> bool:
    """Extract cover image from an EPUB file.

    Tries three strategies:
    1. OPF metadata cover reference
    2. Filename heuristic (files containing 'cover')
    3. First image in the archive

    Returns True on success, False on failure.
    """
    try:
        with zipfile.ZipFile(book_path, "r") as zf:
            names = zf.namelist()
            image_exts = (".jpg", ".jpeg", ".png", ".gif", ".webp")

            # Strategy 1: Parse OPF for cover metadata
            cover_path = _find_cover_from_opf(zf, names)
            if cover_path:
                _extract_image(zf, cover_path, dest)
                return True

            # Strategy 2: Filename heuristic
            for name in names:
                lower = name.lower()
                if "cover" in lower and lower.endswith(image_exts):
                    _extract_image(zf, name, dest)
                    return True

            # Strategy 3: First image in archive
            for name in names:
                if name.lower().endswith(image_exts):
                    _extract_image(zf, name, dest)
                    return True

        return False
    except Exception:
        return False


def _find_cover_from_opf(zf: zipfile.ZipFile, names: list[str]) -> str | None:
    """Find cover image path by parsing the OPF manifest."""
    # Find the OPF file
    opf_path = None
    for name in names:
        if name.lower().endswith(".opf"):
            opf_path = name
            break
    if not opf_path:
        return None

    try:
        opf_data = zf.read(opf_path)
        root = ET.fromstring(opf_data)
        ns = {"opf": "http://www.idpf.org/2007/opf"}

        # Find meta with name="cover"
        for meta in root.findall(".//opf:meta[@name='cover']", ns):
            cover_id = meta.get("content")
            if not cover_id:
                continue
            # Find the manifest item with that ID
            for item in root.findall(".//opf:item", ns):
                if item.get("id") == cover_id:
                    href = item.get("href", "")
                    # Resolve relative to OPF directory
                    opf_dir = os.path.dirname(opf_path)
                    full_path = os.path.join(opf_dir, href) if opf_dir else href
                    # Normalize path separators
                    full_path = full_path.replace("\\", "/")
                    if full_path in names:
                        return full_path

        # Also check for items with properties="cover-image" (EPUB 3)
        for item in root.findall(".//opf:item", ns):
            props = item.get("properties", "")
            if "cover-image" in props:
                href = item.get("href", "")
                opf_dir = os.path.dirname(opf_path)
                full_path = os.path.join(opf_dir, href) if opf_dir else href
                full_path = full_path.replace("\\", "/")
                if full_path in names:
                    return full_path
    except Exception:
        pass

    return None


def _extract_image(zf: zipfile.ZipFile, image_path: str, dest: str) -> None:
    """Extract an image from a zip file and write it to dest."""
    data = zf.read(image_path)
    with open(dest, "wb") as f:
        f.write(data)


def generate_preview(
    books_dir: str, book_id: int, book_path: str, extension: str
) -> str | None:
    """Generate a preview image for a book, using cache if available.

    Returns the path to the preview JPEG, or None if preview not possible.
    """
    preview_path = get_preview_path(books_dir, book_id)

    # Return cached version if it exists
    if os.path.exists(preview_path):
        return preview_path

    ext = extension.lower()
    if ext == "pdf":
        ok = generate_pdf_preview(book_path, preview_path)
    elif ext == "epub":
        ok = generate_epub_preview(book_path, preview_path)
    else:
        return None

    if ok:
        return preview_path

    # Clean up failed partial file
    if os.path.exists(preview_path):
        os.remove(preview_path)
    return None
