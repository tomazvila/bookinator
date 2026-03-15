"""Clean non-book entries from the manifest before uploading."""
import json
import re
import sys

# Patterns in dest_filename that indicate non-book documents
NON_BOOK_DEST_PATTERNS = [
    # Financial reports (not books)
    r"ISM Report", r"\bPMI\b", r"STOXX", r"ZEW", r"Finanzmarkt",
    r"F-report", r"Factsheet", r"Sector PMI",
    # Business/financial documents
    r"Invoice", r"Payment Order", r"Payment Confirmation",
    r"Bank Statement", r"Annual Report", r"Interim Report",
    r"financial results", r"Quarterly Report",
    # Personal documents
    r"Booking Confirmation", r"Booking Document", r"Certificate",
    r"COVID", r"Health Declaration", r"Nuomos sutartis",
    r"Draudimo|draudimo", r"sąskaita", r"Green Card",
    r"Event Ticket", r"Bus Ticket",
    r"Resume -|Tomas Mažvila\.pdf|Tomas Mazvila CV",
    r"Dovanų kuponas", r"Form_FR\d",
    r"Employment Contract|Darbo sutart",
    r"MOKĖJIMO KVITAS", r"SUTARTIES NUTRAUKIMAS",
    r"apgyvendinimo.*sutartis",
    r"Pažyma apie", r"Proof of Residence",
    r"PRAŠYMAS APSIGYVENTIS|prasymas\.pdf",
    r"Sertifikatas",
    # Tickets and events
    r"Devilstone", r"eBilietai",
    # Junk/misc
    r"CamScanner", r"Coupon-", r"Checkout\.pdf",
    r"QR Code Generator",
    r"Pakvietimas|Invitation",
    r"VĮRC Savitarna",
    r"^mantodoc\.pdf$", r"^sts\.pdf$", r"^sutartis\.pdf$",
    r"^merged_teorija\.pdf$",
    r"^LT\.pdf$", r"^VISAS_\d+\.pdf$",
    r"strechpratimai",
    r"Test tweet", r"PowerPoint",
    r"Manual Todo Document",
    r"CEP\.pdf$",
    r"Atmintinė studentams",
    r"Savitarna",
]

# Patterns in original path that indicate non-book files
NON_BOOK_PATH_PATTERNS = [
    r"CamScanner",
]

COMPILED_DEST = [(re.compile(p, re.IGNORECASE), p) for p in NON_BOOK_DEST_PATTERNS]
COMPILED_PATH = [(re.compile(p, re.IGNORECASE), p) for p in NON_BOOK_PATH_PATTERNS]


def is_non_book(entry):
    name = entry["dest_filename"]
    path = entry.get("path", "")

    for pat, raw in COMPILED_DEST:
        if pat.search(name):
            return True, f"dest matches: {raw}"

    for pat, raw in COMPILED_PATH:
        if pat.search(path):
            return True, f"path matches: {raw}"

    return False, ""


def main():
    with open("manifest.json") as f:
        data = json.load(f)

    keep = {}
    remove = {}

    for h, entry in data.items():
        non_book, reason = is_non_book(entry)
        if non_book:
            remove[h] = (entry, reason)
        else:
            keep[h] = entry

    print(f"Total entries: {len(data)}")
    print(f"Keeping: {len(keep)}")
    print(f"Removing: {len(remove)}")
    print()

    # Show category breakdown of what we're keeping
    from collections import Counter
    keep_cats = Counter(e["category"] for e in keep.values())
    print("=== KEEPING (by category) ===")
    for cat, count in keep_cats.most_common():
        print(f"  {cat}: {count}")

    if "--apply" in sys.argv:
        with open("manifest.json", "w") as f:
            json.dump(keep, f, indent=2, ensure_ascii=False)
        print(f"\nManifest cleaned! {len(keep)} entries remaining.")
    else:
        print("\nDry run. Use --apply to save changes.")
        print("\n=== SAMPLE REMOVALS ===")
        for i, (h, (entry, reason)) in enumerate(list(remove.items())[:30]):
            print(f"  [{entry['category']}] {entry['dest_filename']}")
            print(f"    Reason: {reason}")


if __name__ == "__main__":
    main()
