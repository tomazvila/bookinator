"""Background worker for book indexing and embedding generation.

Runs as a separate process from the web server so CPU-heavy ONNX
inference doesn't interfere with serving requests.
"""

import logging
import os
import time

from bookstuff.web.index import get_db_path, init_db, reindex
from bookstuff.web.embeddings import get_embedder
from bookstuff.web.semantic import backfill_book_embeddings, index_pending_books

logger = logging.getLogger(__name__)

REINDEX_INTERVAL = 300  # 5 minutes


def main():
    logging.basicConfig(level=logging.INFO)

    books_dir = os.environ.get("BOOKS_DIR", "/mnt/ssdb/books")
    db_path = get_db_path(books_dir)
    conn = init_db(db_path)

    get_embedder()

    logger.info("Worker started (books_dir=%s)", books_dir)

    # One-time backfill: compute book-level embeddings for existing indexed books
    try:
        filled = backfill_book_embeddings(conn)
        if filled:
            logger.info("Backfilled %d book-level embeddings", filled)
    except Exception:
        logger.exception("Book embedding backfill failed")

    while True:
        try:
            count = reindex(conn, books_dir)
            logger.info("Reindexed: %d books", count)
        except Exception:
            logger.exception("Reindex failed")

        try:
            if get_embedder() is not None:
                indexed = index_pending_books(conn, books_dir)
                if indexed:
                    logger.info("Embedded %d books", indexed)
        except Exception:
            logger.exception("Semantic indexing failed")

        time.sleep(REINDEX_INTERVAL)


if __name__ == "__main__":
    main()
