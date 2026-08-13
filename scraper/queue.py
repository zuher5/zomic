import json
import sqlite3
import time


class JobQueue:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS job (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'queued',
                attempts INTEGER NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        self.conn.commit()

    def close(self):
        self.conn.close()

    def enqueue(self, job_type, payload=None, *, dedupe=True):
        payload = json.dumps(payload or {})
        if dedupe:
            existing = self.conn.execute(
                "SELECT id FROM job WHERE type = ? AND payload = ? AND status IN ('queued','running')",
                (job_type, payload),
            ).fetchone()
            if existing:
                return existing["id"]
        cur = self.conn.execute(
            "INSERT INTO job (type, payload) VALUES (?, ?)", (job_type, payload)
        )
        self.conn.commit()
        return cur.lastrowid

    def claim_next(self, job_type=None):
        rows = self.conn.execute(
            "SELECT id FROM job WHERE status = 'queued' ORDER BY id LIMIT 1"
        ).fetchall()
        for row in rows:
            if job_type is None or row["id"]:
                pass
        updated = self.conn.execute(
            """
            UPDATE job SET status = 'running', attempts = attempts + 1,
                           updated_at = datetime('now')
            WHERE id = (
                SELECT id FROM job
                WHERE status = 'queued'
                ORDER BY id LIMIT 1
            )
            RETURNING id, type, payload, attempts
            """
        ).fetchone()
        self.conn.commit()
        if updated is None:
            return None
        return dict(updated, payload=json.loads(updated["payload"]))

    def complete(self, job_id):
        self.conn.execute(
            "UPDATE job SET status = 'completed', updated_at = datetime('now') WHERE id = ?",
            (job_id,),
        )
        self.conn.commit()

    def fail(self, job_id, error):
        self.conn.execute(
            "UPDATE job SET status = 'failed', error = ?, updated_at = datetime('now') WHERE id = ?",
            (str(error)[:500], job_id),
        )
        self.conn.commit()

    def retry_failed(self, job_type=None, max_attempts=5):
        query = "SELECT id FROM job WHERE status = 'failed' AND attempts < ?"
        params = [max_attempts]
        if job_type:
            query += " AND type = ?"
            params.append(job_type)
        rows = self.conn.execute(query, params).fetchall()
        for row in rows:
            self.conn.execute(
                "UPDATE job SET status = 'queued', error = '', updated_at = datetime('now') WHERE id = ?",
                (row["id"],),
            )
        self.conn.commit()
        return [r["id"] for r in rows]

    def counts(self):
        rows = self.conn.execute(
            "SELECT status, COUNT(*) AS n FROM job GROUP BY status"
        ).fetchall()
        counts = {"queued": 0, "running": 0, "completed": 0, "failed": 0}
        for row in rows:
            counts[row["status"]] = row["n"]
        return counts

    def list_jobs(self, status=None, limit=50):
        query = "SELECT id, type, payload, status, attempts, error, created_at, updated_at FROM job"
        params = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(query, params).fetchall()
        jobs = []
        for r in rows:
            job = dict(r)
            job["payload"] = json.loads(job["payload"])
            jobs.append(job)
        return jobs

    def enqueue_scrape_comic(self, slug):
        return self.enqueue("scrape_comic", {"slug": slug})

    def enqueue_scrape_chapters(self, slug):
        return self.enqueue("scrape_chapters", {"slug": slug})

    def enqueue_scrape_pages(self, slug, chapter_ref):
        return self.enqueue("scrape_pages", {"slug": slug, "chapter": chapter_ref})

    def enqueue_download_images(self, slug=None):
        payload = {"slug": slug} if slug else {}
        return self.enqueue("download_images", payload)