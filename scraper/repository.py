import json
import sqlite3


SCHEMA = """
CREATE TABLE IF NOT EXISTS source (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    base_url TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS comic (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL REFERENCES source(id),
    external_id TEXT NOT NULL,
    slug TEXT NOT NULL,
    title TEXT NOT NULL,
    synopsis TEXT NOT NULL DEFAULT '',
    author TEXT NOT NULL DEFAULT '',
    cover_url TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    format TEXT NOT NULL DEFAULT '',
    rating REAL NOT NULL DEFAULT 0,
    genres TEXT NOT NULL DEFAULT '[]',
    UNIQUE (source_id, slug)
);

CREATE TABLE IF NOT EXISTS chapter (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    comic_id INTEGER NOT NULL REFERENCES comic(id),
    external_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    slug TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    UNIQUE (comic_id, external_id)
);

CREATE TABLE IF NOT EXISTS page (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id INTEGER NOT NULL REFERENCES chapter(id),
    position INTEGER NOT NULL,
    url TEXT NOT NULL,
    storage_key TEXT NOT NULL DEFAULT '',
    downloaded INTEGER NOT NULL DEFAULT 0,
    UNIQUE (chapter_id, position)
);

CREATE TABLE IF NOT EXISTS job (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'queued',
    attempts INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_comic_source ON comic(source_id);
CREATE INDEX IF NOT EXISTS idx_chapter_comic ON chapter(comic_id);
CREATE INDEX IF NOT EXISTS idx_page_chapter ON page(chapter_id);
CREATE INDEX IF NOT EXISTS idx_job_status ON job(status);
"""

MIGRATIONS = [
    "ALTER TABLE source ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE page ADD COLUMN storage_key TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE page ADD COLUMN downloaded INTEGER NOT NULL DEFAULT 0",
]


