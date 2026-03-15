# BookStuff — E-Book Scanner, Classifier & Uploader

## Overview

A Python CLI tool that scans local directories for e-books, classifies them by subject/category using LLM-assisted analysis (Claude API), deduplicates them, and uploads them to a remote server in an organized directory structure. Also supports reorganizing existing book collections already on the remote server.

## Infrastructure

- **Stack**: Python, nix flake, pytest
- **Everything runs through nix**: `nix develop`, `nix build`, `nix flake check`
- **Remote server**: `ssh lilvilla@ssh.tomazvi.la` (SSH key auth, no password)
- **Remote destination**: `/mnt/ssdb/books/`
- **Transfer**: `rsync` over SSH
- **Classification**: Claude API (Anthropic Python SDK) for subject classification
- **Manifest**: `./manifest.json` in the project directory

## Local scan directories

- `/Users/home/Programming/bookstuff`
- `~/Downloads`
- `~/Documents`

Scan recursively into subdirectories. **Skip**: hidden directories (`.git`, `.Trash`, etc.), `src/`, `tests/`, `test_fixtures/`.

No file size limits — scan everything that matches.

## Remote scan directories (reorganization)

Existing book collections on the remote server should also be reorganized into `/mnt/ssdb/books/`:
- `/mnt/ssdb/AK/`
- `/mnt/ssdb/financial knowloedge/`

These are scanned over SSH, classified, and moved (on the remote) into the organized `/mnt/ssdb/books/<category>/` structure. Same dedup and safety rules apply — never delete, only move/copy.

## E-book file formats

Recognized extensions: `.pdf`, `.epub`, `.mobi`, `.djvu`, `.azw3`, `.cbz`

## Filtering — ignore non-books

Not all files with these extensions are books. The tool MUST filter out:
- Invoices, receipts, bills
- CVs, resumes, cover letters
- Tax documents, bank statements
- Any personal/administrative documents

Use a combination of filename heuristics and (for ambiguous cases) content sampling to decide. When in doubt, **skip the file** and log it as "skipped — uncertain" rather than uploading junk.

## Classification — LLM-assisted (Claude API)

Books must be classified into a subject/category for organization. The approach:

1. **Read metadata first** — EPUB has rich metadata (title, author, subject). PDF has XMP/DocInfo. Use these when available.
2. **Fall back to content sampling** — If metadata is insufficient, extract text from first ~5 pages.
3. **Send to Claude API for classification** — Pass the extracted metadata/content to Claude API with the category taxonomy. Ask it to return: title, author (if detectable), and category. This is far more accurate than keyword matching.
4. **Image-scanned PDFs** (no extractable text) — classify as `uncategorized` and upload anyway.
5. **Normalize filenames** — `Author - Title.ext` format when author/title are known, otherwise keep original filename cleaned up (no special chars, no excessive whitespace).

### Claude API usage

- Use `anthropic` Python SDK
- API key from `ANTHROPIC_API_KEY` env var (must be set, fail clearly if missing)
- Use a small/cheap model (e.g., `claude-haiku-4-5-20251001`) for classification to minimize cost
- Batch classifications where possible to reduce API calls
- Cache classification results in the manifest so re-runs don't re-classify

### Category taxonomy

```
books/
├── programming/
├── computer-science/
├── mathematics/
├── physics/
├── finance-and-economics/
├── business-and-management/
├── philosophy/
├── psychology/
├── self-help/
├── history/
├── science/
├── fiction/
├── reference/
├── art-and-design/
├── uncategorized/
```

If a book doesn't clearly fit, put it in `uncategorized/`. The LLM should pick from this list only.

## Deduplication

