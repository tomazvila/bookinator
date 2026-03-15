#!/usr/bin/env python3
"""Batch organize all ebooks on the remote server.

Usage:
    python batch_organize.py classify     # Classify all files, save plan to plan.json
    python batch_organize.py show         # Show plan summary
    python batch_organize.py execute      # Execute the plan (copy files on remote)
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
from bookstuff.classifier import classify_batch, CATEGORIES

REMOTE_HOST = "lilvilla@ssh.tomazvi.la"
REMOTE_DEST = "/mnt/ssdb/books"
FILE_LIST = Path("/tmp/ssdb_all_ebooks.txt")
PLAN_FILE = Path("plan.json")
BATCH_SIZE = 20


def load_file_list() -> list[str]:
    return [l.strip() for l in FILE_LIST.read_text().splitlines() if l.strip()]


def load_plan() -> dict:
    if PLAN_FILE.exists():
        return json.loads(PLAN_FILE.read_text())
    return {"classified": {}, "skipped": [], "errors": []}


def save_plan(plan: dict):
    PLAN_FILE.write_text(json.dumps(plan, indent=2, ensure_ascii=False))


def classify_all():
    api_key = os.environ.get("ANTHROPIC_API_KEY") or Path("key.txt").read_text().strip()
    files = load_file_list()
    plan = load_plan()

    already_done = set(plan["classified"].keys()) | set(plan["skipped"]) | set(plan["errors"])
    remaining = [f for f in files if f not in already_done]

    print(f"Total files: {len(files)}")
    print(f"Already processed: {len(already_done)}")
    print(f"Remaining: {len(remaining)}")

    if not remaining:
        print("All files already classified!")
        return

    batches = [remaining[i:i+BATCH_SIZE] for i in range(0, len(remaining), BATCH_SIZE)]
    print(f"Processing {len(batches)} batches of {BATCH_SIZE}...")

    for batch_idx, batch in enumerate(batches):
        print(f"\n[{batch_idx+1}/{len(batches)}] Classifying {len(batch)} files...", end=" ", flush=True)

        try:
            results = classify_batch(batch, api_key)

            skipped = 0
            classified = 0
            for r in results:
                if r["category"] == "skip":
                    plan["skipped"].append(r["path"])
                    skipped += 1
                else:
                    plan["classified"][r["path"]] = {
                        "title": r["title"],
                        "author": r["author"],
                        "category": r["category"],
                        "dest_filename": r["dest_filename"],
                    }
                    classified += 1

            print(f"OK ({classified} books, {skipped} skipped)")

        except Exception as e:
            print(f"ERROR: {e}")
            for f in batch:
                if f not in plan["classified"] and f not in plan["skipped"]:
                    plan["errors"].append(f)

        save_plan(plan)

        # Small delay to respect rate limits
        if batch_idx < len(batches) - 1:
            time.sleep(0.5)

    print(f"\nDone! {len(plan['classified'])} classified, {len(plan['skipped'])} skipped, {len(plan['errors'])} errors")
    print(f"Plan saved to {PLAN_FILE}")


def show_plan():
    plan = load_plan()

    if not plan["classified"]:
        print("No plan yet. Run 'classify' first.")
        return

    # Count by category
    cats = {}
    for entry in plan["classified"].values():
        cat = entry["category"]
        cats[cat] = cats.get(cat, 0) + 1

    print(f"=== Plan Summary ===")
    print(f"Total books to organize: {len(plan['classified'])}")
    print(f"Skipped (not books):     {len(plan['skipped'])}")
    print(f"Errors:                  {len(plan['errors'])}")
    print()
    print("By category:")
    for cat in sorted(cats.keys(), key=lambda c: cats[c], reverse=True):
        print(f"  {cat:<28} {cats[cat]:>5}")

    # Show a few samples per category
    print("\n=== Samples ===")
    shown = {}
    for path, entry in plan["classified"].items():
        cat = entry["category"]
        if cat not in shown:
            shown[cat] = 0
        if shown[cat] < 3:
            print(f"  [{cat}] {entry['dest_filename']}")
            shown[cat] += 1


def _escape_shell(s: str) -> str:
    """Escape a string for safe use inside double quotes in shell."""
    s = s.replace("\\", "\\\\")
    s = s.replace('"', '\\"')
    s = s.replace("$", "\\$")
    s = s.replace("`", "\\`")
    # Don't escape ! — non-interactive bash doesn't do history expansion
    return s


def execute_plan():
    plan = load_plan()

    if not plan["classified"]:
        print("No plan. Run 'classify' first.")
        return

    total = len(plan["classified"])
    print(f"Executing plan: copying {total} books to {REMOTE_DEST}/...")

    # Build a single shell script to run on the remote server
    lines = ["#!/bin/bash", "set -f", "ok=0; fail=0; skip=0"]

    # Create all category directories
    cats = set(e["category"] for e in plan["classified"].values())
    for c in sorted(cats):
        lines.append(f'mkdir -p "{REMOTE_DEST}/{c}"')

    # Generate cp commands using double quotes for proper escaping
    for source, entry in plan["classified"].items():
        src_esc = _escape_shell(source)
        dest_esc = _escape_shell(f"{REMOTE_DEST}/{entry['category']}/{entry['dest_filename']}")
        lines.append(
            f'if [ -f "{dest_esc}" ]; then skip=$((skip+1)); '
            f'elif cp "{src_esc}" "{dest_esc}" 2>/dev/null; then ok=$((ok+1)); '
            f'else fail=$((fail+1)); echo "FAIL: {src_esc}"; fi'
        )

    lines.append('echo "RESULT: $ok copied, $skip already existed, $fail failed"')

    script = "\n".join(lines)
    script_path = Path("/tmp/bookstuff_execute.sh")
    script_path.write_text(script)

    print(f"Generated script with {total} copy commands. Uploading and executing...")

    # Upload script to remote
    subprocess.run(
        ["scp", str(script_path), f"{REMOTE_HOST}:/tmp/bookstuff_execute.sh"],
        check=True, capture_output=True,
    )

    # Execute on remote with progress
    proc = subprocess.Popen(
        ["ssh", REMOTE_HOST, "bash", "/tmp/bookstuff_execute.sh"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )

    if proc.stdout:
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("FAIL:") or line.startswith("RESULT:"):
                print(f"  {line}")

    proc.wait()
    print("Done!")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "classify":
        classify_all()
    elif cmd == "show":
        show_plan()
    elif cmd == "execute":
        execute_plan()
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)