class Repository:
    def __init__(self, path):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self):
        existing = {
            r["name"]
            for r in self.conn.execute(
                "SELECT name FROM pragma_table_info('source')"
            ).fetchall()
        }
        if "enabled" not in existing:
            self.conn.execute(MIGRATIONS[0])
        existing = {
            r["name"]
            for r in self.conn.execute(
                "SELECT name FROM pragma_table_info('page')"
            ).fetchall()
        }
        if "storage_key" not in existing:
            self.conn.execute(MIGRATIONS[1])
        if "downloaded" not in existing:
            self.conn.execute(MIGRATIONS[2])

    def close(self):
        self.conn.close()

    def get_or_create_source(self, name, base_url):
        row = self.conn.execute(
            "SELECT id FROM source WHERE name = ?", (name,)
        ).fetchone()
        if row:
            return row["id"]
        cur = self.conn.execute(
            "INSERT INTO source (name, base_url) VALUES (?, ?)", (name, base_url)
        )
        self.conn.commit()
        return cur.lastrowid

    def list_sources(self):
        rows = self.conn.execute(
            "SELECT id, name, base_url, enabled FROM source ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]

    def set_source_enabled(self, source_id, enabled):
        self.conn.execute(
            "UPDATE source SET enabled = ? WHERE id = ?", (1 if enabled else 0, source_id)
        )
        self.conn.commit()

    def get_enabled_sources(self):
        rows = self.conn.execute(
            "SELECT id, name, base_url FROM source WHERE enabled = 1 ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_source(self, source_id):
        row = self.conn.execute(
            "SELECT id, name, base_url, enabled FROM source WHERE id = ?", (source_id,)
        ).fetchone()
        return dict(row) if row else None

    def upsert_comic(self, source_id, comic):
        cur = self.conn.execute(
            """
            INSERT INTO comic (source_id, external_id, slug, title, synopsis, author,
                               cover_url, status, format, rating, genres)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (source_id, slug) DO UPDATE SET
                external_id = excluded.external_id,
                title = excluded.title,
                synopsis = excluded.synopsis,
                author = excluded.author,
                cover_url = excluded.cover_url,
                status = excluded.status,
                format = excluded.format,
                rating = excluded.rating,
                genres = excluded.genres
            """,
            (
                source_id,
                comic.external_id,
                comic.slug,
                comic.title,
                comic.synopsis,
                comic.author,
                comic.cover_url,
                comic.status,
                comic.format,
                comic.rating,
                json.dumps(comic.genres),
            ),
        )
        self.conn.commit()
        return self.get_comic_id(source_id, comic.slug)

    def get_comic_id(self, source_id, slug):
        row = self.conn.execute(
            "SELECT id FROM comic WHERE source_id = ? AND slug = ?",
            (source_id, slug),
        ).fetchone()
        return row["id"] if row else None

    def upsert_chapter(self, comic_id, chapter):
        self.conn.execute(
            """
            INSERT INTO chapter (comic_id, external_id, idx, slug, title)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (comic_id, external_id) DO UPDATE SET
                idx = excluded.idx,
                slug = excluded.slug,
                title = excluded.title
            """,
            (comic_id, chapter.external_id, chapter.index, chapter.slug, chapter.title),
        )
        self.conn.commit()

    def get_chapter_id(self, comic_id, external_id):
        row = self.conn.execute(
            "SELECT id FROM chapter WHERE comic_id = ? AND external_id = ?",
            (comic_id, external_id),
        ).fetchone()
        return row["id"] if row else None

    def upsert_pages(self, chapter_id, pages):
        for page in pages:
            self.conn.execute(
                """
                INSERT INTO page (chapter_id, position, url)
                VALUES (?, ?, ?)
                ON CONFLICT (chapter_id, position) DO UPDATE SET url = excluded.url
                """,
                (chapter_id, page.position, page.url),
            )
        self.conn.commit()

    def counts(self):
        row = self.conn.execute(
            "SELECT (SELECT COUNT(*) FROM comic), (SELECT COUNT(*) FROM chapter),"
            " (SELECT COUNT(*) FROM page)"
        ).fetchone()
        return dict(comic=row[0], chapter=row[1], page=row[2])

    def search_comics(self, keyword, limit=20, offset=0):
        like = f"%{keyword}%"
        rows = self.conn.execute(
            """
            SELECT id, external_id, slug, title, synopsis, author, cover_url,
                   status, format, rating, genres
            FROM comic
            WHERE title LIKE ? OR slug LIKE ?
            ORDER BY id DESC LIMIT ? OFFSET ?
            """,
            (like, like, limit, offset),
        ).fetchall()
        return [self._comic_row(r) for r in rows]

    def count_search_comics(self, keyword):
        like = f"%{keyword}%"
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM comic WHERE title LIKE ? OR slug LIKE ?",
            (like, like),
        ).fetchone()
        return row["n"]

    def list_comics(self, limit=20, offset=0):
        rows = self.conn.execute(
            """
            SELECT id, external_id, slug, title, synopsis, author, cover_url,
                   status, format, rating, genres
            FROM comic
            ORDER BY id DESC LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        return [self._comic_row(r) for r in rows]

    def get_comic_by_id(self, comic_id):
        row = self.conn.execute(
            """
            SELECT id, external_id, slug, title, synopsis, author, cover_url,
                   status, format, rating, genres
            FROM comic WHERE id = ?
            """,
            (comic_id,),
        ).fetchone()
        return self._comic_row(row) if row else None

    def list_chapters(self, comic_id):
        rows = self.conn.execute(
            """
            SELECT id, comic_id, external_id, idx, slug, title
            FROM chapter WHERE comic_id = ? ORDER BY idx
            """,
            (comic_id,),
        ).fetchall()
        return [self._chapter_row(r) for r in rows]

    def get_chapter_by_id(self, chapter_id):
        row = self.conn.execute(
            """
            SELECT id, comic_id, external_id, idx, slug, title
            FROM chapter WHERE id = ?
            """,
            (chapter_id,),
        ).fetchone()
        return self._chapter_row(row) if row else None

    def list_pages(self, chapter_id):
        rows = self.conn.execute(
            """
            SELECT id, position, url FROM page
            WHERE chapter_id = ? ORDER BY position
            """,
            (chapter_id,),
        ).fetchall()
        return [self._page_row(r) for r in rows]

    def get_pending_pages(self, limit=100):
        rows = self.conn.execute(
            """
            SELECT p.id AS page_id, p.url, p.chapter_id, c.id AS comic_id, c.slug
            FROM page p
            JOIN chapter ch ON ch.id = p.chapter_id
            JOIN comic c ON c.id = ch.comic_id
            WHERE p.downloaded = 0
            ORDER BY p.id LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_page_downloaded(self, page_id, storage_key):
        self.conn.execute(
            "UPDATE page SET storage_key = ?, downloaded = 1 WHERE id = ?",
            (storage_key, page_id),
        )
        self.conn.commit()

    @staticmethod
    def _comic_row(r):
        return {
            "id": r["id"],
            "external_id": r["external_id"],
            "slug": r["slug"],
            "title": r["title"],
            "synopsis": r["synopsis"],
            "author": r["author"],
            "cover_url": r["cover_url"],
            "status": r["status"],
            "format": r["format"],
            "rating": r["rating"],
            "genres": json.loads(r["genres"]),
        }

    @staticmethod
    def _chapter_row(r):
        return {
            "id": r["id"],
            "comic_id": r["comic_id"],
            "external_id": r["external_id"],
            "index": r["idx"],
            "slug": r["slug"],
            "title": r["title"],
        }

    @staticmethod
    def _page_row(r):
        return {"id": r["id"], "position": r["position"], "url": r["url"]}