- Detect duplicates by **file content hash** (SHA-256).
- Before uploading, check if a file with the same hash already exists on the remote (maintain a local manifest/index of what's been uploaded).
- **NEVER delete a local or remote file automatically.** If a duplicate is detected, skip the upload and log it. No destructive operations on accident.
- The manifest is stored at `./manifest.json` in the project directory, and synced to the remote at `/mnt/ssdb/books/manifest.json`.

## Dry-run mode

`--dry-run` flag that:
- Scans and classifies all books
- Shows what would be uploaded and where
- Shows detected duplicates
- Does NOT transfer any files
- Outputs a summary report

## CLI interface

```
bookstuff scan [--dry-run] [--verbose]
bookstuff upload [--dry-run] [--verbose]
bookstuff status
bookstuff reorganize [--dry-run] [--verbose]
```

- `scan` — scan local dirs, classify, detect dupes, update local manifest
- `upload` — transfer pending books to remote server via rsync
- `status` — print summary of manifest state (uploaded, pending, duplicates)
- `reorganize` — scan existing remote directories (`AK`, `financial knowloedge`), classify, and move books into `/mnt/ssdb/books/<category>/` on the remote

## Remote directory structure

```
/mnt/ssdb/books/
├── programming/
│   ├── Author - Title.pdf
│   └── ...
├── mathematics/
│   └── ...
├── manifest.json
└── ...
```

## Project structure

```
bookstuff/
├── flake.nix
├── flake.lock
├── PRD.md
├── ralph.sh
├── manifest.json
├── src/
│   └── bookstuff/
│       ├── __init__.py
│       ├── cli.py          # CLI entry point (click)
│       ├── scanner.py      # Find e-book files in directories
│       ├── filter.py       # Decide if a file is a real book vs junk
│       ├── classifier.py   # Extract metadata + LLM classification
│       ├── dedup.py        # SHA-256 hashing, duplicate detection
│       ├── uploader.py     # rsync transfer to remote
│       ├── manifest.py     # Manifest read/write/query
│       └── reorganizer.py  # Reorganize existing remote collections
├── tests/
│   ├── test_scanner.py
│   ├── test_filter.py
│   ├── test_classifier.py
│   ├── test_dedup.py
│   ├── test_uploader.py
│   ├── test_manifest.py
│   ├── test_reorganizer.py
│   ├── test_cli.py
│   └── test_integration.py  # Integration tests (SSH to real server)
└── test_fixtures/
    └── (small sample files for tests)
```

## Tasks (parallelizable)

Each task should have tests written FIRST, then implementation.

### Task 1: Project scaffolding
- Create `flake.nix` with Python + dependencies (ebooklib, pymupdf, click, anthropic)
- Set up `src/bookstuff/` package structure
- Verify `nix develop --command python -m pytest tests/ -v` runs

### Task 2: Scanner (`scanner.py`)
- Recursively scan directories for files matching e-book extensions
- Skip hidden directories, `src/`, `tests/`, `test_fixtures/`
- Return list of `BookFile(path, extension, size, mtime)` objects
- Handle permission errors gracefully (log and skip)
- Tests: mock filesystem, verify correct files found, hidden dirs skipped

### Task 3: Filter (`filter.py`)
- Filename-based heuristics: reject files matching patterns like `invoice`, `receipt`, `cv`, `resume`, `bank`, `statement`, `tax`
- For ambiguous PDFs: sample first page text, check for invoice/receipt/personal doc patterns
- Return `FilterResult(path, is_book, reason)`
- Tests: sample filenames and mock content, verify filtering decisions

### Task 4: Classifier (`classifier.py`)
- Extract metadata from EPUB (ebooklib) and PDF (pymupdf)
- If metadata insufficient, extract text from first ~5 pages
- Call Claude API (haiku) with extracted info + category taxonomy, get back title/author/category
- Image-scanned PDFs with no extractable text → `uncategorized`
- Cache results in manifest to avoid re-classifying
- Normalize filenames: `Author - Title.ext`
- Return `ClassificationResult(path, title, author, category, confidence, dest_filename)`
- Tests: mock Claude API responses, fixture EPUBs/PDFs with known metadata, verify classification

### Task 5: Dedup & Manifest (`dedup.py`, `manifest.py`)
- SHA-256 hash files
- Manifest as JSON: `{hash: {path, category, dest_filename, uploaded_at, remote_path}}`
- Load/save manifest at `./manifest.json`
- Sync manifest to remote `/mnt/ssdb/books/manifest.json`
- Check for duplicates before upload
- NEVER delete files — only skip and log
- Tests: verify hash computation, manifest CRUD, duplicate detection

### Task 6: Uploader (`uploader.py`)
- Use `rsync -avz -e ssh` to transfer files to `lilvilla@ssh.tomazvi.la:/mnt/ssdb/books/<category>/`
- Create remote directories as needed
- Update manifest after successful upload
- Dry-run mode: log what would happen, don't transfer
- Tests: mock subprocess/rsync calls, verify correct commands built

### Task 7: Reorganizer (`reorganizer.py`)
- SSH to remote, list files in `/mnt/ssdb/AK/` and `/mnt/ssdb/financial knowloedge/`
- For each e-book: download metadata/content sample, classify via Claude API
- Move (on the remote via SSH `mv`) into `/mnt/ssdb/books/<category>/`
- Update manifest
- Dry-run mode: show plan without moving
- NEVER delete — only move into organized structure
- Tests: mock SSH commands, verify move plans

### Task 8: CLI (`cli.py`)
- `scan`, `upload`, `status`, `reorganize` subcommands
- `--dry-run` and `--verbose` flags
- Wire everything together
- Fail clearly if `ANTHROPIC_API_KEY` is not set
- Tests: invoke CLI with test args, verify output

### Task 9: Integration tests (`test_integration.py`)
- Real SSH connection to `lilvilla@ssh.tomazvi.la`
- Verify remote directory creation, rsync transfer, manifest sync
- Mark with `@pytest.mark.integration` so they can be skipped in CI
- Run with: `nix develop --command python -m pytest tests/test_integration.py -v -m integration`

## Completion criteria

All tests pass. `bookstuff scan --dry-run` produces a correct classification report for the local directories. `bookstuff upload --dry-run` shows the correct rsync plan. `bookstuff reorganize --dry-run` shows a plan for existing remote collections. No destructive operations ever happen automatically.

## Safety rules

1. **NEVER delete files** — not locally, not remotely. Only copy/upload/move-into-organized-structure.
2. **NEVER overwrite** — if destination exists and differs, log a conflict, don't overwrite.
3. **Dry-run is default-safe** — the tool should be safe to run at any time.
4. **Log everything** — every decision (skip, classify, upload, duplicate, move) should be logged.
5. **Reorganize = move, not delete** — remote reorganization moves files into the new structure, source files in `AK`/`financial knowloedge` are left alone until manually cleaned up.
