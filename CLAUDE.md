# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

BookStuff is a Python CLI tool that scans local directories for e-books, classifies them by subject/category using Claude API (Anthropic SDK), deduplicates via SHA-256 hashing, and uploads them to a remote server (`lilvilla@ssh.tomazvi.la:/mnt/ssdb/books/`) via rsync. It also reorganizes existing remote book collections.

## Build & Development Commands

Everything runs through nix:

```bash
# Enter dev shell
nix develop

# Run all unit tests (excludes integration tests)
nix develop --command python -m pytest tests/ -v -m 'not integration'

# Run a single test file
nix develop --command python -m pytest tests/test_scanner.py -v

# Run a single test
nix develop --command python -m pytest tests/test_scanner.py::test_function_name -v

# Run integration tests (requires SSH access to remote server)
nix develop --command python -m pytest tests/test_integration.py -v -m integration

# Build / check
nix build
nix flake check
```

## Automated Development Loop

`ralph.sh` is a "Ralph Wiggum Loop" — it repeatedly invokes Claude Code with `--dangerously-skip-permissions` and `--output-format stream-json`, reads `PRD.md`, checks test state, picks tasks, writes tests first, then implements until all tests pass. It logs iteration summaries to `ralph_log.md`. Run with `./ralph.sh [max_iterations]`.

## Architecture

The CLI is built with `click` and organized into these modules under `src/bookstuff/`:

| Module | Purpose |
|---|---|
| `cli.py` | Click CLI entry point with `scan`, `upload`, `status`, `reorganize` subcommands |
| `scanner.py` | Recursively finds e-book files (`.pdf`, `.epub`, `.mobi`, `.djvu`, `.azw3`, `.cbz`) in local dirs, skipping hidden dirs and `src/`, `tests/`, `test_fixtures/` |
| `filter.py` | Distinguishes real books from invoices/CVs/tax docs using filename heuristics and content sampling |
| `classifier.py` | Extracts metadata (ebooklib for EPUB, pymupdf for PDF), falls back to content sampling, then calls Claude API (`claude-haiku-4-5-20251001`) for title/author/category classification. Normalizes filenames to `Author - Title.ext` |
| `dedup.py` | SHA-256 hashing for duplicate detection |
| `manifest.py` | JSON manifest (`./manifest.json`) tracking uploaded files, synced to remote at `/mnt/ssdb/books/manifest.json` |
| `uploader.py` | Transfers files via `rsync -avz -e ssh` to remote server |
| `reorganizer.py` | Scans existing remote dirs (`/mnt/ssdb/AK/`, `/mnt/ssdb/financial knowloedge/`) over SSH, classifies, and moves books into organized structure on the remote |

**Data flow**: Scanner -> Filter -> Classifier -> Dedup -> Uploader (with Manifest tracking throughout)

## Key Dependencies (managed in flake.nix)

- `ebooklib` — EPUB metadata extraction
- `pymupdf` — PDF metadata/text extraction
- `click` — CLI framework
- `anthropic` — Claude API for LLM classification

## Category Taxonomy

Books are classified into: `programming`, `computer-science`, `mathematics`, `physics`, `finance-and-investing`, `business-and-management`, `philosophy`, `psychology`, `self-help`, `history`, `science`, `fiction`, `reference`, `art-and-design`, `uncategorized`.

## Safety Rules

- **NEVER delete files** — locally or remotely. Only copy/upload/move-into-organized-structure.
- **NEVER overwrite** — log conflicts if destination exists and differs.
- Reorganize means move, not delete — source files in `AK`/`financial knowloedge` are left alone.
- `ANTHROPIC_API_KEY` env var must be set; fail clearly if missing.

## Testing Conventions

- Tests live in `tests/` with a `test_` prefix per module.
- Unit tests must use mocks — no real SSH, no real directory scanning, no real API calls.
- Integration tests (`test_integration.py`) use `@pytest.mark.integration` and CAN connect to the real remote server.
- Test fixtures go in `test_fixtures/` (small sample EPUBs/PDFs).
- Write tests FIRST, then implement (TDD workflow per PRD).

## Local Scan Directories

- `/Users/home/Programming/bookstuff` (the project dir itself, contains `EBooks/`)
- `~/Downloads`
- `~/Documents`

## Remote Server

- Host: `lilvilla@ssh.tomazvi.la` (SSH key auth)
- Destination: `/mnt/ssdb/books/<category>/`
- Existing collections to reorganize: `/mnt/ssdb/AK/`, `/mnt/ssdb/financial knowloedge/`

## Design Context

### Users
Personal tool for a single developer managing a large e-book collection. Used when searching for a specific book to read or reference — efficiency matters more than exploration. Accessed via `books.tomazvi.la` on local network.

### Brand Personality
**Bold, modern, sharp.** The interface should feel like a precision tool — confident and direct, not decorative. Think Notion or Obsidian: structured, clean, keyboard-friendly.

### Aesthetic Direction
- **Theme**: Tokyo Night dark palette (already established in `style.css`)
- **Typography**: Inter, clean hierarchy, no ornamental type
- **Layout**: Dense but breathable — maximize information density without clutter
- **References**: Notion, Obsidian — knowledge management tools with crisp edges and structured layouts
- **Anti-references**: Goodreads (too social/cluttered), Calibre (too utilitarian/dated)
- **Mode**: Dark only — no light mode needed

### Design Principles
1. **Speed over spectacle** — The interface exists to find and download books fast. Every element should reduce time-to-book.
2. **Structure is the aesthetic** — Well-organized information IS the design. Categories, metadata, and search results should feel satisfying through clarity alone.
3. **Sharp, not soft** — Prefer crisp edges, strong contrast, and decisive spacing over rounded, gentle, or playful treatments.
4. **No decoration without function** — Every visual element must earn its place. Color-coded extension badges work because they convey information at a glance.
5. **Keyboard-first interactions** — Design for someone who reaches for `/` before the mouse.
