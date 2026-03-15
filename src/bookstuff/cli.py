"""Click CLI entry point."""

import logging
import os
import sys
from pathlib import Path

import click

from bookstuff.scanner import scan_directories
from bookstuff.filter import filter_file
from bookstuff.classifier import classify_book, extract_pdf_metadata, extract_epub_metadata
from bookstuff.dedup import hash_file
from bookstuff.manifest import Manifest
from bookstuff.uploader import upload_file
from bookstuff.reorganizer import reorganize

SCAN_DIRS = [
    Path("/Users/home/Programming/bookstuff"),
    Path.home() / "Downloads",
    Path.home() / "Documents",
]

MANIFEST_PATH = Path("./manifest.json")


@click.group()
@click.option("--verbose", is_flag=True, help="Enable verbose logging.")
def cli(verbose):
    """BookStuff — E-Book Scanner, Classifier & Uploader."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


@cli.command()
@click.option("--dry-run", is_flag=True, help="Show what would happen without making changes.")
@click.option("--verbose", is_flag=True, help="Enable verbose logging.")
def scan(dry_run, verbose):
    """Scan local directories for e-books, classify, and detect duplicates."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        click.echo("Warning: ANTHROPIC_API_KEY not set. Books will be classified as 'uncategorized'.")

    manifest = Manifest(MANIFEST_PATH)
    manifest.load()

    click.echo("Scanning directories...")
    books = scan_directories(SCAN_DIRS)
    click.echo(f"Found {len(books)} e-book files.")

    for bf in books:
        # Filter
        fr = filter_file(bf.path)
        if not fr.is_book:
            click.echo(f"  SKIP (not a book): {bf.path.name} — {fr.reason}")
            continue

        # Dedup
        file_hash = hash_file(bf.path)
        if manifest.has_hash(file_hash):
            click.echo(f"  SKIP (duplicate): {bf.path.name}")
            continue

        # Classify
        metadata = {}
        content_sample = ""
        if bf.extension == ".pdf":
            metadata, content_sample = extract_pdf_metadata(bf.path)
        elif bf.extension == ".epub":
            metadata = extract_epub_metadata(bf.path)

        result = classify_book(
            path=bf.path,
            metadata=metadata,
            content_sample=content_sample,
            api_key=api_key,
        )

        click.echo(f"  {result.category}: {result.dest_filename}")

        manifest.add_entry(
            file_hash=file_hash,
            path=str(bf.path),
            category=result.category,
            dest_filename=result.dest_filename,
        )

    if not dry_run:
        manifest.save()
        click.echo(f"Manifest saved ({len(manifest.entries)} entries).")
    else:
        click.echo("[DRY RUN] Manifest not saved.")

    stats = manifest.get_stats()
    click.echo(f"Total: {stats['total']}, Pending: {stats['pending']}, Uploaded: {stats['uploaded']}")


@cli.command()
@click.option("--dry-run", is_flag=True, help="Show what would be uploaded without transferring.")
@click.option("--verbose", is_flag=True, help="Enable verbose logging.")
def upload(dry_run, verbose):
    """Upload pending books to remote server."""
    manifest = Manifest(MANIFEST_PATH)
    manifest.load()

    pending = manifest.get_pending()
    if not pending:
        click.echo("Nothing to upload.")
        return

    click.echo(f"Uploading {len(pending)} files...")

    for file_hash, entry in pending.items():
        local_path = Path(entry["path"])
        if not local_path.exists():
            click.echo(f"  SKIP (file missing): {entry['path']}")
            continue

        if dry_run:
            click.echo(f"  [DRY RUN] Would upload: {entry['dest_filename']} -> {entry['category']}/")
            continue

        ok = upload_file(
            local_path=local_path,
            category=entry["category"],
            dest_filename=entry["dest_filename"],
        )

        if ok:
            remote_path = f"/mnt/ssdb/books/{entry['category']}/{entry['dest_filename']}"
            manifest.mark_uploaded(file_hash, remote_path)
            click.echo(f"  OK: {entry['dest_filename']}")
        else:
            click.echo(f"  FAIL: {entry['dest_filename']}")

    if not dry_run:
        manifest.save()

    stats = manifest.get_stats()
    click.echo(f"Total: {stats['total']}, Pending: {stats['pending']}, Uploaded: {stats['uploaded']}")


@cli.command()
def status():
    """Show manifest status."""
    manifest = Manifest(MANIFEST_PATH)
    manifest.load()

    stats = manifest.get_stats()
    click.echo(f"Total: {stats['total']}")
    click.echo(f"Uploaded: {stats['uploaded']}")
    click.echo(f"Pending: {stats['pending']}")

    pending = manifest.get_pending()
    if pending:
        click.echo("\nPending files:")
        for h, entry in pending.items():
            click.echo(f"  {entry['dest_filename']} -> {entry['category']}/")


@cli.command()
@click.option("--dry-run", is_flag=True, help="Show reorganization plan without executing.")
@click.option("--verbose", is_flag=True, help="Enable verbose logging.")
def reorganize_cmd(dry_run, verbose):
    """Reorganize existing remote book collections."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        click.echo("Error: ANTHROPIC_API_KEY must be set for reorganization.")
        sys.exit(1)

    click.echo("Reorganizing remote collections...")
    results = reorganize(dry_run=dry_run, api_key=api_key)

    for dir_result in results:
        click.echo(f"\n{dir_result['directory']}:")
        for plan in dir_result["plans"]:
            prefix = "[DRY RUN] " if dry_run else ""
            click.echo(f"  {prefix}{plan['source']} -> {plan['destination']}")
        if not dry_run:
            click.echo(f"  Success: {dir_result['successes']}, Failures: {dir_result['failures']}")


# Register the reorganize command with the correct name
cli.add_command(reorganize_cmd, name="reorganize")
