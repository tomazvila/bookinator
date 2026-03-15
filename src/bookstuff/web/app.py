"""Flask web application for browsing and searching the book collection."""

import logging
import os

from flask import Flask, jsonify, render_template, request, send_from_directory, abort

from bookstuff.web.index import get_db_path, init_db, reindex, search, get_categories, start_reindex_thread
from bookstuff.web.preview import generate_preview

logger = logging.getLogger(__name__)


def create_app(books_dir: str | None = None, reindex_on_start: bool = True) -> Flask:
    """Create and configure the Flask application."""
    books_dir = books_dir or os.environ.get("BOOKS_DIR", "/mnt/ssdb/books")

    app = Flask(__name__)
    app.config["BOOKS_DIR"] = books_dir

    db_path = get_db_path(books_dir)
    conn = init_db(db_path)

    if reindex_on_start:
        count = reindex(conn, books_dir)
        logger.info("Initial index: %d books", count)
        start_reindex_thread(conn, books_dir)

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/search")
    def api_search():
        q = request.args.get("q", "").strip()
        category = request.args.get("category", "").strip() or None
        limit = min(int(request.args.get("limit", 50)), 200)
        offset = int(request.args.get("offset", 0))
        results = search(conn, q, category=category, limit=limit, offset=offset)
        return jsonify({"results": results, "count": len(results)})

    @app.route("/api/categories")
    def api_categories():
        cats = get_categories(conn)
        return jsonify({"categories": cats})

    @app.route("/api/health")
    def api_health():
        count = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        return jsonify({"status": "ok", "books": count})

    @app.route("/book/<int:book_id>")
    def book_detail(book_id):
        row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        if not row:
            abort(404)
        return render_template("book.html", book=dict(row))

    @app.route("/api/preview/<int:book_id>")
    def preview(book_id):
        row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        if not row:
            abort(404)
        book = dict(row)
        book_path = os.path.join(books_dir, book["path"])
        result = generate_preview(books_dir, book_id, book_path, book["extension"])
        if not result:
            abort(404)
        directory = os.path.dirname(result)
        filename = os.path.basename(result)
        return send_from_directory(directory, filename, mimetype="image/jpeg")

    @app.route("/download/<category>/<filename>")
    def download(category, filename):
        directory = os.path.join(books_dir, category)
        if not os.path.isdir(directory):
            abort(404)
        return send_from_directory(directory, filename, as_attachment=True)

    return app


def main():
    port = int(os.environ.get("PORT", 5001))
    app = create_app()
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
