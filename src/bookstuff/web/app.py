"""Flask web application for browsing and searching the book collection."""

import logging
import os
import time
from collections import defaultdict

from flask import Flask, jsonify, render_template, request, send_from_directory, abort
from werkzeug.utils import secure_filename

from bookstuff.web.index import get_db_path, init_db, reindex, get_categories, EBOOK_EXTENSIONS, parse_filename
from bookstuff.web.password import verify_password
from bookstuff.web.preview import generate_preview
from bookstuff.web.semantic import hybrid_search, get_embedding_status, is_semantic_available
from bookstuff.web.embeddings import get_embedder

logger = logging.getLogger(__name__)

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_WINDOW = 300  # seconds


class _RateLimiter:
    """IP-based rate limiter tracking failed password attempts."""

    def __init__(self, max_attempts: int = MAX_FAILED_ATTEMPTS,
                 window: int = LOCKOUT_WINDOW):
        self.max_attempts = max_attempts
        self.window = window
        self._failures: dict[str, list[float]] = defaultdict(list)

    def is_blocked(self, ip: str) -> bool:
        now = time.monotonic()
        self._failures[ip] = [t for t in self._failures[ip] if now - t < self.window]
        return len(self._failures[ip]) >= self.max_attempts

    def record_failure(self, ip: str) -> None:
        self._failures[ip].append(time.monotonic())


def create_app(books_dir: str | None = None, reindex_on_start: bool = True) -> Flask:
    """Create and configure the Flask application."""
    books_dir = books_dir or os.environ.get("BOOKS_DIR", "/mnt/ssdb/books")

    app = Flask(__name__)
    app.config["BOOKS_DIR"] = books_dir
    app.config["UPLOAD_PASSWORD_HASH"] = os.environ.get("UPLOAD_PASSWORD_HASH", "")
    app.config["UPLOAD_PEPPER"] = os.environ.get("UPLOAD_PEPPER", "")

    upload_limiter = _RateLimiter()

    db_path = get_db_path(books_dir)
    conn = init_db(db_path)

    # Initialize local embedding model for search queries (logs warning if not found)
    get_embedder()

    if reindex_on_start:
        count = reindex(conn, books_dir)
        logger.info("Initial index: %d books", count)

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/search")
    def api_search():
        q = request.args.get("q", "").strip()
        category = request.args.get("category", "").strip() or None
        limit = min(int(request.args.get("limit", 50)), 200)
        offset = int(request.args.get("offset", 0))

        results = hybrid_search(conn, q, category=category, limit=limit, offset=offset)
        mode = "hybrid" if get_embedder() is not None and is_semantic_available(conn) else "keyword"
        return jsonify({"results": results, "count": len(results), "mode": mode})

    @app.route("/api/search/status")
    def api_search_status():
        status = get_embedding_status(conn)
        status["semantic_available"] = is_semantic_available(conn) and get_embedder() is not None
        return jsonify(status)

    @app.route("/api/categories")
    def api_categories():
        cats = get_categories(conn)
        return jsonify({"categories": cats})

    @app.route("/api/health")
    def api_health():
        try:
            count = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        except Exception:
            return jsonify({"status": "ok", "books": -1})
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

    @app.route("/api/upload", methods=["POST"])
    def api_upload():
        client_ip = request.headers.get("CF-Connecting-IP") or request.remote_addr
        if upload_limiter.is_blocked(client_ip):
            return jsonify({"error": "Too many attempts, try again later"}), 429

        password = request.form.get("password", "")
        if not verify_password(password, app.config["UPLOAD_PASSWORD_HASH"],
                               app.config["UPLOAD_PEPPER"]):
            upload_limiter.record_failure(client_ip)
            return jsonify({"error": "Invalid password"}), 401

        file = request.files.get("file")
        if not file or not file.filename:
            return jsonify({"error": "No file provided"}), 400

        filename = secure_filename(file.filename)
        if not filename:
            return jsonify({"error": "Invalid filename"}), 400

        ext = os.path.splitext(filename)[1].lower()
        if ext not in EBOOK_EXTENSIONS:
            allowed = ", ".join(sorted(EBOOK_EXTENSIONS))
            return jsonify({"error": f"Unsupported format. Allowed: {allowed}"}), 400

        category = request.form.get("category", "uncategorized").strip()
        if not category:
            category = "uncategorized"

        category_dir = os.path.join(books_dir, category)
        os.makedirs(category_dir, exist_ok=True)

        dest = os.path.join(category_dir, filename)
        if os.path.exists(dest):
            return jsonify({"error": "A file with this name already exists in this category"}), 409

        file.save(dest)
        logger.info("Uploaded %s to %s", filename, category)

        # Add to index immediately
        author, title = parse_filename(filename)
        rel_path = os.path.join(category, filename)
        size_bytes = os.path.getsize(dest)
        conn.execute(
            """INSERT OR IGNORE INTO books
               (filename, author, title, category, extension, size_bytes, path)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (filename, author, title, category, ext.lstrip("."), size_bytes, rel_path),
        )
        conn.commit()

        book_row = conn.execute("SELECT id FROM books WHERE path = ?", (rel_path,)).fetchone()
        book_id = book_row["id"] if book_row else None

        # Queue for semantic indexing
        if book_id:
            conn.execute(
                "INSERT OR IGNORE INTO embedding_status (book_id, status) VALUES (?, 'pending')",
                (book_id,),
            )
            conn.commit()

        return jsonify({
            "ok": True,
            "id": book_id,
            "filename": filename,
            "category": category,
        }), 201

    return app


def main():
    logging.basicConfig(level=logging.INFO)
    port = int(os.environ.get("PORT", 5001))

    try:
        from gunicorn.app.base import BaseApplication

        class _StandaloneApplication(BaseApplication):
            def __init__(self, app_factory, options=None):
                self.app_factory = app_factory
                self.options = options or {}
                super().__init__()

            def load_config(self):
                for key, value in self.options.items():
                    self.cfg.set(key.lower(), value)

            def load(self):
                return self.app_factory()

        options = {
            "bind": f"0.0.0.0:{port}",
            "workers": 1,
            "threads": 4,
            "worker_class": "gthread",
            "timeout": 120,
            "accesslog": "-",
        }
        _StandaloneApplication(create_app, options).run()
    except ImportError:
        logger.warning("gunicorn not installed, falling back to Flask dev server")
        app = create_app()
        app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
